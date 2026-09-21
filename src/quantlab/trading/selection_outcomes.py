"""Retrospective outcome review of Playbook selections against their own frozen CandidateSet (research_only).

A SelectionDecision splits a frozen CandidateSet into selected and unselected symbols. ``PaperOutcomeReview`` only
follows executed PaperPlans, so the unselected side -- a filter's possible false negatives -- was never measured.
This module measures both sides of a selection the same way, from accepted DailyMarket snapshots only.

It is a selection diagnostic, not a trading result: close-to-close signal returns with no fills, costs, price-limit
access or queueing. It never writes Decision / Strategy Intent / Paper and never changes weights or rules.

Windows: ``D1..Dn`` compound the ``n`` trading sessions after the selection day, starting from that day's close, so
no price observed after the selection moment is treated as known. ``D0`` (the selection day itself, previous close to
close) is produced only for pre-open ``PREP`` selections, where the previous close was known at ``as_of``.

Each (selection, window) is frozen once all of its sessions have accepted snapshots. A later accepted revision that
changes a frozen result raises ``REVIEW_CONFLICT`` instead of rewriting history.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
from uuid import uuid4
import errno
import fcntl
import math
import os

from quantlab.data.daily_market_archive import DailyMarketArchive, DailyMarketArchiveError
from quantlab.data.forward_daily import ForwardDailyError, ForwardReferenceArchive
from quantlab.experiments.campaign_state import read_checked, write_checked
from quantlab.storage.codec import digest

from .playbook_store import PlaybookError, PlaybookStore

FORMAT = 'selection-outcome-review-v1'
DEFAULT_WINDOWS = (0, 1, 2, 3, 5, 10)
MAX_WINDOW = 60
PRE_OPEN_FRAMES = ('PREP',)
GROUPS = ('SELECTED', 'UNSELECTED')
EXTREMES_LIMIT = 20
# Returns within this distance of a group mean are ties, not out/under-performance (float noise).
TIE_TOLERANCE = 1e-9
MIN_SUMMARY_SAMPLES = 3
SEMANTICS = 'SIGNAL_CLOSE_TO_CLOSE_RETURN_NOT_EXECUTABLE'
POLICY = {'automatic_reweighting': False, 'writes_decision_intent_or_paper': False, 'alpha_claimed': False,
          'significance_tested': False}
LIMITATIONS = [
    '只衡量同一冻结 CandidateSet 内“选中 vs 未选中”的信号收益，不是成交结果：没有费用、滑点、涨跌停买卖可达性或排板。',
    'D1 起从选择日收盘价起算；D0 只对盘前 PREP 选择计算（选择日昨收→收盘）。盘中 Frame 的当日走势不计入，避免把选择时点之后的价格当作前提。',
    '收益按 DailyMarket 每日 close/preclose 连乘，preclose 已含除权；停牌日计为 0 并单独计数；缺少当日行的证券标记为无数据，不填 0、不换股。',
    '候选完整性与 PIT 等级沿用 CandidateSet 原值；PARTIAL/UNKNOWN 候选集的“未选中”不代表全部可选标的。',
    '描述性选择诊断：不做显著性检验、不自动调权、不写 Decision/Strategy Intent/Paper；未选中跑赢不等于当时应当选中。',
    'DailyMarket 为 Baostock 研究口径（research_only），不覆盖北交所。',
]


class SelectionOutcomeError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _windows(values):
    if values is None:
        return DEFAULT_WINDOWS
    if not isinstance(values, (list, tuple)) or not values:
        raise SelectionOutcomeError('INVALID_ARGUMENT', 'windows 必须是非空整数列表。')
    result = []
    for value in values:
        if type(value) is not int or not 0 <= value <= MAX_WINDOW:
            raise SelectionOutcomeError('INVALID_ARGUMENT', f'windows 必须是 0–{MAX_WINDOW} 的整数。')
        if value not in result:
            result.append(value)
    return tuple(sorted(result))


def _label(window):
    return f'D{window}'


def _stats(values):
    measured = [value for value in values if value is not None]
    if not measured:
        return {'total': len(values), 'measured': 0, 'mean': None, 'median': None, 'min': None, 'max': None}
    return {'total': len(values), 'measured': len(measured), 'mean': math.fsum(measured) / len(measured),
            'median': median(measured), 'min': min(measured), 'max': max(measured)}


class SelectionOutcomeService:
    def __init__(self, output, now_fn=None):
        self.output = Path(output).resolve()
        if not self.output.is_dir():
            raise SelectionOutcomeError('INVALID_WORKSPACE', '工作空间不存在。')
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.root = self.output / '_trading' / 'selection_outcomes'
        self.store = PlaybookStore(self.output)
        self.daily = DailyMarketArchive(self.output)
        self.references = ForwardReferenceArchive(self.output)
        self._frames = {}
        self._calendar = None

    # ---- inputs -------------------------------------------------------------------------------------------------
    def _guard(self):
        for path in (self.output / '_trading', self.root):
            if path.is_symlink():
                raise SelectionOutcomeError('INVALID_WORKSPACE', '选择结果复盘目录不能是符号链接。')
            if path.exists() and not path.is_dir():
                raise SelectionOutcomeError('INVALID_WORKSPACE', '选择结果复盘路径必须是目录。')

    def _refresh_inputs(self):
        """A build is a new observation boundary; do not retain missing days, revisions, or calendar snapshots."""
        self._frames.clear()
        self._calendar = None

    @contextmanager
    def _freeze_lock(self):
        """POSIX process lock for immutable review publication (this service is intentionally POSIX-only)."""
        self._guard()
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise SelectionOutcomeError('INVALID_WORKSPACE', '选择结果复盘目录不能是符号链接。')
        path = self.root / '.freeze.lock'
        if path.is_symlink():
            raise SelectionOutcomeError('INVALID_WORKSPACE', '选择结果复盘锁不能是符号链接。')
        with path.open('a+b') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _selection_bundle(self, selection_id):
        try:
            selection = self.store.get_selection(selection_id)
            candidates = self.store.get_candidate_set(selection['candidate_set_id'])
            case = self.store.get_case(selection['case_id'])
        except PlaybookError as error:
            raise SelectionOutcomeError(error.code, str(error)) from None
        return selection, candidates, case

    def _trading_calendar(self):
        """Ordered trading days from the most recent forward reference snapshot (past days never change)."""
        if self._calendar is None:
            try:
                manifests = self.references.list()
            except ForwardDailyError as error:
                raise SelectionOutcomeError(error.code, str(error)) from None
            if not manifests:
                raise SelectionOutcomeError('REFERENCE_NOT_FOUND', '没有前瞻参考快照（交易日历），无法确定选择日之后的交易日。')
            latest = manifests[0]
            try:
                loaded = self.references.load(latest['snapshot_id'])
            except ForwardDailyError as error:
                raise SelectionOutcomeError(error.code, str(error)) from None
            days = [date.fromisoformat(day) for day, flag in loaded['trade_calendar'] if flag == '1']
            self._calendar = {'snapshot_id': latest['snapshot_id'], 'days': days, 'last_day': latest['calendar_last_day']}
        return self._calendar

    def _frame(self, day):
        key = day.isoformat()
        if key not in self._frames:
            try:
                frame, manifest = self.daily.read_frame(day)
            except DailyMarketArchiveError as error:
                if error.code != 'NOT_FOUND':
                    raise SelectionOutcomeError(error.code, str(error)) from None
                self._frames[key] = None
            else:
                rows = {}
                for code, status, close, preclose in frame.select('code', 'tradestatus', 'close', 'preclose').iter_rows():
                    rows[code] = (status, close, preclose)
                self._frames[key] = {'rows': rows, 'snapshot': {'date': key, 'snapshot_id': manifest['snapshot_id'],
                                     'content_hash': manifest['content_hash'], 'fetched_at': manifest['fetched_at']}}
        return self._frames[key]

    # ---- measurement ----------------------------------------------------------------------------------------------
    @staticmethod
    def _symbol_return(symbol, frames):
        factor, suspended = 1.0, 0
        for frame in frames:
            row = frame['rows'].get(symbol)
            if row is None:
                return None, suspended, 'NO_DAILY_ROW'
            status, close, preclose = row
            if status != '1':
                suspended += 1
                continue
            if close is None or preclose is None or not close > 0 or not preclose > 0:
                return None, suspended, 'NO_PRICE'
            factor *= close / preclose
        return factor - 1.0, suspended, 'MEASURED'

    def _sessions(self, trading_day, window, frame_name):
        if window == 0 and frame_name not in PRE_OPEN_FRAMES:
            return None
        calendar = self._trading_calendar()
        day = date.fromisoformat(trading_day)
        if not calendar['days'] or day < calendar['days'][0]:
            raise SelectionOutcomeError('OUTSIDE_CALENDAR', f'选择日 {trading_day} 早于前瞻参考交易日历的覆盖范围。')
        if day.isoformat() > calendar['last_day']:
            return []
        if day not in calendar['days']:
            raise SelectionOutcomeError('NOT_A_TRADING_DAY', f'选择日 {trading_day} 不是交易日。')
        if window == 0:
            return [day] if frame_name in PRE_OPEN_FRAMES else None
        later = [value for value in calendar['days'] if value > day]
        return later[:window] if len(later) >= window else []

    def _measure(self, selection, candidates, case, window, sessions):
        frames = [self._frame(day) for day in sessions]
        missing = [day.isoformat() for day, frame in zip(sessions, frames) if frame is None]
        if missing:
            return None, {'window': _label(window), 'status': 'DATA_MISSING', 'missing_days': missing}
        selected = set(selection['selected_symbols'])
        symbols = []
        for symbol in candidates['candidate_symbols']:
            value, suspended, status = self._symbol_return(symbol, frames)
            symbols.append({'symbol': symbol, 'group': 'SELECTED' if symbol in selected else 'UNSELECTED',
                            'status': status, 'return': value, 'suspended_sessions': suspended})
        by_group = {group: [row['return'] for row in symbols if row['group'] == group] for group in GROUPS}
        groups = {group: _stats(values) for group, values in by_group.items()}
        groups['CANDIDATE_POOL'] = _stats([row['return'] for row in symbols])
        selected_mean, unselected_mean = groups['SELECTED']['mean'], groups['UNSELECTED']['mean']
        spread = selected_mean - unselected_mean if selected_mean is not None and unselected_mean is not None else None
        above = [] if selected_mean is None else sorted(
            ({'symbol': row['symbol'], 'return': row['return']} for row in symbols
             if row['group'] == 'UNSELECTED' and row['return'] is not None
             and row['return'] > selected_mean + TIE_TOLERANCE),
            key=lambda item: (-item['return'], item['symbol']))[:EXTREMES_LIMIT]
        below = [] if unselected_mean is None else sorted(
            ({'symbol': row['symbol'], 'return': row['return']} for row in symbols
             if row['group'] == 'SELECTED' and row['return'] is not None
             and row['return'] < unselected_mean - TIE_TOLERANCE),
            key=lambda item: (item['return'], item['symbol']))[:EXTREMES_LIMIT]
        snapshots = [frame['snapshot'] for frame in frames]
        core = {
            'format': FORMAT, 'selection_id': selection['selection_id'], 'selection_kind': selection['kind'],
            'candidate_set_id': candidates['candidate_set_id'], 'case_id': case['case_id'],
            'definition_id': candidates['definition_id'], 'playbook_key': case['playbook_key'],
            'playbook_version': case['playbook_version'], 'frame': candidates['frame'],
            'trading_day': candidates['trading_day'], 'selection_as_of': selection['as_of'],
            'candidate_completeness': candidates['completeness'], 'candidate_pit_status': candidates['pit_status'],
            'candidate_count': candidates['candidate_count'], 'window': window, 'window_label': _label(window),
            'reference': 'SELECTION_DAY_PRECLOSE' if window == 0 else 'SELECTION_DAY_CLOSE',
            'sessions': [day.isoformat() for day in sessions], 'daily_market_snapshots': snapshots,
            'calendar_reference_snapshot_id': self._trading_calendar()['snapshot_id'],
            'data_cutoff_at': max(item['fetched_at'] for item in snapshots),
            'symbols': symbols, 'groups': groups, 'spread_selected_minus_unselected': spread,
            'unselected_above_selected_mean': above, 'selected_below_unselected_mean': below,
            'semantics': SEMANTICS, 'qualification': 'research_only', 'future_data_used': False,
            'policy': dict(POLICY), 'limitations': list(LIMITATIONS),
        }
        return core, None

    # ---- persistence ----------------------------------------------------------------------------------------------
    def _folder(self, selection_id):
        try:
            self.store.get_selection(selection_id)
        except PlaybookError as error:
            raise SelectionOutcomeError(error.code, str(error)) from None
        folder = self.root / selection_id
        if folder.is_symlink():
            raise SelectionOutcomeError('INVALID_WORKSPACE', '选择结果复盘目录不能是符号链接。')
        return folder

    @staticmethod
    def _review_core(value):
        return {key: item for key, item in value.items() if key not in ('review_hash', 'created_at')}

    @classmethod
    def _material_core(cls, value):
        # Reference snapshots are append-only observations. Their identity is not material when the actual
        # window sessions and accepted DailyMarket snapshots are unchanged.
        return {key: item for key, item in cls._review_core(value).items()
                if key != 'calendar_reference_snapshot_id'}

    @staticmethod
    def _finite(value):
        return type(value) in (int, float) and math.isfinite(value)

    def _validate_review(self, value, path, bundle=None):
        if not isinstance(value, dict):
            raise ValueError('复盘记录必须是对象。')
        required = {
            'format', 'selection_id', 'selection_kind', 'candidate_set_id', 'case_id', 'definition_id',
            'playbook_key', 'playbook_version', 'frame', 'trading_day', 'selection_as_of',
            'candidate_completeness', 'candidate_pit_status', 'candidate_count', 'window', 'window_label',
            'reference', 'sessions', 'daily_market_snapshots', 'calendar_reference_snapshot_id',
            'data_cutoff_at', 'symbols', 'groups', 'spread_selected_minus_unselected',
            'unselected_above_selected_mean', 'selected_below_unselected_mean', 'semantics', 'qualification',
            'future_data_used', 'policy', 'limitations', 'review_hash', 'created_at',
        }
        missing = sorted(required - set(value))
        if missing:
            raise ValueError('复盘记录缺少字段：' + ', '.join(missing[:10]))
        if value['format'] != FORMAT:
            raise ValueError('复盘记录 format 无效。')
        core = self._review_core(value)
        if not isinstance(value['review_hash'], str) or value['review_hash'] != digest(core):
            raise ValueError('复盘记录 review_hash 校验失败。')
        try:
            created = datetime.fromisoformat(value['created_at'])
            trading_day = date.fromisoformat(value['trading_day'])
        except (TypeError, ValueError):
            raise ValueError('复盘记录日期字段无效。') from None
        if created.tzinfo is None:
            raise ValueError('复盘记录 created_at 必须带时区。')
        window = value['window']
        if type(window) is not int or not 0 <= window <= MAX_WINDOW or value['window_label'] != _label(window):
            raise ValueError('复盘记录窗口身份无效。')
        if path.parent.name != value['selection_id'] or path.name != value['window_label'] + '.json':
            raise ValueError('复盘记录路径与 selection/window 身份不一致。')
        if not isinstance(value['sessions'], list) or len(value['sessions']) != (1 if window == 0 else window):
            raise ValueError('复盘记录 sessions 形状无效。')
        try:
            sessions = [date.fromisoformat(item) for item in value['sessions']]
        except (TypeError, ValueError):
            raise ValueError('复盘记录 sessions 日期无效。') from None
        if sessions != sorted(set(sessions)) or (window == 0 and sessions != [trading_day]) \
                or (window > 0 and any(day <= trading_day for day in sessions)):
            raise ValueError('复盘记录 sessions 与窗口不一致。')
        snapshots = value['daily_market_snapshots']
        if not isinstance(snapshots, list) or len(snapshots) != len(sessions):
            raise ValueError('复盘记录 DailyMarket 快照形状无效。')
        for day, snapshot in zip(value['sessions'], snapshots):
            if not isinstance(snapshot, dict) or snapshot.get('date') != day \
                    or not all(isinstance(snapshot.get(key), str) and snapshot[key]
                               for key in ('snapshot_id', 'content_hash', 'fetched_at')):
                raise ValueError('复盘记录 DailyMarket 快照身份无效。')
        symbols = value['symbols']
        if type(value['candidate_count']) is not int or value['candidate_count'] < 0 \
                or not isinstance(symbols, list) or len(symbols) != value['candidate_count']:
            raise ValueError('复盘记录证券数量无效。')
        seen = set()
        for row in symbols:
            if not isinstance(row, dict) or set(row) != {'symbol', 'group', 'status', 'return', 'suspended_sessions'} \
                    or not isinstance(row['symbol'], str) or not row['symbol'] or row['symbol'] in seen \
                    or row['group'] not in GROUPS or row['status'] not in ('MEASURED', 'NO_DAILY_ROW', 'NO_PRICE') \
                    or type(row['suspended_sessions']) is not int or row['suspended_sessions'] < 0 \
                    or (row['return'] is not None and not self._finite(row['return'])):
                raise ValueError('复盘记录逐证券结果形状无效。')
            seen.add(row['symbol'])
        groups = value['groups']
        if not isinstance(groups, dict) or set(groups) != {*GROUPS, 'CANDIDATE_POOL'}:
            raise ValueError('复盘记录分组字段无效。')
        for group in (*GROUPS, 'CANDIDATE_POOL'):
            returns = [row['return'] for row in symbols if group == 'CANDIDATE_POOL' or row['group'] == group]
            if groups[group] != _stats(returns):
                raise ValueError('复盘记录分组统计与逐证券结果不一致。')
        selected_mean = groups['SELECTED']['mean']
        unselected_mean = groups['UNSELECTED']['mean']
        expected_spread = (selected_mean - unselected_mean
                           if selected_mean is not None and unselected_mean is not None else None)
        if value['spread_selected_minus_unselected'] != expected_spread:
            raise ValueError('复盘记录收益差与分组统计不一致。')
        if value['semantics'] != SEMANTICS or value['qualification'] != 'research_only' \
                or value['future_data_used'] is not False or value['policy'] != POLICY \
                or not isinstance(value['limitations'], list):
            raise ValueError('复盘记录研究语义或策略边界无效。')
        if bundle is not None:
            selection, candidates, case = bundle
            identities = {
                'selection_id': selection['selection_id'], 'selection_kind': selection['kind'],
                'candidate_set_id': candidates['candidate_set_id'], 'case_id': case['case_id'],
                'definition_id': candidates['definition_id'], 'playbook_key': case['playbook_key'],
                'playbook_version': case['playbook_version'], 'frame': candidates['frame'],
                'trading_day': candidates['trading_day'], 'selection_as_of': selection['as_of'],
                'candidate_completeness': candidates['completeness'], 'candidate_pit_status': candidates['pit_status'],
                'candidate_count': candidates['candidate_count'],
            }
            if any(value.get(key) != expected for key, expected in identities.items()):
                raise ValueError('复盘记录与冻结 Selection/CandidateSet/Case 身份不一致。')
            if seen != set(candidates['candidate_symbols']):
                raise ValueError('复盘记录证券集合与冻结 CandidateSet 不一致。')
            selected = set(selection['selected_symbols'])
            if any((row['symbol'] in selected) != (row['group'] == 'SELECTED') for row in symbols):
                raise ValueError('复盘记录选中分组与冻结 Selection 不一致。')
        return value

    def _read_review(self, path, bundle=None):
        if path.is_symlink() or not path.is_file():
            raise SelectionOutcomeError('CORRUPT_REVIEW', '复盘记录不能是符号链接且必须是普通文件。')
        try:
            value = read_checked(path)
            return self._validate_review(value, path, bundle)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise SelectionOutcomeError('CORRUPT_REVIEW', str(error)) from None

    @staticmethod
    def _publish_once(path, value):
        """Publish complete bytes while the caller holds _freeze_lock, including on exFAT.

        Hard links add kernel-level no-replace protection where supported. On filesystems without
        links, all service writers still serialize through the lock and recheck before atomic rename;
        unrelated programs writing these internal records do not participate in that lock contract.
        """
        temporary = path.with_name('.publish-' + str(uuid4()) + '.pending')
        try:
            write_checked(temporary, value)
            try:
                os.link(temporary, path)
            except OSError as error:
                if error.errno not in {errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS}:
                    raise
                if path.exists() or path.is_symlink():
                    raise FileExistsError(errno.EEXIST, 'Review already exists', str(path)) from None
                os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _freeze(self, folder, core):
        review_hash = digest(core)
        path = folder / (core['window_label'] + '.json')
        bundle = self._selection_bundle(core['selection_id'])
        with self._freeze_lock():
            folder.mkdir(parents=True, exist_ok=True)
            if folder.is_symlink() or path.is_symlink():
                raise SelectionOutcomeError('INVALID_WORKSPACE', '选择结果复盘记录路径不能是符号链接。')
            if path.exists():
                old = self._read_review(path, bundle)
                if digest(self._material_core(old)) != digest(self._material_core(core)):
                    raise SelectionOutcomeError('REVIEW_CONFLICT', '后来数据改变了已冻结的选择结果复盘，需人工核对交易日历或 DailyMarket 修订。')
                return old, False
            stamp = self.now_fn()
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise SelectionOutcomeError('INVALID_CLOCK', '时钟必须带时区。')
            value = {**core, 'review_hash': review_hash, 'created_at': stamp.astimezone(timezone.utc).isoformat()}
            try:
                self._publish_once(path, value)
            except FileExistsError:
                # A non-cooperating writer appeared despite the service lock. Never replace it; validate and compare.
                old = self._read_review(path, bundle)
                if digest(self._material_core(old)) == digest(self._material_core(core)):
                    return old, False
                raise SelectionOutcomeError('REVIEW_CONFLICT', '并发请求提交了不同的选择结果复盘；原冻结记录未覆盖。') from None
            return value, True

    # ---- public API -------------------------------------------------------------------------------------------------
    def build(self, selection_id, windows=None):
        """Freeze every window of one selection that is computable now; report the rest as pending."""
        self._guard()
        self._refresh_inputs()
        windows = _windows(windows)
        selection, candidates, case = self._selection_bundle(selection_id)
        folder = self._folder(selection_id)
        records, created, pending = [], 0, []
        for window in windows:
            sessions = self._sessions(candidates['trading_day'], window, candidates['frame'])
            if sessions is None:
                pending.append({'window': _label(window), 'status': 'NOT_APPLICABLE',
                                'reason': 'D0 只对盘前 PREP 选择计算；盘中选择的当日走势包含选择后才知道的价格。'})
                continue
            if not sessions:
                pending.append({'window': _label(window), 'status': 'NOT_YET_OBSERVED',
                                'reason': '交易日历中选择日之后的交易日不足（尚未到达或参考快照未更新）。'})
                continue
            core, blocked = self._measure(selection, candidates, case, window, sessions)
            if blocked is not None:
                pending.append(blocked)
                continue
            value, new = self._freeze(folder, core)
            records.append(value)
            created += int(new)
        return {'selection_id': selection_id, 'records': records, 'created': created, 'pending': pending,
                'strategy_intent_mutated': False, 'weights_mutated': False}

    def auto_all(self, windows=None, kind='', limit=2000):
        """Review every stored selection (optionally one kind); one selection's failure never stops the others."""
        if type(limit) is not int or not 1 <= limit <= 20000:
            raise SelectionOutcomeError('INVALID_ARGUMENT', 'limit 必须为1–20000。')
        windows = _windows(windows)
        selections, offset = [], 0
        while len(selections) < limit:
            try:
                page = self.store.list_selections(kind=kind, offset=offset, limit=min(200, limit - len(selections)))
            except PlaybookError as error:
                if error.code == 'NOT_FOUND':
                    break
                raise SelectionOutcomeError(error.code, str(error)) from None
            rows = page['records']
            selections.extend(rows)
            offset += len(rows)
            if not rows or offset >= page['total']:
                break
        created, frozen, errors, pending = 0, 0, [], 0
        for row in selections:
            for window in windows:
                try:
                    result = self.build(row['selection_id'], [window])
                except (SelectionOutcomeError, OSError, ValueError, KeyError, TypeError) as error:
                    errors.append({'selection_id': row['selection_id'], 'window': _label(window),
                                   'code': getattr(error, 'code', type(error).__name__), 'message': str(error)[:300]})
                    continue
                created += result['created']
                frozen += len(result['records'])
                pending += len(result['pending'])
        attempted = len(selections) * len(windows)
        failed = len(errors)
        status = 'SUCCESS' if not errors else ('FAILED' if failed == attempted else 'PARTIAL_FAILURE')
        return {'status': status, 'selections_checked': len(selections), 'windows_attempted': attempted,
                'windows_frozen': frozen, 'windows_created': created, 'windows_pending': pending,
                'windows_failed': failed, 'errors': errors, 'strategy_intent_mutated': False,
                'weights_mutated': False}

    def _archive_error(self, path, message):
        try:
            relative = path.relative_to(self.root).as_posix()
        except ValueError:
            relative = path.name
        return {'code': 'CORRUPT_REVIEW', 'path': relative, 'message': str(message)[:300]}

    def _records(self, selection_id=None):
        """Return every valid record plus every archive error; invalid records never enter aggregates."""
        self._guard()
        if not self.root.exists():
            return [], []
        rows, errors = [], []
        if selection_id is not None:
            folders = [self.root / selection_id]
        else:
            folders = sorted(path for path in self.root.iterdir() if path.name != '.freeze.lock')
        for folder in folders:
            if not folder.exists() and not folder.is_symlink():
                continue
            if folder.is_symlink() or not folder.is_dir():
                errors.append(self._archive_error(folder, '选择结果复盘 selection 路径必须是普通目录，不能是符号链接。'))
                continue
            try:
                bundle = self._selection_bundle(folder.name)
            except SelectionOutcomeError as error:
                errors.append(self._archive_error(folder, 'selection 路径身份无效：' + str(error)))
                continue
            for path in sorted(folder.iterdir()):
                if path.name.startswith('.publish-') and path.name.endswith('.pending'):
                    continue
                if path.suffix != '.json':
                    continue
                try:
                    rows.append(self._read_review(path, bundle))
                except SelectionOutcomeError as error:
                    errors.append(self._archive_error(path, str(error)))
        return rows, errors

    @staticmethod
    def _matches(row, definition_id, kind, frame):
        return ((not definition_id or row['definition_id'] == definition_id)
                and (not kind or row['selection_kind'] == kind) and (not frame or row['frame'] == frame))

    @staticmethod
    def compact(row):
        """Record without the per-symbol list, for tools and listings with size limits."""
        return {key: value for key, value in row.items() if key != 'symbols'}

    def get(self, selection_id):
        self._folder(selection_id)
        rows, errors = self._records(selection_id)
        return {'selection_id': selection_id, 'records': sorted(rows, key=lambda row: row['window']),
                'errors': errors, 'incomplete': bool(errors)}

    def list(self, definition_id='', kind='', frame='', offset=0, limit=200, full=False):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000 \
                or type(full) is not bool:
            raise SelectionOutcomeError('INVALID_ARGUMENT', 'offset/limit/full 无效。')
        records, errors = self._records()
        rows = [row if full else self.compact(row) for row in records
                if self._matches(row, definition_id, kind, frame)]
        rows.sort(key=lambda row: (row['trading_day'], row['selection_id'], row['window']), reverse=True)
        return {'total': len(rows), 'records': rows[offset:offset + limit], 'errors': errors,
                'incomplete': bool(errors)}

    def summary(self, definition_id='', kind='', frame=''):
        """Descriptive spread of selected vs unselected per playbook version, kind, frame and window."""
        records, errors = self._records()
        groups = {}
        for row in records:
            if not self._matches(row, definition_id, kind, frame):
                continue
            key = (row['playbook_key'], row['playbook_version'], row['selection_kind'], row['frame'], row['window'])
            groups.setdefault(key, []).append(row)
        result = []
        for (playbook_key, version, selection_kind, frame_name, window), rows in sorted(groups.items()):
            spreads = [row['spread_selected_minus_unselected'] for row in rows
                       if row['spread_selected_minus_unselected'] is not None]
            if not spreads:
                status = 'NO_SAMPLES'
            elif len(spreads) < MIN_SUMMARY_SAMPLES:
                status = 'INSUFFICIENT_SAMPLES'
            else:
                status = 'OBSERVATION_ONLY'
            result.append({
                'playbook_key': playbook_key, 'playbook_version': version, 'selection_kind': selection_kind,
                'frame': frame_name, 'window_label': _label(window), 'selections': len(rows),
                'selections_with_both_groups': len(spreads),
                'no_trade_selections': sum(1 for row in rows if row['groups']['SELECTED']['total'] == 0),
                'spread_mean': math.fsum(spreads) / len(spreads) if spreads else None,
                'spread_median': median(spreads) if spreads else None,
                'positive_spread_share': sum(1 for value in spreads if value > 0) / len(spreads) if spreads else None,
                'sample_status': status,
            })
        return {'format': FORMAT + '-summary', 'rows': result, 'semantics': SEMANTICS, 'policy': dict(POLICY),
                'note': '描述性观察：未做显著性检验；不同 kind/frame/window 不合并；不是 Alpha、可成交收益或调权依据。',
                'limitations': list(LIMITATIONS), 'errors': errors, 'incomplete': bool(errors)}


__all__ = ['DEFAULT_WINDOWS', 'FORMAT', 'LIMITATIONS', 'SEMANTICS', 'SelectionOutcomeError', 'SelectionOutcomeService']

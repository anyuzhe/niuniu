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

from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
import math

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

    def _freeze(self, folder, core):
        review_hash = digest(core)
        path = folder / (core['window_label'] + '.json')
        if path.exists():
            try:
                old = read_checked(path)
            except (OSError, ValueError) as error:
                raise SelectionOutcomeError('CORRUPT_REVIEW', str(error)) from None
            if old.get('review_hash') != review_hash:
                raise SelectionOutcomeError('REVIEW_CONFLICT', '后来数据改变了已冻结的选择结果复盘，需人工核对 DailyMarket 修订。')
            return old, False
        stamp = self.now_fn()
        if not isinstance(stamp, datetime) or stamp.tzinfo is None:
            raise SelectionOutcomeError('INVALID_CLOCK', '时钟必须带时区。')
        value = {**core, 'review_hash': review_hash, 'created_at': stamp.astimezone(timezone.utc).isoformat()}
        folder.mkdir(parents=True, exist_ok=True)
        write_checked(path, value)
        return value, True

    # ---- public API -------------------------------------------------------------------------------------------------
    def build(self, selection_id, windows=None):
        """Freeze every window of one selection that is computable now; report the rest as pending."""
        self._guard()
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
            try:
                result = self.build(row['selection_id'], windows)
            except (SelectionOutcomeError, OSError, ValueError, KeyError, TypeError) as error:
                errors.append({'selection_id': row['selection_id'], 'code': getattr(error, 'code', type(error).__name__),
                               'message': str(error)[:300]})
                continue
            created += result['created']
            frozen += len(result['records'])
            pending += len(result['pending'])
        return {'selections_checked': len(selections), 'windows_frozen': frozen, 'windows_created': created,
                'windows_pending': pending, 'errors': errors, 'strategy_intent_mutated': False, 'weights_mutated': False}

    def _records(self):
        self._guard()
        if not self.root.exists():
            return []
        rows = []
        for folder in sorted(p for p in self.root.iterdir() if p.is_dir() and not p.is_symlink()):
            for path in sorted(folder.glob('D*.json')):
                if path.is_symlink():
                    continue
                try:
                    value = read_checked(path)
                except (OSError, ValueError):
                    continue
                if value.get('format') == FORMAT:
                    rows.append(value)
        return rows

    @staticmethod
    def _matches(row, definition_id, kind, frame):
        return ((not definition_id or row['definition_id'] == definition_id)
                and (not kind or row['selection_kind'] == kind) and (not frame or row['frame'] == frame))

    @staticmethod
    def compact(row):
        """Record without the per-symbol list, for tools and listings with size limits."""
        return {key: value for key, value in row.items() if key != 'symbols'}

    def get(self, selection_id):
        folder = self._folder(selection_id)
        rows = []
        if folder.exists():
            for path in sorted(folder.glob('D*.json')):
                try:
                    rows.append(read_checked(path))
                except (OSError, ValueError) as error:
                    raise SelectionOutcomeError('CORRUPT_REVIEW', str(error)) from None
        return {'selection_id': selection_id, 'records': sorted(rows, key=lambda row: row['window'])}

    def list(self, definition_id='', kind='', frame='', offset=0, limit=200):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise SelectionOutcomeError('INVALID_ARGUMENT', 'offset/limit 无效。')
        rows = [self.compact(row) for row in self._records() if self._matches(row, definition_id, kind, frame)]
        rows.sort(key=lambda row: (row['trading_day'], row['selection_id'], row['window']), reverse=True)
        return {'total': len(rows), 'records': rows[offset:offset + limit]}

    def summary(self, definition_id='', kind='', frame=''):
        """Descriptive spread of selected vs unselected per playbook version, kind, frame and window."""
        groups = {}
        for row in self._records():
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
                'limitations': list(LIMITATIONS)}


__all__ = ['DEFAULT_WINDOWS', 'FORMAT', 'LIMITATIONS', 'SEMANTICS', 'SelectionOutcomeError', 'SelectionOutcomeService']

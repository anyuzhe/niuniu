"""Limit-up / limit-down event library over retrospective full-market daily captures.

Every event row is a stock session that touched the reconstructed limit-up or limit-down
price, or followed a limit-up close or a broken board. Features are known at the T-day
close; label columns use T+1/T+2 sessions and must never be used as features. Limits
come from the dated research regime, so the library is research_only and never certifies
strict PIT, official MarketRules or a PIT Universe.
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5
import hashlib
import io
import json
import re

import polars as pl

from quantlab.data.forward_daily import EXTENSION_FORMAT, ForwardDailyError, resolve_forward
from quantlab.data.retro_daily import RetroDailyError, RetroDailyStore
from quantlab.storage.codec import digest, encode

from .limit_states import LIMIT_STATE_VERSION, annotate_limit_states
from .price_limit_regime import REGIME_VERSION

FORMAT = 'limit-event-library-v1'
BUILDER_VERSION = 'limit-event-builder-v1'
BUILD = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
SOURCES = ('price_limit_regime.py', 'limit_states.py', 'limit_events.py', '../data/forward_daily.py')
FEATURE_COLUMNS = (
    'date', 'code', 'board', 'limit_rate', 'limit_rule_reason', 'is_st', 'listing_date', 'sessions_since_listing',
    'preclose', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turn', 'limit_up_price', 'limit_down_price',
    'day_ret', 'open_gap', 'amplitude', 'ret_5d', 'ret_20d', 'amount_rank_pct',
    'is_limit_up_close', 'touched_limit_up', 'is_broken_board', 'is_one_word_limit_up', 'is_t_board',
    'is_limit_down_close', 'touched_limit_down', 'is_limit_up_to_down', 'is_limit_down_to_up',
    'limit_up_streak', 'limit_ups_5d', 'limit_ups_10d', 'is_first_board',
    'prev_is_limit_up_close', 'prev_limit_up_streak', 'prev_is_broken_board',
)
LABEL_COLUMNS = (
    't1_date', 't1_tradable', 't1_open_ret', 't1_high_ret', 't1_low_ret', 't1_close_ret',
    't1_open_at_limit_up', 't1_open_at_limit_down', 't1_is_limit_up_close', 't1_touched_limit_up',
    't1_is_broken_board', 't1_is_limit_down_close', 't1_limit_up_streak',
    't2_date', 't2_tradable', 't2_open_ret_day', 't2_close_ret_day',
    'ret_close_to_t2close', 'ret_t1open_to_t1close', 'ret_t1open_to_t2open', 'ret_t1open_to_t2close',
)
LIMITATIONS = [
    '涨跌停价由按日期生效的研究制度表推算，不是官方逐日 MarketRules；资格为 research_only。',
    '输入是 Baostock 回溯日线与抓取时的 stock_basic 快照，不是 PIT Universe，也不认证历史首次发布时间。',
    '特征只使用 T 日收盘已知的数据；t1_/t2_/ret_ 标签使用未来交易日，严禁作为特征。',
    '标签收益以交易所前收为基准复利计算（已含除权除息调整），未计费用、滑点和成交可行性；可执行收益须经 AR-3.2 成交模型。',
    '新股无涨跌幅期、未建模制度、临近退市（30 个交易日）与价格越过推算涨跌停价的行不进入事件。',
    '不覆盖北交所；ret_5d/ret_20d 按可交易交易日复利，停牌期间不计入窗口。',
]


class LimitEventError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def code_fingerprint():
    folder = Path(__file__).resolve().parent
    parts = {name.replace('../', ''): hashlib.sha256((folder / name).resolve().read_bytes()).hexdigest() for name in SOURCES}
    return {'files': parts, 'digest': digest(parts)}


def _checked(value):
    return {**value, 'checksum': digest(value)}


def _verify_checked(value, what):
    if not isinstance(value, dict) or 'checksum' not in value:
        raise LimitEventError('CORRUPT_ARCHIVE', what + ' 缺少 checksum。')
    core = {k: v for k, v in value.items() if k != 'checksum'}
    if value['checksum'] != digest(core):
        raise LimitEventError('CORRUPT_ARCHIVE', what + ' checksum 校验失败。')
    return core


def _position_ge(calendar, day):
    index = bisect_left(calendar, day)
    return index if index < len(calendar) else None


BATCH_SYMBOLS = 500


def split_inputs(inputs):
    """Recover the build request (retro capture ids, forward_through) from manifest ``inputs``."""
    captures = [item['capture_id'] for item in inputs if 'capture_id' in item]
    forward = [item for item in inputs if item.get('kind') == EXTENSION_FORMAT]
    if len(forward) > 1 or len(captures) + len(forward) != len(inputs):
        raise LimitEventError('CORRUPT_ARCHIVE', 'manifest inputs 结构无效。')
    return captures, (forward[0]['through'] if forward else None)


def resolve_inputs(store, capture_ids, forward_through=None):
    """Validate complete, contiguous retro captures (plus optional DailyMarket forward days) without loading retro data."""
    if not isinstance(capture_ids, (list, tuple)) or not capture_ids or len(set(capture_ids)) != len(capture_ids):
        raise LimitEventError('INVALID_ARGUMENT', 'capture_ids 必须为不重复的非空列表。')
    try:
        plans = sorted((store.plan(cid, with_symbols=True) for cid in capture_ids), key=lambda p: p['start'])
        for previous, current in zip(plans, plans[1:]):
            if date.fromisoformat(previous['end']) + timedelta(days=1) != date.fromisoformat(current['start']):
                raise LimitEventError('NON_CONTIGUOUS_INPUTS', f"capture {previous['capture_id']} 与 {current['capture_id']} 的区间不连续。")
        calendar, inputs = [], []
        for plan in plans:
            evidence = store.panel_evidence(plan['capture_id'])
            calendar.extend(date.fromisoformat(day) for day in store.trading_days(plan['capture_id']))
            inputs.append({'capture_id': plan['capture_id'], 'start': plan['start'], 'end': plan['end'],
                           'manifest_digest': evidence['manifest_digest'], 'rows': evidence['rows'],
                           'stock_basic_content_hash': plan['stock_basic_content_hash'],
                           'calendar_content_hash': plan['calendar_content_hash']})
        reference = store.reference(plans[-1]['capture_id'])['stock_basic']
    except RetroDailyError as error:
        raise LimitEventError(error.code, str(error)) from None
    if any(b <= a for a, b in zip(calendar, calendar[1:])):
        raise LimitEventError('CORRUPT_INPUT', '交易日历未严格递增。')
    symbols = sorted({s for plan in plans for s in plan['symbols']})
    resolved = {'plans': plans, 'calendar': calendar, 'reference': reference, 'inputs': inputs, 'symbols': symbols, 'forward': None}
    if forward_through is not None:
        try:
            forward = resolve_forward(store.output, calendar, forward_through)
        except ForwardDailyError as error:
            raise LimitEventError(error.code, str(error)) from None
        resolved.update(calendar=calendar + forward['days'], reference=forward['stock_basic'], inputs=inputs + [forward['evidence']],
                        symbols=sorted(set(symbols) | set(forward['symbols'])), forward=forward)
    return resolved


def _read_batch(store, resolved, batch):
    frames = []
    for plan in resolved['plans']:
        members = set(plan['symbols'])
        subset = [s for s in batch if s in members]
        if subset:
            try:
                panel, _ = store.read_panel(plan['capture_id'], symbols=subset)
            except RetroDailyError as error:
                raise LimitEventError(error.code, str(error)) from None
            frames.append(panel)
    if resolved.get('forward') is not None:
        frames.append(resolved['forward']['panel'].filter(pl.col('code').is_in(list(batch))))
    panel = pl.concat(frames, how='vertical').sort('code', 'date')
    if panel.select(pl.struct('code', 'date').is_duplicated().any()).item():
        raise LimitEventError('CORRUPT_INPUT', '输入面板存在重复证券日期。')
    if panel.filter(~pl.col('date').is_in(resolved['calendar'])).height:
        raise LimitEventError('CORRUPT_INPUT', '输入面板含日历外日期。')
    return panel


def iter_state_batches(store, resolved, batch_symbols=BATCH_SYMBOLS):
    """Yield annotated states per symbol batch; every state feature is a per-security sequence."""
    if type(batch_symbols) is not int or batch_symbols < 1:
        raise LimitEventError('INVALID_ARGUMENT', 'batch_symbols 必须为正整数。')
    symbols = resolved['symbols']
    for index in range(0, len(symbols), batch_symbols):
        panel = _read_batch(store, resolved, symbols[index:index + batch_symbols])
        yield prepare_states(panel, resolved['calendar'], resolved['reference'])


def load_inputs(store, capture_ids, forward_through=None):
    """Load complete, contiguous retro captures in memory (small workspaces and tests)."""
    resolved = resolve_inputs(store, capture_ids, forward_through)
    panel = _read_batch(store, resolved, resolved['symbols'])
    return panel, resolved['calendar'], resolved['reference'], resolved['inputs']


def _listing_columns(panel, calendar, reference):
    listing, delisting = {}, {}
    for code, _name, ipo, out, kind, _status in reference:
        if ipo:
            listing[code] = date.fromisoformat(ipo)
        if out:
            delisting[code] = date.fromisoformat(out)
    calendar_frame = pl.DataFrame({'date': calendar, '_pos': list(range(len(calendar)))},
                                  schema={'date': pl.Date, '_pos': pl.Int64})
    codes = panel['code'].unique().to_list()
    rows = []
    first, last = calendar[0], calendar[-1]
    for code in codes:
        listed = listing.get(code)
        delisted = delisting.get(code)
        listing_pos = _position_ge(calendar, listed) if listed is not None and first <= listed <= last else None
        delisting_pos = _position_ge(calendar, delisted) if delisted is not None and delisted <= last else None
        rows.append({'code': code, 'listing_date': listed, '_listing_pos': listing_pos, '_delisting_pos': delisting_pos})
    codes_frame = pl.DataFrame(rows, schema={'code': pl.String, 'listing_date': pl.Date,
                                             '_listing_pos': pl.Int64, '_delisting_pos': pl.Int64})
    frame = panel.join(calendar_frame, on='date', how='left').join(codes_frame, on='code', how='left')
    since = pl.when(pl.col('_listing_pos').is_not_null() & (pl.col('_pos') >= pl.col('_listing_pos'))) \
        .then(pl.col('_pos') - pl.col('_listing_pos') + 1)
    to_delisting = pl.when(pl.col('_delisting_pos').is_not_null() & (pl.col('_delisting_pos') >= pl.col('_pos'))) \
        .then(pl.col('_delisting_pos') - pl.col('_pos')).when(pl.col('_delisting_pos').is_not_null()).then(0)
    return frame.with_columns(since.cast(pl.Int64).alias('sessions_since_listing'),
                              to_delisting.cast(pl.Int64).alias('sessions_to_delisting'))


def prepare_states(panel, calendar, reference):
    """Annotated full panel with calendar position, listing sequence and T-day returns."""
    frame = _listing_columns(panel, calendar, reference).with_columns(
        (pl.col('tradestatus') == 1).alias('tradable'), (pl.col('isST') == 1).alias('is_st'))
    states = annotate_limit_states(frame).sort('code', 'date')
    tradable = pl.col('tradable')
    return states.with_columns(
        pl.when(tradable).then(pl.col('close') / pl.col('preclose') - 1).alias('day_ret'),
        pl.when(tradable).then(pl.col('open') / pl.col('preclose') - 1).alias('open_gap'),
        pl.when(tradable).then((pl.col('high') - pl.col('low')) / pl.col('preclose')).alias('amplitude'),
    )


def _events_from_states(states):
    """Per-security event rows (without the cross-sectional amount rank) plus additive statistics."""
    tradable = pl.col('tradable')
    compounding = states.filter(tradable).select('code', 'date', 'day_ret').with_columns(
        (1 + pl.col('day_ret')).log().alias('_log'))
    compounding = compounding.with_columns(
        (pl.col('_log').rolling_sum(window_size=5, min_samples=5).over('code').exp() - 1).alias('ret_5d'),
        (pl.col('_log').rolling_sum(window_size=20, min_samples=20).over('code').exp() - 1).alias('ret_20d'),
    ).select('code', 'date', 'ret_5d', 'ret_20d')
    amounts = states.filter(tradable & pl.col('amount').is_not_null()).select('code', 'date', 'amount')
    # A previous session whose prices breach the reconstructed limits has unreliable states
    # (usually an unmodeled regime such as delisting consolidation), so it cannot trigger events.
    previous_violation = states.filter(tradable).select('code', 'date', 'limit_price_violation').with_columns(
        pl.col('limit_price_violation').fill_null(False).shift(1).over('code').fill_null(False).alias('_prev_violation')
    ).select('code', 'date', '_prev_violation')
    states = states.join(compounding, on=['code', 'date'], how='left')
    states = states.join(previous_violation, on=['code', 'date'], how='left').sort('code', 'date')
    nxt = {}
    for step in (1, 2):
        prefix = f't{step}_'
        shifted = [pl.col(c).shift(-step).over('code').alias(prefix + c) for c in (
            'date', '_pos', 'tradable', 'open', 'high', 'low', 'close', 'preclose', 'limit_up_price', 'limit_down_price',
            'is_limit_up_close', 'touched_limit_up', 'is_broken_board', 'is_limit_down_close', 'limit_up_streak')]
        nxt[step] = shifted
    states = states.with_columns(*nxt[1], *nxt[2])
    for step in (1, 2):
        prefix = f't{step}_'
        aligned = pl.col(prefix + '_pos') == pl.col('_pos') + step
        states = states.with_columns(
            pl.when(aligned).then(pl.col(prefix + 'date')).alias(prefix + 'date'),
            pl.when(aligned).then(pl.col(prefix + 'tradable').fill_null(False)).otherwise(False).alias(prefix + 'tradable'))
    t1_ok, t2_ok = pl.col('t1_tradable'), pl.col('t1_tradable') & pl.col('t2_tradable')

    def cents(name):
        return (pl.col(name) * 100).round(0).cast(pl.Int64)

    states = states.with_columns(
        pl.when(t1_ok).then(pl.col('t1_open') / pl.col('t1_preclose') - 1).alias('t1_open_ret'),
        pl.when(t1_ok).then(pl.col('t1_high') / pl.col('t1_preclose') - 1).alias('t1_high_ret'),
        pl.when(t1_ok).then(pl.col('t1_low') / pl.col('t1_preclose') - 1).alias('t1_low_ret'),
        pl.when(t1_ok).then(pl.col('t1_close') / pl.col('t1_preclose') - 1).alias('t1_close_ret'),
        pl.when(t1_ok & pl.col('t1_limit_up_price').is_not_null()).then(cents('t1_open') == cents('t1_limit_up_price')).alias('t1_open_at_limit_up'),
        pl.when(t1_ok & pl.col('t1_limit_down_price').is_not_null()).then(cents('t1_open') == cents('t1_limit_down_price')).alias('t1_open_at_limit_down'),
        pl.when(t1_ok).then(pl.col('t1_is_limit_up_close')).alias('t1_is_limit_up_close'),
        pl.when(t1_ok).then(pl.col('t1_touched_limit_up')).alias('t1_touched_limit_up'),
        pl.when(t1_ok).then(pl.col('t1_is_broken_board')).alias('t1_is_broken_board'),
        pl.when(t1_ok).then(pl.col('t1_is_limit_down_close')).alias('t1_is_limit_down_close'),
        pl.when(t1_ok).then(pl.col('t1_limit_up_streak')).alias('t1_limit_up_streak'),
        pl.when(pl.col('t2_tradable')).then(pl.col('t2_open') / pl.col('t2_preclose') - 1).alias('t2_open_ret_day'),
        pl.when(pl.col('t2_tradable')).then(pl.col('t2_close') / pl.col('t2_preclose') - 1).alias('t2_close_ret_day'),
    )
    states = states.with_columns(
        pl.when(t2_ok).then((1 + pl.col('t1_close_ret')) * (1 + pl.col('t2_close_ret_day')) - 1).alias('ret_close_to_t2close'),
        pl.when(t1_ok).then(pl.col('t1_close') / pl.col('t1_open') - 1).alias('ret_t1open_to_t1close'),
        pl.when(t2_ok).then(pl.col('t1_close') / pl.col('t1_open') * (1 + pl.col('t2_open_ret_day')) - 1).alias('ret_t1open_to_t2open'),
        pl.when(t2_ok).then(pl.col('t1_close') / pl.col('t1_open') * (1 + pl.col('t2_close_ret_day')) - 1).alias('ret_t1open_to_t2close'),
    )
    eligible = tradable & (pl.col('limit_rule_status') == 'NORMAL') & ~pl.col('limit_price_violation').fill_null(False)
    previous_trigger = (pl.col('prev_is_limit_up_close').fill_null(False) | pl.col('prev_is_broken_board').fill_null(False)) \
        & ~pl.col('_prev_violation').fill_null(False)
    trigger = pl.col('touched_limit_up').fill_null(False) | pl.col('touched_limit_down').fill_null(False) | previous_trigger
    columns = [c for c in FEATURE_COLUMNS if c != 'amount_rank_pct'] + list(LABEL_COLUMNS)
    events = states.filter(eligible & trigger).select(columns)
    trad = states.filter(tradable)
    status_counts = trad.group_by('limit_rule_status', 'limit_rule_reason').len()
    partial = {'panel_rows': states.height, 'tradable_rows': trad.height,
               'rule_counts': {f"{r['limit_rule_status']}:{r['limit_rule_reason']}": r['len'] for r in status_counts.to_dicts()},
               'violation_rows': trad.filter(pl.col('limit_price_violation').fill_null(False)).height}
    return events, partial, amounts


def _finalize_events(parts):
    ranks = pl.concat([amounts for _e, _p, amounts in parts], how='vertical').with_columns(
        (pl.col('amount').rank(method='average').over('date') / pl.len().over('date')).alias('amount_rank_pct')
    ).select('code', 'date', 'amount_rank_pct')
    events = pl.concat([e for e, _p, _a in parts], how='vertical').join(ranks, on=['code', 'date'], how='left')
    events = events.select(list(FEATURE_COLUMNS) + list(LABEL_COLUMNS)).sort('date', 'code')
    rule_counts = {}
    for _e, partial, _a in parts:
        for key, value in partial['rule_counts'].items():
            rule_counts[key] = rule_counts.get(key, 0) + value
    stats = {
        'panel_rows': sum(p['panel_rows'] for _e, p, _a in parts), 'tradable_rows': sum(p['tradable_rows'] for _e, p, _a in parts),
        'rule_counts': dict(sorted(rule_counts.items())), 'violation_rows': sum(p['violation_rows'] for _e, p, _a in parts),
        'events': events.height,
        'limit_up_close': events.filter(pl.col('is_limit_up_close')).height,
        'touched_limit_up': events.filter(pl.col('touched_limit_up')).height,
        'broken_board': events.filter(pl.col('is_broken_board')).height,
        'one_word_limit_up': events.filter(pl.col('is_one_word_limit_up')).height,
        'touched_limit_down': events.filter(pl.col('touched_limit_down')).height,
        'limit_down_close': events.filter(pl.col('is_limit_down_close')).height,
        'max_limit_up_streak': int(events['limit_up_streak'].max() or 0) if events.height else 0,
        'first_event_date': events['date'].min().isoformat() if events.height else None,
        'last_event_date': events['date'].max().isoformat() if events.height else None,
    }
    return events, stats


def build_event_frame(panel, calendar, reference, states=None):
    """In-memory event build for small panels; results equal the batched build."""
    states = prepare_states(panel, calendar, reference) if states is None else states
    return _finalize_events([_events_from_states(states)])


def build_event_frame_batched(store, resolved, batch_symbols=BATCH_SYMBOLS):
    return _finalize_events([_events_from_states(states) for states in iter_state_batches(store, resolved, batch_symbols)])


class LimitEventLibrary:
    def __init__(self, output, now_fn=None, batch_symbols=BATCH_SYMBOLS):
        self.output = Path(output).resolve()
        if not self.output.is_dir():
            raise LimitEventError('INVALID_WORKSPACE', '工作空间不存在。')
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.batch_symbols = batch_symbols
        self.root = self.output / '_limit_research' / 'limit_events'

    def _guard(self):
        for path in (self.output / '_limit_research', self.root):
            if path.is_symlink():
                raise LimitEventError('INVALID_WORKSPACE', '事件库路径不能是符号链接。')

    def _folder(self, build_id):
        if not isinstance(build_id, str) or not BUILD.fullmatch(build_id):
            raise LimitEventError('INVALID_ARGUMENT', 'build_id 无效。')
        folder = self.root / build_id
        if folder.is_symlink():
            raise LimitEventError('INVALID_WORKSPACE', 'build 目录不能是符号链接。')
        return folder

    def build(self, capture_ids, forward_through=None):
        self._guard()
        store = RetroDailyStore(self.output)
        resolved = resolve_inputs(store, list(capture_ids), forward_through)
        calendar, inputs = resolved['calendar'], resolved['inputs']
        fingerprint = code_fingerprint()
        identity = {'builder_version': BUILDER_VERSION, 'regime_version': REGIME_VERSION,
                    'limit_state_version': LIMIT_STATE_VERSION, 'code_fingerprint': fingerprint['digest'], 'inputs': inputs}
        build_id = str(uuid5(NAMESPACE_URL, 'niuniu-limit-events:' + digest(identity)))
        folder = self._folder(build_id)
        if folder.exists():
            return {**self.get(build_id), 'created': False}
        events, stats = build_event_frame_batched(store, resolved, self.batch_symbols)
        stream = io.BytesIO()
        events.write_parquet(stream, compression='zstd')
        payload = stream.getvalue()
        created = self.now_fn()
        if not isinstance(created, datetime) or created.tzinfo is None:
            raise LimitEventError('INVALID_CLOCK', '时钟必须带时区。')
        manifest = {'format': FORMAT, 'build_id': build_id, **identity, 'code_files': fingerprint['files'],
                    'calendar': {'first': calendar[0].isoformat(), 'last': calendar[-1].isoformat(), 'trading_days': len(calendar)},
                    'stats': stats, 'feature_columns': list(FEATURE_COLUMNS), 'label_columns': list(LABEL_COLUMNS),
                    'events_sha256': hashlib.sha256(payload).hexdigest(), 'created_at': created.astimezone(timezone.utc).isoformat(),
                    'qualification': 'research_only', 'limitations': LIMITATIONS}
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / ('.tmp-' + str(uuid4()))
        temporary.mkdir()
        (temporary / 'events.parquet').write_bytes(payload)
        (temporary / 'manifest.json').write_text(encode(_checked(manifest)), encoding='utf-8')
        temporary.replace(folder)
        return {**manifest, 'created': True}

    def get(self, build_id):
        folder = self._folder(build_id)
        path = folder / 'manifest.json'
        if path.is_symlink() or not path.is_file():
            raise LimitEventError('NOT_FOUND', '事件库 build 不存在。')
        manifest = _verify_checked(json.loads(path.read_bytes()), 'manifest.json')
        if manifest.get('format') != FORMAT or manifest.get('build_id') != build_id:
            raise LimitEventError('CORRUPT_ARCHIVE', 'manifest.json 身份无效。')
        return manifest

    def list(self):
        self._guard()
        if not self.root.exists():
            return []
        rows = []
        for folder in sorted(p for p in self.root.iterdir() if p.is_dir() and BUILD.fullmatch(p.name)):
            try:
                manifest = self.get(folder.name)
                captures, through = split_inputs(manifest['inputs'])
                rows.append({'build_id': folder.name, 'created_at': manifest['created_at'], 'calendar': manifest['calendar'],
                             'events': manifest['stats']['events'], 'inputs': captures, 'forward_through': through})
            except (LimitEventError, ValueError):
                rows.append({'build_id': folder.name, 'error': 'CORRUPT_ARCHIVE'})
        return rows

    def read_events(self, build_id, *, start=None, end=None, columns=None):
        manifest = self.get(build_id)
        path = self._folder(build_id) / 'events.parquet'
        if path.is_symlink() or not path.is_file():
            raise LimitEventError('CORRUPT_ARCHIVE', 'events.parquet 缺失。')
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != manifest['events_sha256']:
            raise LimitEventError('CORRUPT_ARCHIVE', 'events.parquet 哈希校验失败。')
        frame = pl.read_parquet(io.BytesIO(payload))
        if frame.height != manifest['stats']['events']:
            raise LimitEventError('CORRUPT_ARCHIVE', 'events.parquet 行数与 manifest 不一致。')
        if start is not None:
            frame = frame.filter(pl.col('date') >= date.fromisoformat(start) if isinstance(start, str) else pl.col('date') >= start)
        if end is not None:
            frame = frame.filter(pl.col('date') <= date.fromisoformat(end) if isinstance(end, str) else pl.col('date') <= end)
        if columns is not None:
            unknown = sorted(set(columns) - set(frame.columns))
            if unknown:
                raise LimitEventError('INVALID_ARGUMENT', '未知列：' + ', '.join(unknown))
            frame = frame.select(list(columns))
        return frame, manifest

    def verify(self, build_id):
        manifest = self.get(build_id)
        stored, _ = self.read_events(build_id)
        fingerprint = code_fingerprint()
        if fingerprint['digest'] != manifest['code_fingerprint']:
            return {'build_id': build_id, 'verified': False, 'reason': 'CODE_CHANGED_REBUILD_REQUIRED'}
        store = RetroDailyStore(self.output)
        try:
            resolved = resolve_inputs(store, *split_inputs(manifest['inputs']))
        except LimitEventError as error:
            return {'build_id': build_id, 'verified': False, 'reason': 'INPUTS_UNAVAILABLE', 'error': error.code}
        if resolved['inputs'] != manifest['inputs']:
            return {'build_id': build_id, 'verified': False, 'reason': 'INPUTS_CHANGED'}
        events, stats = build_event_frame_batched(store, resolved, self.batch_symbols)
        same = events.equals(stored) and stats == manifest['stats']
        return {'build_id': build_id, 'verified': bool(same), 'reason': 'RECOMPUTED_IDENTICAL' if same else 'RECOMPUTED_DIFFERS'}

    def summary(self, build_id):
        events, manifest = self.read_events(build_id)
        year = pl.col('date').dt.year().alias('year')
        up = events.filter(pl.col('is_limit_up_close'))
        by_year = events.group_by(year).agg(
            pl.col('is_limit_up_close').sum().alias('limit_up_close'), pl.col('is_broken_board').sum().alias('broken_board'),
            pl.col('touched_limit_up').sum().alias('touched_limit_up'), pl.col('is_limit_down_close').sum().alias('limit_down_close'),
        ).sort('year').with_columns((pl.col('broken_board') / pl.col('touched_limit_up')).alias('broken_rate'))
        groups = up.with_columns(
            pl.when(pl.col('limit_up_streak') >= 3).then(pl.lit('3+')).otherwise(pl.col('limit_up_streak').cast(pl.String)).alias('streak_group')
        ).group_by('streak_group').agg(
            pl.len().alias('events'), pl.col('t1_is_limit_up_close').mean().alias('t1_limit_up_rate'),
            pl.col('t1_open_ret').mean().alias('t1_open_ret_mean'), pl.col('t1_close_ret').mean().alias('t1_close_ret_mean'),
            pl.col('t1_open_at_limit_up').mean().alias('t1_open_at_limit_up_rate'),
        ).sort('streak_group')
        return {'build_id': build_id, 'calendar': manifest['calendar'], 'stats': manifest['stats'],
                'by_year': by_year.to_dicts(), 'limit_up_close_by_streak': groups.to_dicts(),
                'note': '统计为信号标签均值，未计费用与成交可行性，不代表可执行收益。'}


__all__ = ['FORMAT', 'BUILDER_VERSION', 'BATCH_SYMBOLS', 'split_inputs', 'FEATURE_COLUMNS', 'LABEL_COLUMNS', 'LIMITATIONS', 'LimitEventError',
           'LimitEventLibrary', 'build_event_frame', 'build_event_frame_batched', 'code_fingerprint', 'iter_state_batches',
           'load_inputs', 'prepare_states', 'resolve_inputs']

"""Forward vendor details for limit events: seal times, seal funds, broken counts, billboard, popularity (research_only).

Eastmoney pools keep only about a month, so these details exist only for days archived after
close. Each day's detail table is keyed by (date, code) and reconciled against our daily-bar
limit states for that day: non-ST limit-up closes must match the vendor pool exactly and the
vendor broken / limit-down pools must be subsets of ours. Event studies may only use details
from days that reconciled.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5
import hashlib
import io
import json
import re

import polars as pl

from quantlab.storage.codec import digest, encode

FORMAT = 'limit-event-details-v1'
RULES_VERSION = 'em-event-details-v1'
REQUIRED = {'limit_up': 'em_limit_up_pool', 'broken': 'em_broken_board_pool', 'limit_down': 'em_limit_down_pool'}
OPTIONAL = {'popularity': 'em_popularity_rank', 'billboard': 'em_billboard_daily', 'buy_seats': 'em_billboard_buy_seats',
            'sell_seats': 'em_billboard_sell_seats', 'strong': 'em_strong_pool'}
INSTITUTION_SEAT = '机构专用'
BUILD = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
DETAIL_SCHEMA = {
    'date': pl.Date, 'code': pl.String,
    'em_in_limit_up_pool': pl.Boolean, 'em_limit_up_streak': pl.Int64, 'em_first_seal_time': pl.String, 'em_first_seal_minute': pl.Int64,
    'em_last_seal_time': pl.String, 'em_last_seal_minute': pl.Int64, 'em_seal_fund': pl.Float64, 'em_seal_fund_ratio': pl.Float64,
    'em_broken_times': pl.Int64, 'em_stat_days': pl.Int64, 'em_stat_limit_ups': pl.Int64, 'em_industry': pl.String,
    'em_in_broken_pool': pl.Boolean, 'em_broken_pool_first_seal_time': pl.String, 'em_broken_pool_times': pl.Int64,
    'em_in_limit_down_pool': pl.Boolean, 'em_limit_down_streak': pl.Int64, 'em_down_seal_fund': pl.Float64, 'em_down_open_times': pl.Int64,
    'em_in_strong_pool': pl.Boolean, 'em_popularity_rank': pl.Int64,
    'em_on_billboard': pl.Boolean, 'em_billboard_reasons': pl.Int64, 'em_billboard_net': pl.Float64, 'em_billboard_deal_ratio': pl.Float64,
    'em_billboard_inst_net': pl.Float64, 'em_billboard_inst_seats': pl.Int64,
    'em_day_consistent': pl.Boolean,
}
DETAIL_COLUMNS = tuple(c for c in DETAIL_SCHEMA if c not in ('date', 'code'))
LIMITATIONS = [
    '明细来自东方财富公开网页接口的收盘后归档，是供应商口径（股池不含 ST），只存在于已归档的交易日；资格 research_only。',
    '封板时间、封单资金、炸板次数、龙虎榜均为收盘后才完整可知的信息，只能用于次日及以后的决策，不能用于当日盘中打板的筛选。',
    '只有与日线涨停状态核对一致（非 ST 涨停集合相同、炸板与跌停池为我们结果的子集）的交易日才标记 em_day_consistent。',
    '龙虎榜按成交额最大的一条上榜记录计净买入与机构席位，同一股票多条上榜理由不重复相加。',
]


class EventDetailError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def code_fingerprint():
    payload = Path(__file__).resolve().read_bytes()
    return hashlib.sha256(payload).hexdigest()


def minutes_after_open(expr):
    """HH:MM:SS → minutes of continuous trading after 09:30 (auction seals before 09:30 count as 0; lunch break excluded)."""
    hours = expr.str.slice(0, 2).cast(pl.Int64, strict=False)
    minutes = expr.str.slice(3, 2).cast(pl.Int64, strict=False)
    total = hours * 60 + minutes
    return (pl.when(total.is_null()).then(None)
            .when(total <= 9 * 60 + 30).then(0)
            .when(total <= 11 * 60 + 30).then(total - (9 * 60 + 30))
            .when(total < 13 * 60).then(120)
            .otherwise(pl.min_horizontal(total - 13 * 60 + 120, pl.lit(240)))).cast(pl.Int64)


def detail_frame(day, tables):
    """Build the per-stock detail rows for one day from archived tables (dict of polars frames)."""
    day = date.fromisoformat(day) if isinstance(day, str) else day
    up = tables['limit_up'].select(
        pl.col('symbol').alias('code'), pl.lit(True).alias('em_in_limit_up_pool'), pl.col('limit_up_streak').alias('em_limit_up_streak'),
        pl.col('first_seal_time').alias('em_first_seal_time'), pl.col('last_seal_time').alias('em_last_seal_time'),
        pl.col('seal_fund').alias('em_seal_fund'),
        pl.when(pl.col('float_market_cap') > 0).then(pl.col('seal_fund') / pl.col('float_market_cap')).alias('em_seal_fund_ratio'),
        pl.col('broken_times').alias('em_broken_times'), pl.col('stat_days').alias('em_stat_days'),
        pl.col('stat_limit_ups').alias('em_stat_limit_ups'), pl.col('industry').alias('em_industry'))
    broken = tables['broken'].select(pl.col('symbol').alias('code'), pl.lit(True).alias('em_in_broken_pool'),
                                     pl.col('first_seal_time').alias('em_broken_pool_first_seal_time'),
                                     pl.col('broken_times').alias('em_broken_pool_times'))
    down = tables['limit_down'].select(pl.col('symbol').alias('code'), pl.lit(True).alias('em_in_limit_down_pool'),
                                       pl.col('limit_down_streak').alias('em_limit_down_streak'), pl.col('seal_fund').alias('em_down_seal_fund'),
                                       pl.col('open_times').alias('em_down_open_times'))
    parts = [up, broken, down]
    if tables.get('strong') is not None:
        parts.append(tables['strong'].select(pl.col('symbol').alias('code'), pl.lit(True).alias('em_in_strong_pool')))
    if tables.get('popularity') is not None:
        parts.append(tables['popularity'].select(pl.col('symbol').alias('code'), pl.col('rank').alias('em_popularity_rank')))
    if tables.get('billboard') is not None:
        board = tables['billboard'].filter(pl.col('is_a_share'))
        primary = board.sort(['symbol', 'billboard_deal', 'trade_id'], descending=[False, True, False], nulls_last=True).group_by(
            'symbol', maintain_order=True).agg(pl.len().alias('em_billboard_reasons'), pl.col('billboard_net').first().alias('em_billboard_net'),
                                               pl.col('deal_ratio').first().alias('em_billboard_deal_ratio'), pl.col('trade_id').first().alias('_trade'))
        seats = []
        for key in ('buy_seats', 'sell_seats'):
            if tables.get(key) is not None:
                seats.append(tables[key].filter(pl.col('seat_name') == INSTITUTION_SEAT).select('symbol', 'trade_id', 'seat_code', 'net'))
        if seats:
            inst = pl.concat(seats, how='vertical').unique(subset=['symbol', 'trade_id', 'seat_code', 'net']).join(
                primary.select('symbol', '_trade'), left_on=['symbol', 'trade_id'], right_on=['symbol', '_trade'], how='inner'
            ).group_by('symbol').agg(pl.col('net').sum().alias('em_billboard_inst_net'), pl.len().alias('em_billboard_inst_seats'))
            primary = primary.join(inst, on='symbol', how='left').with_columns(pl.col('em_billboard_inst_seats').fill_null(0))
        parts.append(primary.drop('_trade').rename({'symbol': 'code'}).with_columns(pl.lit(True).alias('em_on_billboard')))
    codes = pl.concat([p.select('code') for p in parts], how='vertical').unique()
    frame = codes
    for part in parts:
        frame = frame.join(part, on='code', how='left')
    frame = frame.with_columns(pl.lit(day).alias('date'), minutes_after_open(pl.col('em_first_seal_time')).alias('em_first_seal_minute'),
                               minutes_after_open(pl.col('em_last_seal_time')).alias('em_last_seal_minute'))
    for name in ('em_in_limit_up_pool', 'em_in_broken_pool', 'em_in_limit_down_pool'):
        frame = frame.with_columns(pl.col(name).fill_null(False))
    if tables.get('strong') is not None:
        frame = frame.with_columns(pl.col('em_in_strong_pool').fill_null(False))
    if tables.get('billboard') is not None:
        frame = frame.with_columns(pl.col('em_on_billboard').fill_null(False))
    for name, dtype in DETAIL_SCHEMA.items():
        if name not in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype).alias(name))
    return frame.select([pl.col(name).cast(dtype) for name, dtype in DETAIL_SCHEMA.items()]).sort('code')


def reconcile(day_events, tables):
    """Compare vendor pools with our daily-bar states for the same day (events table rows of that day)."""
    ours_up = set(day_events.filter(pl.col('is_limit_up_close') & ~pl.col('is_st'))['code'].to_list())
    ours_down = set(day_events.filter(pl.col('is_limit_down_close'))['code'].to_list())
    ours_broken = set(day_events.filter(pl.col('is_broken_board'))['code'].to_list())

    def vendor(key):
        return {s for s in tables[key]['symbol'].to_list() if not s.startswith('bj.')}

    up, down, broken = vendor('limit_up'), vendor('limit_down'), vendor('broken')
    checks = {
        'limit_up': {'ours_non_st': len(ours_up), 'vendor': len(up), 'ours_only': sorted(ours_up - up), 'vendor_only': sorted(up - ours_up)},
        'limit_down': {'ours': len(ours_down), 'vendor': len(down), 'vendor_only': sorted(down - ours_down), 'ours_only': len(ours_down - down)},
        'broken': {'ours': len(ours_broken), 'vendor': len(broken), 'vendor_only': sorted(broken - ours_broken), 'ours_only': len(ours_broken - broken)},
    }
    consistent = (not checks['limit_up']['ours_only'] and not checks['limit_up']['vendor_only'] and not checks['limit_down']['vendor_only']
                  and not checks['broken']['vendor_only'])
    return ('CONSISTENT' if consistent else 'INCONSISTENT'), checks


class EventDetailLibrary:
    def __init__(self, output, *, now_fn=None, evidence=None, event_library=None):
        self.output = Path(output).resolve()
        if not self.output.is_dir():
            raise EventDetailError('INVALID_WORKSPACE', '工作空间不存在。')
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._evidence = evidence
        self._events = event_library
        self.root = self.output / '_limit_research' / 'event_details'

    def evidence(self):
        if self._evidence is None:
            from quantlab.data.public_evidence import PublicEvidenceArchive
            self._evidence = PublicEvidenceArchive(self.output)
        return self._evidence

    def events(self):
        if self._events is None:
            from .limit_events import LimitEventLibrary
            self._events = LimitEventLibrary(self.output)
        return self._events

    def _accepted(self, source, day):
        from quantlab.data.public_evidence import PublicEvidenceError
        try:
            self.evidence().get(source, day)
            return True
        except PublicEvidenceError as error:
            if error.code == 'NOT_FOUND':
                return False
            raise EventDetailError(error.code, str(error)) from None

    def resolve(self, day):
        day = date.fromisoformat(day) if isinstance(day, str) else day
        missing = [s for s in REQUIRED.values() if not self._accepted(s, day)]
        if missing:
            raise EventDetailError('POOLS_MISSING', f'{day} 缺少已接受的股池归档：' + ', '.join(missing))
        tables, inputs = {}, []
        for key, source in {**REQUIRED, **OPTIONAL}.items():
            if key in OPTIONAL and not self._accepted(source, day):
                tables[key] = None
                continue
            frame, manifest = self.evidence().read_table(source, day)
            tables[key] = frame
            inputs.append({'source_id': source, 'capture_id': manifest['capture_id'], 'content_hash': manifest['content_hash']})
        library = self.events().latest_covering(day)
        identity = {'format': FORMAT, 'rules_version': RULES_VERSION, 'code_fingerprint': code_fingerprint(), 'trading_day': day.isoformat(),
                    'inputs': inputs, 'event_library_build_id': library['build_id'] if library else None}
        return {'day': day, 'tables': tables, 'library': library, 'identity': identity,
                'build_id': str(uuid5(NAMESPACE_URL, 'niuniu-event-details:' + digest(identity)))}

    def _day_dir(self, day):
        for path in (self.output / '_limit_research', self.root):
            if path.is_symlink():
                raise EventDetailError('INVALID_WORKSPACE', '事件明细目录不能是符号链接。')
        return self.root / (day.isoformat() if isinstance(day, date) else date.fromisoformat(day).isoformat())

    def is_current(self, day):
        try:
            resolved = self.resolve(day)
        except EventDetailError:
            return False
        return (self._day_dir(resolved['day']) / resolved['build_id'] / 'manifest.json').is_file()

    def build(self, day):
        resolved = self.resolve(day)
        folder = self._day_dir(resolved['day']) / resolved['build_id']
        if folder.exists():
            return {**self.get(resolved['day'], resolved['build_id']), 'created': False}
        details = detail_frame(resolved['day'], resolved['tables'])
        status, checks = 'UNCHECKED', None
        if resolved['library'] is not None:
            day_events, _ = self.events().read_events(resolved['library']['build_id'], start=resolved['day'], end=resolved['day'],
                                                      columns=['date', 'code', 'is_st', 'is_limit_up_close', 'is_limit_down_close', 'is_broken_board'])
            status, checks = reconcile(day_events, resolved['tables'])
        details = details.with_columns(pl.lit(status == 'CONSISTENT').alias('em_day_consistent'))
        stream = io.BytesIO()
        details.write_parquet(stream, compression='zstd')
        payload = stream.getvalue()
        created = self.now_fn()
        if not isinstance(created, datetime) or created.tzinfo is None:
            raise EventDetailError('INVALID_CLOCK', '时钟必须带时区。')
        manifest = {**resolved['identity'], 'build_id': resolved['build_id'], 'created_at': created.astimezone(timezone.utc).isoformat(),
                    'rows': details.height, 'reconciliation': status, 'checks': checks,
                    'optional_sources_missing': sorted(OPTIONAL[k] for k, v in resolved['tables'].items() if k in OPTIONAL and v is None),
                    'details_sha256': hashlib.sha256(payload).hexdigest(), 'qualification': 'research_only', 'limitations': LIMITATIONS}
        folder.parent.mkdir(parents=True, exist_ok=True)
        temporary = folder.parent / ('.tmp-' + str(uuid4()))
        temporary.mkdir()
        (temporary / 'details.parquet').write_bytes(payload)
        (temporary / 'manifest.json').write_text(encode({**manifest, 'checksum': digest(manifest)}), encoding='utf-8')
        temporary.replace(folder)
        return {**manifest, 'created': True}

    def get(self, day, build_id=None):
        folder = self._day_dir(day)
        if build_id is None:
            builds = [p.name for p in folder.iterdir() if p.is_dir() and BUILD.fullmatch(p.name)] if folder.is_dir() else []
            if not builds:
                raise EventDetailError('NOT_FOUND', f'{day} 没有事件明细 build。')
            return max((self.get(day, b) for b in builds), key=lambda m: (m['created_at'], m['build_id']))
        if not BUILD.fullmatch(build_id or ''):
            raise EventDetailError('INVALID_ARGUMENT', 'build_id 无效。')
        path = folder / build_id / 'manifest.json'
        if path.is_symlink() or not path.is_file():
            raise EventDetailError('NOT_FOUND', '事件明细 build 不存在。')
        value = json.loads(path.read_bytes())
        core = {k: v for k, v in value.items() if k != 'checksum'}
        if value.get('checksum') != digest(core) or core.get('format') != FORMAT or core.get('build_id') != build_id:
            raise EventDetailError('CORRUPT_ARCHIVE', '事件明细 manifest 校验失败。')
        return core

    def read(self, day, build_id=None):
        manifest = self.get(day, build_id)
        payload = (self._day_dir(day) / manifest['build_id'] / 'details.parquet').read_bytes()
        if hashlib.sha256(payload).hexdigest() != manifest['details_sha256']:
            raise EventDetailError('CORRUPT_ARCHIVE', 'details.parquet 哈希校验失败。')
        frame = pl.read_parquet(io.BytesIO(payload))
        if frame.height != manifest['rows']:
            raise EventDetailError('CORRUPT_ARCHIVE', 'details.parquet 行数与 manifest 不一致。')
        return frame, manifest

    def list_days(self, limit=500):
        if not self.root.is_dir():
            return []
        rows = []
        for folder in sorted((p for p in self.root.iterdir() if p.is_dir() and re.fullmatch(r'\d{4}-\d{2}-\d{2}', p.name)), reverse=True)[:limit]:
            try:
                manifest = self.get(folder.name)
                rows.append({'trading_day': folder.name, 'build_id': manifest['build_id'], 'rows': manifest['rows'],
                             'reconciliation': manifest['reconciliation'], 'created_at': manifest['created_at']})
            except EventDetailError as error:
                rows.append({'trading_day': folder.name, 'error': error.code})
        return rows

    def read_range(self, start=None, end=None):
        """Latest detail build per archived day in [start, end]; returns (frame, [manifest summaries])."""
        frames, used = [], []
        for row in sorted(self.list_days(limit=5000), key=lambda r: r['trading_day']):
            if 'error' in row or (start and row['trading_day'] < str(start)) or (end and row['trading_day'] > str(end)):
                continue
            frame, manifest = self.read(row['trading_day'], row['build_id'])
            frames.append(frame)
            used.append({'trading_day': row['trading_day'], 'build_id': row['build_id'], 'reconciliation': manifest['reconciliation'],
                         'optional_sources_missing': manifest['optional_sources_missing']})
        empty = pl.DataFrame(schema=DETAIL_SCHEMA)
        return (pl.concat(frames, how='vertical') if frames else empty), used

    def attach(self, events, start=None, end=None):
        """Left-join detail columns onto event rows using only days that reconciled.

        On a reconciled day a stock absent from a vendor pool gets ``False`` for that pool flag (not null);
        optional-source flags are only filled on days where that source was archived.
        """
        details, used = self.read_range(start, end)
        consistent = {row['trading_day']: row for row in used if row['reconciliation'] == 'CONSISTENT'}
        details = details.filter(pl.col('date').cast(pl.String).is_in(sorted(consistent))).drop('em_day_consistent')
        joined = events.join(details, on=['date', 'code'], how='left')
        day_text = pl.col('date').cast(pl.String)
        in_day = day_text.is_in(sorted(consistent))
        exprs = [in_day.alias('em_day_consistent')]
        for flag in ('em_in_limit_up_pool', 'em_in_broken_pool', 'em_in_limit_down_pool'):
            exprs.append(pl.when(in_day).then(pl.col(flag).fill_null(False)).otherwise(pl.col(flag)).alias(flag))
        for flag, source in (('em_in_strong_pool', OPTIONAL['strong']), ('em_on_billboard', OPTIONAL['billboard'])):
            days = sorted(d for d, row in consistent.items() if source not in row['optional_sources_missing'])
            exprs.append(pl.when(day_text.is_in(days)).then(pl.col(flag).fill_null(False)).otherwise(pl.col(flag)).alias(flag))
        return joined.with_columns(exprs), used


__all__ = ['FORMAT', 'RULES_VERSION', 'DETAIL_COLUMNS', 'DETAIL_SCHEMA', 'LIMITATIONS', 'EventDetailError', 'EventDetailLibrary',
           'detail_frame', 'minutes_after_open', 'reconcile']

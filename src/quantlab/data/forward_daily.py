"""Forward extension of the retro daily panel with accepted DailyMarket snapshots (research_only).

The retro capture freezes history once; later trading days arrive as one DailyMarket snapshot per
day. To join them safely a build needs a reference snapshot taken on or after the last forward day:
Baostock ``stock_basic`` (listing and delisting dates, including new listings) and the trading
calendar. Every forward trading day must have an accepted DailyMarket snapshot; any gap fails the
build instead of silently skipping a session.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo
import gzip
import hashlib
import json
import re

import polars as pl

from quantlab.storage.codec import digest, encode

from .daily_market_archive import DailyMarketArchive, DailyMarketArchiveError
from .retro_daily import BASIC_FIELDS, CALENDAR_FIELDS, SCHEMA, SYMBOL, RetroDailyError, _Session, _query_all, _sdk_version

FORMAT = 'baostock-forward-reference-v1'
EXTENSION_FORMAT = 'forward-daily-market-extension-v1'
TZ = ZoneInfo('Asia/Shanghai')
CALENDAR_LOOKBACK_DAYS = 400
SNAPSHOT = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
LIMITATIONS = [
    'stock_basic 与交易日历是抓取当时的 Baostock 快照，as_of 为抓取日（上海时间）；不是 PIT Universe。',
    '前瞻日线来自 DailyMarket 每日快照，与回溯日线同源同字段；资格 research_only。',
]


class ForwardDailyError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _day(value, name='date'):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ForwardDailyError('INVALID_ARGUMENT', name + ' 必须为 YYYY-MM-DD。') from None


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _gzip_json(value):
    return gzip.compress(encode(value).encode('utf-8'), mtime=0)


def _checked(value):
    return {**value, 'checksum': digest(value)}


def _verify(value, what):
    if not isinstance(value, dict) or 'checksum' not in value:
        raise ForwardDailyError('CORRUPT_ARCHIVE', what + ' 缺少 checksum。')
    core = {k: v for k, v in value.items() if k != 'checksum'}
    if value['checksum'] != digest(core):
        raise ForwardDailyError('CORRUPT_ARCHIVE', what + ' checksum 校验失败。')
    return core


class ForwardReferenceArchive:
    """Append-only Baostock reference snapshots: one directory per distinct content."""

    def __init__(self, output, now_fn=None, calendar_lookback_days=CALENDAR_LOOKBACK_DAYS):
        self.output = Path(output).resolve()
        if not self.output.is_dir():
            raise ForwardDailyError('INVALID_WORKSPACE', '工作空间不存在。')
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.calendar_lookback_days = calendar_lookback_days
        self.root = self.output / '_market_data' / 'forward_reference'

    def _guard(self):
        for path in (self.output / '_market_data', self.root):
            if path.is_symlink():
                raise ForwardDailyError('INVALID_WORKSPACE', '前瞻参考目录不能是符号链接。')

    def capture(self, *, sdk=None):
        self._guard()
        fetched = self.now_fn()
        if not isinstance(fetched, datetime) or fetched.tzinfo is None:
            raise ForwardDailyError('INVALID_CLOCK', '时钟必须带时区。')
        as_of = fetched.astimezone(TZ).date()
        start = as_of - timedelta(days=self.calendar_lookback_days)
        try:
            with _Session(sdk) as client:
                basic = _query_all(client.query_stock_basic(), BASIC_FIELDS, 'stock_basic')
                calendar = _query_all(client.query_trade_dates(start_date=start.isoformat(), end_date=as_of.isoformat()),
                                      CALENDAR_FIELDS, 'trade_dates')
                version = _sdk_version(client)
        except RetroDailyError as error:
            raise ForwardDailyError(error.code, str(error)) from None
        days = []
        for day_text, flag in calendar:
            day = _day(day_text, 'calendar_date')
            if not start <= day <= as_of or flag not in ('0', '1'):
                raise ForwardDailyError('DATA_SCHEMA', '交易日历存在范围外日期或非法标记。')
            days.append(day)
        if not days or len(set(days)) != len(days) or days != sorted(days) or days[-1] != as_of \
                or (days[-1] - days[0]).days + 1 != len(days):
            raise ForwardDailyError('DATA_SCHEMA', '交易日历必须连续覆盖到抓取日且不重复。')
        codes = [row[0] for row in basic]
        if len(set(codes)) != len(codes) or not any(row[4] == '1' and SYMBOL.fullmatch(row[0]) for row in basic):
            raise ForwardDailyError('DATA_SCHEMA', 'stock_basic 证券代码重复或没有沪深 A 股。')
        basic_value = {'format': 'baostock-stock-basic-v1', 'fields': list(BASIC_FIELDS), 'rows': basic}
        calendar_value = {'format': 'baostock-trade-calendar-v1', 'fields': list(CALENDAR_FIELDS), 'rows': calendar}
        basic_bytes, calendar_bytes = _gzip_json(basic_value), _gzip_json(calendar_value)
        identity = {'as_of': as_of.isoformat(), 'stock_basic_content_hash': digest(basic_value), 'calendar_content_hash': digest(calendar_value)}
        snapshot_id = str(uuid5(NAMESPACE_URL, 'niuniu-forward-reference:' + digest(identity)))
        folder = self.root / snapshot_id
        if folder.exists():
            return {**self.get(snapshot_id), 'created': False}
        manifest = {'format': FORMAT, 'snapshot_id': snapshot_id, **identity, 'fetched_at': fetched.astimezone(timezone.utc).isoformat(),
                    'sdk_version': version, 'calendar_first_day': days[0].isoformat(), 'calendar_last_day': days[-1].isoformat(),
                    'stock_basic_rows': len(basic), 'a_share_rows': sum(1 for row in basic if row[4] == '1' and SYMBOL.fullmatch(row[0])),
                    'stock_basic_file_sha256': _sha(basic_bytes), 'calendar_file_sha256': _sha(calendar_bytes),
                    'qualification': 'research_only', 'limitations': LIMITATIONS}
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / ('.tmp-' + str(uuid4()))
        temporary.mkdir()
        (temporary / 'stock_basic.json.gz').write_bytes(basic_bytes)
        (temporary / 'trade_calendar.json.gz').write_bytes(calendar_bytes)
        (temporary / 'manifest.json').write_text(encode(_checked(manifest)), encoding='utf-8')
        temporary.replace(folder)
        return {**manifest, 'created': True}

    def get(self, snapshot_id):
        self._guard()
        if not isinstance(snapshot_id, str) or not SNAPSHOT.fullmatch(snapshot_id):
            raise ForwardDailyError('INVALID_ARGUMENT', 'snapshot_id 无效。')
        folder = self.root / snapshot_id
        path = folder / 'manifest.json'
        if folder.is_symlink() or path.is_symlink() or not path.is_file():
            raise ForwardDailyError('NOT_FOUND', '前瞻参考快照不存在。')
        manifest = _verify(json.loads(path.read_bytes()), 'manifest.json')
        if manifest.get('format') != FORMAT or manifest.get('snapshot_id') != snapshot_id:
            raise ForwardDailyError('CORRUPT_ARCHIVE', '前瞻参考 manifest 身份无效。')
        return manifest

    def load(self, snapshot_id):
        manifest = self.get(snapshot_id)
        result = {'manifest': manifest}
        for name, file_key, content_key, fields in (
                ('stock_basic', 'stock_basic_file_sha256', 'stock_basic_content_hash', BASIC_FIELDS),
                ('trade_calendar', 'calendar_file_sha256', 'calendar_content_hash', CALENDAR_FIELDS)):
            path = self.root / snapshot_id / (name + '.json.gz')
            if path.is_symlink() or not path.is_file():
                raise ForwardDailyError('CORRUPT_ARCHIVE', name + ' 文件缺失。')
            payload = path.read_bytes()
            if _sha(payload) != manifest[file_key]:
                raise ForwardDailyError('CORRUPT_ARCHIVE', name + ' 文件哈希校验失败。')
            value = json.loads(gzip.decompress(payload))
            if digest(value) != manifest[content_key] or tuple(value.get('fields', ())) != fields:
                raise ForwardDailyError('CORRUPT_ARCHIVE', name + ' 内容校验失败。')
            result[name] = value['rows']
        return result

    def list(self):
        self._guard()
        if not self.root.exists():
            return []
        rows = []
        for folder in self.root.iterdir():
            if folder.is_dir() and SNAPSHOT.fullmatch(folder.name):
                rows.append(self.get(folder.name))
        return sorted(rows, key=lambda m: (m['as_of'], m['fetched_at']), reverse=True)

    def latest_covering(self, day):
        """Most recent snapshot captured on or after ``day`` (so it knows listings up to that day)."""
        day = _day(day)
        for manifest in self.list():
            if manifest['as_of'] >= day.isoformat() and manifest['calendar_last_day'] >= day.isoformat():
                return manifest
        raise ForwardDailyError('REFERENCE_NOT_FOUND', f'没有 {day} 当日或之后抓取的前瞻参考快照（stock_basic 与交易日历）。')

    def captured_on(self, day):
        day = _day(day).isoformat()
        return any(m['as_of'] == day for m in self.list())


def _to_schema(frame):
    return frame.with_columns(pl.col('tradestatus').cast(pl.UInt8), pl.col('isST').cast(pl.UInt8)).select(
        [pl.col(name).cast(dtype) for name, dtype in SCHEMA.items()])


def resolve_forward(output, retro_calendar, through):
    """Validate and load forward trading days after the retro calendar through ``through`` (inclusive)."""
    through = _day(through, 'forward_through')
    if not retro_calendar:
        raise ForwardDailyError('INVALID_ARGUMENT', '回溯交易日历为空。')
    last_retro = retro_calendar[-1]
    if through <= last_retro:
        raise ForwardDailyError('FORWARD_RANGE', f'forward_through 必须晚于回溯数据最后交易日 {last_retro}。')
    references = ForwardReferenceArchive(output)
    manifest = references.latest_covering(through)
    reference = references.load(manifest['snapshot_id'])
    flags = {date.fromisoformat(d): f for d, f in reference['trade_calendar']}
    first_known = min(flags)
    if first_known > last_retro:
        raise ForwardDailyError('FORWARD_RANGE', '前瞻参考交易日历没有覆盖到回溯数据最后交易日。')
    overlap = sorted(d for d, f in flags.items() if f == '1' and d <= last_retro)
    retro_overlap = [d for d in retro_calendar if d >= first_known]
    if overlap != retro_overlap:
        raise ForwardDailyError('CALENDAR_MISMATCH', '前瞻参考交易日历与回溯交易日历在重叠区间不一致。')
    days = sorted(d for d, f in flags.items() if f == '1' and last_retro < d <= through)
    if not days:
        raise ForwardDailyError('FORWARD_RANGE', '回溯数据之后到 forward_through 没有交易日。')
    archive = DailyMarketArchive(output)
    missing = [d.isoformat() for d in days if archive.accepted(d) is None]
    if missing:
        raise ForwardDailyError('FORWARD_GAP', '以下交易日缺少 accepted DailyMarket 快照：' + ', '.join(missing[:10]))
    a_shares = {row[0] for row in reference['stock_basic'] if row[4] == '1' and SYMBOL.fullmatch(row[0])}
    frames, evidence_days, excluded = [], [], set()
    for day in days:
        try:
            frame, day_manifest = archive.read_frame(day)
        except DailyMarketArchiveError as error:
            raise ForwardDailyError(error.code, str(error)) from None
        converted = _to_schema(frame)
        unknown = set(converted['code'].to_list()) - a_shares
        excluded |= unknown
        frames.append(converted.filter(pl.col('code').is_in(sorted(a_shares))))
        evidence_days.append({'date': day.isoformat(), 'snapshot_id': day_manifest['snapshot_id'],
                              'content_hash': day_manifest['content_hash'], 'rows': frame.height, 'excluded': len(unknown)})
    panel = pl.concat(frames, how='vertical').sort('code', 'date')
    evidence = {'kind': EXTENSION_FORMAT, 'through': through.isoformat(), 'first_day': days[0].isoformat(), 'last_day': days[-1].isoformat(),
                'days': evidence_days, 'reference_snapshot_id': manifest['snapshot_id'], 'reference_as_of': manifest['as_of'],
                'stock_basic_content_hash': manifest['stock_basic_content_hash'], 'calendar_content_hash': manifest['calendar_content_hash'],
                'excluded_codes': sorted(excluded)}
    return {'days': days, 'panel': panel, 'stock_basic': reference['stock_basic'], 'symbols': sorted(panel['code'].unique().to_list()),
            'evidence': evidence}


__all__ = ['FORMAT', 'EXTENSION_FORMAT', 'ForwardDailyError', 'ForwardReferenceArchive', 'resolve_forward']

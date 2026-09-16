"""Retrospective full A-share daily panel from Baostock per-symbol backfill; research_only.

A capture plan freezes the date range, provider fields and the stock_basic / trading
calendar reference bytes. Per-symbol data is fetched resumably (optionally by disjoint
shards in parallel processes) and each symbol directory is written atomically with
SHA256-verified raw rows, a typed Parquet file and a checksummed manifest.

Values are provider observations at fetch time. They do not certify historical first
publication, a PIT Universe, official SecurityStatus or official price limits.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo
import gzip
import hashlib
import io
import json
import re
import socket
import time

import polars as pl

from quantlab.storage.codec import digest, encode

FORMAT = 'retro-daily-baostock-v1'
PLAN_FORMAT = 'retro-daily-plan-v1'
SYMBOL_FORMAT = 'retro-daily-symbol-v1'
FAILURE_FORMAT = 'retro-daily-failure-v1'
FIELDS = ('date', 'code', 'open', 'high', 'low', 'close', 'preclose', 'volume', 'amount', 'adjustflag',
          'turn', 'tradestatus', 'pctChg', 'isST')
BASIC_FIELDS = ('code', 'code_name', 'ipoDate', 'outDate', 'type', 'status')
CALENDAR_FIELDS = ('calendar_date', 'is_trading_day')
SYMBOL = re.compile(r'^(sh|sz)\.\d{6}$')
CAPTURE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
EARLIEST = date(1990, 12, 19)
TZ = ZoneInfo('Asia/Shanghai')
MAX_ROWS_PER_SYMBOL = 20000
MAX_CONSECUTIVE_FAILURES = 5
SCHEMA = {'date': pl.Date, 'code': pl.String, 'open': pl.Float64, 'high': pl.Float64, 'low': pl.Float64,
          'close': pl.Float64, 'preclose': pl.Float64, 'volume': pl.Float64, 'amount': pl.Float64,
          'adjustflag': pl.String, 'turn': pl.Float64, 'tradestatus': pl.UInt8, 'pctChg': pl.Float64, 'isST': pl.UInt8}
LIMITATIONS = [
    'Baostock 抓取时点的回溯观察值，不认证历史首次发布时间；资格为 research_only。',
    'stock_basic 与交易日历是本次抓取快照；上市/退市日期是回溯信息，不是 PIT Universe。',
    '只覆盖沪深 A 股（type=1）；不含北交所、B 股、指数、基金和债券。',
    'isST/tradestatus 是供应商回溯标记，不等于官方逐日 SecurityStatus；涨跌停价须由制度表推算，不构成官方 MarketRules。',
]


class RetroDailyError(ValueError):
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
        raise RetroDailyError('INVALID_ARGUMENT', f'{name} 必须为 YYYY-MM-DD。') from None


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _gzip_json(value):
    return gzip.compress(encode(value).encode('utf-8'), compresslevel=6, mtime=0)


def _checked(value):
    return {**value, 'checksum': digest(value)}


def _verify_checked(value, what):
    if not isinstance(value, dict) or 'checksum' not in value:
        raise RetroDailyError('CORRUPT_ARCHIVE', what + ' 缺少 checksum。')
    core = {k: v for k, v in value.items() if k != 'checksum'}
    if value['checksum'] != digest(core):
        raise RetroDailyError('CORRUPT_ARCHIVE', what + ' checksum 校验失败。')
    return core


def _read_json(path, what, limit=20_000_000):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise RetroDailyError('CORRUPT_ARCHIVE', what + ' 不存在、是符号链接或超过大小限制。')
    try:
        return json.loads(path.read_bytes())
    except ValueError:
        raise RetroDailyError('CORRUPT_ARCHIVE', what + ' 不是有效 JSON。') from None


def shard_of(symbol, shards):
    if type(shards) is not int or not 1 <= shards <= 64:
        raise RetroDailyError('INVALID_ARGUMENT', 'shards 必须为 1–64。')
    return int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16) % shards


def _float(value, name, *, positive=False, nonnegative=False, optional=False):
    if value in ('', None):
        if optional:
            return None
        raise RetroDailyError('DATA_SCHEMA', name + ' 不能为空。')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise RetroDailyError('DATA_SCHEMA', name + ' 必须为数值。') from None
    if number != number or abs(number) == float('inf'):
        raise RetroDailyError('DATA_SCHEMA', name + ' 必须为有限数。')
    if positive and number <= 0:
        raise RetroDailyError('DATA_SCHEMA', name + ' 必须大于0。')
    if nonnegative and number < 0:
        raise RetroDailyError('DATA_SCHEMA', name + ' 不能小于0。')
    return number


def normalize_symbol_rows(rows, symbol, start, end, trading_days):
    """Validate provider string rows for one symbol and return typed records."""
    records = []
    previous = None
    if len(rows) > MAX_ROWS_PER_SYMBOL:
        raise RetroDailyError('BUDGET_EXCEEDED', '单证券行数超过上限。')
    for values in rows:
        if not isinstance(values, (list, tuple)) or len(values) != len(FIELDS) or any(not isinstance(v, str) for v in values):
            raise RetroDailyError('DATA_SCHEMA', '返回行与字段合同不一致。')
        row = dict(zip(FIELDS, values))
        day = _day(row['date'])
        if not start <= day <= end:
            raise RetroDailyError('DATA_SCHEMA', f'{symbol} 返回了计划范围外日期 {day}。')
        if day.isoformat() not in trading_days:
            raise RetroDailyError('DATA_SCHEMA', f'{symbol} 返回了非交易日 {day}。')
        if previous is not None and day <= previous:
            raise RetroDailyError('DATA_SCHEMA', f'{symbol} 日期未严格递增。')
        previous = day
        if row['code'] != symbol:
            raise RetroDailyError('DATA_SCHEMA', f'{symbol} 返回了其他证券代码。')
        if row['adjustflag'] != '3':
            raise RetroDailyError('DATA_SCHEMA', '必须是不复权 adjustflag=3。')
        if row['tradestatus'] not in ('0', '1') or row['isST'] not in ('0', '1'):
            raise RetroDailyError('DATA_SCHEMA', 'tradestatus/isST 必须为 0/1。')
        tradable = row['tradestatus'] == '1'
        record = {'date': day, 'code': symbol, 'adjustflag': '3', 'tradestatus': int(row['tradestatus']),
                  'isST': int(row['isST'])}
        for key in ('open', 'high', 'low', 'close', 'preclose'):
            record[key] = _float(row[key], key, positive=tradable, optional=not tradable)
        record['volume'] = _float(row['volume'], 'volume', nonnegative=True, optional=not tradable)
        record['amount'] = _float(row['amount'], 'amount', nonnegative=True, optional=True)
        record['turn'] = _float(row['turn'], 'turn', optional=True)
        record['pctChg'] = _float(row['pctChg'], 'pctChg', optional=True)
        if tradable:
            o, h, l, c = (record[k] for k in ('open', 'high', 'low', 'close'))
            if h < max(o, l, c) or l > min(o, h, c):
                raise RetroDailyError('DATA_SCHEMA', f'{symbol} {day} OHLC 关系无效。')
        records.append(record)
    return records


def _frame(records):
    if not records:
        return pl.DataFrame(schema=SCHEMA)
    return pl.DataFrame(records, schema=SCHEMA).select(list(SCHEMA))


def _parquet(frame):
    stream = io.BytesIO()
    frame.write_parquet(stream, compression='zstd')
    return stream.getvalue()


def _query_all(query, expected, what):
    if getattr(query, 'error_code', None) != '0':
        raise RetroDailyError('PROVIDER_ERROR', what + ' 查询失败：' + str(getattr(query, 'error_msg', ''))[:200])
    if tuple(getattr(query, 'fields', ())) != tuple(expected):
        raise RetroDailyError('DATA_SCHEMA', what + ' 字段版本发生变化。')
    rows = []
    while query.next():
        values = query.get_row_data()
        if len(values) != len(expected) or any(not isinstance(v, str) for v in values):
            raise RetroDailyError('DATA_SCHEMA', what + ' 返回行与字段不一致。')
        rows.append(list(values))
        if len(rows) > 200000:
            raise RetroDailyError('BUDGET_EXCEEDED', what + ' 行数超过上限。')
    if getattr(query, 'error_code', None) != '0':
        raise RetroDailyError('PROVIDER_ERROR', what + ' 分页失败：' + str(getattr(query, 'error_msg', ''))[:200])
    return rows


class _Session:
    def __init__(self, sdk):
        self.sdk = sdk
        self.logged = False
        self.old_timeout = None

    def __enter__(self):
        if self.sdk is None:
            import baostock as sdk
            self.sdk = sdk
        self.old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(30)
        login = self.sdk.login()
        if getattr(login, 'error_code', None) != '0':
            socket.setdefaulttimeout(self.old_timeout)
            raise RetroDailyError('PROVIDER_ERROR', 'Baostock 登录失败：' + str(getattr(login, 'error_msg', ''))[:200])
        self.logged = True
        return self.sdk

    def __exit__(self, *exc):
        try:
            if self.logged:
                self.sdk.logout()
        finally:
            socket.setdefaulttimeout(self.old_timeout)
        return False


def _sdk_version(sdk):
    version = getattr(sdk, '__version__', None)
    if version:
        return str(version)
    try:
        from importlib.metadata import version as package_version
        return package_version('baostock')
    except Exception:
        return 'unknown'


class RetroDailyStore:
    def __init__(self, output, now_fn=None, today_fn=None):
        self.output = Path(output).resolve()
        if not self.output.is_dir():
            raise RetroDailyError('INVALID_WORKSPACE', '工作空间不存在。')
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.today_fn = today_fn or (lambda: datetime.now(TZ).date())
        self.root = self.output / '_market_data' / 'retro_daily'

    # ---- paths -------------------------------------------------------------------------------
    def _guard(self):
        for path in (self.output / '_market_data', self.root):
            if path.is_symlink():
                raise RetroDailyError('INVALID_WORKSPACE', '回溯日线路径不能是符号链接。')

    def _capture_dir(self, capture_id):
        if not isinstance(capture_id, str) or not CAPTURE.fullmatch(capture_id):
            raise RetroDailyError('INVALID_ARGUMENT', 'capture_id 无效。')
        folder = self.root / capture_id
        if folder.is_symlink():
            raise RetroDailyError('INVALID_WORKSPACE', 'capture 目录不能是符号链接。')
        return folder

    @staticmethod
    def _symbol_key(symbol):
        if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
            raise RetroDailyError('INVALID_ARGUMENT', 'symbol 必须为 sh/sz.XXXXXX。')
        return symbol.replace('.', '_')

    # ---- plan ---------------------------------------------------------------------------------
    def create_plan(self, start, end, *, sdk=None):
        self._guard()
        start, end = _day(start, 'start'), _day(end, 'end')
        if start < EARLIEST or end < start:
            raise RetroDailyError('INVALID_ARGUMENT', 'start/end 范围无效。')
        if end > self.today_fn():
            raise RetroDailyError('INVALID_ARGUMENT', 'end 不能晚于今天。')
        with _Session(sdk) as client:
            basic = _query_all(client.query_stock_basic(), BASIC_FIELDS, 'stock_basic')
            calendar = _query_all(client.query_trade_dates(start_date=start.isoformat(), end_date=end.isoformat()),
                                  CALENDAR_FIELDS, 'trade_dates')
            version = _sdk_version(client)
        expected = (end - start).days + 1
        seen = {}
        for day_text, flag in calendar:
            day = _day(day_text)
            if not start <= day <= end or flag not in ('0', '1') or day_text in seen:
                raise RetroDailyError('DATA_SCHEMA', '交易日历存在范围外、重复或非法标记。')
            seen[day_text] = flag
        if len(seen) != expected:
            raise RetroDailyError('DATA_SCHEMA', '交易日历未完整覆盖计划区间。')
        trading_days = sorted(day for day, flag in seen.items() if flag == '1')
        if not trading_days:
            raise RetroDailyError('NO_DATA', '计划区间内没有交易日。')
        symbols = []
        codes = set()
        for code, _name, ipo, out, kind, _status in basic:
            if code in codes:
                raise RetroDailyError('DATA_SCHEMA', 'stock_basic 证券代码重复。')
            codes.add(code)
            if kind != '1' or not SYMBOL.fullmatch(code) or not ipo:
                continue
            listed = _day(ipo, 'ipoDate')
            delisted = _day(out, 'outDate') if out else None
            if listed <= end and (delisted is None or delisted >= start):
                symbols.append(code)
        symbols.sort()
        if not symbols:
            raise RetroDailyError('NO_DATA', 'stock_basic 中没有计划范围内的沪深 A 股。')
        basic_value = {'format': 'baostock-stock-basic-v1', 'fields': list(BASIC_FIELDS), 'rows': basic}
        calendar_value = {'format': 'baostock-trade-calendar-v1', 'fields': list(CALENDAR_FIELDS), 'rows': calendar}
        basic_bytes, calendar_bytes = _gzip_json(basic_value), _gzip_json(calendar_value)
        basic_hash, calendar_hash = digest(basic_value), digest(calendar_value)
        capture_id = str(uuid5(NAMESPACE_URL, f'niuniu-retro-daily:{start}:{end}:{basic_hash}:{calendar_hash}'))
        folder = self._capture_dir(capture_id)
        if folder.exists():
            existing = self.plan(capture_id)
            return {**existing, 'created': False}
        created = self.now_fn()
        if not isinstance(created, datetime) or created.tzinfo is None:
            raise RetroDailyError('INVALID_CLOCK', '时钟必须带时区。')
        plan = {'format': PLAN_FORMAT, 'dataset_format': FORMAT, 'capture_id': capture_id,
                'start': start.isoformat(), 'end': end.isoformat(), 'fields': list(FIELDS),
                'created_at': created.astimezone(timezone.utc).isoformat(), 'sdk_version': version,
                'provider': 'baostock.query_history_k_data_plus(frequency=d, adjustflag=3)',
                'stock_basic_content_hash': basic_hash, 'stock_basic_file_sha256': _sha(basic_bytes),
                'calendar_content_hash': calendar_hash, 'calendar_file_sha256': _sha(calendar_bytes),
                'trading_days': len(trading_days), 'first_trading_day': trading_days[0],
                'last_trading_day': trading_days[-1], 'symbols': symbols, 'symbol_count': len(symbols),
                'qualification': 'research_only', 'limitations': LIMITATIONS}
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / ('.tmp-plan-' + str(uuid4()))
        (temporary / 'reference').mkdir(parents=True)
        (temporary / 'symbols').mkdir()
        (temporary / 'failures').mkdir()
        (temporary / 'reference' / 'stock_basic.json.gz').write_bytes(basic_bytes)
        (temporary / 'reference' / 'trade_calendar.json.gz').write_bytes(calendar_bytes)
        (temporary / 'plan.json').write_text(encode(_checked(plan)), encoding='utf-8')
        temporary.replace(folder)
        return {**self._plan_summary(plan), 'created': True}

    @staticmethod
    def _plan_summary(plan):
        return {k: v for k, v in plan.items() if k != 'symbols'}

    def plan(self, capture_id, *, with_symbols=False):
        folder = self._capture_dir(capture_id)
        value = _verify_checked(_read_json(folder / 'plan.json', 'plan.json'), 'plan.json')
        required = {'format', 'dataset_format', 'capture_id', 'start', 'end', 'fields', 'created_at', 'sdk_version',
                    'provider', 'stock_basic_content_hash', 'stock_basic_file_sha256', 'calendar_content_hash',
                    'calendar_file_sha256', 'trading_days', 'first_trading_day', 'last_trading_day', 'symbols',
                    'symbol_count', 'qualification', 'limitations'}
        if set(value) != required or value['format'] != PLAN_FORMAT or value['capture_id'] != capture_id:
            raise RetroDailyError('CORRUPT_ARCHIVE', 'plan.json 字段或身份无效。')
        if tuple(value['fields']) != FIELDS or len(value['symbols']) != value['symbol_count']:
            raise RetroDailyError('CORRUPT_ARCHIVE', 'plan.json 字段合同或证券数量不一致。')
        return value if with_symbols else self._plan_summary(value)

    def reference(self, capture_id):
        plan = self.plan(capture_id)
        folder = self._capture_dir(capture_id) / 'reference'
        result = {}
        for name, file_key, content_key, fields in (
                ('stock_basic', 'stock_basic_file_sha256', 'stock_basic_content_hash', BASIC_FIELDS),
                ('trade_calendar', 'calendar_file_sha256', 'calendar_content_hash', CALENDAR_FIELDS)):
            path = folder / (name + '.json.gz')
            if path.is_symlink() or not path.is_file():
                raise RetroDailyError('CORRUPT_ARCHIVE', name + ' 参考文件缺失。')
            payload = path.read_bytes()
            if _sha(payload) != plan[file_key]:
                raise RetroDailyError('CORRUPT_ARCHIVE', name + ' 参考文件哈希校验失败。')
            value = json.loads(gzip.decompress(payload))
            if digest(value) != plan[content_key] or tuple(value.get('fields', ())) != fields:
                raise RetroDailyError('CORRUPT_ARCHIVE', name + ' 参考内容校验失败。')
            result[name] = value['rows']
        return result

    def trading_days(self, capture_id):
        calendar = self.reference(capture_id)['trade_calendar']
        return [day for day, flag in calendar if flag == '1']

    # ---- symbols -------------------------------------------------------------------------------
    def _symbol_dir(self, capture_id, symbol):
        return self._capture_dir(capture_id) / 'symbols' / self._symbol_key(symbol)

    def symbol_manifest(self, capture_id, symbol, *, deep=True):
        folder = self._symbol_dir(capture_id, symbol)
        if folder.is_symlink():
            raise RetroDailyError('CORRUPT_ARCHIVE', '证券目录不能是符号链接。')
        if not folder.exists():
            return None
        value = _verify_checked(_read_json(folder / 'manifest.json', symbol + ' manifest'), symbol + ' manifest')
        required = {'format', 'capture_id', 'symbol', 'status', 'rows', 'first_date', 'last_date', 'tradable_rows',
                    'st_rows', 'raw_sha256', 'parquet_sha256', 'content_hash', 'fetched_at', 'sdk_version'}
        if set(value) != required or value['format'] != SYMBOL_FORMAT or value['capture_id'] != capture_id or value['symbol'] != symbol:
            raise RetroDailyError('CORRUPT_ARCHIVE', symbol + ' manifest 字段或身份无效。')
        if deep:
            for name, key in (('rows.json.gz', 'raw_sha256'), ('daily.parquet', 'parquet_sha256')):
                path = folder / name
                if path.is_symlink() or not path.is_file() or _sha(path.read_bytes()) != value[key]:
                    raise RetroDailyError('CORRUPT_ARCHIVE', f'{symbol} {name} 哈希校验失败。')
        return value

    def _write_symbol(self, capture_id, symbol, rows, records, version):
        fetched = self.now_fn()
        if not isinstance(fetched, datetime) or fetched.tzinfo is None:
            raise RetroDailyError('INVALID_CLOCK', '时钟必须带时区。')
        raw_value = {'format': 'baostock-daily-symbol-raw-v1', 'symbol': symbol, 'fields': list(FIELDS), 'rows': rows}
        raw_bytes = _gzip_json(raw_value)
        frame = _frame(records)
        parquet_bytes = _parquet(frame)
        manifest = {'format': SYMBOL_FORMAT, 'capture_id': capture_id, 'symbol': symbol,
                    'status': 'OK' if records else 'EMPTY', 'rows': len(records),
                    'first_date': records[0]['date'].isoformat() if records else None,
                    'last_date': records[-1]['date'].isoformat() if records else None,
                    'tradable_rows': sum(r['tradestatus'] == 1 for r in records),
                    'st_rows': sum(r['isST'] == 1 for r in records),
                    'raw_sha256': _sha(raw_bytes), 'parquet_sha256': _sha(parquet_bytes),
                    'content_hash': digest(raw_value), 'fetched_at': fetched.astimezone(timezone.utc).isoformat(),
                    'sdk_version': version}
        parent = self._capture_dir(capture_id) / 'symbols'
        temporary = parent / ('.tmp-' + self._symbol_key(symbol) + '-' + str(uuid4()))
        temporary.mkdir()
        (temporary / 'rows.json.gz').write_bytes(raw_bytes)
        (temporary / 'daily.parquet').write_bytes(parquet_bytes)
        (temporary / 'manifest.json').write_text(encode(_checked(manifest)), encoding='utf-8')
        destination = self._symbol_dir(capture_id, symbol)
        try:
            temporary.replace(destination)
        except OSError:
            if destination.exists():
                # Another process completed the same symbol first; keep the existing verified copy.
                self.symbol_manifest(capture_id, symbol)
                for child in temporary.iterdir():
                    child.unlink()
                temporary.rmdir()
                return manifest
            raise
        failure = self._capture_dir(capture_id) / 'failures' / (self._symbol_key(symbol) + '.json')
        if failure.exists() and not failure.is_symlink():
            failure.unlink()
        return manifest

    def _record_failure(self, capture_id, symbol, error):
        path = self._capture_dir(capture_id) / 'failures' / (self._symbol_key(symbol) + '.json')
        attempts = 0
        if path.exists():
            try:
                attempts = _verify_checked(_read_json(path, 'failure'), 'failure')['attempts']
            except RetroDailyError:
                attempts = 0
        value = {'format': FAILURE_FORMAT, 'capture_id': capture_id, 'symbol': symbol, 'attempts': attempts + 1,
                 'code': getattr(error, 'code', 'PROVIDER_ERROR'), 'message': str(error)[:300],
                 'last_attempt_at': self.now_fn().astimezone(timezone.utc).isoformat()}
        temporary = path.with_name('.' + path.name + '-' + str(uuid4()) + '.tmp')
        temporary.write_text(encode(_checked(value)), encoding='utf-8')
        temporary.replace(path)
        return value

    def _cleanup_temporaries(self, capture_id, shard, shards):
        """Remove interrupted temporary writes that belong to this shard only.

        A killed process can leave ``symbols/.tmp-<key>-<uuid>`` directories or failure-record
        temp files. Running the same shard concurrently is not supported, so files of this
        shard are safe to remove; other shards' temporaries are never touched.
        """
        folder = self._capture_dir(capture_id)
        removed = 0
        pattern = re.compile(r'^\.tmp-((?:sh|sz)_\d{6})-[0-9a-f-]{36}$')
        failure_pattern = re.compile(r'^\.((?:sh|sz)_\d{6})\.json-[0-9a-f-]{36}\.tmp$')
        for directory, matcher in ((folder / 'symbols', pattern), (folder / 'failures', failure_pattern)):
            if not directory.is_dir():
                continue
            for entry in directory.iterdir():
                match = matcher.fullmatch(entry.name)
                if not match or entry.is_symlink() or shard_of(match.group(1).replace('_', '.'), shards) != shard:
                    continue
                if entry.is_dir():
                    for child in entry.iterdir():
                        if child.is_file() and not child.is_symlink():
                            child.unlink()
                    entry.rmdir()
                elif entry.is_file():
                    entry.unlink()
                removed += 1
        return removed

    def fetch(self, capture_id, *, max_seconds=140.0, shard=0, shards=1, max_symbols=None, sdk=None, clock=time.monotonic):
        """Fetch pending symbols of one shard until ``max_seconds`` elapses.

        ``max_seconds`` only stops starting new symbols; a single provider query can take
        tens of seconds under load, so an external process timeout should leave a margin.
        Do not run the same shard concurrently.
        """
        self._guard()
        plan = self.plan(capture_id, with_symbols=True)
        if type(shard) is not int or not 0 <= shard < shards:
            raise RetroDailyError('INVALID_ARGUMENT', 'shard 必须在 [0, shards) 内。')
        if max_symbols is not None and (type(max_symbols) is not int or max_symbols < 1):
            raise RetroDailyError('INVALID_ARGUMENT', 'max_symbols 必须为正整数。')
        if type(max_seconds) not in (int, float) or not 1 <= max_seconds <= 86400:
            raise RetroDailyError('INVALID_ARGUMENT', 'max_seconds 必须为 1–86400。')
        folder = self._capture_dir(capture_id)
        cleaned = self._cleanup_temporaries(capture_id, shard, shards)
        mine = [s for s in plan['symbols'] if shard_of(s, shards) == shard]
        pending = [s for s in mine if not (folder / 'symbols' / self._symbol_key(s)).exists()]
        start, end = _day(plan['start']), _day(plan['end'])
        trading_days = set(self.trading_days(capture_id))
        began = clock()
        result = {'capture_id': capture_id, 'shard': shard, 'shards': shards, 'shard_symbols': len(mine),
                  'attempted': 0, 'completed': 0, 'empty': 0, 'failed': 0, 'rows': 0, 'stopped_by': 'done',
                  'cleaned_temporaries': cleaned}
        if not pending:
            result['remaining_in_shard'] = 0
            return result
        consecutive = 0
        with _Session(sdk) as client:
            version = _sdk_version(client)
            for symbol in pending:
                if max_symbols is not None and result['attempted'] >= max_symbols:
                    result['stopped_by'] = 'max_symbols'
                    break
                if clock() - began >= max_seconds:
                    result['stopped_by'] = 'deadline'
                    break
                result['attempted'] += 1
                try:
                    query = client.query_history_k_data_plus(symbol, ','.join(FIELDS), start_date=start.isoformat(),
                                                             end_date=end.isoformat(), frequency='d', adjustflag='3')
                    rows = _query_all(query, FIELDS, symbol)
                    records = normalize_symbol_rows(rows, symbol, start, end, trading_days)
                    manifest = self._write_symbol(capture_id, symbol, rows, records, version)
                except (RetroDailyError, OSError) as error:
                    self._record_failure(capture_id, symbol, error)
                    result['failed'] += 1
                    consecutive += 1
                    if consecutive >= MAX_CONSECUTIVE_FAILURES:
                        result['stopped_by'] = 'consecutive_failures'
                        break
                    continue
                consecutive = 0
                result['completed'] += 1
                result['empty'] += int(manifest['status'] == 'EMPTY')
                result['rows'] += manifest['rows']
        result['remaining_in_shard'] = sum(1 for s in mine if not (folder / 'symbols' / self._symbol_key(s)).exists())
        return result

    # ---- inspection ---------------------------------------------------------------------------
    def list(self):
        self._guard()
        if not self.root.exists():
            return []
        rows = []
        for folder in sorted(p for p in self.root.iterdir() if p.is_dir() and CAPTURE.fullmatch(p.name)):
            try:
                rows.append(self.plan(folder.name))
            except RetroDailyError as error:
                rows.append({'capture_id': folder.name, 'error': error.code})
        return rows

    def status(self, capture_id, *, deep=False):
        plan = self.plan(capture_id, with_symbols=True)
        folder = self._capture_dir(capture_id)
        done = empty = rows = tradable = st = corrupt = 0
        first = last = None
        corrupt_symbols = []
        for symbol in plan['symbols']:
            try:
                manifest = self.symbol_manifest(capture_id, symbol, deep=deep)
            except RetroDailyError:
                corrupt += 1
                corrupt_symbols.append(symbol)
                continue
            if manifest is None:
                continue
            done += 1
            empty += int(manifest['status'] == 'EMPTY')
            rows += manifest['rows']
            tradable += manifest['tradable_rows']
            st += manifest['st_rows']
            if manifest['first_date']:
                first = min(first or manifest['first_date'], manifest['first_date'])
                last = max(last or manifest['last_date'], manifest['last_date'])
        failures = []
        failure_dir = folder / 'failures'
        if failure_dir.is_dir():
            for path in sorted(failure_dir.glob('*.json')):
                try:
                    value = _verify_checked(_read_json(path, 'failure'), 'failure')
                    failures.append({k: value[k] for k in ('symbol', 'attempts', 'code', 'message')})
                except RetroDailyError:
                    failures.append({'symbol': path.stem, 'attempts': None, 'code': 'CORRUPT_FAILURE_RECORD', 'message': ''})
        pending = plan['symbol_count'] - done - corrupt
        return {**self._plan_summary(plan), 'completed_symbols': done, 'empty_symbols': empty, 'pending_symbols': pending,
                'corrupt_symbols': corrupt_symbols, 'failures': failures[:50], 'failure_count': len(failures),
                'rows': rows, 'tradable_rows': tradable, 'st_rows': st, 'first_date': first, 'last_date': last,
                'complete': pending == 0 and corrupt == 0, 'deep_verified': deep}

    def read_panel(self, capture_id, *, start=None, end=None, symbols=None, require_complete=True):
        plan = self.plan(capture_id, with_symbols=True)
        wanted = plan['symbols'] if symbols is None else sorted(set(symbols))
        unknown = sorted(set(wanted) - set(plan['symbols']))
        if unknown:
            raise RetroDailyError('INVALID_ARGUMENT', '证券不在 capture 计划内：' + ', '.join(unknown[:5]))
        start = _day(start, 'start') if start is not None else None
        end = _day(end, 'end') if end is not None else None
        frames, manifests, missing = [], [], []
        for symbol in wanted:
            manifest = self.symbol_manifest(capture_id, symbol, deep=False)
            if manifest is None:
                missing.append(symbol)
                continue
            path = self._symbol_dir(capture_id, symbol) / 'daily.parquet'
            payload = path.read_bytes()
            if _sha(payload) != manifest['parquet_sha256']:
                raise RetroDailyError('CORRUPT_ARCHIVE', f'{symbol} daily.parquet 哈希校验失败。')
            manifests.append({'symbol': symbol, 'parquet_sha256': manifest['parquet_sha256'], 'rows': manifest['rows']})
            if manifest['rows']:
                frame = pl.read_parquet(io.BytesIO(payload))
                if frame.height != manifest['rows'] or frame.columns != list(SCHEMA):
                    raise RetroDailyError('CORRUPT_ARCHIVE', f'{symbol} daily.parquet 行数或字段异常。')
                frames.append(frame)
        if missing and require_complete:
            raise RetroDailyError('INCOMPLETE_CAPTURE', f'capture 尚有 {len(missing)} 只证券未完成抓取。')
        panel = pl.concat(frames, how='vertical') if frames else pl.DataFrame(schema=SCHEMA)
        if start is not None:
            panel = panel.filter(pl.col('date') >= start)
        if end is not None:
            panel = panel.filter(pl.col('date') <= end)
        meta = {'capture_id': capture_id, 'dataset_format': FORMAT, 'qualification': 'research_only',
                'symbols_requested': len(wanted), 'symbols_loaded': len(manifests), 'missing_symbols': missing,
                'manifest_digest': digest(manifests), 'rows': panel.height,
                'stock_basic_content_hash': plan['stock_basic_content_hash'],
                'calendar_content_hash': plan['calendar_content_hash'], 'limitations': plan['limitations']}
        return panel.sort('date', 'code'), meta

    def quarantine_corrupt(self, capture_id, *, confirmed=False):
        if confirmed is not True:
            raise RetroDailyError('CONFIRMATION_REQUIRED', '隔离损坏证券目录需要显式确认。')
        plan = self.plan(capture_id, with_symbols=True)
        folder = self._capture_dir(capture_id)
        moved = []
        for symbol in plan['symbols']:
            try:
                self.symbol_manifest(capture_id, symbol, deep=True)
            except RetroDailyError:
                source = self._symbol_dir(capture_id, symbol)
                if source.exists() and not source.is_symlink():
                    target = folder / 'quarantine' / (self._symbol_key(symbol) + '-' + str(uuid4()))
                    target.parent.mkdir(exist_ok=True)
                    source.replace(target)
                    moved.append(symbol)
        return {'capture_id': capture_id, 'quarantined': moved}


__all__ = ['FORMAT', 'FIELDS', 'BASIC_FIELDS', 'CALENDAR_FIELDS', 'LIMITATIONS', 'RetroDailyError', 'RetroDailyStore',
           'normalize_symbol_rows', 'shard_of']

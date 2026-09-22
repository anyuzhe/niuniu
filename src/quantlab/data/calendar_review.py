"""Explicit, bounded calendar/date-presence review. No download or data writes.

These diagnostics do not change Provider routing, F9 export, approval or PIT rules.
"""
from __future__ import annotations
from collections import Counter
from datetime import date
from pathlib import Path
import hashlib
import io
import re
import stat

import polars as pl
import pyarrow.parquet as pq
from quantlab.data.session_coverage import calendar_window
from quantlab.storage.codec import digest

SOURCES = ('baostock_bronze', 'retro_capture', 'archived_dataset')
MAX_DAYS = 371
MAX_SYMBOLS = 10
MAX_FILE_BYTES = 32_000_000
MAX_TOTAL_BYTES = 256_000_000
BRONZE = 'lake/bronze/provider=baostock/'
CALENDAR = BRONZE + 'trade_calendar/calendar.parquet'
BASIC = BRONZE + 'stock_basic/stock_basic.parquet'
LIMITATIONS = [
    'Date presence against one explicitly selected retrospective provider calendar only; not Strict PIT or tradability.',
    'Listing interval is inclusive ipoDate/outDate from that source; blank outDate means no end reported, not a historical status certificate.',
    'Missing rows are not inferred to be suspension; stored suspended rows remain present and are reported separately.',
    'Date-set completeness does not certify OHLC values, price adjustment or F9 export compatibility.',
    'No source fallback, tail append, cross-source calendar merge, download, export, approval or execution.',
]


def _day(value):
    if type(value) is date:
        return value
    if type(value) is not str:
        raise ValueError('Date must be an explicit YYYY-MM-DD value')
    parsed = date.fromisoformat(value)
    if str(parsed) != value:
        raise ValueError('Date must be canonical YYYY-MM-DD')
    return parsed


def _request(source, capture_id, start, end, symbols=None):
    if source not in SOURCES or type(source) is not str:
        raise ValueError('Select explicit source: ' + ', '.join(SOURCES))
    if type(capture_id) is not str or (source == 'retro_capture' and not re.fullmatch(
            r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', capture_id)):
        raise ValueError('retro_capture requires an exact capture_id')
    if source != 'retro_capture' and capture_id:
        raise ValueError('capture_id must be empty for this source')
    lo, hi = _day(start), _day(end)
    if not 0 <= (hi-lo).days < MAX_DAYS:
        raise ValueError('Select 1–371 natural days')
    selected = ()
    if symbols is not None:
        if type(symbols) is not str:
            raise ValueError('symbols must be a string')
        selected = tuple(symbols.replace(',', ' ').split())
        if not 1 <= len(selected) <= MAX_SYMBOLS or len(set(selected)) != len(selected) or any(
                not re.fullmatch(r'(sh|sz)\.\d{6}', s) for s in selected):
            raise ValueError('Select 1–10 distinct sh/sz codes')
    return lo, hi, selected


def _redirect(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


class _Reader:
    """Bounded exact-byte reading under the host root, with end-of-query recheck."""
    def __init__(self, root):
        if root is None:
            raise ValueError('Selected source root not configured')
        supplied = Path(root)
        if _redirect(supplied) or not supplied.is_dir():
            raise ValueError('Source root missing or symlink/junction')
        self.root = supplied.resolve()
        self.files = {}
        self.total = 0

    def path(self, relative):
        path = self.root
        for part in Path(relative).parts:
            if part in ('..', '/'):
                raise ValueError('Source path escaped root')
            path = path / part
            if _redirect(path):
                raise ValueError('Source symlink/junction rejected')
        if not path.resolve().is_relative_to(self.root):
            raise ValueError('Source path escaped root')
        return path

    def read(self, relative):
        path = self.path(relative)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
            raise ValueError('Source file exceeds byte/type budget')
        if self.total + info.st_size > MAX_TOTAL_BYTES:
            raise ValueError('Total source byte budget exceeded')
        with path.open('rb') as stream:
            payload = stream.read(MAX_FILE_BYTES+1)
        if len(payload) != info.st_size or len(payload) > MAX_FILE_BYTES:
            raise ValueError('Source changed while reading')
        self.track(relative, payload)
        return payload

    def track(self, relative, payload):
        fingerprint = hashlib.sha256(payload).hexdigest()
        old = self.files.get(relative)
        if old and old['sha256'] != fingerprint:
            raise ValueError('Source changed during inspection')
        if not old:
            self.total += len(payload)
            if self.total > MAX_TOTAL_BYTES:
                raise ValueError('Total source byte budget exceeded')
        self.files[relative] = {'relative_file': relative, 'sha256': fingerprint, 'bytes': len(payload)}

    def parquet(self, relative, max_rows=20_000):
        payload = self.read(relative)
        metadata = pq.ParquetFile(io.BytesIO(payload)).metadata
        if metadata.num_rows > max_rows or metadata.num_columns > 64 or metadata.num_row_groups > 128:
            raise ValueError('Parquet row/column/group budget exceeded')
        return pl.read_parquet(io.BytesIO(payload))

    def recheck(self):
        for relative, record in self.files.items():
            path = self.path(relative)
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size != record['bytes']:
                raise ValueError('Source changed during inspection')
            with path.open('rb') as stream:
                payload = stream.read(record['bytes']+1)
            if len(payload) != record['bytes'] or hashlib.sha256(payload).hexdigest() != record['sha256']:
                raise ValueError('Source changed during inspection')

    def evidence(self):
        return [dict(self.files[key]) for key in sorted(self.files)]


class _Source:
    def __init__(self, data_root, source, capture_id, lo, hi, source_workspace):
        self.source, self.capture_id = source, capture_id
        self.reader = _Reader(source_workspace if source == 'retro_capture' else data_root)
        self.frames = {}; self.basic = None; self.bridge = None; self.dataset_id = None
        self.permitted = None; self.symbols = None; self.initial_refs = None
        if source == 'baostock_bronze':
            for marker in ('manifest.json', 'baostock-series.json', 'baostock-dataset.json', 'archived-daily-dataset.json'):
                if self.reader.path(marker).exists():
                    raise ValueError('Managed source cannot fall back to bronze inspection')
            calendar = self.reader.parquet(CALENDAR, 40_000)
        else:
            from quantlab.data.archived_daily_dataset import _plan_and_references
            from quantlab.data.retro_daily import BASIC_FIELDS, CALENDAR_FIELDS
            names = ('plan.json', 'reference/stock_basic.json.gz', 'reference/trade_calendar.json.gz')
            if source == 'retro_capture':
                from quantlab.agent.qm50_archived_inputs import ArchivedDailyBridge
                self.bridge = ArchivedDailyBridge(self.reader.root)
                prefix = self.bridge.store._capture_dir(capture_id).relative_to(self.reader.root).as_posix()
                files = {name: self.reader.read(prefix+'/'+name) for name in names}
                self.initial_refs = files
            else:
                from quantlab.data.archived_daily_dataset import _inspect_package, MARKER
                checked = _inspect_package(self.reader.root)
                self.dataset_id = checked['manifest']['dataset_id']
                packaged = checked['manifest']['request']; capture_id = packaged['capture_id']
                self.symbols = set(packaged['symbols'])
                self.permitted = (_day(packaged['start']), _day(packaged['end']))
                self.reader.track(MARKER, checked['marker_payload'])
                for name, payload in checked['payloads'].items():
                    self.reader.track(name, payload)
                files = {name: checked['payloads']['source/'+name] for name in names}
                for symbol in packaged['symbols']:
                    name = 'source/symbols/'+symbol.replace('.', '_')+'/daily.parquet'
                    self.frames[symbol] = pl.read_parquet(io.BytesIO(checked['payloads'][name]))
            plan, basic_rows, calendar_rows = _plan_and_references(files, capture_id)
            self.plan = plan
            if self.permitted is None:
                self.permitted = (_day(plan['start']), _day(plan['end']))
                self.symbols = set(plan['symbols'])
            self.basic = pl.DataFrame(basic_rows, schema=list(BASIC_FIELDS), orient='row')
            calendar = pl.DataFrame(calendar_rows, schema=list(CALENDAR_FIELDS), orient='row')
        self.calendar = calendar_window(calendar, lo, hi)
        # Keep the capture's original JSON-content digest distinct from the
        # normalized date/flag semantic digest and the physical file SHA256.
        self.calendar['source_calendar_content_hash'] = (
            self.plan['calendar_content_hash'] if source != 'baostock_bronze' else None)
        blockers = []
        if not self.calendar['range_covered']:
            blockers.append('calendar_range_not_covered')
        if self.permitted and not self.permitted[0] <= lo <= hi <= self.permitted[1]:
            blockers.append('source_range_exceeded')
        self.calendar.update(source=source, capture_id=capture_id if source != 'baostock_bronze' else None,
            dataset_id=self.dataset_id, start=str(lo), end=str(hi), blockers=blockers,
            incomplete=bool(blockers), status='blocked' if blockers else 'available',
            permitted_range=[str(d) for d in self.permitted] if self.permitted else None,
            strict_pit=False, official_verified=False,
            evidence=self.reader.evidence(), limitations=LIMITATIONS)

    def bars(self, symbols, lo, hi):
        if self.source == 'baostock_bronze':
            self.basic = self.reader.parquet(BASIC)
            errors = {}
            for symbol in symbols:
                try:
                    self.frames[symbol] = self.reader.parquet(BRONZE+'stock_kline_daily/'+symbol.replace('.', '_')+'.parquet')
                except (OSError, ValueError, pl.exceptions.PolarsError) as exc:
                    errors[symbol] = str(exc)
            return errors
        if not set(symbols) <= self.symbols:
            raise ValueError('Requested symbols outside exact selected source')
        if self.bridge is not None:
            payloads, files, evidence, _, _, _ = self.bridge.load(self.capture_id, ' '.join(symbols), str(lo), str(hi))
            if files != self.initial_refs:
                raise ValueError('Capture references changed during inspection')
            for symbol, parts in payloads.items():
                self.frames[symbol] = pl.read_parquet(io.BytesIO(parts['daily']))
            self.market_evidence = evidence
        return {}


def _dates(values):
    return [str(day) for day in sorted(values)]


def _symbol_result(frame, basic, symbol, sessions, lo, hi):
    if not {'code', 'ipoDate', 'outDate'} <= set(basic.columns):
        raise ValueError('Lifecycle metadata missing code/ipoDate/outDate')
    matches = basic.filter(pl.col('code') == symbol)
    if matches.height != 1:
        raise ValueError('Lifecycle missing or ambiguous for '+symbol)
    row = matches.row(0, named=True)
    listed = _day(row['ipoDate'])
    ended = None if row['outDate'] == '' else _day(row['outDate'])
    if ended is not None and ended < listed:
        raise ValueError('Invalid listing interval')
    expected = {d for d in sessions if d >= listed and (ended is None or d <= ended)}
    if not {'date', 'code', 'adjustflag'} <= set(frame.columns):
        raise ValueError('Daily source missing date/code/adjustflag')
    if frame.filter(pl.col('code').is_null() | (pl.col('code') != symbol) |
                    pl.col('adjustflag').is_null() | (pl.col('adjustflag') != '3')).height:
        raise ValueError('Daily source symbol/raw flag mismatch')
    # Validate dates before filtering; a malformed date must not disappear in a filter.
    all_dates = [_day(v) for v in frame['date'].to_list()]
    states = frame['tradestatus'].to_list() if 'tradestatus' in frame.columns else [None]*frame.height
    selected = [(d, state) for d, state in zip(all_dates, states) if lo <= d <= hi]
    counts = Counter(d for d, _ in selected); actual = set(counts)
    missing, extra = expected-actual, actual-expected
    duplicates = {d for d, n in counts.items() if n > 1}
    suspended = {d for d, state in selected if type(state) in (str, int) and str(state) == '0'}
    unknown = {d for d, state in selected if type(state) not in (str, int) or str(state) not in ('0', '1')}
    blockers = []
    if suspended: blockers.append('requested_nontrading_rows')
    if unknown: blockers.append('trade_status_unknown')
    if missing or extra or duplicates: blockers.append('date_presence_not_exact')
    if expected != sessions: blockers.append('f9_requires_all_calendar_sessions')
    if not expected: blockers.append('no_expected_sessions_in_listing_interval')
    return {'symbol': symbol, 'ipo_date': str(listed), 'out_date': str(ended) if ended else None,
        'expected_dates_count': len(expected), 'actual_dates_count': len(actual), 'actual_rows': len(selected),
        'missing_dates': _dates(missing), 'unexpected_dates': _dates(extra), 'duplicate_dates': _dates(duplicates),
        'not_listed_dates': _dates(sessions-expected), 'suspended_dates': _dates(suspended),
        'unknown_state_dates': _dates(unknown), 'f9_blockers': blockers,
        'date_set_complete': bool(expected) and not (missing or extra or duplicates)}


def get_trading_calendar(data_root, source, capture_id, start, end, *, source_workspace=None):
    lo, hi, _ = _request(source, capture_id, start, end)
    material = _Source(data_root, source, capture_id, lo, hi, source_workspace)
    material.reader.recheck()
    return material.calendar


def check_daily_date_coverage(data_root, source, capture_id, symbols, start, end, *, source_workspace=None):
    lo, hi, selected = _request(source, capture_id, start, end, symbols)
    material = _Source(data_root, source, capture_id, lo, hi, source_workspace)
    calendar = material.calendar
    blockers = list(calendar['blockers'])
    if calendar['range_covered'] and not calendar['trading_dates']:
        blockers.append('no_calendar_trading_sessions')
    records, errors = [], []
    if not blockers:
        source_errors = material.bars(selected, lo, hi)
        sessions = {_day(d) for d in calendar['trading_dates']}
        for symbol in selected:
            try:
                if symbol in source_errors:
                    raise ValueError(source_errors[symbol])
                records.append(_symbol_result(material.frames[symbol], material.basic, symbol, sessions, lo, hi))
            except (ValueError, TypeError, pl.exceptions.PolarsError) as exc:
                errors.append({'symbol': symbol, 'code': 'SOURCE_NOT_COMPARABLE',
                               'message': str(exc).replace(str(material.reader.root), '<source-root>')[:400]})
                records.append({'symbol': symbol, 'date_set_complete': False, 'missing_dates': None,
                                'unexpected_dates': None, 'duplicate_dates': None})
    material.reader.recheck()
    incomplete = bool(blockers or errors) or any(not r['date_set_complete'] for r in records)
    value = {'method': 'explicit-source-daily-date-review-v1', 'source': source, 'capture_id': capture_id,
        'start': start, 'end': end, 'symbols': list(selected), 'calendar': calendar, 'records': records,
        'blockers': blockers, 'errors': errors, 'incomplete': incomplete,
        'status': 'blocked' if blockers else 'incomplete' if incomplete else 'complete',
        'evidence': material.reader.evidence(), 'strict_pit': False, 'tradability_verified': False,
        'price_values_verified': False, 'f9_export_verified': False, 'data_changed': False,
        'limitations': LIMITATIONS}
    if hasattr(material, 'market_evidence'):
        value['archive_evidence'] = material.market_evidence
    value['review_hash'] = digest(value)
    return value

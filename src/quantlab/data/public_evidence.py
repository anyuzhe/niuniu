"""After-close archive of public web market evidence (limit pools, billboard, boards, popularity).

Captures are forward observations: raw response bytes, request specs, fetch time and a
normalized table are stored immutably with SHA256 checksums. Public webpage APIs are not
official exchange feeds, carry no SLA and never certify strict PIT. Intraday capture is
not authorized here, and past trading days are only captured with an explicit late flag.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo
import hashlib
import io
import json
import re
import time as _time

import polars as pl

from quantlab.storage.codec import digest, encode

FORMAT = 'public-evidence-capture-v1'
TZ = ZoneInfo('Asia/Shanghai')
ALLOWED_HOSTS = frozenset({'push2ex.eastmoney.com', 'push2.eastmoney.com', 'datacenter-web.eastmoney.com',
                           'emappdata.eastmoney.com'})
HTTP_TIMEOUT = 15
MAX_BODY = 10_000_000
MAX_REQUESTS_PER_CAPTURE = 800
MIN_INTERVAL_SECONDS = 0.5
CLOSE = time(15, 0)
NEXT_SESSION_CUTOFF = time(9, 15)
SOURCE_ID = re.compile(r'^[a-z][a-z0-9_]{2,40}$')
CAPTURE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
TIMINGS = ('SAME_DAY_AFTER_CLOSE', 'BEFORE_NEXT_SESSION', 'LATE')


class PublicEvidenceError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RequestSpec:
    url: str
    method: str = 'GET'
    body: bytes | None = None
    headers: tuple = ()

    def describe(self):
        return {'url': self.url, 'method': self.method, 'headers': [list(h) for h in self.headers],
                'body_sha256': hashlib.sha256(self.body).hexdigest() if self.body is not None else None,
                'body': self.body.decode('utf-8') if self.body is not None else None}


@dataclass
class Response:
    request: RequestSpec
    status: int
    final_url: str
    content_type: str
    body: bytes
    fetched_at: datetime


@dataclass
class ParsedTable:
    rows: list
    schema: dict
    warnings: list = field(default_factory=list)


class Source:
    """Base class: subclasses define identity, requests, optional pagination and parsing."""
    source_id = ''
    parser_version = ''
    description = ''
    limitations: tuple = ()

    def requests(self, day):
        raise NotImplementedError

    def follow_up(self, day, responses):
        return []

    def parse(self, day, responses):
        raise NotImplementedError


def http_fetch(spec):
    parsed = urlparse(spec.url)
    if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS:
        raise PublicEvidenceError('HOST_NOT_ALLOWED', '公开证据主机不在白名单：' + str(parsed.hostname))
    if spec.method not in ('GET', 'POST'):
        raise PublicEvidenceError('INVALID_REQUEST', '只允许 GET/POST。')
    headers = {'User-Agent': 'Mozilla/5.0', **dict(spec.headers)}
    request = Request(spec.url, data=spec.body, headers=headers, method=spec.method)
    with urlopen(request, timeout=HTTP_TIMEOUT) as response:
        final = urlparse(response.geturl())
        if final.scheme != 'https' or final.hostname not in ALLOWED_HOSTS:
            raise PublicEvidenceError('HOST_NOT_ALLOWED', '重定向离开白名单。')
        body = response.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise PublicEvidenceError('BUDGET_EXCEEDED', '响应超过 10MB。')
        return response.status, response.geturl(), response.headers.get('Content-Type', ''), body


def _day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise PublicEvidenceError('INVALID_ARGUMENT', '交易日必须为 YYYY-MM-DD。') from None


def next_weekday(day):
    following = day + timedelta(days=1)
    while following.weekday() >= 5:
        following += timedelta(days=1)
    return following


def capture_timing(day, fetched_at):
    """Classify a capture by when it happened relative to the trading day's close."""
    if not isinstance(fetched_at, datetime) or fetched_at.tzinfo is None:
        raise PublicEvidenceError('INVALID_CLOCK', '抓取时间必须带时区。')
    local = fetched_at.astimezone(TZ)
    if local.date() < day or (local.date() == day and local.time() < CLOSE):
        return 'NOT_AFTER_CLOSE'
    if local.date() == day:
        return 'SAME_DAY_AFTER_CLOSE'
    if local < datetime.combine(next_weekday(day), NEXT_SESSION_CUTOFF, TZ):
        return 'BEFORE_NEXT_SESSION'
    return 'LATE'


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _checked(value):
    return {**value, 'checksum': digest(value)}


def _verify(value, what):
    if not isinstance(value, dict) or 'checksum' not in value:
        raise PublicEvidenceError('CORRUPT_ARCHIVE', what + ' 缺少 checksum。')
    core = {k: v for k, v in value.items() if k != 'checksum'}
    if value['checksum'] != digest(core):
        raise PublicEvidenceError('CORRUPT_ARCHIVE', what + ' checksum 校验失败。')
    return core


class PublicEvidenceArchive:
    def __init__(self, output, *, sources=None, now_fn=None, http=None, sleep=_time.sleep, calendar_days=None):
        self.output = Path(output).resolve()
        if not self.output.is_dir():
            raise PublicEvidenceError('INVALID_WORKSPACE', '工作空间不存在。')
        if sources is None:
            from quantlab.data.eastmoney_sources import default_sources
            sources = default_sources()
        self.sources = {s.source_id: s for s in sources}
        if any(not SOURCE_ID.fullmatch(s) for s in self.sources):
            raise PublicEvidenceError('INVALID_SOURCE', 'source_id 无效。')
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.http = http or http_fetch
        self.sleep = sleep
        self.calendar_days = calendar_days
        self.root = self.output / '_market_data' / 'public_evidence'

    # ---- helpers -------------------------------------------------------------------------------
    def _source(self, source_id):
        source = self.sources.get(source_id)
        if source is None:
            raise PublicEvidenceError('UNKNOWN_SOURCE', '未知公开证据来源：' + str(source_id))
        return source

    def _day_dir(self, source_id, day):
        self._source(source_id)
        for path in (self.output / '_market_data', self.root, self.root / source_id):
            if path.is_symlink():
                raise PublicEvidenceError('INVALID_WORKSPACE', '公开证据路径不能是符号链接。')
        return self.root / source_id / _day(day).isoformat()

    def _calendar_status(self, day):
        if day.weekday() >= 5:
            raise PublicEvidenceError('NOT_TRADING_DAY', '周末不是交易日。')
        if self.calendar_days is None:
            return False
        if day.isoformat() in self.calendar_days:
            return True
        return False

    def _fetch_all(self, source, day):
        responses, queue, last = [], list(source.requests(day)), None
        while queue:
            if len(responses) >= MAX_REQUESTS_PER_CAPTURE:
                raise PublicEvidenceError('BUDGET_EXCEEDED', '单次抓取请求数超过上限。')
            spec = queue.pop(0)
            if last is not None:
                wait = MIN_INTERVAL_SECONDS - (_time.monotonic() - last)
                if wait > 0:
                    self.sleep(wait)
            try:
                status, final_url, content_type, body = self.http(spec)
            except PublicEvidenceError:
                raise
            except Exception as error:
                raise PublicEvidenceError('PROVIDER_ERROR', f'{source.source_id} 请求失败：{type(error).__name__}: {str(error)[:160]}') from None
            last = _time.monotonic()
            if status != 200:
                raise PublicEvidenceError('PROVIDER_ERROR', f'{source.source_id} HTTP {status}。')
            fetched = self.now_fn()
            responses.append(Response(spec, status, final_url, content_type, body, fetched))
            if not queue:
                queue.extend(source.follow_up(day, responses))
        return responses

    def _pointer(self, folder):
        path = folder / 'accepted.json'
        if not path.exists():
            return None
        if path.is_symlink():
            raise PublicEvidenceError('CORRUPT_ARCHIVE', 'accepted 指针不能是符号链接。')
        return _verify(json.loads(path.read_bytes()), 'accepted.json')

    def _write_pointer(self, folder, value):
        path = folder / 'accepted.json'
        temporary = folder / ('.accepted-' + str(uuid4()) + '.tmp')
        temporary.write_text(encode(_checked(value)), encoding='utf-8')
        temporary.replace(path)

    # ---- capture -------------------------------------------------------------------------------
    def capture(self, source_id, day, *, allow_late=False):
        source = self._source(source_id)
        day = _day(day)
        calendar_verified = self._calendar_status(day)
        started = self.now_fn()
        timing = capture_timing(day, started)
        if timing == 'NOT_AFTER_CLOSE':
            raise PublicEvidenceError('NOT_AFTER_CLOSE', '只授权收盘后归档；盘中或未来日期不抓取。')
        if timing == 'LATE' and allow_late is not True:
            raise PublicEvidenceError('LATE_CAPTURE_NOT_ALLOWED', '已过下一交易日 09:15，补抓需显式 allow_late，结果标记为 LATE。')
        folder = self._day_dir(source_id, day)
        responses = self._fetch_all(source, day)
        parsed = source.parse(day, responses)
        if not isinstance(parsed, ParsedTable):
            raise PublicEvidenceError('PARSER_ERROR', '解析器返回类型无效。')
        try:
            frame = pl.DataFrame(parsed.rows, schema=parsed.schema, orient='row') if parsed.rows else pl.DataFrame(schema=parsed.schema)
        except Exception as error:
            raise PublicEvidenceError('DATA_SCHEMA', f'{source_id} 规范化表构建失败：{str(error)[:200]}') from None
        content_hash = digest({'source_id': source_id, 'parser_version': source.parser_version, 'day': day.isoformat(),
                               'rows': parsed.rows})
        capture_id = str(uuid5(NAMESPACE_URL, f'niuniu-public-evidence:{source_id}:{day}:{started.isoformat()}:{content_hash}'))
        stream = io.BytesIO()
        frame.write_parquet(stream, compression='zstd')
        table_bytes = stream.getvalue()
        finished = self.now_fn()
        response_entries = []
        for index, response in enumerate(responses):
            response_entries.append({'index': index, 'request': response.request.describe(), 'status': response.status,
                                     'final_url': response.final_url, 'content_type': response.content_type,
                                     'fetched_at': response.fetched_at.astimezone(timezone.utc).isoformat(),
                                     'bytes': len(response.body), 'sha256': _sha(response.body)})
        folder.mkdir(parents=True, exist_ok=True)
        pointer = self._pointer(folder)
        accepted = self.get(source_id, day) if pointer else None
        if accepted and accepted['content_hash'] == content_hash:
            return {**accepted, 'created': False, 'revision_detected': False}
        state = 'accepted' if accepted is None else 'revision_review'
        manifest = {'format': FORMAT, 'capture_id': capture_id, 'source_id': source_id, 'parser_version': source.parser_version,
                    'description': source.description, 'trading_day': day.isoformat(), 'capture_timing': timing,
                    'calendar_verified': calendar_verified, 'started_at': started.astimezone(timezone.utc).isoformat(),
                    'finished_at': finished.astimezone(timezone.utc).isoformat(), 'responses': response_entries,
                    'rows': frame.height, 'columns': list(frame.columns), 'table_sha256': _sha(table_bytes),
                    'content_hash': content_hash, 'warnings': parsed.warnings, 'capture_state': state,
                    'revision_of': accepted['capture_id'] if accepted else None,
                    'qualification': 'research_only' if timing != 'LATE' else 'research_only_late_capture',
                    'limitations': list(source.limitations) + ['公开网页接口，不是交易所官方数据；不认证 strict PIT；接口字段与口径可能变化。']}
        temporary = folder / ('.tmp-' + str(uuid4()))
        (temporary / 'responses').mkdir(parents=True)
        for index, response in enumerate(responses):
            (temporary / 'responses' / f'{index:04d}.bin').write_bytes(response.body)
        (temporary / 'table.parquet').write_bytes(table_bytes)
        (temporary / 'manifest.json').write_text(encode(_checked(manifest)), encoding='utf-8')
        temporary.replace(folder / capture_id)
        if accepted is None:
            self._write_pointer(folder, {'source_id': source_id, 'trading_day': day.isoformat(), 'capture_id': capture_id,
                                         'manifest_sha256': _sha((folder / capture_id / 'manifest.json').read_bytes())})
        return {**manifest, 'created': True, 'revision_detected': state == 'revision_review'}

    # ---- reading -------------------------------------------------------------------------------
    def _manifest(self, source_id, day, capture_id, *, deep=True):
        if not CAPTURE.fullmatch(capture_id or ''):
            raise PublicEvidenceError('INVALID_ARGUMENT', 'capture_id 无效。')
        folder = self._day_dir(source_id, day) / capture_id
        path = folder / 'manifest.json'
        if folder.is_symlink() or path.is_symlink() or not path.is_file():
            raise PublicEvidenceError('NOT_FOUND', '公开证据 capture 不存在。')
        manifest = _verify(json.loads(path.read_bytes()), 'manifest.json')
        if manifest.get('format') != FORMAT or manifest.get('capture_id') != capture_id or manifest.get('source_id') != source_id:
            raise PublicEvidenceError('CORRUPT_ARCHIVE', 'manifest 身份无效。')
        if deep:
            if _sha((folder / 'table.parquet').read_bytes()) != manifest['table_sha256']:
                raise PublicEvidenceError('CORRUPT_ARCHIVE', 'table.parquet 哈希校验失败。')
            for entry in manifest['responses']:
                body = (folder / 'responses' / f"{entry['index']:04d}.bin").read_bytes()
                if _sha(body) != entry['sha256']:
                    raise PublicEvidenceError('CORRUPT_ARCHIVE', '原始响应哈希校验失败。')
        return manifest, folder

    def get(self, source_id, day, capture_id=None):
        folder = self._day_dir(source_id, day)
        if capture_id is None:
            pointer = self._pointer(folder) if folder.exists() else None
            if pointer is None:
                raise PublicEvidenceError('NOT_FOUND', '该来源该交易日没有已接受的归档。')
            capture_id = pointer['capture_id']
            manifest, path = self._manifest(source_id, day, capture_id)
            if _sha((path / 'manifest.json').read_bytes()) != pointer['manifest_sha256']:
                raise PublicEvidenceError('CORRUPT_ARCHIVE', 'accepted 指针与 manifest 不一致。')
            return {**manifest, 'accepted': True}
        manifest, _ = self._manifest(source_id, day, capture_id)
        pointer = self._pointer(folder)
        return {**manifest, 'accepted': bool(pointer and pointer['capture_id'] == capture_id)}

    def read_table(self, source_id, day, capture_id=None):
        manifest = self.get(source_id, day, capture_id)
        folder = self._day_dir(source_id, day) / manifest['capture_id']
        frame = pl.read_parquet(io.BytesIO((folder / 'table.parquet').read_bytes()))
        if frame.height != manifest['rows']:
            raise PublicEvidenceError('CORRUPT_ARCHIVE', 'table.parquet 行数与 manifest 不一致。')
        return frame, manifest

    def accept_revision(self, source_id, day, capture_id, *, confirmed=False):
        if confirmed is not True:
            raise PublicEvidenceError('CONFIRMATION_REQUIRED', '接受修订需要显式确认。')
        current = self.get(source_id, day)
        candidate, folder = self._manifest(source_id, day, capture_id)
        if candidate['capture_state'] != 'revision_review' or candidate['revision_of'] != current['capture_id']:
            raise PublicEvidenceError('INVALID_REVISION', '只能接受基于当前归档的修订。')
        self._write_pointer(folder.parent, {'source_id': source_id, 'trading_day': _day(day).isoformat(), 'capture_id': capture_id,
                                            'manifest_sha256': _sha((folder / 'manifest.json').read_bytes())})
        return {**candidate, 'accepted': True}

    def list_days(self, source_id, limit=500):
        base = self.root / self._source(source_id).source_id
        if type(limit) is not int or not 1 <= limit <= 5000:
            raise PublicEvidenceError('INVALID_ARGUMENT', 'limit 必须为 1–5000。')
        if not base.exists():
            return []
        rows = []
        for folder in sorted((p for p in base.iterdir() if p.is_dir() and re.fullmatch(r'\d{4}-\d{2}-\d{2}', p.name)), reverse=True):
            try:
                manifest = self.get(source_id, folder.name)
            except PublicEvidenceError as error:
                rows.append({'trading_day': folder.name, 'error': error.code})
                continue
            revisions = sum(1 for p in folder.iterdir() if p.is_dir() and CAPTURE.fullmatch(p.name) and p.name != manifest['capture_id'])
            rows.append({'trading_day': folder.name, 'capture_id': manifest['capture_id'], 'rows': manifest['rows'],
                         'capture_timing': manifest['capture_timing'], 'started_at': manifest['started_at'],
                         'other_captures': revisions})
            if len(rows) >= limit:
                break
        return rows

    def overview(self):
        return {source_id: {'description': source.description, 'parser_version': source.parser_version,
                            'days': len(self.list_days(source_id, limit=5000))} for source_id, source in sorted(self.sources.items())}


__all__ = ['FORMAT', 'ALLOWED_HOSTS', 'TIMINGS', 'PublicEvidenceError', 'RequestSpec', 'Response', 'ParsedTable', 'Source',
           'PublicEvidenceArchive', 'capture_timing', 'http_fetch', 'next_weekday']

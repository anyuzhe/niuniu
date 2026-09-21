"""TDX control-plane bundles: fixed shards, minimal checkpoints, verified imports.

Bundle files belong on a real authenticated file transport, never in MCP text.
Only explicit personal research is supported; a drained queue is not certification.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile

import polars as pl

from quantlab.data.tdx_lake import (
    TdxLake, FAMILIES, QUALIFICATION, digest, encode, frame_for, now,
    rows_for, safe, sha, write_json, is_redirect,
)
from quantlab.data.tdx_sharding import (
    ALGORITHM, ROLE_FILE, GLOBAL_FAMILIES, checked, sealed, shard_for,
    make_assignment, validate_assignment, require_owned_job, read_role,
    load_worker_assignment, validate_worker_queue,
)
from quantlab.agent.tdx_collection_cli import (
    load_scheduler_policy, validate_scheduler_policy, writer_lease,
)

BOOTSTRAP_FORMAT = 'tdx-worker-bootstrap-v1'
RESULT_FORMAT = 'tdx-worker-results-v1'
CLUSTER_FORMAT = 'tdx-distributed-cluster-v1'
JOB_COLUMNS = ('job_id', 'plan_id', 'family', 'symbol', 'day', 'offset', 'priority',
               'state', 'attempts', 'rows', 'chunk', 'error', 'updated_at')
ACTIVE_STATES = frozenset(('PENDING', 'RUNNING', 'STORED', 'ERROR', 'STALLED', 'PAGE_LIMIT', 'SKIPPED_POLICY'))
ALL_STATES = ACTIVE_STATES | frozenset(('SAVED', 'EMPTY', 'CHECKPOINT'))
PAGE_FILES = ('response.json.gz', 'data.parquet', 'manifest.json')
MAX_BUNDLE_BYTES = 16 * 1024**3
MAX_PAGE_BYTES = 64 * 1024**2
MAX_METADATA_BYTES = 128 * 1024**2


class BundleConflict(ValueError):
    """Incoming evidence failed validation; canonical bytes remain unchanged."""


class BundleDeferred(RuntimeError):
    """Valid delivery must wait for an earlier bundle or sufficient local capacity."""


def require_disk(path: Path, bytes_needed: int) -> None:
    if shutil.disk_usage(path).free < 30*1024**3 + bytes_needed:
        raise BundleDeferred('DISK_RESERVE: preserve 30 GiB while staging transfers')


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def local_path(root: Path, text: str) -> Path:
    if not isinstance(text, str) or '\\' in text or ':' in text or '\x00' in text:
        raise ValueError('Unsafe portable bundle path')
    relative = PurePosixPath(text)
    if relative.is_absolute() or not relative.parts or any(p in ('..', '.') for p in relative.parts):
        raise ValueError('Unsafe portable bundle path')
    return safe(root, root.joinpath(*relative.parts))


def portable_chunk(text: str | None) -> str | None:
    return text.replace('\\', '/') if text is not None else None


def validate_plan(body: dict, pid: str) -> None:
    if digest(body) != pid or body.get('personal_research_only') is not True or body.get('commercial_or_trading_use', False) is not False:
        raise ValueError('Invalid personal-research plan')
    days = body.get('trading_days')
    if not isinstance(days, list) or not days or days != sorted(set(days)):
        raise ValueError('Invalid distributed trading calendar')
    if any(not isinstance(d, str) or date.fromisoformat(d).isoformat() != d for d in days):
        raise ValueError('Noncanonical distributed calendar')


def validate_job(job: dict, assignment: dict, plan: dict) -> dict:
    if not isinstance(job, dict) or any(k not in job for k in JOB_COLUMNS):
        raise ValueError('Incomplete distributed job record')
    require_owned_job(assignment, job)
    if job['state'] not in ALL_STATES or job['day'] not in plan['trading_days']:
        raise ValueError('Invalid distributed job state/date')
    for name, lo, hi in (('offset', 0, 1000000), ('attempts', 0, 1000000),
                         ('rows', 0, 10000000), ('priority', -1000000000, 1000000000)):
        if type(job[name]) is not int or not lo <= job[name] <= hi:
            raise ValueError('Invalid distributed job '+name)
    if job['error'] is not None and (not isinstance(job['error'], str) or len(job['error']) > 10000):
        raise ValueError('Invalid distributed error record')
    if not isinstance(job['updated_at'], str):
        raise ValueError('Invalid distributed job timestamp')
    datetime.fromisoformat(job['updated_at'])
    if job['chunk'] is not None:
        chunk = portable_chunk(job['chunk'])
        if PurePosixPath(chunk).is_absolute() or '..' in PurePosixPath(chunk).parts or ':' in chunk:
            raise ValueError('Invalid job checkpoint path')
    return {k: job[k] for k in JOB_COLUMNS}


def page_descriptor(lake: TdxLake, job: dict, state: str) -> tuple[dict, object]:
    sid = PurePosixPath(portable_chunk(job['chunk'])).name
    source = lake.page_source(job['family'], sid, portable_chunk(job['chunk']))
    manifest = source.verify()
    for key in ('plan_id', 'family', 'symbol', 'day', 'offset'):
        if manifest[key] != job[key]:
            raise ValueError('Checkpoint request identity mismatch')
    descriptor = {'source_id': sid, 'family': job['family'], 'job_id': job['job_id'],
        'state': state, 'rows': manifest['rows'], 'raw_sha256': manifest['raw_sha256'],
        'parquet_sha256': manifest['parquet_sha256'], 'manifest_sha256': source.sha256('manifest.json')}
    return descriptor, source


def verify_bundle_page(folder: Path, item: dict, assignment: dict, plan: dict) -> tuple[dict, dict, list]:
    sid, family = item.get('source_id'), item.get('family')
    if family not in FAMILIES or not re.fullmatch(r'[a-f0-9]{64}', str(sid)):
        raise ValueError('Invalid incoming page identity')
    for filename, field in (('response.json.gz', 'raw_sha256'), ('data.parquet', 'parquet_sha256'), ('manifest.json', 'manifest_sha256')):
        path = folder/filename
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_PAGE_BYTES or file_sha(path) != item[field]:
            raise ValueError('Incoming page checksum/size mismatch: '+filename)
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    checked(manifest)
    for key in ('source_id', 'family', 'rows', 'raw_sha256', 'parquet_sha256'):
        if manifest.get(key) != item.get(key):
            raise ValueError('Incoming manifest/descriptor mismatch')
    if manifest.get('qualification') != QUALIFICATION or manifest.get('complete_history') is not False:
        raise ValueError('Incoming qualification was upgraded')
    with gzip.open(folder/'response.json.gz', 'rb') as stream:
        raw_bytes = stream.read(MAX_PAGE_BYTES + 1)
    if len(raw_bytes) > MAX_PAGE_BYTES:
        raise ValueError('Oversized expanded source response')
    raw = json.loads(raw_bytes)
    request = raw.get('request')
    if not isinstance(request, dict) or request.get('job_id') != item['job_id'] or raw.get('parser') != 'eltdx==3.2.2':
        raise ValueError('Incoming raw request/parser mismatch')
    require_owned_job(assignment, request)
    if request['day'] not in plan['trading_days']:
        raise ValueError('Incoming request day outside canonical plan')
    for key in ('plan_id', 'family', 'symbol', 'day', 'offset'):
        if request.get(key) != manifest.get(key):
            raise ValueError('Incoming raw/manifest request mismatch')
    result = raw.get('result')
    if result is None or isinstance(result, dict) and result.get('error_code') not in (None, 0, '0'):
        raise ValueError('Error/None is not an empty successful response')
    if digest({'job': request['job_id'], 'body': result}) != sid:
        raise ValueError('Incoming source_id does not identify raw request/result')
    if isinstance(result, dict) and family in ('bars_1m','bars_5m','bars_daily','trades','auction','finance','capital_changes'):
        if result.get('code') and result.get('exchange', '')+'.'+result['code'] != request['symbol']:
            raise ValueError('Wrong incoming response security')
        if result.get('trading_date') and result['trading_date'] != request['day']:
            raise ValueError('Wrong incoming response date')
    observed = raw.get('observed_at')
    if observed != manifest.get('observed_at') or datetime.fromisoformat(observed).tzinfo is None:
        raise ValueError('Incoming observation time mismatch')
    rows = rows_for(family, result)
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows) or len(rows) != manifest['rows']:
        raise ValueError('Incoming parsed row count/schema mismatch')
    if item['state'] == 'SAVED' and not rows or item['state'] == 'EMPTY' and rows:
        raise ValueError('Incoming SAVED/EMPTY classification mismatch')
    actual = pl.read_parquet(folder/'data.parquet')
    expected = frame_for(family, rows, request, observed, sid)
    if actual.schema != expected.schema or not actual.equals(expected):
        raise ValueError('Incoming Parquet does not exactly reproduce raw rows')
    return manifest, raw, rows


def _source_size(source, filename):
    return source.size(filename) if hasattr(source,'size') else (source/filename).stat().st_size


@contextmanager
def _source_open(source, filename):
    if hasattr(source,'open') and not isinstance(source,Path):
        with source.open(filename) as stream:yield stream
    else:
        path=source/filename
        if path.is_symlink():raise ValueError('Unsafe source page')
        with path.open('rb') as stream:yield stream


def write_bundle(directory: Path, body: dict, sources: dict) -> dict:
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    value = sealed(body, 'bundle_id')
    target = directory/(value['bundle_id']+'.tar')
    temporary = directory/('.'+str(uuid4())+'.part')
    metadata = encode(value).encode('utf-8')
    require_disk(directory, len(metadata) + sum(_source_size(sources[p['source_id']],f) for p in value['pages'] for f in PAGE_FILES))
    if len(metadata) > MAX_METADATA_BYTES:
        raise ValueError('Bundle metadata too large')
    try:
        with tarfile.open(temporary, 'w', format=tarfile.PAX_FORMAT) as archive:
            info = tarfile.TarInfo('bundle.json'); info.size = len(metadata); info.mode = 0o600
            archive.addfile(info, io.BytesIO(metadata))
            for item in value['pages']:
                source = sources[item['source_id']]
                for filename in PAGE_FILES:
                    size = _source_size(source,filename)
                    if size > MAX_PAGE_BYTES:
                        raise ValueError('Unsafe/oversized source page')
                    info = tarfile.TarInfo('pages/'+item['source_id']+'/'+filename)
                    info.size = size; info.mode = 0o600
                    with _source_open(source,filename) as stream:
                        archive.addfile(info, stream)
        if temporary.stat().st_size > MAX_BUNDLE_BYTES:
            raise ValueError('Bundle exceeds transfer budget')
        receipt = {'bundle_id': value['bundle_id'], 'sha256': file_sha(temporary),
            'bytes': temporary.stat().st_size, 'path': str(target),
            'format': value['format'], 'machine_name': value['assignment']['machine_name'],
            'shard_id': value['assignment']['shard_id'], 'created_at': now()}
        if target.exists():
            if file_sha(target) != receipt['sha256']:
                raise BundleConflict('Existing bundle differs; refusing overwrite')
            temporary.unlink()
        else:
            temporary.rename(target)
        write_json(directory/(value['bundle_id']+'.receipt.json'), receipt)
        return receipt
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def unpack_bundle(path: Path, expected_sha: str, parent: Path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_BUNDLE_BYTES:
        raise ValueError('Invalid bundle file/size')
    if not re.fullmatch(r'[a-f0-9]{64}', expected_sha or '') or file_sha(path) != expected_sha:
        raise ValueError('Bundle transport SHA256 mismatch')
    parent = parent.resolve(); parent.mkdir(parents=True, exist_ok=True)
    require_disk(parent, path.stat().st_size)
    with tempfile.TemporaryDirectory(prefix='.tdx-bundle-', dir=parent) as temp:
        root = Path(temp).resolve(); seen = set(); total = 0
        with tarfile.open(path, 'r:') as archive:
            for member in archive:
                name = member.name
                if not member.isfile() or name.casefold() in seen or len(seen) >= 100000:
                    raise ValueError('Duplicate/non-file/oversized archive inventory')
                if name != 'bundle.json' and not re.fullmatch(r'pages/[a-f0-9]{64}/(response\.json\.gz|data\.parquet|manifest\.json)', name):
                    raise ValueError('Unexpected/unsafe archive member')
                limit = MAX_METADATA_BYTES if name == 'bundle.json' else MAX_PAGE_BYTES
                if not 0 <= member.size <= limit:
                    raise ValueError('Archive member exceeds budget')
                total += member.size
                if total > MAX_BUNDLE_BYTES:
                    raise ValueError('Expanded bundle exceeds budget')
                seen.add(name.casefold())
                target = local_path(root, name); target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError('Missing archive payload')
                with source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, 1024*1024)
        value = json.loads((root/'bundle.json').read_text(encoding='utf-8'))
        checked(value, 'bundle_id')
        expected = {'bundle.json'}
        if not isinstance(value.get('pages'), list):
            raise ValueError('Missing bundle page inventory')
        identifiers = set()
        for item in value['pages']:
            sid = item['source_id']
            if sid in identifiers or not re.fullmatch(r'[a-f0-9]{64}', sid):
                raise ValueError('Duplicate/invalid source_id in bundle')
            identifiers.add(sid)
            expected.update('pages/'+sid+'/'+f for f in PAGE_FILES)
        if expected != seen:
            raise ValueError('Bundle file inventory mismatch')
        yield root, value


def _insert_job(con, job: dict) -> None:
    con.execute('INSERT OR IGNORE INTO jobs('+','.join(JOB_COLUMNS)+') VALUES ('+','.join('?' for _ in JOB_COLUMNS)+')', tuple(job[k] for k in JOB_COLUMNS))


def create_bootstraps(lake: TdxLake, pid: str, output: Path,
                      machines=('macbook', 'homepc', '601')) -> dict:
    if len(machines) != len(set(machines)) or not 1 <= len(machines) <= 32:
        raise ValueError('Invalid worker machine inventory')
    with writer_lease(lake):
        if not (lake.base/'STOP').exists():
            raise ValueError('Stop canonical collection before exporting checkpoints')
        if read_role(lake) is not None:
            raise ValueError('Distributed role already exists; never silently re-bootstrap an active cluster')
        lake.reconcile_publications()
        plan = lake.plan(pid); validate_plan(plan, pid)
        policy = load_scheduler_policy(lake, pid)
        if not policy.get('policy_id'):
            raise ValueError('Reviewed scheduler policy required before sharding')
        with lake.db(readonly=True) as con:
            all_jobs = [dict(r) for r in con.execute('SELECT * FROM jobs WHERE plan_id=? ORDER BY job_id', (pid,))]
        if any(j['state'] in ('RUNNING', 'STORED') for j in all_jobs):
            raise ValueError('Unreconciled in-flight jobs; perform bounded recovery before bootstrap')
        snapshot = digest(all_jobs)
        cluster_id = digest({'plan_id': pid, 'policy_id': policy['policy_id'], 'shard_algorithm': ALGORITHM,
                             'machines': list(machines), 'queue_snapshot': snapshot})
        assignments = [make_assignment(plan, pid, policy['policy_id'], cluster_id, len(machines), i, name)
                       for i, name in enumerate(machines)]
        output = Path(output).resolve()/cluster_id
        receipts = []
        for assignment in assignments:
            def owned(job):
                return assignment['shard_id'] == 0 if job['family'] in GLOBAL_FAMILIES else shard_for(job['symbol'], len(machines)) == assignment['shard_id']
            own = [j for j in all_jobs if owned(j)]
            frontier = [dict(j) for j in own if j['state'] in ACTIVE_STATES]
            checkpoints = {}; pages = {}; sources = {}
            with lake.db(readonly=True) as con:
                for index, job in enumerate(frontier):
                    validate_job(job, assignment, plan)
                    if job['chunk']:
                        item, folder = page_descriptor(lake, job, job['state'])
                        pages[item['source_id']] = item; sources[item['source_id']] = folder
                    if job['offset'] and (job['family'].startswith('bars_') or job['family'] == 'trades'):
                        previous = con.execute("SELECT * FROM jobs WHERE plan_id=? AND family=? AND symbol=? AND day=? AND offset<? AND state='SAVED' AND chunk IS NOT NULL ORDER BY offset DESC LIMIT 1",
                            (pid, job['family'], job['symbol'], job['day'], job['offset'])).fetchone()
                        if not previous or previous['offset']+previous['rows'] != job['offset']:
                            raise ValueError('Missing exact previous saved checkpoint for '+job['job_id'])
                        previous = dict(previous); validate_job(previous, assignment, plan)
                        item, folder = page_descriptor(lake, previous, 'CHECKPOINT')
                        checkpoints[previous['job_id']] = {**previous, 'checkpoint_source_id': item['source_id']}
                        pages[item['source_id']] = item; sources[item['source_id']] = folder
                    if index and index % 500 == 0:
                        print(encode({'phase': 'bootstrap_checkpoints', 'shard_id': assignment['shard_id'], 'frontiers_checked': index, 'checkpoint_pages': len(pages)}), flush=True)
            baseline = dict(Counter(j['state'] for j in own))
            body = {'format': BOOTSTRAP_FORMAT, 'plan_id': pid, 'plan': plan, 'policy': policy,
                'assignment': assignment, 'queue_snapshot': snapshot, 'created_at': now(),
                'frontier_jobs': frontier, 'checkpoint_jobs': list(checkpoints.values()),
                'baseline_queue_counts': baseline, 'pages': sorted(pages.values(), key=lambda x: x['source_id']),
                'qualification': QUALIFICATION, 'license': 'ELTDX Research-Only; personal noncommercial research only',
                'history_complete': False}
            receipt = write_bundle(output, body, sources)
            receipt.update({'symbols': assignment['symbol_count'], 'frontier_jobs': len(frontier), 'checkpoint_pages': len(pages)})
            receipts.append(receipt)
            print(encode({'phase': 'bootstrap_ready', **receipt}), flush=True)
        cluster = sealed({'format': CLUSTER_FORMAT, 'cluster_id': cluster_id, 'plan_id': pid,
            'policy_id': policy['policy_id'], 'shard_algorithm': ALGORITHM, 'shard_count': len(machines),
            'queue_snapshot': snapshot, 'assignments': assignments, 'bundles': receipts,
            'created_at': now(), 'history_complete': False})
        write_json(output/'cluster.json', cluster)
        write_json(lake.base/ROLE_FILE, sealed({'role': 'coordinator', 'cluster': cluster, 'created_at': now()}))
        return cluster


def install_bootstrap(destination: Path, bundle_path: Path, expected_sha: str) -> dict:
    destination = Path(destination).absolute()
    if is_redirect(destination):
        raise ValueError('Worker destination cannot be a symlink/junction')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with unpack_bundle(bundle_path, expected_sha, destination.parent) as (unpacked, body):
        if body.get('format') != BOOTSTRAP_FORMAT or body.get('history_complete') is not False:
            raise ValueError('Not a supported worker bootstrap')
        plan, pid, policy = body['plan'], body['plan_id'], body['policy']
        validate_plan(plan, pid); validate_scheduler_policy(policy, pid)
        assignment = validate_assignment(body['assignment'], plan, pid, policy['policy_id'])
        if destination.exists() and any(destination.iterdir()):
            existing = TdxLake(destination); role = read_role(existing)
            if role and role.get('role') == 'worker' and role.get('bootstrap_id') == body['bundle_id'] and role.get('bootstrap_sha256') == expected_sha:
                load_worker_assignment(existing, pid, policy['policy_id'])
                return {'already_installed': True, 'data_root': str(destination), 'assignment': assignment['assignment_id']}
            raise ValueError('Refusing to overwrite a nonempty worker data root')
        pages = {item['source_id']: item for item in body['pages']}
        verified = {}
        for index, item in enumerate(body['pages']):
            # Retain only manifests: thousands of checkpoint raw dictionaries must
            # not stay resident on the 16 GiB coordinator/worker installation host.
            verified[item['source_id']] = verify_bundle_page(unpacked/'pages'/item['source_id'], item, assignment, plan)[0]
            if index and index % 500 == 0:
                print(encode({'phase': 'bootstrap_verify', 'shard_id': assignment['shard_id'], 'pages': index}), flush=True)
        frontier = [validate_job(j, assignment, plan) for j in body['frontier_jobs']]
        prior = [validate_job(j, assignment, plan) for j in body['checkpoint_jobs']]
        identifiers = [j['job_id'] for j in frontier+prior]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError('Duplicate jobs in bootstrap')
        prior_by_key = {(j['family'], j['symbol'], j['day'], j['offset']+j['rows']): j for j in prior}
        for job in frontier:
            if job['offset'] and (job['family'].startswith('bars_') or job['family'] == 'trades'):
                if (job['family'], job['symbol'], job['day'], job['offset']) not in prior_by_key:
                    raise ValueError('Bootstrap omitted preceding pagination evidence')
        stage = destination.parent/('.'+destination.name+'.bootstrap-'+str(uuid4()))
        stage.mkdir()
        try:
            worker = TdxLake(stage, create=True)
            if worker.add_plan(plan) != pid:
                raise ValueError('Bootstrap plan changed')
            copied = {}
            for item in body['pages']:
                sid = item['source_id']
                section = '_checkpoints' if item['state'] == 'CHECKPOINT' else '_stored'
                target = worker.base/section/item['family']/sid
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(unpacked/'pages'/sid, target)
                copied[sid] = target.relative_to(worker.root).as_posix()
            sid_by_job = {p['job_id']: p['source_id'] for p in body['pages']}
            with worker.db() as con:
                for job in prior:
                    if job['job_id'] not in sid_by_job:
                        raise ValueError('Missing checkpoint page')
                    sid = sid_by_job[job['job_id']]
                    manifest = verified[sid]
                    if manifest['offset'] != job['offset'] or manifest['rows'] != job['rows']:
                        raise ValueError('Checkpoint cursor/row count differs')
                    _insert_job(con, {**job, 'state': 'CHECKPOINT', 'chunk': copied[sid]})
                for job in frontier:
                    sid = sid_by_job.get(job['job_id'])
                    if bool(job['chunk']) != bool(sid):
                        raise ValueError('Incomplete frontier saved-byte evidence')
                    _insert_job(con, {**job, 'chunk': copied[sid] if sid else None,
                        'state': 'PENDING' if job['state'] in ('RUNNING', 'STORED') else job['state']})
                con.commit()
            write_json(worker.base/'active-plan.json', {'plan_id': pid, 'created_at': now()})
            write_json(worker.base/'scheduler-policy.json', policy)
            write_json(worker.base/ROLE_FILE, sealed({'role': 'worker', 'assignment': assignment,
                'bootstrap_id': body['bundle_id'], 'bootstrap_sha256': expected_sha,
                'baseline_queue_counts': body['baseline_queue_counts'], 'created_at': now()}))
            (worker.base/'STOP').write_text('BOOTSTRAP_AWAITING_BOUNDED_ACCEPTANCE', encoding='utf-8')
            validate_worker_queue(worker, assignment)
            if destination.exists():
                destination.rmdir()  # Only the previously inspected empty directory is removable.
            stage.rename(destination)
            # DuckDB view paths are local absolute paths, not the temporary installation root.
            TdxLake(destination, create=True)
            return {'already_installed': False, 'data_root': str(destination), 'plan_id': pid,
                'shard_id': assignment['shard_id'], 'symbols': assignment['symbol_count'],
                'frontier_jobs': len(frontier), 'checkpoint_pages': len(pages), 'stop_requested': True}
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def worker_status(lake: TdxLake) -> dict:
    role = read_role(lake)
    if not role or role.get('role') != 'worker':
        raise ValueError('Worker role required')
    assignment = role['assignment']; pid = assignment['plan_id']
    load_worker_assignment(lake, pid, load_scheduler_policy(lake, pid).get('policy_id'))
    with lake.db(readonly=True) as con:
        counts = {r['state']: r['n'] for r in con.execute('SELECT state,count(*) n FROM jobs WHERE plan_id=? GROUP BY state', (pid,))}
        publications = [dict(r) for r in con.execute('SELECT family,count(*) pages,sum(rows) rows FROM publications GROUP BY family')]
        errors = [dict(r) for r in con.execute("SELECT job_id,family,symbol,day,offset,state,attempts,error FROM jobs WHERE state IN ('ERROR','STALLED','PAGE_LIMIT') ORDER BY job_id")]
        frontier_digest = digest([dict(r) for r in con.execute("SELECT job_id,day,offset,state,attempts,updated_at FROM jobs WHERE state NOT IN ('SAVED','EMPTY','CHECKPOINT') ORDER BY job_id")])
    progress = {}
    if (lake.base/'progress.json').exists():
        progress = json.loads((lake.base/'progress.json').read_text(encoding='utf-8'))
    return {'machine_name': assignment['machine_name'], 'shard_id': assignment['shard_id'],
        'shard_count': assignment['shard_count'], 'plan_id': pid, 'assignment_id': assignment['assignment_id'],
        'cluster_id': assignment['cluster_id'], 'symbol_count': assignment['symbol_count'],
        'counts': counts, 'new_publications': publications, 'errors': errors,
        'baseline_queue_counts': role['baseline_queue_counts'], 'frontier_digest': frontier_digest,
        'progress': progress, 'stop_requested': (lake.base/'STOP').exists(),
        'auto_halted': (lake.base/'AUTO_HALT.json').exists(), 'observed_at': now(), 'history_complete': False}


def export_results(lake: TdxLake, output: Path, *, max_pages=1000, max_bytes=256*1024**2) -> dict:
    if type(max_pages) is not int or not 1 <= max_pages <= 10000 or not 1024**2 <= max_bytes <= MAX_BUNDLE_BYTES:
        raise ValueError('Invalid result export budget')
    with writer_lease(lake):
        lake.reconcile_publications()
        role = read_role(lake)
        if not role or role.get('role') != 'worker':
            raise ValueError('Results can only originate from an assigned worker')
        assignment = role['assignment']; pid = assignment['plan_id']; plan = lake.plan(pid)
        load_worker_assignment(lake, pid, load_scheduler_policy(lake, pid).get('policy_id'))
        validate_worker_queue(lake, assignment)
        with lake.db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS distributed_exports(source_id TEXT PRIMARY KEY,bundle_id TEXT NOT NULL,created_at TEXT NOT NULL)')
            con.execute('CREATE TABLE IF NOT EXISTS distributed_result_bundles(bundle_id TEXT PRIMARY KEY,path TEXT NOT NULL,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,acked INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,sequence_no INTEGER NOT NULL UNIQUE)')
            sequence_no=con.execute('SELECT coalesce(max(sequence_no),0)+1 FROM distributed_result_bundles').fetchone()[0]
            candidates = [dict(r) for r in con.execute("SELECT j.*,p.source_id FROM publications p JOIN jobs j ON j.chunk=p.chunk LEFT JOIN distributed_exports x ON x.source_id=p.source_id WHERE p.plan_id=? AND j.state IN ('SAVED','EMPTY') AND x.source_id IS NULL ORDER BY p.rowid LIMIT ?", (pid, max_pages))]
            con.commit()
        pages = {}; sources = {}; jobs = []; total = 0
        for candidate in candidates:
            job = validate_job(candidate, assignment, plan)
            item, folder = page_descriptor(lake, job, job['state'])
            size = sum(folder.size(f) for f in PAGE_FILES)
            if pages and total+size > max_bytes:
                break
            total += size; pages[item['source_id']] = item; sources[item['source_id']] = folder; jobs.append(job)
        dependencies = []
        for item in list(pages.values()):
            manifest = json.loads(sources[item['source_id']].read_bytes('manifest.json'))
            origin = manifest.get('origin', '')
            if item['family'] == 'opening_match':
                if not origin.startswith('exact_rows_from_trade_page:'):
                    raise ValueError('Opening-match publication lacks an exact trade parent')
                parent_id = origin.split(':', 1)[1]
                if parent_id not in pages:
                    with lake.db(readonly=True) as con:
                        parent = con.execute("SELECT j.*,p.source_id FROM publications p JOIN jobs j ON j.chunk=p.chunk WHERE p.source_id=? AND j.state='SAVED'", (parent_id,)).fetchone()
                    if parent is None:
                        raise ValueError('Opening-match parent is not SAVED')
                    parent = dict(parent); descriptor, folder = page_descriptor(lake, parent, 'DEPENDENCY')
                    pages[parent_id] = descriptor; sources[parent_id] = folder; dependencies.append(parent_id)
        status = worker_status(lake)
        body = {'format': RESULT_FORMAT, 'plan_id': pid, 'assignment': assignment, 'sequence_no': sequence_no,
            'policy_id': assignment['policy_id'], 'created_at': now(), 'jobs': jobs,
            'dependency_pages': dependencies, 'pages': sorted(pages.values(), key=lambda p: p['source_id']),
            'status': status, 'history_complete': False, 'qualification': QUALIFICATION}
        receipt = {**write_bundle(Path(output), body, sources), 'sequence_no': sequence_no}
        write_json(Path(receipt['path']).with_suffix('.receipt.json'), receipt)
        with lake.db() as con:
            for item in pages.values():
                if item['state'] != 'DEPENDENCY':
                    con.execute('INSERT OR IGNORE INTO distributed_exports VALUES (?,?,?)', (item['source_id'], receipt['bundle_id'], now()))
            con.execute('INSERT OR IGNORE INTO distributed_result_bundles(bundle_id,path,sha256,bytes,created_at,sequence_no) VALUES (?,?,?,?,?,?)',
                        (receipt['bundle_id'], receipt['path'], receipt['sha256'], receipt['bytes'], now(), sequence_no))
            con.commit()
        return {**receipt, 'exported_pages': len(jobs), 'dependency_pages': len(dependencies)}


def _verify_import_chains(lake, jobs, page_for_job, verified):
    strip=lambda rr:[{k:v for k,v in r.items() if k not in ('index','absolute_index')} for r in rr]
    for job in jobs.values():
        if not job['offset'] or not (job['family'].startswith('bars_') or job['family']=='trades'):
            continue
        candidates={j['job_id']:(j,verified[page_for_job[j['job_id']]][2]) for j in jobs.values()
            if j['family']==job['family'] and j['symbol']==job['symbol'] and j['day']==job['day']
            and j['offset']<job['offset'] and j['offset']+j['rows']==job['offset'] and j['state']=='SAVED'}
        with lake.db(readonly=True) as con:
            previous=con.execute("SELECT * FROM jobs WHERE plan_id=? AND family=? AND symbol=? AND day=? AND offset<? AND offset+rows=? AND state='SAVED' AND chunk IS NOT NULL",
                (job['plan_id'],job['family'],job['symbol'],job['day'],job['offset'],job['offset'])).fetchall()
        for row in previous:
            row=dict(row)
            if row['job_id'] in candidates:continue
            sid=PurePosixPath(portable_chunk(row['chunk'])).name
            source=lake.page_source(row['family'],sid,portable_chunk(row['chunk']))
            metadata=source.verify()
            with source.open('response.json.gz') as compressed, gzip.GzipFile(fileobj=compressed) as stream:raw=json.loads(stream.read(MAX_PAGE_BYTES+1))
            candidates[row['job_id']]=(row,rows_for(row['family'],raw['result']))
        if len(candidates)!=1:
            raise ValueError('Incoming pagination lacks one exact preceding saved page')
        previous,previous_rows=next(iter(candidates.values()))
        current_rows=verified[page_for_job[job['job_id']]][2]
        if len(previous_rows)!=previous['rows'] or not previous_rows:
            raise ValueError('Preceding saved page has invalid row count')
        if current_rows and digest(strip(previous_rows))==digest(strip(current_rows)):
            raise ValueError('Incoming pagination repeats preceding source rows')


def _validate_node_status(status,assignment):
    if not isinstance(status,dict) or status.get('assignment_id')!=assignment['assignment_id'] or status.get('cluster_id')!=assignment['cluster_id'] or status.get('history_complete') is not False:
        raise ValueError('Worker status identity/qualification mismatch')
    if status.get('plan_id')!=assignment['plan_id'] or status.get('shard_id')!=assignment['shard_id'] or status.get('shard_count')!=assignment['shard_count']:
        raise ValueError('Worker status plan/shard mismatch')
    if datetime.fromisoformat(status['observed_at']).tzinfo is None:
        raise ValueError('Worker status timestamp lacks timezone')
    if not isinstance(status.get('counts'),dict) or any(k not in ALL_STATES or type(v) is not int or v<0 for k,v in status['counts'].items()):
        raise ValueError('Invalid worker state counts')
    if status.get('progress',{}).get('full_history_complete',False) is not False:
        raise ValueError('Worker progress incorrectly claims history completion')


def _quarantine(lake: TdxLake, path: Path, expected_sha: str, error: Exception) -> None:
    directory = lake.base/'_quarantine'/'bundles'; directory.mkdir(parents=True, exist_ok=True)
    actual = file_sha(path)
    target = directory/(actual+'.tar')
    if not target.exists():
        temporary = directory/('.'+str(uuid4())+'.part'); shutil.copyfile(path, temporary); temporary.rename(target)
    write_json(directory/(actual+'.conflict.json'), {'sha256': actual, 'expected_sha256': expected_sha,
        'reason': type(error).__name__+': '+str(error)[:2000], 'observed_at': now(), 'state': 'QUARANTINE', 'history_complete': False})


def import_results(lake: TdxLake, bundle_path: Path, expected_sha: str) -> dict:
    path = Path(bundle_path)
    try:
        with writer_lease(lake):
            lake.reconcile_publications()
            role = read_role(lake)
            if not role or role.get('role') != 'coordinator':
                raise ValueError('Only the canonical coordinator may merge worker results')
            cluster = checked(role['cluster']); pid = cluster['plan_id']; plan = lake.plan(pid)
            policy = load_scheduler_policy(lake, pid)
            with unpack_bundle(path, expected_sha, lake.base/'_incoming') as (unpacked, body):
                if body.get('format') != RESULT_FORMAT or body.get('plan_id') != pid or body.get('history_complete') is not False or body.get('qualification')!=QUALIFICATION:
                    raise ValueError('Wrong result format/plan/qualification')
                assignment = validate_assignment(body['assignment'], plan, pid, policy['policy_id'])
                if assignment['cluster_id'] != cluster['cluster_id'] or assignment not in cluster['assignments']:
                    raise ValueError('Worker assignment is not registered with this coordinator')
                sequence_no=body.get('sequence_no')
                if type(sequence_no) is not int or sequence_no<1:raise ValueError('Invalid result sequence')
                with lake.db(readonly=True) as con:
                    table=con.execute("SELECT 1 FROM sqlite_master WHERE name='distributed_imports'").fetchone()
                    previous=con.execute('SELECT sha256,sequence_no FROM distributed_imports WHERE bundle_id=?',(body['bundle_id'],)).fetchone() if table else None
                    last_sequence=con.execute('SELECT coalesce(max(sequence_no),0) FROM distributed_imports WHERE assignment_id=?',(assignment['assignment_id'],)).fetchone()[0] if table else 0
                if previous:
                    if previous['sha256']!=expected_sha or previous['sequence_no']!=sequence_no:raise BundleConflict('Existing result sequence/hash conflict')
                elif sequence_no>last_sequence+1:
                    raise BundleDeferred('Earlier result bundle required: expected '+str(last_sequence+1))
                elif sequence_no<=last_sequence:
                    raise BundleConflict('Result sequence reused by a different bundle')
                status=body['status'];_validate_node_status(status,assignment)
                jobs = {j['job_id']: validate_job(j, assignment, plan) for j in body['jobs']}
                if len(jobs) != len(body['jobs']) or any(j['state'] not in ('SAVED', 'EMPTY') for j in jobs.values()):
                    raise ValueError('Only exact SAVED/EMPTY jobs may be imported')
                verified = {}; page_for_job = {}; existing = {}; new_items = []
                for item in body['pages']:
                    if item['state'] not in ('SAVED', 'EMPTY', 'DEPENDENCY'):
                        raise ValueError('Uncommitted page included in result bundle')
                    sid = item['source_id']
                    verified[sid] = verify_bundle_page(unpacked/'pages'/sid, item, assignment, plan)
                    if item['state'] != 'DEPENDENCY':
                        if item['job_id'] in page_for_job or item['job_id'] not in jobs:
                            raise ValueError('Ambiguous or missing imported job')
                        page_for_job[item['job_id']] = sid
                        job = jobs[item['job_id']]; manifest = verified[sid][0]
                        for key in ('plan_id', 'family', 'symbol', 'day', 'offset', 'rows'):
                            if manifest[key] != job[key]:
                                raise ValueError('Imported job/page differs')
                        if job['state'] != item['state']:
                            raise ValueError('Imported job/page state differs')
                        with lake.db(readonly=True) as con:
                            old = con.execute('SELECT * FROM publications WHERE source_id=?', (sid,)).fetchone()
                            old_job = con.execute('SELECT * FROM jobs WHERE job_id=?', (job['job_id'],)).fetchone()
                        if old:
                            source = lake.page_source(item['family'], sid, portable_chunk(old['chunk']))
                            current = source.verify()
                            for key in ('raw_sha256', 'parquet_sha256', 'observed_at'):
                                if current[key] != manifest[key]:
                                    raise BundleConflict('Same source_id has different verified bytes: '+sid)
                            if source.sha256('manifest.json') != item['manifest_sha256']:
                                raise BundleConflict('Same source_id has a different manifest: '+sid)
                            existing[sid] = True
                        else:
                            if old_job and old_job['state'] in ('SAVED', 'EMPTY') and old_job['chunk'] and PurePosixPath(portable_chunk(old_job['chunk'])).name != sid:
                                raise BundleConflict('Canonical job already names another immutable source: '+job['job_id'])
                            new_items.append(item)
                if set(page_for_job) != set(jobs):
                    raise ValueError('Result job inventory does not equal published pages')
                if set(body.get('dependency_pages',[]))!={p['source_id'] for p in body['pages'] if p['state']=='DEPENDENCY'}:
                    raise ValueError('Dependency inventory mismatch')
                _verify_import_chains(lake,jobs,page_for_job,verified)
                require_disk(lake.root,sum(sum((unpacked/'pages'/p['source_id']/f).stat().st_size for f in PAGE_FILES) for p in new_items))
                for sid, (manifest, raw, rows) in verified.items():
                    if manifest['family'] == 'opening_match':
                        origin = manifest.get('origin', '')
                        parent_id = origin.split(':', 1)[1] if origin.startswith('exact_rows_from_trade_page:') else ''
                        if parent_id not in verified:
                            raise ValueError('Missing exact opening-match parent evidence')
                        parent_manifest, parent_raw, parent_rows = verified[parent_id]
                        if parent_manifest['family'] != 'trades' or any(parent_manifest[k] != manifest[k] for k in ('plan_id', 'symbol', 'day', 'offset')):
                            raise ValueError('Opening-match parent request differs')
                        if rows != [r for r in parent_rows if r.get('event_kind') == 'opening_match']:
                            raise ValueError('Opening-match rows were not copied exactly')
                # No canonical files or jobs are modified until every input page and conflict check passes.
                with lake.db() as con:
                    con.execute('CREATE TABLE IF NOT EXISTS distributed_imports(bundle_id TEXT PRIMARY KEY,sha256 TEXT NOT NULL,assignment_id TEXT NOT NULL,imported_pages INTEGER NOT NULL,duplicate_pages INTEGER NOT NULL,imported_at TEXT NOT NULL,sequence_no INTEGER NOT NULL,UNIQUE(assignment_id,sequence_no))')
                    con.execute('CREATE TABLE IF NOT EXISTS distributed_node_status(assignment_id TEXT PRIMARY KEY,body TEXT NOT NULL,observed_at TEXT NOT NULL)')
                    con.execute('CREATE TABLE IF NOT EXISTS distributed_job_audit(event_id TEXT PRIMARY KEY,job_id TEXT NOT NULL,before_json TEXT NOT NULL,bundle_id TEXT NOT NULL,created_at TEXT NOT NULL)')
                    previous = con.execute('SELECT sha256 FROM distributed_imports WHERE bundle_id=?', (body['bundle_id'],)).fetchone()
                    if previous and previous[0] != expected_sha:
                        raise BundleConflict('Bundle identity reused with another transport hash')
                    con.commit()
                for item in new_items:
                    sid = item['source_id']; job = jobs[item['job_id']]
                    target = lake.base/'_stored'/item['family']/sid
                    if target.exists():
                        present = lake.verify_page_at(target, item['family'], sid)
                        if present != {k: v for k, v in verified[sid][0].items() if k != 'checksum'}:
                            raise BundleConflict('Conflicting interrupted import staging page')
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        temporary = target.with_name('.'+sid+'.'+str(uuid4())+'.part')
                        shutil.copytree(unpacked/'pages'/sid, temporary); temporary.rename(target)
                    with lake.db() as con:
                        old = con.execute('SELECT * FROM jobs WHERE job_id=?', (job['job_id'],)).fetchone()
                        if old:
                            con.execute('INSERT OR IGNORE INTO distributed_job_audit VALUES (?,?,?,?,?)',
                                (digest([body['bundle_id'], dict(old)]), job['job_id'], encode(dict(old)), body['bundle_id'], now()))
                        _insert_job(con, job); con.commit()
                    lake.commit_saved_page({**job, 'chunk': target.relative_to(lake.root).as_posix()}, empty_audit_only=True)
                receipt = {'bundle_id': body['bundle_id'], 'sha256': expected_sha, 'machine_name': assignment['machine_name'], 'sequence_no': sequence_no,
                    'shard_id': assignment['shard_id'], 'imported_pages': len(new_items), 'duplicate_pages': len(existing),
                    'imported_at': now(), 'history_complete': False, 'state': 'MERGED'}
                with lake.db() as con:
                    con.execute('INSERT OR IGNORE INTO distributed_imports VALUES (?,?,?,?,?,?,?)',
                        (body['bundle_id'], expected_sha, assignment['assignment_id'], len(new_items), len(existing), receipt['imported_at'], sequence_no))
                    old = con.execute('SELECT observed_at FROM distributed_node_status WHERE assignment_id=?', (assignment['assignment_id'],)).fetchone()
                    if not old or old[0] <= status['observed_at']:
                        con.execute('INSERT OR REPLACE INTO distributed_node_status VALUES (?,?,?)', (assignment['assignment_id'], encode(status), status['observed_at']))
                    con.commit()
                receipts = lake.base/'distributed-receipts'; receipts.mkdir(exist_ok=True)
                write_json(receipts/(body['bundle_id']+'.json'), receipt)
                return receipt
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
        if 'owns the TDX writer lease' in str(exc):raise
        if path.is_file() and path.stat().st_size <= MAX_BUNDLE_BYTES:
            _quarantine(lake, path, expected_sha, exc)
        raise BundleConflict(str(exc)) from exc


def aggregate_status(lake: TdxLake) -> dict:
    role = read_role(lake)
    if not role or role.get('role') != 'coordinator':
        raise ValueError('Coordinator role required')
    cluster = checked(role['cluster']); nodes = []
    with lake.db(readonly=True) as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        latest = {r['assignment_id']: json.loads(r['body']) for r in con.execute('SELECT * FROM distributed_node_status')} if 'distributed_node_status' in tables else {}
        publications = [dict(r) for r in con.execute('SELECT family,count(*) pages,sum(rows) rows FROM publications GROUP BY family')]
        merge = dict(con.execute('SELECT count(*) bundles,max(imported_at) last_merge FROM distributed_imports').fetchone()) if 'distributed_imports' in tables else {'bundles': 0, 'last_merge': None}
    for assignment in cluster['assignments']:
        status = latest.get(assignment['assignment_id'])
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(status['observed_at'])).total_seconds() if status else None
        nodes.append({'machine_name': assignment['machine_name'], 'shard_id': assignment['shard_id'],
            'symbol_count': assignment['symbol_count'], 'observation': 'RECENT_REPORT' if age is not None and age < 900 else 'STALE_OR_NOT_REPORTED',
            'age_seconds': round(age, 1) if age is not None else None, 'status': status})
    conflicts = list((lake.base/'_quarantine'/'bundles').glob('*.conflict.json'))
    return {'cluster_id': cluster['cluster_id'], 'plan_id': cluster['plan_id'], 'shard_algorithm': ALGORITHM,
        'nodes': nodes, 'canonical_publications': publications, 'imports': merge, 'conflicts': len(conflicts),
        'history_complete': False, 'qualification': QUALIFICATION,
        'note': 'A recent report is not proof of a live process. Canonical legacy PENDING rows are delegated, not an additional runnable queue.'}

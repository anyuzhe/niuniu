"""Read-only projection of existing proposal, JobQueue and result records.

No queue is constructed, no data provider is opened, and no persisted state is repaired.
Manifest/header checks are deliberately distinct from expensive input/result deep audits.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

from quantlab.agent.proposal_store import ProposalStore, identifier
from quantlab.storage.codec import digest
from quantlab.storage.approval_inputs import FORMAT as FREEZE_FORMAT, validate_approval_freeze_receipt

FORMAT = 'niuniu-proposal-progress-v1'
ACTIVE = {'queued', 'running'}
TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted'}
MAX_JSON_BYTES = 4 * 1024 * 1024
LIMITATIONS = [
    '只读既有提案、任务和结果；不批准、不启动、不取消、不恢复、不重跑，也不修复回执。',
    '任务状态来自持久日志，未核实执行进程在线；更新时间不是心跳，不推算剩余时间。',
    '冻结清单和结果头部的身份核对不等于全部数据字节深验、数值复算或Alpha认证。',
    '阶段内completed/total不是全任务百分比。跨文件观察不是全工作空间原子快照。',
]


def _safe(path):
    path = Path(path).absolute()
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError('INVALID_ARTIFACT：进度读取路径不能包含符号链接。')
    return path


def _json(path, limit=MAX_JSON_BYTES):
    path = _safe(path)
    if not path.is_file():
        raise FileNotFoundError('记录不存在：' + path.name)
    if path.stat().st_size > limit:
        raise ValueError('RESULT_TOO_LARGE：记录超过有界读取预算。')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('RESULT_TOO_LARGE：记录超过有界读取预算。')
    return _decode_json(raw), hashlib.sha256(raw).hexdigest()


def _decode_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError('重复JSON字段：' + key)
            result[key] = value
        return result
    def constant(value): raise ValueError('非有限JSON数值')
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(value, dict): raise ValueError('记录必须为JSON对象')
    return value


def _proposal(output, proposal_id):
    # Reuse the canonical row decoder while avoiding the writer's BEGIN IMMEDIATE.
    store = ProposalStore(output)
    for path in (store.directory, store.path, *[Path(str(store.path)+s) for s in ('-journal','-wal','-shm')]):
        _safe(path)
    if not store.path.is_file(): raise FileNotFoundError('没有提案数据库')
    connection = sqlite3.connect(store.path.as_uri()+'?mode=ro', uri=True, timeout=1)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')  # Stable read transaction; no writer lock or schema changes.
        size = connection.execute('SELECT length(CAST(payload AS BLOB)) FROM proposals WHERE id=?', (proposal_id,)).fetchone()
        if size is not None and size[0] > MAX_JSON_BYTES:
            raise ValueError('RESULT_TOO_LARGE：提案超过读取预算。')
        row = connection.execute('SELECT * FROM proposals WHERE id=?', (proposal_id,)).fetchone()
        if row is not None:_decode_json(row['payload'])  # Duplicate fields must not disappear before checksum verification.
        record = store.decode(row)
    finally: connection.close()
    if record['proposal_id'] != proposal_id or record['status'] not in {'pending','approved','submitted','rejected'}:
        raise ValueError('提案身份或状态无效')
    identifier(record['job_id'])
    if not isinstance(record.get('plan'), dict) or not isinstance(record['plan'].get('spec'), dict):
        raise ValueError('提案缺少固定研究配置')
    return record


def read_proposal_progress(output, proposal_id):
    """Read one exact proposal's progress without requiring its original market root."""
    try: identifier(proposal_id)
    except ValueError as exc: raise ValueError('INVALID_ARGUMENT：需要完整规范proposal_id。') from exc
    output = _safe(output)
    if not output.is_dir(): raise ValueError('INVALID_ARGUMENT：工作空间不存在。')
    report = {'format': FORMAT, 'proposal_id': proposal_id,
              'observed_at': datetime.now(timezone.utc).isoformat(),
              'phase': 'unavailable', 'proposal': None, 'job': None,
              'freeze': {'state': 'not_observed', 'manifest_identity_verified': False, 'payload_bytes_verified': False},
              'result': None, 'can_open_result': False, 'refresh_recommended': False,
              'process_liveness_verified': False, 'errors': [], 'incomplete': False,
              'limitations': list(LIMITATIONS)}
    def error(stage, code, exc):
        message = str(exc)
        report['errors'].append({'stage': stage, 'code': code, 'message': message[:600],
                                 'message_truncated': len(message) > 600})
        report.update(incomplete=True, can_open_result=False, refresh_recommended=False)
    try: proposal = _proposal(output, proposal_id)
    except Exception as exc:
        error('proposal', 'PROPOSAL_UNAVAILABLE', exc)
        return report
    report['proposal'] = {k: proposal[k] for k in ('proposal_id','proposal_digest','status','job_id','created_at','approved_at')}
    report['proposal']['question'] = proposal['plan']['spec'].get('question', '')
    status = proposal['status']
    report['phase'] = {'pending':'awaiting_approval','rejected':'rejected','approved':'approved_not_enqueued','submitted':'missing_job'}[status]
    job_path = output / '_jobs' / (proposal['job_id'] + '.json')
    job = None
    job_hash = None
    try:
        _safe(job_path)
        if job_path.exists():
            job, job_hash = _json(job_path)
            if job.get('job_id') != proposal['job_id'] or job.get('spec') != proposal['plan']['spec']:
                raise ValueError('任务编号或配置与提案不一致')
            if job.get('status') not in ACTIVE | TERMINAL or type(job.get('attempt')) is not int or job['attempt'] < 1:
                raise ValueError('任务状态或attempt无效')
            if status not in {'approved','submitted'}:
                raise ValueError('未批准或已拒绝提案出现任务记录')
            guard = job.get('execution_guard')
            expected = {'runtime':proposal['plan']['binding']['runtime'],
                        'cooperative_seconds':proposal['plan']['budget']['cooperative_seconds'],
                        'max_active_jobs':proposal['plan']['budget']['max_active_jobs']}
            if not isinstance(guard, dict) or set(guard) != set(expected) | {'approval_freeze'} or any(guard.get(k) != v for k,v in expected.items()):
                raise ValueError('任务执行约束与原提案不一致或缺少冻结回执')
            validate_approval_freeze_receipt(guard['approval_freeze'])
            report['job'] = {k: job.get(k) for k in ('job_id','status','attempt','created_at','started_at','finished_at',
                            'progress','checkpoint_summary','error','cancel_requested','run_id','experiment_id')}
            report['phase'] = 'cancel_requested' if job['status'] in ACTIVE and job.get('cancel_requested') else job['status']
            report['submission_receipt_pending'] = status == 'approved'
        elif status == 'submitted':
            error('job', 'LOST_JOB', '提案已提交但任务日志缺失；请检查原工作空间，不自动重建任务。')
    except Exception as exc:
        error('job', 'JOB_RECORD_INVALID', exc)
        report['phase'] = 'inconsistent'
        job = None
    freeze_path = output / '_approval_input_freezes' / proposal_id / 'manifest.json'
    freeze_hash = None
    try:
        _safe(freeze_path)
        if status in {'pending','rejected'}:
            report['freeze']['state'] = 'unapproved_candidate' if freeze_path.parent.exists() else 'not_created'
        else:
            envelope, freeze_hash = _json(freeze_path)
            manifest = envelope.get('manifest')
            if not isinstance(manifest, dict) or envelope.get('checksum') != digest(manifest):
                raise ValueError('冻结清单损坏')
            if manifest.get('format') != FREEZE_FORMAT or manifest.get('freeze_id') != proposal_id or manifest.get('spec_digest') != digest(proposal['plan']['spec']):
                raise ValueError('冻结清单身份与原提案不一致')
            if job is not None:
                expected = job['execution_guard']['approval_freeze']
                if expected['freeze_id'] != proposal_id or expected['manifest_hash'] != digest(manifest) or expected['spec_digest'] != manifest['spec_digest']:
                    raise ValueError('任务冻结回执与清单不一致')
            report['freeze'].update(state='manifest_checked', manifest_identity_verified=True,
                                     freeze_id=proposal_id, manifest_hash=digest(manifest), captured_at=manifest.get('captured_at'))
    except Exception as exc:
        report['freeze']['state'] = 'unavailable'
        error('freeze', 'FREEZE_MANIFEST_INVALID', exc)
    if job is not None and job['status'] == 'completed':
        try:
            run_id = identifier(job.get('run_id'))
            path = _safe(output / run_id / 'experiment.json')
            if not path.is_file(): raise FileNotFoundError('完成任务的结果归档缺失')
            # Validate bounded JSON syntax, then retain header fields only; payload semantics remain unaudited.
            if path.stat().st_size > 64 * 1024 * 1024:
                raise ValueError('RESULT_TOO_LARGE：结果头部核对超出本进度接口预算，请在结果目录中显式核验。')
            before = (path.stat().st_size, path.stat().st_mtime_ns)
            result_record, _ = _json(path, 64 * 1024 * 1024)
            result = {k:result_record[k] for k in ('run_id','experiment_id','status','kind','created_at') if k in result_record}
            if before != (path.stat().st_size, path.stat().st_mtime_ns): raise ValueError('结果在读取期间变化')
            if result.get('run_id') != run_id or not job.get('experiment_id') or result.get('experiment_id') != job['experiment_id'] or result.get('status') != 'completed':
                raise ValueError('结果头部身份或状态与完成任务不一致')
            report['result'] = {**result, 'verification': 'header_identity_only', 'payload_bytes_verified': False}
        except Exception as exc: error('result', 'RESULT_UNAVAILABLE', exc)
    try:
        if _proposal(output, proposal_id) != proposal:
            raise ValueError('提案在跨文件读取期间变化，请刷新')
        if freeze_hash is not None:
            try:
                if _json(freeze_path)[1] != freeze_hash:
                    raise ValueError('冻结清单在跨文件读取期间变化，请刷新')
            except Exception:
                report['freeze'].update(state='changed_during_read', manifest_identity_verified=False)
                raise
        if job_hash is not None and _json(job_path)[1] != job_hash:
            raise ValueError('任务在跨文件读取期间变化，请刷新')
        if job_hash is None and job_path.exists() and job is None and not report['errors']:
            raise ValueError('任务刚刚入队，请刷新')
    except Exception as exc: error('observation', 'CHANGED_DURING_READ', exc)
    report['can_open_result'] = bool(report['result'] and not report['errors'])
    report['refresh_recommended'] = not report['errors'] and report['phase'] in {'awaiting_approval','approved_not_enqueued','queued','running','cancel_requested'}
    return report

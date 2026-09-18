"""Versioned, fail-closed ownership contract for personal-research TDX workers."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from quantlab.data.tdx_lake import FAMILIES, digest, safe

ALGORITHM = 'sha256-utf8-symbol-mod-v1'
FORMAT = 'tdx-worker-assignment-v1'
ROLE_FILE = 'distributed-role.json'
GLOBAL_FAMILIES = frozenset(('securities', 'limit_ladder'))


def shard_for(symbol: str, count: int) -> int:
    if not isinstance(symbol, str) or not re.fullmatch(r'(sh|sz|bj)\.\d{6}', symbol):
        raise ValueError('Invalid shard symbol')
    if type(count) is not int or not 1 <= count <= 32:
        raise ValueError('Invalid shard count')
    return int(hashlib.sha256(symbol.encode('utf-8')).hexdigest(), 16) % count


def sealed(value: dict, key: str = 'checksum') -> dict:
    core = {k: v for k, v in value.items() if k != key}
    return {**core, key: digest(core)}


def checked(value: dict, key: str = 'checksum') -> dict:
    if not isinstance(value, dict) or value.get(key) != digest({k: v for k, v in value.items() if k != key}):
        raise ValueError('Distributed contract checksum mismatch')
    return value


def make_assignment(plan: dict, pid: str, policy_id: str, cluster_id: str,
                    shard_count: int, shard_id: int, machine_name: str) -> dict:
    if digest(plan) != pid or type(shard_id) is not int or not 0 <= shard_id < shard_count:
        raise ValueError('Invalid plan/shard identity')
    symbols = sorted(s for s in plan['symbols'] if shard_for(s, shard_count) == shard_id)
    return sealed({'format': FORMAT, 'plan_id': pid, 'plan_body_hash': digest(plan),
        'policy_id': policy_id, 'cluster_id': cluster_id, 'shard_algorithm': ALGORITHM,
        'shard_count': shard_count, 'shard_id': shard_id, 'machine_name': machine_name,
        'symbols': symbols, 'symbol_count': len(symbols), 'symbols_digest': digest(symbols),
        'global_tasks': shard_id == 0, 'personal_research_only': True,
        'history_complete': False}, 'assignment_id')


def validate_assignment(value: dict, plan: dict, pid: str, policy_id: str) -> dict:
    checked(value, 'assignment_id')
    if value.get('format') != FORMAT or value.get('shard_algorithm') != ALGORITHM:
        raise ValueError('Unsupported TDX shard algorithm/format')
    if value.get('plan_id') != pid or value.get('plan_body_hash') != digest(plan) or digest(plan) != pid:
        raise ValueError('Distributed plan identity mismatch')
    if value.get('policy_id') != policy_id:
        raise ValueError('Distributed scheduler policy mismatch')
    count, index = value.get('shard_count'), value.get('shard_id')
    if type(count) is not int or not 1 <= count <= 32 or type(index) is not int or not 0 <= index < count:
        raise ValueError('Invalid TDX shard range')
    symbols = plan.get('symbols')
    if not isinstance(symbols, list) or len(symbols) != len(set(symbols)):
        raise ValueError('Invalid distributed symbol universe')
    expected = sorted(s for s in symbols if shard_for(s, count) == index)
    if value.get('symbols') != expected or value.get('symbols_digest') != digest(expected) or value.get('symbol_count') != len(expected):
        raise ValueError('Distributed symbol assignment mismatch')
    if value.get('global_tasks') is not (index == 0) or value.get('personal_research_only') is not True or value.get('history_complete') is not False:
        raise ValueError('Invalid worker qualification/global ownership')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', str(value.get('machine_name', ''))):
        raise ValueError('Invalid machine name')
    if not re.fullmatch(r'[a-f0-9]{64}', str(value.get('cluster_id', ''))):
        raise ValueError('Invalid cluster identity')
    return value


def require_owned_job(assignment: dict | None, job: dict) -> None:
    if assignment is None:
        return
    if job.get('plan_id') != assignment['plan_id'] or job.get('family') not in FAMILIES:
        raise ValueError('Job plan/family outside worker contract')
    symbol, family = job.get('symbol'), job['family']
    if family in GLOBAL_FAMILIES:
        if assignment['shard_id'] != 0 or symbol:
            raise ValueError('Global TDX task belongs only to worker 0')
    elif symbol not in assignment['symbols'] or shard_for(symbol, assignment['shard_count']) != assignment['shard_id']:
        raise ValueError('Job belongs to a different TDX shard')
    expected = digest([job['plan_id'], family, symbol, job['day'], job['offset']])
    if expected != job.get('job_id'):
        raise ValueError('Distributed job identity mismatch')


def read_role(lake) -> dict | None:
    path = safe(lake.root, lake.base / ROLE_FILE)
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 4_000_000:
        raise ValueError('Invalid distributed role file')
    return checked(json.loads(path.read_text(encoding='utf-8')))


def load_worker_assignment(lake, pid: str, policy_id: str | None) -> dict | None:
    role = read_role(lake)
    if role is None:
        return None
    if role.get('role') != 'worker':
        raise ValueError('Canonical coordinator cannot run an unsharded collector; use its worker data root')
    return validate_assignment(role.get('assignment'), lake.plan(pid), pid, policy_id)


def validate_worker_queue(lake, assignment: dict | None) -> None:
    if assignment is None:
        return
    with lake.db(readonly=True) as con:
        rows = con.execute('SELECT job_id,plan_id,family,symbol,day,offset FROM jobs').fetchall()
    for row in rows:
        require_owned_job(assignment, dict(row))

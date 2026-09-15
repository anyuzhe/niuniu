"""Immutable, non-executing archive for an already cloned external Research Skill.

The archive command never performs ``git clone``/``fetch`` and never runs files from
an external repository. It binds canonical Git blobs to SHA256 objects under the
independent data root. Curating an archived snapshot creates another local Research
Skill package, still retrospective and ineligible for Strict PIT or trading.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from uuid import uuid4
import json
import os
import re
import shutil
import subprocess

from quantlab.experiments.campaign_state import read_checked, write_checked
from quantlab.knowledge.research_skill import (
    EVIDENCE_ROLES, FORMAT as PACKAGE_FORMAT, REQUIRED_POLICY,
    ResearchSkillError, audit_research_skill,
)
from quantlab.storage.codec import digest

ARCHIVE_FORMAT = 'niuniu-research-skill-git-archive-v1'
ARCHIVE_AUDIT_FORMAT = 'niuniu-research-skill-git-archive-audit-v1'
CURATION_FORMAT = 'niuniu-research-skill-git-curation-plan-v1'
MAX_FILES = 2_000
MAX_FILE_BYTES = 16_000_000
MAX_TOTAL_BYTES = 128_000_000
MAX_PLAN_BYTES = 1_000_000
OID = re.compile(r'^[0-9a-f]{40,64}$')
SLUG = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')
HASH = re.compile(r'^[0-9a-f]{64}$')
ARCHIVE_BLOCKERS = [
    'upstream_authenticity_not_independently_verified',
    'source_publication_time_unverified',
    'external_scripts_not_reviewed_or_executed',
    'not_strict_pit_or_alpha_evidence',
]
_ARCHIVE_FIELDS = {
    'format', 'archive_snapshot', 'skill_key', 'origin_url', 'commit', 'tree',
    'commit_author_at', 'commit_committer_at', 'observed_at', 'file_count',
    'total_bytes', 'inventory_digest', 'files', 'acquisition', 'boundaries',
    'blockers', 'scope',
}
_FILE_FIELDS = {'path', 'mode', 'git_blob', 'bytes', 'sha256', 'object_path'}
_ACQUISITION_FIELDS = {
    'mode', 'host_authorized', 'network_used_by_archiver', 'repository_clean',
}
_BOUNDARY_FIELDS = {
    'scripts_executed', 'source_publication_verified', 'strict_pit_eligible',
    'alpha_claimed', 'strategy_source_written', 'playbook_written',
    'daily_scanner_eligible', 'direct_trade_eligible',
}
_PLAN_FIELDS = {
    'format', 'skill_key', 'control_snapshot', 'archive_snapshot', 'version', 'status',
    'strategy_source_kind', 'title', 'summary', 'keywords', 'resources',
    'claims', 'alignments', 'hypotheses',
}
_PLAN_RESOURCE_FIELDS = {
    'resource_id', 'upstream_path', 'target_path', 'role', 'sha256', 'bytes',
    'locator',
}


def _fail(code: str, message: str):
    raise ResearchSkillError(code, message)


def _aware(value, name):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    except ValueError:
        _fail('TIMING_INVALID', name + ' 必须是带时区 ISO 8601 时间。')
    if not isinstance(parsed, datetime) or parsed.tzinfo is None:
        _fail('TIMING_INVALID', name + ' 必须是带时区 ISO 8601 时间。')
    return parsed


def _slug(value, name='skill_key'):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        _fail('SCHEMA_INVALID', name + ' 格式无效。')
    return value


def _hash(value, name):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        _fail('SCHEMA_INVALID', name + ' 必须是 64 位小写 SHA256。')
    return value


def _oid(value, name):
    if not isinstance(value, str) or not OID.fullmatch(value):
        _fail('GIT_IDENTITY_INVALID', name + ' 必须是完整 Git object id。')
    return value


def _relative(value, name):
    if not isinstance(value, str) or not value or len(value) > 800:
        _fail('PATH_INVALID', name + ' 必须是规范相对路径。')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or '.' in path.parts or path.as_posix() != value:
        _fail('PATH_INVALID', name + ' 必须是规范相对路径。')
    return path


def _origin(value):
    if not isinstance(value, str) or len(value) > 2_000:
        _fail('ORIGIN_INVALID', 'expected origin 必须是 HTTPS URL。')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        _fail('ORIGIN_INVALID', 'expected origin 必须是不含凭证/query/fragment 的 HTTPS URL。')
    return value


def _git(repository, *arguments, text=True):
    command = [
        'git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
        '-c', 'diff.external=', '-C', str(repository), *arguments,
    ]
    environment = {**os.environ, 'GIT_NO_LAZY_FETCH': '1', 'GIT_TERMINAL_PROMPT': '0',
        'GIT_PAGER': 'cat'}
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=text, timeout=30,
            env=environment)
    except (OSError, subprocess.SubprocessError):
        _fail('GIT_READ_FAILED', '无法以只读方式核验本地 Git repository。')
    return result.stdout


def _repository(path):
    supplied = Path(path).expanduser()
    if supplied.is_symlink() or not supplied.is_dir():
        _fail('REPOSITORY_INVALID', 'Git repository 不存在或为符号链接。')
    root = supplied.resolve()
    git_dir = root / '.git'
    if git_dir.is_symlink() or not git_dir.is_dir():
        _fail('REPOSITORY_INVALID', '只接受具有普通 .git 目录的独立 checkout。')
    return root


def _data_root(path):
    supplied = Path(path).expanduser()
    if supplied.is_symlink() or not supplied.is_dir():
        _fail('DATA_ROOT_INVALID', 'Research Skill 数据根不存在或为符号链接。')
    return supplied.resolve()


def _safe_directory(root, relative, *, create=False):
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            _fail('ARCHIVE_PATH_INVALID', 'Research Skill archive 目录类型无效或为符号链接。')
        if create:
            current.mkdir(exist_ok=True)
    return current


def _tree_rows(repository, commit):
    raw = _git(repository, 'ls-tree', '-r', '-z', '--long', commit, text=False)
    rows = []
    for record in raw.split(b'\0'):
        if not record:
            continue
        try:
            header, encoded_path = record.split(b'\t', 1)
            mode, kind, blob, size = header.decode('ascii').split()
            path = encoded_path.decode('utf-8')
        except (ValueError, UnicodeDecodeError):
            _fail('GIT_TREE_INVALID', 'Git tree 含无法解析的路径或记录。')
        relative = _relative(path, 'git path')
        if kind != 'blob' or mode not in {'100644', '100755'}:
            _fail('GIT_TREE_INVALID', '拒绝 symlink、submodule 或特殊 Git tree mode：' + path)
        try:
            byte_count = int(size)
        except ValueError:
            _fail('GIT_TREE_INVALID', 'Git blob size 无效：' + path)
        if byte_count <= 0 or byte_count > MAX_FILE_BYTES:
            _fail('BUDGET_EXCEEDED', 'Git blob 为空或超过 16MB：' + path)
        rows.append({'path': relative.as_posix(), 'mode': mode, 'git_blob': _oid(blob, 'git blob'),
            'bytes': byte_count})
        if len(rows) > MAX_FILES:
            _fail('BUDGET_EXCEEDED', 'Git tree 文件数超过 2,000。')
    if not rows:
        _fail('GIT_TREE_INVALID', 'Git tree 为空。')
    if sum(item['bytes'] for item in rows) > MAX_TOTAL_BYTES:
        _fail('BUDGET_EXCEEDED', 'Git tree 总字节超过 128MB。')
    return rows


def _worktree_files(repository):
    result = set()
    for parent, directories, files in os.walk(repository, followlinks=False):
        base = Path(parent)
        directories[:] = [name for name in directories if not (base == repository and name == '.git')]
        for name in [*directories, *files]:
            path = base / name
            if path.is_symlink():
                _fail('REPOSITORY_DIRTY', 'checkout 含符号链接：' + str(path.relative_to(repository)))
        for name in files:
            result.add((base / name).relative_to(repository).as_posix())
    return result


def _save_object(root, payload):
    value = sha256(payload).hexdigest()
    directory = _safe_directory(root, 'research/external_research_skills/objects', create=True)
    relative = Path('research/external_research_skills/objects') / (value + '.bin')
    target = directory / (value + '.bin')
    if target.is_symlink():
        _fail('ARCHIVE_PATH_INVALID', 'Research Skill object 路径不能是符号链接。')
    if target.exists():
        actual = target.read_bytes()
        if actual != payload:
            _fail('OBJECT_HASH_COLLISION', '既有 Research Skill object 与 SHA256 不匹配。')
    else:
        temporary = target.with_name('.' + uuid4().hex + '.pending')
        try:
            with temporary.open('xb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return value, relative.as_posix()


def _archive_identity(value):
    return digest({key: item for key, item in value.items() if key not in {'archive_snapshot', 'observed_at'}})


def _object_payload(root, item):
    expected = Path('research/external_research_skills/objects') / (item['sha256'] + '.bin')
    if item['object_path'] != expected.as_posix():
        raise ValueError('object_path mismatch')
    directory = _safe_directory(root, 'research/external_research_skills/objects')
    target = directory / (item['sha256'] + '.bin')
    if target.is_symlink() or not target.is_file():
        raise ValueError('object missing')
    payload = target.read_bytes()
    if len(payload) != item['bytes'] or sha256(payload).hexdigest() != item['sha256']:
        raise ValueError('object digest mismatch')
    return payload


def _verify_receipt(root, path):
    try:
        value = read_checked(path)
        if not isinstance(value, dict) or set(value) != _ARCHIVE_FIELDS or value['format'] != ARCHIVE_FORMAT:
            raise ValueError('schema invalid')
        skill_key = _slug(value['skill_key'])
        if path.parent.name != skill_key or path.stem != value['archive_snapshot']:
            raise ValueError('receipt path identity mismatch')
        if value['archive_snapshot'] != _archive_identity(value):
            raise ValueError('archive snapshot mismatch')
        _origin(value['origin_url'])
        _oid(value['commit'], 'commit')
        _oid(value['tree'], 'tree')
        _aware(value['commit_author_at'], 'commit_author_at')
        _aware(value['commit_committer_at'], 'commit_committer_at')
        _aware(value['observed_at'], 'observed_at')
        if set(value['acquisition']) != _ACQUISITION_FIELDS or value['acquisition'] != {
                'mode': 'HOST_AUTHORIZED_GIT_CLONE', 'host_authorized': True,
                'network_used_by_archiver': False, 'repository_clean': True}:
            raise ValueError('acquisition boundary invalid')
        if set(value['boundaries']) != _BOUNDARY_FIELDS or any(value['boundaries'].values()):
            raise ValueError('qualification boundary invalid')
        if value['blockers'] != ARCHIVE_BLOCKERS or not isinstance(value['scope'], str) or not value['scope']:
            raise ValueError('archive blockers invalid')
        rows = value['files']
        if not isinstance(rows, list) or not rows or len(rows) > MAX_FILES:
            raise ValueError('inventory invalid')
        paths = set()
        total = 0
        normalized = []
        for item in rows:
            if not isinstance(item, dict) or set(item) != _FILE_FIELDS:
                raise ValueError('file schema invalid')
            relative = _relative(item['path'], 'archive path').as_posix()
            if relative in paths or item['mode'] not in {'100644', '100755'}:
                raise ValueError('archive path/mode invalid')
            paths.add(relative)
            _oid(item['git_blob'], 'git blob')
            _hash(item['sha256'], 'file sha256')
            if type(item['bytes']) is not int or not 0 < item['bytes'] <= MAX_FILE_BYTES:
                raise ValueError('archive bytes invalid')
            _object_payload(root, item)
            total += item['bytes']
            normalized.append(item)
        if (value['file_count'] != len(rows) or value['total_bytes'] != total
                or total > MAX_TOTAL_BYTES or value['inventory_digest'] != digest(normalized)):
            raise ValueError('archive inventory summary invalid')
        return {'verified': True, 'receipt': value, 'reason': None}
    except (OSError, ValueError, TypeError, KeyError, ResearchSkillError, json.JSONDecodeError) as error:
        return {'verified': False, 'receipt': None,
            'reason': 'git_archive_' + str(error).replace(' ', '_')[:160]}


def archive_git_research_skill(data_root, repository, skill_key, expected_origin,
        expected_commit, expected_tree, *, confirm_untrusted_no_exec=False, now_fn=None):
    """Archive one exact local checkout; this function performs no network operation."""
    if confirm_untrusted_no_exec is not True:
        _fail('CONFIRMATION_REQUIRED', '必须确认外部 Git 内容不受信任且归档器绝不执行其中脚本。')
    root = _data_root(data_root)
    repository = _repository(repository)
    skill_key = _slug(skill_key)
    expected_origin = _origin(expected_origin)
    expected_commit = _oid(expected_commit, 'expected_commit')
    expected_tree = _oid(expected_tree, 'expected_tree')
    origin = _git(repository, 'remote', 'get-url', 'origin').strip()
    commit = _git(repository, 'rev-parse', 'HEAD').strip()
    tree = _git(repository, 'rev-parse', 'HEAD^{tree}').strip()
    if origin != expected_origin or commit != expected_commit or tree != expected_tree:
        _fail('GIT_IDENTITY_MISMATCH', 'origin/HEAD/tree 与宿主固定值不一致。')
    dates = _git(repository, 'show', '-s', '--format=%aI%x00%cI', commit).strip().split('\x00')
    if len(dates) != 2:
        _fail('GIT_IDENTITY_INVALID', '无法读取 commit author/committer time。')
    author_at = _aware(dates[0], 'commit_author_at').isoformat()
    committer_at = _aware(dates[1], 'commit_committer_at').isoformat()
    rows = _tree_rows(repository, commit)
    actual_paths = _worktree_files(repository)
    expected_paths = {item['path'] for item in rows}
    if actual_paths != expected_paths:
        _fail('REPOSITORY_DIRTY', 'checkout 存在缺失、未跟踪或额外文件。')
    archived = []
    for item in rows:
        payload = _git(repository, 'cat-file', 'blob', item['git_blob'], text=False)
        target = repository.joinpath(*PurePosixPath(item['path']).parts)
        if not target.is_file() or target.is_symlink() or target.read_bytes() != payload:
            _fail('REPOSITORY_DIRTY', 'checkout 字节与 Git blob 不一致：' + item['path'])
        if len(payload) != item['bytes']:
            _fail('GIT_TREE_INVALID', 'Git blob 长度与 ls-tree 不一致：' + item['path'])
        value, object_path = _save_object(root, payload)
        archived.append({**item, 'sha256': value, 'object_path': object_path})
    observed = _aware((now_fn or (lambda: datetime.now(timezone.utc)))(), 'observed_at').isoformat()
    receipt = {'format': ARCHIVE_FORMAT, 'archive_snapshot': '', 'skill_key': skill_key,
        'origin_url': origin, 'commit': commit, 'tree': tree, 'commit_author_at': author_at,
        'commit_committer_at': committer_at, 'observed_at': observed,
        'file_count': len(archived), 'total_bytes': sum(item['bytes'] for item in archived),
        'inventory_digest': digest(archived), 'files': archived,
        'acquisition': {'mode': 'HOST_AUTHORIZED_GIT_CLONE', 'host_authorized': True,
            'network_used_by_archiver': False, 'repository_clean': True},
        'boundaries': {'scripts_executed': False, 'source_publication_verified': False,
            'strict_pit_eligible': False, 'alpha_claimed': False,
            'strategy_source_written': False, 'playbook_written': False,
            'daily_scanner_eligible': False, 'direct_trade_eligible': False},
        'blockers': ARCHIVE_BLOCKERS,
        'scope': ('Immutable bytes and Git identity of a host-authorized clone only. Git metadata and '
            'embedded source URLs do not independently prove authorship, completeness, publication '
            'time, disclosed-action accuracy, outcomes, Alpha, or Strict PIT eligibility.')}
    receipt['archive_snapshot'] = _archive_identity(receipt)
    receipt_directory = _safe_directory(root,
        'research/external_research_skills/git_receipts/' + skill_key, create=True)
    path = receipt_directory / (receipt['archive_snapshot'] + '.json')
    if path.is_symlink():
        _fail('ARCHIVE_PATH_INVALID', 'Git archive receipt 路径不能是符号链接。')
    if path.exists():
        checked = _verify_receipt(root, path)
        if not checked['verified']:
            _fail('ARCHIVE_INVALID', '既有 Git archive receipt 校验失败：' + checked['reason'])
        existing = checked['receipt']
        comparable = lambda value: {key: item for key, item in value.items()
            if key not in {'archive_snapshot', 'observed_at'}}
        if comparable(existing) != comparable(receipt):
            _fail('ARCHIVE_IDENTITY_MISMATCH', '同一 archive snapshot 已存在不同内容。')
        return {'created': False, 'path': str(path), 'archive_snapshot': path.stem,
            'commit': commit, 'tree': tree, 'files': len(archived),
            'total_bytes': receipt['total_bytes'], 'strict_pit_eligible': False,
            'scripts_executed': False}
    write_checked(path, receipt)
    checked = _verify_receipt(root, path)
    if not checked['verified']:
        _fail('ARCHIVE_INVALID', 'Git archive receipt 写入后自校验失败：' + checked['reason'])
    return {'created': True, 'path': str(path), 'archive_snapshot': path.stem,
        'commit': commit, 'tree': tree, 'files': len(archived),
        'total_bytes': receipt['total_bytes'], 'strict_pit_eligible': False,
        'scripts_executed': False}


def audit_git_research_skill_archives(data_root, skill_key=None):
    """Verify append-only Git receipts and every content-addressed object."""
    root = _data_root(data_root)
    if skill_key is not None:
        skill_key = _slug(skill_key)
    base = _safe_directory(root, 'research/external_research_skills/git_receipts')
    paths = []
    if base.is_dir():
        for directory in sorted(base.iterdir()):
            if directory.is_symlink() or not directory.is_dir() or not SLUG.fullmatch(directory.name):
                _fail('ARCHIVE_PATH_INVALID', 'Git receipt skill 目录无效或为符号链接。')
            for path in sorted(directory.iterdir()):
                if path.is_symlink() or not path.is_file() or path.suffix != '.json':
                    _fail('ARCHIVE_PATH_INVALID', 'Git receipt 目录只能包含普通 JSON 文件。')
                if skill_key is None or directory.name == skill_key:
                    paths.append(path)
    verified = []
    invalid = []
    total_files = total_bytes = 0
    for path in paths:
        checked = _verify_receipt(root, path)
        if not checked['verified']:
            invalid.append({'path': str(path.relative_to(root)), 'reason': checked['reason']})
            continue
        receipt = checked['receipt']
        total_files += receipt['file_count']
        total_bytes += receipt['total_bytes']
        verified.append({'skill_key': receipt['skill_key'],
            'archive_snapshot': receipt['archive_snapshot'], 'commit': receipt['commit'],
            'tree': receipt['tree'], 'observed_at': receipt['observed_at'],
            'files': receipt['file_count'], 'bytes': receipt['total_bytes']})
    return {'format': ARCHIVE_AUDIT_FORMAT, 'receipt_files': len(paths),
        'verified_receipts': len(verified), 'invalid_receipts': len(invalid),
        'archived_file_records': total_files, 'archived_bytes': total_bytes,
        'snapshots': verified[-100:], 'snapshots_omitted': max(0, len(verified) - 100),
        'invalid': invalid[:100], 'invalid_omitted': max(0, len(invalid) - 100),
        'boundaries': {'scripts_executed': False, 'source_publication_verified': False,
            'strict_pit_eligible': False, 'alpha_claimed': False},
        'scope': ('Archive integrity inventory only; it does not authenticate embedded claims, '
            'verify source publication time, or grant StrategySource/Playbook/trading eligibility.')}


def _load_plan(path):
    supplied = Path(path).expanduser()
    if (supplied.is_symlink() or not supplied.is_file() or supplied.stat().st_size <= 0
            or supplied.stat().st_size > MAX_PLAN_BYTES):
        _fail('PLAN_INVALID', 'curation plan 缺失、为符号链接、为空或超过 1MB。')
    try:
        value = json.loads(supplied.read_text(encoding='utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail('PLAN_INVALID', 'curation plan 必须是 UTF-8 JSON。')
    if not isinstance(value, dict) or set(value) != _PLAN_FIELDS or value['format'] != CURATION_FORMAT:
        _fail('PLAN_INVALID', 'curation plan schema/format 无效。')
    return value


def _copy_file(source, target):
    if source.is_symlink() or not source.is_file():
        _fail('RESOURCE_MISSING', 'curation 控制资源缺失或为符号链接。')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())


def materialize_git_research_skill(data_root, control_package, plan, *,
        confirm_retrospective_only=False):
    """Create a content-addressed curated package from one verified Git receipt."""
    if confirm_retrospective_only is not True:
        _fail('CONFIRMATION_REQUIRED', '必须确认 Git 导入证据只能作为回顾性 Research Skill。')
    root = _data_root(data_root)
    control_supplied = Path(control_package).expanduser()
    if control_supplied.is_symlink() or not control_supplied.is_dir():
        _fail('PACKAGE_INVALID', 'control package 不存在或为符号链接。')
    control = control_supplied.resolve()
    control_audit = audit_research_skill(control)
    if (control_audit['counts']['primary_statements'] or control_audit['counts']['disclosed_actions']
            or control_audit['counts']['realized_outcomes'] or control_audit['counts']['scripts']):
        _fail('CONTROL_PACKAGE_INVALID', 'control package 只能包含非证据控制文档且不能包含脚本。')
    raw_control = json.loads((control / 'skill.yml').read_text(encoding='utf-8'))
    value = _load_plan(plan)
    skill_key = _slug(value['skill_key'])
    if skill_key != control_audit['skill_key']:
        _fail('PLAN_INVALID', 'curation plan 与 control package skill_key 不一致。')
    control_snapshot = _hash(value['control_snapshot'], 'control_snapshot')
    if control_snapshot != control_audit['package_snapshot']:
        _fail('PACKAGE_IDENTITY_MISMATCH', 'control package 与 curation plan 固定 snapshot 不一致。')
    snapshot = _hash(value['archive_snapshot'], 'archive_snapshot')
    receipt_directory = _safe_directory(root,
        'research/external_research_skills/git_receipts/' + skill_key)
    receipt_path = receipt_directory / (snapshot + '.json')
    checked = _verify_receipt(root, receipt_path)
    if not checked['verified']:
        _fail('ARCHIVE_INVALID', 'curation 引用的 Git archive receipt 无效：' + checked['reason'])
    receipt = checked['receipt']
    inventory = {item['path']: item for item in receipt['files']}
    rows = value['resources']
    if not isinstance(rows, list) or not rows or len(rows) > 100:
        _fail('PLAN_INVALID', 'curation resources 必须包含 1～100 项。')
    seen_ids = {item['resource_id'] for item in raw_control['resources']}
    seen_paths = {item['path'] for item in raw_control['resources']}
    additions = []
    for item in rows:
        if not isinstance(item, dict) or set(item) != _PLAN_RESOURCE_FIELDS:
            _fail('PLAN_INVALID', 'curation resource schema 无效。')
        resource_id = _slug(item['resource_id'], 'resource_id')
        upstream = _relative(item['upstream_path'], 'upstream_path').as_posix()
        target = _relative(item['target_path'], 'target_path').as_posix()
        role = item['role']
        if role not in EVIDENCE_ROLES | {'DOCUMENTATION'}:
            _fail('PLAN_INVALID', 'curation 只允许导入证据或 DOCUMENTATION 资源。')
        if not target.startswith('references/upstream/'):
            _fail('PATH_INVALID', 'curation target_path 必须位于 references/upstream/。')
        if resource_id in seen_ids or target in seen_paths:
            _fail('PLAN_INVALID', 'curation resource id/path 重复。')
        seen_ids.add(resource_id)
        seen_paths.add(target)
        archived = inventory.get(upstream)
        expected_hash = _hash(item['sha256'], 'curation sha256')
        expected_bytes = item['bytes']
        if (not archived or archived['sha256'] != expected_hash or archived['bytes'] != expected_bytes
                or type(expected_bytes) is not int):
            _fail('ARCHIVE_IDENTITY_MISMATCH', 'curation resource 与 Git archive inventory 不一致：' + upstream)
        locator = item['locator']
        if not isinstance(locator, str) or not locator.startswith('https://') or len(locator) > 2_000:
            _fail('PLAN_INVALID', 'curation locator 必须是 HTTPS URL。')
        additions.append({'resource_id': resource_id, 'path': target, 'role': role,
            'sha256': expected_hash, 'bytes': expected_bytes, 'locator': locator,
            'published_at': None, 'available_at': receipt['observed_at'] if role in EVIDENCE_ROLES else None,
            'timing_class': 'RETROSPECTIVE_REFERENCE' if role in EVIDENCE_ROLES else 'NOT_APPLICABLE',
            '_archive_item': archived})
    parent = _safe_directory(root,
        'research/external_research_skills/packages/' + skill_key, create=True)
    temporary = parent / ('.' + uuid4().hex + '.pending')
    temporary.mkdir()
    try:
        for item in raw_control['resources']:
            relative = _relative(item['path'], 'control resource path')
            _copy_file(control.joinpath(*relative.parts), temporary.joinpath(*relative.parts))
        resources = list(raw_control['resources'])
        for item in additions:
            relative = PurePosixPath(item['path'])
            payload = _object_payload(root, item['_archive_item'])
            target = temporary.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            resources.append({key: val for key, val in item.items() if key != '_archive_item'})
        manifest = {'format': PACKAGE_FORMAT, 'skill_key': skill_key, 'title': value['title'],
            'version': value['version'], 'status': value['status'],
            'strategy_source_kind': value['strategy_source_kind'], 'summary': value['summary'],
            'keywords': value['keywords'], 'resources': resources, 'claims': value['claims'],
            'alignments': value['alignments'], 'hypotheses': value['hypotheses'],
            'policy': REQUIRED_POLICY}
        (temporary / 'skill.yml').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        package_audit = audit_research_skill(temporary)
        target = parent / package_audit['package_snapshot']
        if target.is_symlink():
            _fail('ARCHIVE_PATH_INVALID', 'curated package target 不能是符号链接。')
        if target.exists():
            existing = audit_research_skill(target)
            if existing['package_snapshot'] != package_audit['package_snapshot']:
                _fail('ARCHIVE_IDENTITY_MISMATCH', '既有 curated package identity 不一致。')
            return {'created': False, 'path': str(target),
                'package_snapshot': existing['package_snapshot'], 'archive_snapshot': snapshot,
                'status': existing['status'], 'strict_pit_eligible': False,
                'source_authenticity_verified': False, 'source_publication_verified': False,
                'scripts_executed': False, 'strategy_source_written': False,
                'playbook_written': False}
        temporary.rename(target)
        final = audit_research_skill(target)
        if final['package_snapshot'] != target.name:
            _fail('ARCHIVE_IDENTITY_MISMATCH', 'curated package 写入后 snapshot 不匹配。')
        return {'created': True, 'path': str(target),
            'package_snapshot': final['package_snapshot'], 'archive_snapshot': snapshot,
            'status': final['status'], 'strict_pit_eligible': False,
            'source_authenticity_verified': False, 'source_publication_verified': False,
            'scripts_executed': False, 'strategy_source_written': False,
            'playbook_written': False}
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


__all__ = [
    'ARCHIVE_FORMAT', 'ARCHIVE_AUDIT_FORMAT', 'CURATION_FORMAT',
    'archive_git_research_skill', 'audit_git_research_skill_archives',
    'materialize_git_research_skill',
]

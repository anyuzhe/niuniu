"""Host-authorized, read-only catalog for curated Research Skill packages.

The library exposes only source-controlled registrations that bind one control package,
one verified Git archive snapshot, and one content-addressed curated package.  It never
fetches a repository, executes bundled code, or writes StrategySource/Playbook/trading
records.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path, PurePosixPath
import json
import os
import re
import subprocess

from quantlab.experiments.campaign_state import read_checked
from quantlab.knowledge.research_skill import (
    EVIDENCE_ROLES, ResearchSkillError, audit_research_skill,
)
from quantlab.knowledge.research_skill_git import (
    CURATION_FORMAT, audit_git_research_skill_archives,
)
from quantlab.storage.codec import digest, encode

LIBRARY_FORMAT = 'niuniu-research-skill-library-v1'
AUTHORIZATION = 'HOST_APPROVED_READ_ONLY'
REGISTRY_RELATIVE = PurePosixPath('research_skills/library.json')
MAX_REGISTRY_BYTES = 1_000_000
MAX_ENTRIES = 100
MAX_EXCERPT_BYTES = 6_000
MAX_RESOURCE_OFFSET = 8_000_000
SLUG = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')
HASH = re.compile(r'^[0-9a-f]{64}$')
REGISTRY_FIELDS = {'format', 'skills'}
ENTRY_FIELDS = {
    'skill_key', 'control_snapshot', 'archive_snapshot', 'package_snapshot',
    'curation_plan', 'authorization',
}
PLAN_FIELDS = {
    'format', 'skill_key', 'control_snapshot', 'archive_snapshot', 'version', 'status',
    'strategy_source_kind', 'title', 'summary', 'keywords', 'resources', 'claims',
    'alignments', 'hypotheses',
}
PLAN_RESOURCE_FIELDS = {
    'resource_id', 'upstream_path', 'target_path', 'role', 'sha256', 'bytes', 'locator',
}
ITEM_TYPES = ('CLAIM', 'HYPOTHESIS', 'ALIGNMENT', 'RESOURCE')
CLASSIFICATIONS = {
    'CLAIM': {'DIRECT_QUOTE', 'METHOD_INFERENCE', 'FACT_TO_VERIFY'},
    'HYPOTHESIS': {'DRAFT', 'INTRADAY', 'SWING', 'MEDIUM_TERM', 'LONG_TERM', 'MULTI_HORIZON'},
    'ALIGNMENT': {'CONSISTENT', 'INCONSISTENT', 'MIXED', 'UNKNOWN'},
    'RESOURCE': {
        'BEHAVIOR_CONTRACT', 'PRIMARY_STATEMENT', 'DISCLOSED_ACTION', 'REALIZED_OUTCOME',
        'METHOD', 'SCORECARD', 'SCRIPT_POLICY', 'DOCUMENTATION',
    },
}


class ResearchSkillLibraryError(ResearchSkillError):
    """A fail-closed library registration, lineage, or read error."""


def _fail(code, message):
    raise ResearchSkillLibraryError(code, message)


def _pairs_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail('LIBRARY_JSON_INVALID', 'Research Skill Library JSON 不能包含重复 key。')
        result[key] = value
    return result


def _json_file(path, maximum, code):
    if path.is_symlink() or not path.is_file():
        _fail(code, 'Research Skill Library 文件缺失或为符号链接。')
    size = path.stat().st_size
    if size <= 0 or size > maximum:
        _fail(code, 'Research Skill Library 文件为空或超过预算。')
    try:
        return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_pairs_object)
    except ResearchSkillLibraryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail(code, 'Research Skill Library 文件必须是 UTF-8 JSON。')


def _slug(value, name='skill_key'):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        _fail('LIBRARY_REGISTRY_INVALID', name + ' 格式无效。')
    return value


def _hash(value, name):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        _fail('LIBRARY_REGISTRY_INVALID', name + ' 必须是 64 位小写 SHA256。')
    return value


def _relative(value, name, *, prefix=None):
    if not isinstance(value, str) or not value or len(value) > 800:
        _fail('LIBRARY_REGISTRY_INVALID', name + ' 必须是规范相对路径。')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or '.' in path.parts or path.as_posix() != value:
        _fail('LIBRARY_REGISTRY_INVALID', name + ' 必须是规范相对路径。')
    if prefix and (not path.parts or path.parts[0] != prefix):
        _fail('LIBRARY_REGISTRY_INVALID', name + ' 必须位于 ' + prefix + '/。')
    return path


def _repository_root(path=None):
    supplied = Path(path).expanduser() if path is not None else Path(__file__).resolve().parents[3]
    if supplied.is_symlink() or not supplied.is_dir():
        _fail('LIBRARY_REPOSITORY_INVALID', 'Research Skill Library 源码根不存在或为符号链接。')
    root = supplied.resolve()
    skills = root / 'research_skills'
    if skills.is_symlink() or not skills.is_dir():
        _fail('LIBRARY_REPOSITORY_INVALID', '源码根缺少普通 research_skills/ 目录。')
    return root


def _data_root(path):
    if path is None:
        _fail('RESEARCH_SKILL_DATA_ROOT_REQUIRED', '读取策展包前必须配置独立数据根。')
    supplied = Path(path).expanduser()
    if supplied.is_symlink() or not supplied.is_dir():
        _fail('RESEARCH_SKILL_DATA_ROOT_INVALID', 'Research Skill 数据根不存在或为符号链接。')
    return supplied.resolve()


def _safe_directory(root, relative, *, required=True):
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            _fail('RESEARCH_SKILL_PATH_INVALID', 'Research Skill Library 目录类型无效或为符号链接。')
        if required and not current.is_dir():
            _fail('RESEARCH_SKILL_NOT_MATERIALIZED', '已授权 Research Skill 策展包尚未写入当前数据根。')
    return current


def _git_metadata(root, required_paths, require_git):
    marker = root / '.git'
    if not marker.exists():
        if require_git:
            _fail('LIBRARY_SOURCE_UNTRACKED', '正式 Research Skill Library 必须来自 Git 跟踪的源码树。')
        return {'tracked': False, 'clean': None, 'commit': None}
    environment = {**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_NO_LAZY_FETCH': '1',
        'GIT_TERMINAL_PROMPT': '0', 'GIT_PAGER': 'cat'}
    command = ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
        '-C', str(root)]
    try:
        status = subprocess.run(command + ['status', '--porcelain=v1', '--', 'research_skills'],
            capture_output=True, text=True, timeout=10, check=False, env=environment)
        tracked = subprocess.run(command + ['ls-files', '-z', '--', 'research_skills'],
            capture_output=True, timeout=10, check=False, env=environment)
        commit = subprocess.run(command + ['rev-parse', 'HEAD'], capture_output=True, text=True,
            timeout=10, check=False, env=environment)
    except (OSError, subprocess.SubprocessError):
        _fail('LIBRARY_GIT_UNAVAILABLE', '无法只读核对 Research Skill Library Git 状态。')
    if status.returncode or tracked.returncode or commit.returncode:
        _fail('LIBRARY_GIT_UNAVAILABLE', '无法只读核对 Research Skill Library Git 状态。')
    if status.stdout.strip():
        _fail('LIBRARY_SOURCE_DIRTY', 'research_skills/ 存在未提交修改，正式只读库拒绝加载。')
    tracked_paths = {value.decode('utf-8') for value in tracked.stdout.split(b'\0') if value}
    if any(path not in tracked_paths for path in required_paths):
        _fail('LIBRARY_SOURCE_UNTRACKED', 'Research Skill Library 授权、控制包或策展计划未纳入 Git。')
    value = commit.stdout.strip().lower()
    if not re.fullmatch(r'[0-9a-f]{40,64}', value):
        _fail('LIBRARY_GIT_UNAVAILABLE', 'Research Skill Library Git commit 无效。')
    return {'tracked': True, 'clean': True, 'commit': value}


def _public_resource(item):
    return {key: item[key] for key in (
        'resource_id', 'role', 'sha256', 'bytes', 'locator', 'published_at',
        'available_at', 'timing_class',
    )}


def _classification(item_type, item):
    if item_type == 'CLAIM':
        return item['kind']
    if item_type == 'HYPOTHESIS':
        return item['target_horizon']
    if item_type == 'ALIGNMENT':
        return item['assessment']
    return item['role']


class ResearchSkillLibrary:
    """Read registered packages after re-verifying source, archive, and package bytes."""

    def __init__(self, data_root=None, repo_root=None, *, require_git=True):
        # Resolve lazily so MCP/chat construction remains available when a packaged
        # installation has no source-controlled research_skills tree.
        candidate = (Path(repo_root).expanduser() if repo_root is not None
            else Path(__file__).resolve().parents[3])
        self.repo_root = candidate.absolute()
        self.data_root = Path(data_root).expanduser() if data_root is not None else None
        self.require_git = require_git is True

    @property
    def registry_path(self):
        return self.repo_root.joinpath(*REGISTRY_RELATIVE.parts)

    def _registry(self):
        self.repo_root = _repository_root(self.repo_root)
        value = _json_file(self.registry_path, MAX_REGISTRY_BYTES, 'LIBRARY_REGISTRY_INVALID')
        if not isinstance(value, dict) or set(value) != REGISTRY_FIELDS or value['format'] != LIBRARY_FORMAT:
            _fail('LIBRARY_REGISTRY_INVALID', 'Research Skill Library registry schema/format 无效。')
        rows = value['skills']
        if not isinstance(rows, list) or len(rows) > MAX_ENTRIES:
            _fail('LIBRARY_REGISTRY_INVALID', 'skills 必须是不超过 100 项的数组。')
        entries = []
        identities = set()
        required = {REGISTRY_RELATIVE.as_posix()}
        for raw in rows:
            if not isinstance(raw, dict) or set(raw) != ENTRY_FIELDS:
                _fail('LIBRARY_REGISTRY_INVALID', 'Research Skill Library entry 字段无效。')
            entry = {
                'skill_key': _slug(raw['skill_key']),
                'control_snapshot': _hash(raw['control_snapshot'], 'control_snapshot'),
                'archive_snapshot': _hash(raw['archive_snapshot'], 'archive_snapshot'),
                'package_snapshot': _hash(raw['package_snapshot'], 'package_snapshot'),
                'curation_plan': _relative(raw['curation_plan'], 'curation_plan', prefix='curation').as_posix(),
                'authorization': raw['authorization'],
            }
            if entry['authorization'] != AUTHORIZATION:
                _fail('LIBRARY_REGISTRY_INVALID', 'Research Skill Library 只接受宿主只读授权。')
            identity = (entry['skill_key'], entry['package_snapshot'])
            if identity in identities:
                _fail('LIBRARY_REGISTRY_INVALID', 'Research Skill Library entry 身份不能重复。')
            identities.add(identity)
            entry['entry_id'] = digest(entry)
            entries.append(entry)
            required.add('research_skills/' + entry['curation_plan'])
            control = self.repo_root / 'research_skills' / entry['skill_key']
            if control.is_symlink() or not control.is_dir():
                _fail('LIBRARY_CONTROL_INVALID', '注册的 Research Skill 控制包缺失或为符号链接。')
            for path in control.rglob('*'):
                if path.is_file() and not path.is_symlink():
                    required.add(path.relative_to(self.repo_root).as_posix())
        source = _git_metadata(self.repo_root, required, self.require_git)
        return {'format': LIBRARY_FORMAT, 'entries': entries, 'source_control': source,
            'registry_snapshot': digest({'format': LIBRARY_FORMAT, 'skills': rows})}

    def _entry(self, skill_key, package_snapshot):
        skill_key = _slug(skill_key)
        package_snapshot = _hash(package_snapshot, 'package_snapshot')
        registry = self._registry()
        matches = [entry for entry in registry['entries']
            if entry['skill_key'] == skill_key and entry['package_snapshot'] == package_snapshot]
        if len(matches) != 1:
            _fail('RESEARCH_SKILL_NOT_AUTHORIZED', '未找到宿主授权的精确 Research Skill snapshot。')
        return registry, matches[0]

    def _control(self, entry):
        root = self.repo_root / 'research_skills' / entry['skill_key']
        audit = audit_research_skill(root)
        if (audit['skill_key'] != entry['skill_key']
                or audit['package_snapshot'] != entry['control_snapshot']):
            _fail('RESEARCH_SKILL_CONTROL_MISMATCH', '控制包与 library registry 固定身份不一致。')
        counts = audit['counts']
        if counts['primary_statements'] or counts['disclosed_actions'] or counts['realized_outcomes'] or counts['scripts']:
            _fail('LIBRARY_CONTROL_INVALID', '正式控制包只能保存 source-free 合同和候选假设。')
        return root, audit

    def _archive(self, root, entry):
        audit = audit_git_research_skill_archives(root, entry['skill_key'])
        if audit['invalid_receipts']:
            _fail('RESEARCH_SKILL_ARCHIVE_INVALID', '该技能存在未通过完整性校验的 Git archive receipt。')
        directory = _safe_directory(root,
            'research/external_research_skills/git_receipts/' + entry['skill_key'])
        path = directory / (entry['archive_snapshot'] + '.json')
        if path.is_symlink() or not path.is_file():
            _fail('RESEARCH_SKILL_ARCHIVE_NOT_VERIFIED', 'registry 固定 Git archive receipt 缺失。')
        try:
            receipt = read_checked(path)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            _fail('RESEARCH_SKILL_ARCHIVE_INVALID', 'Git archive receipt checksum 无效。')
        if (receipt.get('archive_snapshot') != entry['archive_snapshot']
                or receipt.get('skill_key') != entry['skill_key']
                or audit['verified_receipts'] != audit['receipt_files']):
            _fail('RESEARCH_SKILL_ARCHIVE_NOT_VERIFIED', 'registry 固定 Git archive snapshot 未通过校验。')
        summary = {'skill_key': receipt['skill_key'],
            'archive_snapshot': receipt['archive_snapshot'], 'commit': receipt['commit'],
            'tree': receipt['tree'], 'observed_at': receipt['observed_at'],
            'files': receipt['file_count'], 'bytes': receipt['total_bytes']}
        return summary, receipt

    def _lineage(self, entry, control_root, control_audit, receipt, package_root,
            package_audit):
        plan_path = self.repo_root / 'research_skills' / entry['curation_plan']
        plan = _json_file(plan_path, MAX_REGISTRY_BYTES, 'RESEARCH_SKILL_LINEAGE_INVALID')
        if not isinstance(plan, dict) or set(plan) != PLAN_FIELDS or plan['format'] != CURATION_FORMAT:
            _fail('RESEARCH_SKILL_LINEAGE_INVALID', 'curation plan schema/format 无效。')
        expected_identity = (entry['skill_key'], entry['control_snapshot'], entry['archive_snapshot'])
        if (plan.get('skill_key'), plan.get('control_snapshot'), plan.get('archive_snapshot')) != expected_identity:
            _fail('RESEARCH_SKILL_LINEAGE_INVALID', 'curation plan 与 registry 固定身份不一致。')
        control = _json_file(control_root / 'skill.yml', 1_000_000, 'LIBRARY_CONTROL_INVALID')
        package = _json_file(package_root / 'skill.yml', 1_000_000, 'RESEARCH_SKILL_PACKAGE_INVALID')
        if (package_audit['package_snapshot'] != entry['package_snapshot']
                or package_audit['skill_key'] != entry['skill_key']
                or control_audit['package_snapshot'] != entry['control_snapshot']):
            _fail('RESEARCH_SKILL_PACKAGE_MISMATCH', '策展包、控制包与 registry 身份不一致。')
        metadata = ('version', 'status', 'strategy_source_kind', 'title', 'summary', 'keywords',
            'claims', 'alignments', 'hypotheses')
        if any(package.get(key) != plan.get(key) for key in metadata):
            _fail('RESEARCH_SKILL_LINEAGE_INVALID', '策展包内容与 source-controlled curation plan 不一致。')
        resources = plan['resources']
        if not isinstance(resources, list) or not resources or len(resources) > 100:
            _fail('RESEARCH_SKILL_LINEAGE_INVALID', 'curation resources 数量无效。')
        control_resources = control.get('resources')
        package_resources = package.get('resources')
        if (not isinstance(control_resources, list) or not isinstance(package_resources, list)
                or package_resources[:len(control_resources)] != control_resources
                or len(package_resources) != len(control_resources) + len(resources)):
            _fail('RESEARCH_SKILL_LINEAGE_INVALID', '策展包资源集合不是 control + curation 的闭合集。')
        inventory = {row['path']: row for row in receipt['files']}
        seen_ids = {row['resource_id'] for row in control_resources}
        seen_targets = {row['path'] for row in control_resources}
        expected_additions = []
        for raw in resources:
            if not isinstance(raw, dict) or set(raw) != PLAN_RESOURCE_FIELDS:
                _fail('RESEARCH_SKILL_LINEAGE_INVALID', 'curation resource schema 无效。')
            resource_id = _slug(raw['resource_id'], 'resource_id')
            upstream = _relative(raw['upstream_path'], 'upstream_path').as_posix()
            target = _relative(raw['target_path'], 'target_path').as_posix()
            if not target.startswith('references/upstream/'):
                _fail('RESEARCH_SKILL_LINEAGE_INVALID', 'curation target 必须位于 references/upstream/。')
            if raw['role'] not in EVIDENCE_ROLES | {'DOCUMENTATION'}:
                _fail('RESEARCH_SKILL_LINEAGE_INVALID', 'curation 不能导入脚本或可执行角色。')
            if resource_id in seen_ids or target in seen_targets:
                _fail('RESEARCH_SKILL_LINEAGE_INVALID', 'curation resource id/path 重复。')
            seen_ids.add(resource_id);seen_targets.add(target)
            archived = inventory.get(upstream)
            if (not archived or archived.get('sha256') != raw['sha256']
                    or archived.get('bytes') != raw['bytes']):
                _fail('RESEARCH_SKILL_LINEAGE_INVALID', 'curation resource 未绑定到已校验 Git blob。')
            expected_additions.append({
                'resource_id': resource_id, 'path': target, 'role': raw['role'],
                'sha256': raw['sha256'], 'bytes': raw['bytes'], 'locator': raw['locator'],
                'published_at': None,
                'available_at': receipt['observed_at'] if raw['role'] in EVIDENCE_ROLES else None,
                'timing_class': ('RETROSPECTIVE_REFERENCE'
                    if raw['role'] in EVIDENCE_ROLES else 'NOT_APPLICABLE'),
            })
        if package_resources[len(control_resources):] != expected_additions:
            _fail('RESEARCH_SKILL_LINEAGE_INVALID', '策展包资源声明与 Git archive/plan 推导结果不一致。')
        if package_audit['counts']['scripts']:
            _fail('RESEARCH_SKILL_PACKAGE_INVALID', 'Agent Library 不接入包含外部 SCRIPT 的策展包。')
        return package

    def _load(self, skill_key, package_snapshot):
        registry, entry = self._entry(skill_key, package_snapshot)
        control_root, control_audit = self._control(entry)
        root = _data_root(self.data_root)
        archive, receipt = self._archive(root, entry)
        directory = _safe_directory(root,
            'research/external_research_skills/packages/' + entry['skill_key'])
        package_root = directory / entry['package_snapshot']
        if package_root.is_symlink() or not package_root.is_dir():
            _fail('RESEARCH_SKILL_NOT_MATERIALIZED', 'registry 固定策展包不存在或为符号链接。')
        package_root = package_root.resolve()
        if not package_root.is_relative_to(root):
            _fail('RESEARCH_SKILL_PATH_INVALID', '策展包路径越过独立数据根。')
        package_audit = audit_research_skill(package_root)
        package = self._lineage(entry, control_root, control_audit, receipt, package_root,
            package_audit)
        return {'registry': registry, 'entry': entry, 'archive': archive, 'receipt': receipt,
            'control_audit': control_audit, 'package_root': package_root,
            'package_audit': package_audit, 'package': package}

    def _source_only(self, registry, entry, availability):
        _, control = self._control(entry)
        return {'entry_id': entry['entry_id'], 'skill_key': entry['skill_key'],
            'title': control['title'], 'version': control['version'], 'status': control['status'],
            'authorization': entry['authorization'], 'package_snapshot': entry['package_snapshot'],
            'control_snapshot': entry['control_snapshot'], 'archive_snapshot': entry['archive_snapshot'],
            'package_available': False, 'integrity': availability, 'archive_verified': False,
            'counts': control['counts'], 'readiness': control['readiness'],
            'blockers': ['curated_data_root_not_configured_or_materialized'],
            'boundaries': control['boundaries']}

    def _summary(self, loaded):
        entry = loaded['entry'];audit = loaded['package_audit'];archive = loaded['archive']
        return {'entry_id': entry['entry_id'], 'skill_key': audit['skill_key'],
            'title': audit['title'], 'version': audit['version'], 'status': audit['status'],
            'strategy_source_kind': audit['strategy_source_kind'], 'keywords': audit['keywords'],
            'authorization': entry['authorization'], 'package_snapshot': audit['package_snapshot'],
            'control_snapshot': entry['control_snapshot'], 'archive_snapshot': entry['archive_snapshot'],
            'package_available': True, 'integrity': 'VERIFIED', 'archive_verified': True,
            'archive': {key: archive[key] for key in
                ('commit', 'tree', 'observed_at', 'files', 'bytes')},
            'counts': audit['counts'], 'readiness': audit['readiness'],
            'blockers': audit['blockers'], 'publication_unverified_resource_ids':
                audit['publication_unverified_resource_ids'], 'boundaries': audit['boundaries']}

    def list(self, query='', offset=0, limit=20):
        if not isinstance(query, str) or len(query) > 200:
            _fail('INVALID_ARGUMENT', 'query 必须是不超过 200 字的文本。')
        if type(offset) is not int or not 0 <= offset <= 100_000:
            _fail('INVALID_ARGUMENT', 'offset 无效。')
        if type(limit) is not int or not 1 <= limit <= 100:
            _fail('INVALID_ARGUMENT', 'limit 无效。')
        registry = self._registry();rows=[]
        materialized = False
        root = None
        if self.data_root is not None:
            root = _data_root(self.data_root)
            base = root / 'research' / 'external_research_skills' / 'packages'
            if base.is_symlink():
                _fail('RESEARCH_SKILL_PATH_INVALID', 'Research Skill packages 根不能是符号链接。')
            materialized = base.is_dir()
        for entry in registry['entries']:
            if materialized and (root / 'research/external_research_skills/packages'
                    / entry['skill_key']).is_dir():
                row = self._summary(self._load(entry['skill_key'], entry['package_snapshot']))
            else:
                row = self._source_only(registry, entry,
                    'DATA_ROOT_NOT_CONFIGURED' if self.data_root is None else 'NOT_MATERIALIZED')
            if query.casefold() in encode(row).casefold():
                rows.append(row)
        return {'format': LIBRARY_FORMAT, 'registry_snapshot': registry['registry_snapshot'],
            'source_control': registry['source_control'], 'records': rows[offset:offset + limit],
            'total': len(rows), 'offset': offset,
            'boundaries': {'read_only': True, 'network_used': False, 'scripts_executed': False,
                'strategy_source_written': False, 'playbook_written': False,
                'strict_pit_eligible': False, 'alpha_claimed': False,
                'daily_scanner_eligible': False, 'direct_trade_eligible': False}}

    def get(self, skill_key, package_snapshot):
        loaded = self._load(skill_key, package_snapshot);audit = loaded['package_audit']
        preview = {key: value for key, value in audit['strategy_source_preview'].items()
            if key != 'archive_ref'}
        roles = Counter(row['role'] for row in loaded['package']['resources'])
        return {'format': LIBRARY_FORMAT, 'skill': self._summary(loaded),
            'resource_role_counts': dict(roles), 'strategy_source_preview': preview,
            'item_types': list(ITEM_TYPES),
            'classification_values': {key: sorted(value) for key, value in CLASSIFICATIONS.items()},
            'scope': ('Verified read-only curation view. DIRECT_QUOTE is verbatim package evidence; '
                'METHOD_INFERENCE and FACT_TO_VERIFY remain distinct. No object is written.')}

    def _enrich(self, loaded, item_type, item):
        package = loaded['package']
        resources = {row['resource_id']: row for row in package['resources']}
        claims = {row['claim_id']: row for row in package['claims']}
        if item_type == 'RESOURCE':
            return {**_public_resource(item), 'excerpt_allowed': item['role'] != 'SCRIPT'}
        if item_type == 'CLAIM':
            return {**item, 'resources': [_public_resource(resources[key])
                for key in item['resource_ids']]}
        if item_type == 'HYPOTHESIS':
            return {**item, 'claims': [self._enrich(loaded, 'CLAIM', claims[key])
                for key in item['claim_ids']]}
        statement = claims[item['statement_claim_id']]
        return {**item, 'statement_claim': self._enrich(loaded, 'CLAIM', statement),
            'actions': [_public_resource(resources[key]) for key in item['action_resource_ids']],
            'outcomes': [_public_resource(resources[key]) for key in item['outcome_resource_ids']]}

    def _search_loaded(self, loaded, item_type, query, classification, offset, limit):
        item_type = item_type.upper() if isinstance(item_type, str) else ''
        if item_type not in ITEM_TYPES:
            _fail('INVALID_ARGUMENT', 'item_type 必须是 CLAIM/HYPOTHESIS/ALIGNMENT/RESOURCE。')
        if not isinstance(query, str) or len(query) > 200:
            _fail('INVALID_ARGUMENT', 'query 必须是不超过 200 字的文本。')
        if not isinstance(classification, str) or len(classification) > 80:
            _fail('INVALID_ARGUMENT', 'classification 必须是不超过 80 字的文本。')
        classification = classification.upper()
        if classification and classification not in CLASSIFICATIONS[item_type]:
            _fail('INVALID_ARGUMENT', 'classification 不属于所选 item_type。')
        if type(offset) is not int or not 0 <= offset <= 100_000:
            _fail('INVALID_ARGUMENT', 'offset 无效。')
        if type(limit) is not int or not 1 <= limit <= 100:
            _fail('INVALID_ARGUMENT', 'limit 无效。')
        field = {'CLAIM': 'claims', 'HYPOTHESIS': 'hypotheses',
            'ALIGNMENT': 'alignments', 'RESOURCE': 'resources'}[item_type]
        rows = loaded['package'][field]
        query_terms = [term for term in re.split(r'[\s,，;；/|]+', query.casefold()) if term]
        selected = []
        for item in rows:
            if classification:
                values = {_classification(item_type, item)}
                if item_type == 'HYPOTHESIS':
                    values.add(item['status'])
                if classification not in values:
                    continue
            enriched = self._enrich(loaded, item_type, item)
            haystack = encode(enriched).casefold()
            if not query_terms or any(term in haystack for term in query_terms):
                selected.append(enriched)
        return {'format': LIBRARY_FORMAT, 'skill_key': loaded['entry']['skill_key'],
            'package_snapshot': loaded['entry']['package_snapshot'], 'item_type': item_type,
            'classification': classification, 'records': selected[offset:offset + limit],
            'total': len(selected), 'offset': offset,
            'interpretation': ('Items are curated research evidence/hypotheses, not StrategySource, '
                'Playbook, Alpha, Daily Decision, or a trade signal.')}

    def search(self, skill_key, package_snapshot, item_type, query='', classification='',
            offset=0, limit=20):
        loaded = self._load(skill_key, package_snapshot)
        return self._search_loaded(loaded, item_type, query, classification, offset, limit)

    def browse(self, skill_key, package_snapshot, query=''):
        """One-audit desktop view; still returns no resource bytes and performs no writes."""
        loaded = self._load(skill_key, package_snapshot)
        result = self.get_from_loaded(loaded)
        result['items'] = {kind.lower(): self._search_loaded(
            loaded, kind, query, '', 0, 100) for kind in ITEM_TYPES}
        return result

    def get_from_loaded(self, loaded):
        audit = loaded['package_audit']
        preview = {key: value for key, value in audit['strategy_source_preview'].items()
            if key != 'archive_ref'}
        roles = Counter(row['role'] for row in loaded['package']['resources'])
        return {'format': LIBRARY_FORMAT, 'skill': self._summary(loaded),
            'resource_role_counts': dict(roles), 'strategy_source_preview': preview,
            'item_types': list(ITEM_TYPES),
            'classification_values': {key: sorted(value) for key, value in CLASSIFICATIONS.items()},
            'scope': ('Verified read-only curation view. DIRECT_QUOTE is verbatim package evidence; '
                'METHOD_INFERENCE and FACT_TO_VERIFY remain distinct. No object is written.')}

    def excerpt(self, skill_key, package_snapshot, resource_id, offset_bytes=0,
            limit_bytes=MAX_EXCERPT_BYTES):
        loaded = self._load(skill_key, package_snapshot)
        if not isinstance(resource_id, str) or not SLUG.fullmatch(resource_id):
            _fail('INVALID_ARGUMENT', 'resource_id 格式无效。')
        if type(offset_bytes) is not int or not 0 <= offset_bytes <= MAX_RESOURCE_OFFSET:
            _fail('INVALID_ARGUMENT', 'offset_bytes 无效。')
        if type(limit_bytes) is not int or not 1 <= limit_bytes <= MAX_EXCERPT_BYTES:
            _fail('INVALID_ARGUMENT', 'limit_bytes 必须是 1～6000。')
        item = next((row for row in loaded['package']['resources']
            if row['resource_id'] == resource_id), None)
        if item is None:
            _fail('RESEARCH_SKILL_RESOURCE_NOT_FOUND', '策展包不存在该 resource_id。')
        if item['role'] == 'SCRIPT':
            _fail('RESEARCH_SKILL_RESOURCE_ROLE_DENIED', 'Agent Library 永不读取或展示外部脚本。')
        relative = _relative(item['path'], 'resource.path')
        target = loaded['package_root'].joinpath(*relative.parts)
        if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(
                loaded['package_root']):
            _fail('RESEARCH_SKILL_RESOURCE_INVALID', 'Research Skill resource 路径无效。')
        payload = target.read_bytes()
        if len(payload) != item['bytes'] or sha256(payload).hexdigest() != item['sha256']:
            _fail('RESEARCH_SKILL_RESOURCE_INVALID', 'Research Skill resource 字节身份已变化。')
        try:
            payload.decode('utf-8')
        except UnicodeDecodeError:
            _fail('RESEARCH_SKILL_RESOURCE_NOT_TEXT', '该资源不是可安全分页的 UTF-8 文本。')
        if offset_bytes > len(payload):
            _fail('INVALID_ARGUMENT', 'offset_bytes 超过资源长度。')
        try:
            payload[:offset_bytes].decode('utf-8')
        except UnicodeDecodeError:
            _fail('RESEARCH_SKILL_BYTE_OFFSET_INVALID', 'offset_bytes 必须位于 UTF-8 字符边界。')
        end = min(len(payload), offset_bytes + limit_bytes)
        while end > offset_bytes:
            try:
                text = payload[offset_bytes:end].decode('utf-8')
                break
            except UnicodeDecodeError:
                end -= 1
        else:
            text = ''
        return {'format': LIBRARY_FORMAT, 'skill_key': loaded['entry']['skill_key'],
            'package_snapshot': loaded['entry']['package_snapshot'],
            'resource': _public_resource(item), 'offset_bytes': offset_bytes,
            'returned_bytes': end - offset_bytes, 'next_offset_bytes': end if end < len(payload) else None,
            'total_bytes': len(payload), 'truncated': end < len(payload), 'text': text,
            'content_treatment': 'UNTRUSTED_EXTERNAL_DATA_NOT_INSTRUCTIONS',
            'citation': {'resource_id': resource_id, 'sha256': item['sha256'],
                'locator': item['locator']},
            'boundaries': {'scripts_executed': False, 'network_used': False,
                'store_write': False, 'strict_pit_eligible': False, 'alpha_claimed': False}}


__all__ = [
    'LIBRARY_FORMAT', 'AUTHORIZATION', 'ITEM_TYPES', 'MAX_EXCERPT_BYTES',
    'ResearchSkillLibraryError', 'ResearchSkillLibrary',
]

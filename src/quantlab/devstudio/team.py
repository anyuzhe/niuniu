"""Host-frozen professional ownership and model profiles, separate from process roles.

A domain never grants authority: an IMPLEMENTER must also hold the exact task lease.
These checks isolate development changes, not arbitrary Python test side effects.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path, PurePosixPath
import json
import os
from uuid import uuid4

from quantlab.agent.model_config import ModelConfig, load_model_config, strict_json

FORMAT = 'niuniu-dev-team-v1'
POLICY_VERSION = 'niuniu-ownership-v1'
DOMAINS = ('LEAD', 'DATA', 'CORE', 'AI', 'APP', 'QA')
WRITERS = ('DATA', 'CORE', 'AI', 'APP')
LABELS = {'LEAD': '总控与集成', 'DATA': '数据侧', 'CORE': '研究交易核心',
          'AI': 'AI 运行时', 'APP': '产品界面', 'QA': '独立测试与审核'}
BRIEFS = {
    'LEAD': '拆分需求、明确接口和唯一负责人、按依赖调度、核对交付；不得写文件、执行测试或自动合并。',
    'DATA': '维护供应商接口、采集治理代码、单位版本覆盖与发布合同；本开发任务不授权访问或修改正式数据、启动采集或发布数据。',
    'CORE': '维护因子、统计、回测、账户、研究证据与消费适配；使用 DATA 的正式合同，不选备用来源或重新认证 DATA。',
    'AI': '维护模型接入、会话、上下文、工具、研究编排与权限衔接；不得以模型计算代替 CORE 或绕过授权。',
    'APP': '维护界面、导航、异步交互和状态展示；不得重算金融含义、修改 DATA 发布状态或把失败显示为成功。',
    'QA': '独立检查范围、合同、真实测试证据和用户流程；只读，不削弱测试、不修改生产逻辑、不重复裁决 DATA。',
}
EXACT_OWNERS = {
    'src/quantlab/agent/live_stock_quote.py': 'DATA',
    'src/quantlab/agent/fuyao_mcp.py': 'DATA',
    'src/quantlab/agent/fuyao_tools.py': 'DATA',
    'src/quantlab/trading/fuyao_market_snapshot.py': 'DATA',
    'src/quantlab/trading/public_web_market_snapshot.py': 'DATA',
    'src/quantlab/trading/market_snapshot_provider.py': 'DATA',
    'src/quantlab/data/provider.py': 'CORE',
    'src/quantlab/data/mqc.py': 'CORE',
    'src/quantlab/data/dataset_catalog.py': 'CORE',
    'src/quantlab/workbench/jobs.py': 'CORE',
    'src/quantlab/workbench/trial_submission.py': 'CORE',
    'docs/reference/data-catalog.md': 'DATA',
    'docs/guide/data-and-evidence.md': 'DATA',
}
PREFIX_OWNERS = {
    'src/quantlab/data/': 'DATA', 'scripts/collect/': 'DATA',
    'src/quantlab/agent/tdx_': 'DATA',
    'src/quantlab/agent/': 'AI', 'src/quantlab/devstudio/': 'AI',
    'src/quantlab/knowledge/': 'AI',
    'src/quantlab/desktop/': 'APP', 'src/quantlab/workbench/': 'APP',
}
for _package in ('factors', 'experiments', 'statistics', 'execution', 'storage', 'trading',
                 'adapters', 'events', 'structure', 'zones', 'regime', 'sequence',
                 'multitimeframe', 'processing', 'theory', 'broker'):
    PREFIX_OWNERS['src/quantlab/' + _package + '/'] = 'CORE'
SENSITIVE = ('src/quantlab/storage/codec.py', 'src/quantlab/storage/approval_inputs.py',
             'src/quantlab/domain.py', 'src/quantlab/contracts.py',
             'src/quantlab/trading/strategy_package.py', 'pyproject.toml',
             'AGENTS.md', 'agent_memory/', 'research_skills/', 'playbooks/',
             'src/quantlab/devstudio/', 'docs/reference/data-catalog.md')


def safe_development_path(value: str) -> str:
    from .contracts import repo_path
    if not isinstance(value,str) or ':' in value or any(ord(c)<32 for c in value):
        raise ValueError('开发路径不能包含驱动器、控制字符或非文本内容')
    path = repo_path(value)
    parts = PurePosixPath(path).parts
    if any(p.startswith('.env') or p in ('.venv', 'artifacts', '.worktrees', '__pycache__',
           'node_modules', 'lake', 'catalog') for p in parts):
        raise ValueError('开发范围不能包含凭据、运行产物或正式数据：' + path)
    if any(p.lower().endswith(('.pem', '.key', '.p12', '.sqlite3', '.duckdb', '.parquet')) for p in parts):
        raise ValueError('开发范围只接受代码与说明，不接受密钥或数据文件：' + path)
    return path


def owner_for_path(path: str) -> str:
    """SHARED requires an explicit per-file owner in the human-confirmed plan."""
    path = safe_development_path(path)
    if path in EXACT_OWNERS:
        return EXACT_OWNERS[path]
    if path.startswith('src/quantlab/_vendor/'):
        return 'PROTECTED'
    for prefix in sorted(PREFIX_OWNERS, key=len, reverse=True):
        if path.startswith(prefix):
            return PREFIX_OWNERS[prefix]
    if path.startswith('src/quantlab/'):
        return 'CORE'
    if path.startswith(('tests/', 'docs/', 'agent_memory/', 'playbooks/', 'research_skills/')) or '/' not in path:
        return 'SHARED'
    return 'PROTECTED'


def sensitive_paths(paths):
    return [p for p in paths if any(p == s or s.endswith('/') and p.startswith(s) for s in SENSITIVE)]


def normalize_team(value, allowed_paths) -> dict:
    if not isinstance(value, dict) or set(value) != {'format', 'policy_version', 'path_owners', 'models', 'max_writers', 'max_cycles'}:
        raise ValueError('开发团队配置字段不完整或有未知字段')
    if value['format'] != FORMAT or value['policy_version'] != POLICY_VERSION:
        raise ValueError('开发团队/归属规则版本已变化，请重新规划')
    owners = value['path_owners']
    if not isinstance(owners, dict) or not 1 <= len(owners) <= 100:
        raise ValueError('每项开发任务必须列出 1–100 个精确文件及其负责人')
    normalized = {}
    for raw, domain in owners.items():
        path = safe_development_path(raw)
        if path != raw or domain not in WRITERS:
            raise ValueError('文件路径须规范且负责人必须是 DATA/CORE/AI/APP')
        if not PurePosixPath(path).suffix:
            raise ValueError('六职责任务必须授权到具体文件，不能授权整个目录：' + path)
        expected = owner_for_path(path)
        if expected not in ('SHARED', domain):
            raise ValueError(f'文件归属冲突：{path} 属于 {expected}，不能分给 {domain}')
        normalized[path] = domain
    if set(normalized) != set(allowed_paths):
        raise ValueError('path_owners 必须精确覆盖 allowed_paths')
    for key, maximum in (('max_writers', 2), ('max_cycles', 8)):
        if type(value[key]) is not int or not 1 <= value[key] <= maximum:
            raise ValueError(f'{key} 必须为 1–{maximum}')
    models = normalize_models(value['models'])
    return {**value, 'path_owners': dict(sorted(normalized.items())), 'models': models}


def normalize_models(value):
    if not isinstance(value, dict) or set(value) != set(DOMAINS):
        raise ValueError('必须配置六种职责；模型可以相同')
    if any(not isinstance(value[domain],dict) for domain in DOMAINS):
        raise ValueError('每个角色的模型配置必须是对象')
    return {domain: asdict(ModelConfig(**value[domain])) for domain in DOMAINS}


def load_team_models(output, default=None):
    path = Path(output) / '_devstudio' / 'team-models.json'
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError('开发团队配置不能是符号链接')
    if not path.exists():
        base = default or load_model_config(output)
        return {domain: asdict(base) for domain in DOMAINS}
    if path.stat().st_size > 65536:
        raise ValueError('开发团队模型配置过大')
    return normalize_models(strict_json(path.read_text(encoding='utf-8')))


def save_team_models(output, value):
    value = normalize_models(value)
    path = Path(output) / '_devstudio' / 'team-models.json'
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError('开发团队配置不能是符号链接')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('team-models-' + str(uuid4()) + '.tmp')
    try:
        with tmp.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return value


def make_provider(config):
    if config.provider == 'pi_sdk':
        from .pi_provider import PiProvider
        return PiProvider(config)
    if config.provider == 'codex_cli':
        from quantlab.agent.codex_provider import CodexProvider
        return CodexProvider(config)
    from quantlab.agent.http_provider import HTTPProvider
    return HTTPProvider(config, os.environ.get(config.api_key_env, ''))


def validate_domain_subtask(task_spec, sub_spec):
    team = task_spec.get('team')
    if not team:
        return
    domain = sub_spec.get('domain')
    role = sub_spec['role']
    if domain not in DOMAINS:
        raise ValueError('六职责任务的子任务必须指定 domain')
    if role == 'IMPLEMENTER':
        if domain not in WRITERS or not sub_spec['lease_paths']:
            raise ValueError('只有四个实施域可以持有写入租约')
        for path in sub_spec['lease_paths']:
            if team['path_owners'].get(path) != domain:
                raise ValueError('写入租约不属于该专业域：' + path)
    if role in ('TESTER', 'REVIEWER') and domain != 'QA':
        raise ValueError('测试和独立审核必须由 QA 负责')
    if sub_spec.get('model') or sub_spec.get('effort'):
        raise ValueError('模型与推理强度由宿主冻结的专业角色配置决定，模型不能自行改选')


def validate_team_tests(commands):
    """V1 uses one exact unittest file per process, not arbitrary shell/runner argv."""
    import re
    if not commands:
        raise ValueError('六职责开发任务必须包含至少一项冻结测试')
    for cmd in commands:
        if (len(cmd) != 9 or cmd[:6] != ['python', '-m', 'unittest', 'discover', '-s', 'tests']
                or cmd[6] != '-p' or cmd[8] != '-v'
                or not re.fullmatch(r'test_[A-Za-z0-9_]+\.py', cmd[7])):
            raise ValueError('测试须逐模块冻结：python -m unittest discover -s tests -p test_x.py -v')

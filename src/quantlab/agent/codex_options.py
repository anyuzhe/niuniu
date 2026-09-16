"""Process-local Codex settings; never modify credentials or global config."""
import json
import re
import os
import tomllib
from pathlib import Path
from quantlab.agent.model_config import ModelError

DISABLED = ('shell_tool','unified_exec','multi_agent','multi_agent_v2','enable_fanout',
    'apps','plugins','hooks','plugin_hooks','browser_use','browser_use_external',
    'computer_use','image_generation','in_app_browser','code_mode','code_mode_only',
    'memories','tool_search','tool_suggest','request_permissions_tool',
    'skill_mcp_dependency_install','workspace_dependencies','shell_snapshot')
LEGACY = ('enabled','max_concurrent_threads_per_session',
    'default_subagent_model','default_subagent_reasoning_effort')


def codex_command(config, home=None):
    options=[];warnings=[]
    home=Path(home) if home is not None else Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    source=home/'config.toml'
    try:
        settings=tomllib.loads(source.read_text(encoding='utf-8')) if source.exists() else {}
    except (OSError,ValueError) as exc:
        raise ModelError('Codex 配置无法解析；未读取登录凭据') from exc
    if config.legacy_agent_compat:
        legacy=settings.get('agents',{})
        for name in LEGACY:
            if name in legacy and not isinstance(legacy[name],dict):
                options += ['-c',f'agents.{name}={{}}']
                warnings.append('仅本进程兼容旧 agents 字段：'+name)
    for name in settings.get('mcp_servers',{}):
        if not re.fullmatch(r'[A-Za-z0-9_-]+',name):
            raise ModelError('MCP 名称无法用本版 CLI 安全隔离，请检查配置名称')
        options += ['-c','mcp_servers.'+name+'.enabled=false']
    options += ['-c','model_provider="openai"','-c','web_search="disabled"']
    for name in DISABLED: options += ['-c',f'features.{name}=false']
    return [config.executable(),*options,'app-server','--listen','stdio://'],warnings

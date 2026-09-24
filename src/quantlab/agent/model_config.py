"""User-selected model transports. Configuration never contains credentials."""
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit
import json
import os
import re
import shutil
from uuid import uuid4


class ModelError(RuntimeError):
    pass


class ChatStopped(ModelError):
    pass


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ModelError('模型 JSON 含重复字段')
            result[key] = value
        return result
    def constant(value): raise ModelError('模型 JSON 含非有限数')
    def floating(value):
        import math
        result=float(value)
        if not math.isfinite(result):raise ModelError('模型 JSON 浮点数溢出')
        return result
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant, parse_float=floating)


@dataclass(frozen=True)
class ModelConfig:
    provider: str = 'codex_cli'
    model: str = ''
    effort: str = 'medium'
    codex_path: str = ''
    base_url: str = 'https://api.openai.com/v1'
    api_key_env: str = 'NIUNIU_MODEL_API_KEY'
    timeout_seconds: int = 180
    max_tool_calls: int = 12
    max_rounds: int = 8
    max_output_tokens: int = 4096
    max_context_chars: int = 120000
    legacy_agent_compat: bool = True
    pi_path: str = ''

    def __post_init__(self):
        if self.provider not in ('codex_cli','responses','chat_completions','pi_sdk'):
            raise ValueError('不支持的模型协议')
        for field in ('model','effort','codex_path','base_url','api_key_env','pi_path'):
            value = getattr(self,field)
            if not isinstance(value,str) or len(value)>2048 or any(ord(c)<32 for c in value):
                raise ValueError('模型配置字段无效：'+field)
        if len(self.model)>200 or (self.provider!='codex_cli' and not self.model.strip()):
            raise ValueError('API 模型需填写实际模型 ID')
        if self.provider == 'pi_sdk' and not re.fullmatch(r'[A-Za-z0-9._-]+/[^\s\x00-\x1f]+', self.model):
            raise ValueError('Pi 模型请填写 provider/model，例如 openai-codex/gpt-6-luna')
        if self.effort not in ('','none','minimal','low','medium','high','xhigh'):
            raise ValueError('无效推理强度；留空使用服务默认值')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',self.api_key_env):
            raise ValueError('密钥环境变量名称无效')
        for field,lo,hi in [('timeout_seconds',10,600),('max_tool_calls',1,24),
            ('max_rounds',1,16),('max_output_tokens',128,16384),('max_context_chars',2000,200000)]:
            value=getattr(self,field)
            if type(value) is not int or not lo<=value<=hi: raise ValueError('模型预算无效：'+field)
        if type(self.legacy_agent_compat) is not bool: raise ValueError('兼容开关须为布尔值')
        parsed=urlsplit(self.base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
            raise ValueError('接口地址不能含凭据、查询参数或片段')
        if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1','::1')):
            raise ValueError('远程接口须用 HTTPS；HTTP 仅限本机回环')

    def executable(self):
        if self.codex_path:
            path=Path(self.codex_path).expanduser()
            if not path.is_absolute() or not path.is_file() or not os.access(path,os.X_OK):
                raise ModelError('Codex 路径必须是可执行文件的绝对路径')
            return str(path)
        command=shutil.which('codex')
        if command: return command
        # GUI apps need not inherit a terminal's nvm PATH.
        candidates=[Path('/opt/homebrew/bin/codex'),Path('/usr/local/bin/codex')]
        candidates += sorted((Path.home()/'.nvm/versions/node').glob('*/bin/codex'),reverse=True)
        for path in candidates:
            if path.is_file() and os.access(path,os.X_OK): return str(path)
        raise ModelError('未找到 Codex CLI，请在模型设置中选择可执行文件')


def assistant_root(output):
    output=Path(output).resolve(); path=output/'_assistant'
    if path.is_symlink(): raise ModelError('助手目录不能是符号链接')
    path.mkdir(parents=True,exist_ok=True)
    return path


def load_model_config(output):
    path=assistant_root(output)/'model.json'
    if not path.exists(): return ModelConfig()
    if path.is_symlink() or path.stat().st_size>16384: raise ModelError('模型配置文件无效')
    value=strict_json(path.read_text(encoding='utf-8'))
    return ModelConfig(**value)


def save_model_config(output, config):
    path=assistant_root(output)/'model.json'
    if path.is_symlink(): raise ModelError('模型配置不能是符号链接')
    temporary=path.with_name('model-'+str(uuid4())+'.tmp')
    try:
        with temporary.open('x',encoding='utf-8') as stream:
            json.dump(asdict(config),stream,ensure_ascii=False,allow_nan=False,indent=2)
        temporary.replace(path)
    finally: temporary.unlink(missing_ok=True)

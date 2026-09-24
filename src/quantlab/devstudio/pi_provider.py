"""Bounded local Pi SDK model transport; every tool dispatch stays host-owned."""
from __future__ import annotations

from collections import deque
from pathlib import Path
from queue import Queue, Empty
from threading import Event, Thread
from tempfile import TemporaryDirectory
import json
import os
import re
import shutil
import signal
import subprocess
import time

from quantlab.agent.model_config import ModelConfig, ModelError, ChatStopped, strict_json
from quantlab.agent.provider_compat import CompletionProtocol

MAX_FRAME = 2_000_000


def resolve_pi(pi_path=''):
    """Find the actual installed SDK via the Pi executable, including GUI nvm PATHs."""
    candidates = [Path(pi_path).expanduser()] if pi_path else []
    if not pi_path:
        command = shutil.which('pi')
        if command: candidates.append(Path(command))
        candidates += [Path('/opt/homebrew/bin/pi'), Path('/usr/local/bin/pi')]
        candidates += sorted((Path.home()/'.nvm/versions/node').glob('*/bin/pi'), reverse=True)
    for command in candidates:
        if not command.is_absolute() or not command.is_file() or not os.access(command, os.X_OK):
            continue
        target = command.resolve()
        package = next((p for p in target.parents if (p/'package.json').is_file()), None)
        if package is None: continue
        try: name = json.loads((package/'package.json').read_text()).get('name')
        except (OSError, ValueError): continue
        if name not in ('@earendil-works/pi-coding-agent', '@mariozechner/pi-coding-agent'): continue
        sdk = package/'dist/index.js'
        node = command.parent/'node'
        if not node.is_file():
            found = shutil.which('node')
            if not found: continue
            node = Path(found)
        if sdk.is_file() and os.access(node, os.X_OK): return str(node), str(sdk)
    raise ModelError('未找到本地 Pi SDK 与 Node，请在六角色配置中填写已安装的 pi 可执行文件绝对路径')


def safe_error(value):
    text = str(value)
    text = re.sub(r'(?i)Bearer\s+\S+', 'Bearer [REDACTED]', text)
    text = re.sub(r'\b(?:sk-[A-Za-z0-9_-]{12,}|eyJ[A-Za-z0-9_.-]{30,})\b', '[REDACTED]', text)
    return text[:1000]


class PiProvider(CompletionProtocol):
    def __init__(self, config):
        if not isinstance(config, ModelConfig) or config.provider != 'pi_sdk':
            raise ValueError('PiProvider requires pi_sdk ModelConfig')
        self.config = config

    def probe(self, stop=None):
        return self._execute('', [], [], None, lambda *_: None, stop or Event(), probe=True)

    def run(self, system, messages, tools, dispatch, emit, stop):
        return self._execute(system, messages, tools, dispatch, emit, stop)

    def _execute(self, system, messages, tools, dispatch, emit, stop, probe=False):
        cfg = self.config
        if stop.is_set(): raise ChatStopped('已停止 Pi 调用')
        if any(m.get('role') not in ('user', 'assistant') or not isinstance(m.get('content'), str) for m in messages):
            raise ModelError('Pi 输入只接受已整理的文本 user/assistant 消息')
        definitions = {t['name']: t for t in tools}
        if len(definitions) != len(tools): raise ModelError('Pi 工具名称重复')
        payload = {'probe':probe, 'model':cfg.model, 'effort':cfg.effort, 'system':system,
                   'messages':messages, 'tools':tools, 'max_rounds':cfg.max_rounds,
                   'max_tool_calls':cfg.max_tool_calls, 'max_context_chars':cfg.max_context_chars,
                   'max_output_tokens':cfg.max_output_tokens}
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        if len(encoded)>cfg.max_context_chars: raise ModelError('Pi 初始上下文超过角色预算')
        node, sdk = resolve_pi(cfg.pi_path)
        bridge = Path(__file__).with_name('pi_bridge.mjs')
        frames, errors = Queue(maxsize=256), deque(maxlen=20)
        env = {**os.environ, 'PI_OFFLINE':'1', 'PI_TELEMETRY':'0'}
        env.pop('NODE_OPTIONS', None)
        with TemporaryDirectory(prefix='niuniu-pi-') as cwd:
            process = subprocess.Popen([node, str(bridge), sdk], cwd=cwd, env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', bufsize=1, start_new_session=True)
            def read_stdout():
                try:
                    while True:
                        line = process.stdout.readline(MAX_FRAME+1)
                        if not line: break
                        if len(line)>MAX_FRAME:
                            frames.put({'type':'error','message':'Pi frame exceeds size limit'}); break
                        try: frames.put(strict_json(line))
                        except (ValueError, ModelError):
                            frames.put({'type':'error','message':'Pi bridge returned invalid JSON'}); break
                finally: frames.put(None)
            def read_stderr():
                for line in process.stderr: errors.append(safe_error(line))
            readers = [Thread(target=read_stdout,daemon=True),Thread(target=read_stderr,daemon=True)]
            for reader in readers: reader.start()
            seen, calls = set(), 0
            deadline = time.monotonic()+cfg.timeout_seconds
            try:
                process.stdin.write(encoded+'\n'); process.stdin.flush()
                while True:
                    if stop.is_set(): raise ChatStopped('已停止 Pi 调用；已有隔离改动保留')
                    if time.monotonic()>=deadline: raise ModelError('Pi 调用达到角色超时上限；未自动重试')
                    try: frame = frames.get(timeout=.1)
                    except Empty: continue
                    if frame is None:
                        raise ModelError('Pi 进程提前退出：'+safe_error(' '.join(errors)))
                    if not isinstance(frame,dict): raise ModelError('Pi frame must be object')
                    kind = frame.get('type')
                    if kind == 'error': raise ModelError('Pi：'+safe_error(frame.get('message','失败')))
                    if kind == 'identity':
                        if cfg.model != str(frame.get('pi_provider'))+'/'+str(frame.get('model')):
                            raise ModelError('Pi 模型身份不匹配')
                        emit('pi_identity',frame)
                    elif kind == 'tool_call':
                        name, identifier, args = frame.get('name'), frame.get('id'), frame.get('arguments')
                        if not isinstance(identifier,str) or identifier in seen or name not in definitions or not isinstance(args,dict):
                            raise ModelError('Pi 调用了未知工具、重复调用或无效参数')
                        seen.add(identifier); calls += 1
                        if calls>cfg.max_tool_calls: raise ModelError('Pi 工具次数超过预算')
                        emit('tool_call',{'name':name,'arguments':args,'call_id':identifier})
                        value = dispatch(name,args,identifier)
                        emit('tool_result',{'name':name,'call_id':identifier,'result':value})
                        reply = json.dumps({'type':'tool_result','id':identifier,'result':value},ensure_ascii=False,allow_nan=False)
                        if len(reply)>MAX_FRAME: raise ModelError('Pi 工具响应超过传输预算')
                        process.stdin.write(reply+'\n'); process.stdin.flush()
                    elif kind == 'result':
                        result = frame.get('result',{})
                        if cfg.model != str(result.get('pi_provider'))+'/'+str(result.get('model')):
                            raise ModelError('Pi 完成结果模型身份不匹配')
                        if not probe and (not isinstance(result.get('text'),str) or not result['text'].strip()):
                            raise ModelError('Pi 没有最终回答')
                        if process.wait(timeout=5)!=0: raise ModelError('Pi 进程非正常结束')
                        if not probe: emit('text_delta',{'text':result['text']})
                        return result
                    else: raise ModelError('Pi 返回未知协议消息')
            except (OSError, subprocess.SubprocessError) as exc:
                raise ModelError('Pi 传输失败：'+safe_error(exc)) from None
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try: process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=3)
                for reader in readers: reader.join(timeout=1)
                for stream in (process.stdin,process.stdout,process.stderr): stream.close()

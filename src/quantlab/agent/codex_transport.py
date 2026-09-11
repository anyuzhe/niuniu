"""Bounded stdio connection to a dedicated, least-privilege Codex process."""
from collections import deque
from pathlib import Path
from queue import Queue, Empty, Full
from threading import Thread, Event
import json
import os
import subprocess
import tempfile
import time
from quantlab.agent.model_config import ModelError, ChatStopped, strict_json
from quantlab.agent.codex_options import codex_command


class CodexTransport:
    def __init__(self,config,stop=None):
        self.config=config;self.stop=stop or Event();self.closed=False;self.sequence=0
        self.pending=deque();self.inbox=Queue(maxsize=256);self.overflow=Event()
        self.deadline=time.monotonic()+config.timeout_seconds
        command,self.warnings=codex_command(config)
        self.directory=tempfile.TemporaryDirectory(prefix='niuniu-codex-')
        env=os.environ.copy()
        env['PATH']=str(Path(command[0]).parent)+os.pathsep+env.get('PATH','')
        try:
            self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,cwd=self.directory.name,env=env,bufsize=0)
        except Exception:
            self.directory.cleanup();raise
        self.reader=Thread(target=self._read,daemon=True);self.reader.start()
        try:
            self.rpc('initialize',{'clientInfo':{'name':'niuniu_research','version':'0.1.0'},
                'capabilities':{'experimentalApi':True}})
            self.send({'method':'initialized','params':{}})
        except Exception:
            self.close();raise

    def _put(self,item):
        try:self.inbox.put_nowait(item)
        except Full:self.overflow.set()

    def _read(self):
        total=0
        try:
            while not self.closed:
                raw=self.process.stdout.readline(1_000_001)
                if not raw:break
                total+=len(raw)
                if len(raw)>1_000_000 or total>8_000_000:
                    self._put(ModelError('Codex 事件流超过本轮预算'));return
                try:message=strict_json(raw.decode('utf-8'))
                except (ValueError,UnicodeError,ModelError):
                    self._put(ModelError('Codex 返回了非预期 JSON 协议'));return
                self._put(message)
        except (OSError,ValueError):pass
        finally:self._put(ModelError('Codex 连接已结束；请检查 CLI 登录与配置'))

    def check(self):
        if self.stop.is_set(): raise ChatStopped('已停止助手；没有取消已批准的研究任务')
        if time.monotonic()>self.deadline: raise ModelError('模型请求达到本轮时限')
        if self.overflow.is_set(): raise ModelError('模型事件积压超过预算')

    def send(self,value):
        self.check()
        payload=(json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n').encode('utf-8')
        if len(payload)>1_000_000: raise ModelError('请求超过协议大小预算')
        try:self.process.stdin.write(payload);self.process.stdin.flush()
        except (OSError,ValueError) as exc:raise ModelError('无法写入 Codex 连接') from exc

    def read(self):
        while True:
            self.check()
            try:value=self.inbox.get(timeout=.1)
            except Empty:continue
            if isinstance(value,Exception):raise value
            if not isinstance(value,dict):raise ModelError('Codex 消息必须为对象')
            return value

    def rpc(self,method,params):
        self.sequence+=1;identifier=self.sequence
        self.send({'id':identifier,'method':method,'params':params})
        while True:
            message=self.read()
            if message.get('id')==identifier and 'method' not in message:
                if 'error' in message:
                    text=str(message['error'].get('message','协议错误'))[:500]
                    raise ModelError('Codex '+method+' 失败：'+text)
                return message.get('result',{})
            self.pending.append(message)
            if len(self.pending)>256:raise ModelError('Codex 握手事件超过预算')

    def event(self):
        self.check()
        return self.pending.popleft() if self.pending else self.read()

    def close(self):
        if self.closed:return
        self.closed=True
        try:
            if self.process.poll() is None:
                self.process.terminate()
                try:self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=3)
            for stream in (self.process.stdin,self.process.stdout):
                if stream:stream.close()
            self.reader.join(timeout=1)
        finally:self.directory.cleanup()

    def __enter__(self):return self
    def __exit__(self,*_):self.close()

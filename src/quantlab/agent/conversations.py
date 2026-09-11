"""Append-only conversation files, independent of numerical experiment archives."""
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock
from uuid import UUID, uuid4
import json
import time
from quantlab.agent.model_config import assistant_root, ModelError, strict_json

_LOCKS={}
_LOCKS_GUARD=Lock()


class ConversationStore:
    def __init__(self,output):
        self.root=assistant_root(output)/'conversations'
        if self.root.is_symlink():raise ModelError('会话目录不能为符号链接')
        self.root.mkdir(exist_ok=True)

    def folder(self,identifier):
        if not isinstance(identifier,str) or str(UUID(identifier))!=identifier:
            raise ModelError('会话编号无效')
        path=self.root/identifier
        if path.is_symlink() or not (path/'meta.json').is_file():raise ModelError('会话不存在')
        return path

    @staticmethod
    def read(path):
        if path.is_symlink() or path.stat().st_size>200000:raise ModelError('会话记录无效或过大')
        return strict_json(path.read_text(encoding='utf-8'))

    @staticmethod
    def write(path,value):
        text=json.dumps(value,ensure_ascii=False,allow_nan=False)
        if len(text.encode('utf-8'))>180000:raise ModelError('会话事件超过大小限制')
        if path.exists():raise ModelError('已有会话事件不能覆盖')
        temporary=path.with_name(str(uuid4())+'.pending')
        try:
            with temporary.open('x',encoding='utf-8') as stream:stream.write(text)
            temporary.replace(path)
        finally:temporary.unlink(missing_ok=True)

    def create(self,title='新研究会话'):
        if not isinstance(title,str) or not title.strip():raise ModelError('会话名称不能为空')
        identifier=str(uuid4());folder=self.root/identifier;folder.mkdir()
        self.write(folder/'meta.json',{'id':identifier,'title':title.strip()[:100],
            'created_at':datetime.now(timezone.utc).isoformat()})
        return identifier

    def list(self,limit=100):
        if type(limit) is not int or not 1<=limit<=500:raise ModelError('会话页大小无效')
        values=[]
        for folder in self.root.iterdir():
            if folder.is_symlink() or not folder.is_dir():continue
            try:
                self.folder(folder.name);values.append(self.read(folder/'meta.json'))
            except (OSError,ValueError,ModelError):continue
        return sorted(values,key=lambda x:x['created_at'],reverse=True)[:limit]

    def append(self,identifier,kind,payload):
        if kind not in ('user','assistant','state','model','tool_start','tool_result'):
            raise ModelError('未知会话事件类型')
        path=self.folder(identifier)/(f'{time.time_ns():020d}-'+str(uuid4())+'.json')
        self.write(path,{'kind':kind,'created_at':datetime.now(timezone.utc).isoformat(),'payload':payload})
        return path.name

    def events(self,identifier,limit=500):
        if type(limit) is not int or not 1<=limit<=2000:raise ModelError('事件页大小无效')
        paths=sorted(self.folder(identifier).glob('[0-9]*.json'))
        return {'events':[self.read(p) for p in paths[-limit:]],'total':len(paths),
            'omitted':max(0,len(paths)-limit)}

    def messages(self,identifier,max_chars):
        history=self.events(identifier,2000)
        if history['omitted']:raise ModelError('会话历史过长，请新建会话')
        result=[];size=0
        for event in history['events']:
            kind=event['kind'];item=event['payload']
            if kind not in ('user','assistant'):continue
            if kind=='assistant' and item.get('status')!='completed':continue
            content=item['text'];size+=len(content)
            if size>max_chars:raise ModelError('会话超过上下文预算；请新建会话或提高配置上限，不自动丢弃早期内容')
            result.append({'role':kind,'content':content})
        return result

    @contextmanager
    def turn_lock(self,identifier):
        import fcntl
        folder=self.folder(identifier);key=str(folder)
        with _LOCKS_GUARD:lock=_LOCKS.setdefault(key,Lock())
        if not lock.acquire(blocking=False):raise ModelError('该会话正在响应')
        try:
            path=folder/'turn.lock'
            if path.is_symlink():raise ModelError('会话锁路径无效')
            with path.open('a+b') as stream:
                try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except OSError as exc:raise ModelError('另一个进程正在使用该会话') from exc
                try:yield
                finally:fcntl.flock(stream,fcntl.LOCK_UN)
        finally:lock.release()

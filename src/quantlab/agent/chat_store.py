"""Local conversation journal. Completed messages are context, not research facts."""
from contextlib import contextmanager,closing
from datetime import datetime,timezone
from pathlib import Path
from uuid import UUID,uuid4
import fcntl
import json
import sqlite3
from quantlab.agent.model_config import assistant_root,ModelError


def stamp():return datetime.now(timezone.utc).isoformat()
def identifier(value):
    if not isinstance(value,str) or str(UUID(value))!=value:raise ValueError('无效会话编号')
    return value


class ChatStore:
    def __init__(self,output):
        self.root=assistant_root(output);self.path=self.root/'chat.sqlite3'
        for suffix in ('','-wal','-shm','-journal'):
            if Path(str(self.path)+suffix).is_symlink():raise ModelError('会话数据库不能是符号链接')
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS conversations
                (id TEXT PRIMARY KEY,title TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS turns
                (id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL,user_text TEXT NOT NULL,
                 assistant_text TEXT NOT NULL,status TEXT NOT NULL,metadata TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chat_events
                (seq INTEGER PRIMARY KEY AUTOINCREMENT,turn_id TEXT NOT NULL,
                 kind TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS turns_conversation ON turns(conversation_id,created_at);
                CREATE INDEX IF NOT EXISTS events_turn ON chat_events(turn_id,seq);''')
    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.path,timeout=10)) as db:
            db.row_factory=sqlite3.Row
            with db:yield db
    def create(self,title='新研究对话'):
        cid=str(uuid4())
        with self.db() as db:db.execute('INSERT INTO conversations VALUES (?,?,?)',(cid,str(title)[:100],stamp()))
        return cid
    def conversations(self):
        with self.db() as db:return [dict(r) for r in db.execute('SELECT * FROM conversations ORDER BY created_at DESC LIMIT 100')]
    def turns(self,cid):
        identifier(cid)
        with self.db() as db:
            if not db.execute('SELECT 1 FROM conversations WHERE id=?',(cid,)).fetchone():raise ValueError('会话不存在')
            rows=db.execute('SELECT * FROM turns WHERE conversation_id=? ORDER BY created_at DESC LIMIT 100',(cid,)).fetchall()
        return [{**dict(r),'metadata':json.loads(r['metadata'])} for r in reversed(rows)]
    @contextmanager
    def lease(self,cid):
        identifier(cid);path=self.root/('conversation-'+cid+'.lock')
        if path.is_symlink():raise ModelError('会话锁不能是符号链接')
        with path.open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as exc:raise ModelError('该会话正在处理另一条消息') from exc
            try:yield
            finally:fcntl.flock(lock,fcntl.LOCK_UN)
    def begin(self,cid,text,config):
        self.turns(cid);tid=str(uuid4())
        with self.db() as db:
            db.execute("UPDATE turns SET status='interrupted' WHERE conversation_id=? AND status='running'",(cid,))
            db.execute('INSERT INTO turns VALUES (?,?,?,?,?,?,?)',
                (tid,cid,text,'','running',json.dumps({'config':config},ensure_ascii=False),stamp()))
        return tid
    def event(self,tid,kind,payload):
        identifier(tid);text=json.dumps(payload,ensure_ascii=False,allow_nan=False)
        if len(text)>100000:raise ModelError('工具日志超过预算')
        with self.db() as db:
            db.execute('INSERT INTO chat_events(turn_id,kind,payload,created_at) VALUES (?,?,?,?)',(tid,kind,text,stamp()))
    def finish(self,tid,status,text,metadata):
        if status not in ('completed','failed','stopped'):raise ValueError('无效对话结束状态')
        with self.db() as db:
            old=db.execute('SELECT metadata FROM turns WHERE id=?',(identifier(tid),)).fetchone()
            if old is None:raise ValueError('对话轮次不存在')
            merged={**json.loads(old['metadata']),**metadata}
            db.execute('UPDATE turns SET status=?,assistant_text=?,metadata=? WHERE id=?',
                (status,text,json.dumps(merged,ensure_ascii=False,allow_nan=False),tid))
    def events(self,tid):
        with self.db() as db:
            return [{'kind':r['kind'],'payload':json.loads(r['payload']),'created_at':r['created_at']}
                for r in db.execute('SELECT * FROM chat_events WHERE turn_id=? ORDER BY seq',(identifier(tid),))]

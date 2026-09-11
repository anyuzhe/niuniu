"""Local proposal journal. Approval is host-only; queues remain authoritative."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
import json
import sqlite3
from quantlab.storage.codec import digest, encode
from quantlab.agent.planning import ProposalError


def now(): return datetime.now(timezone.utc).isoformat()


def identifier(value):
    try:
        if not isinstance(value,str) or str(UUID(value)) != value: raise ValueError()
    except (ValueError,TypeError,AttributeError):
        raise ProposalError('INVALID_ARGUMENT','需要规范 UUID。') from None
    return value


class ProposalStore:
    def __init__(self, output):
        self.output = Path(output).resolve(); self.directory = self.output/'_agent'
        self.path = self.directory/'proposals.sqlite3'
        if not self.output.is_dir(): raise ProposalError('INVALID_WORKSPACE','产物目录不存在。')

    @contextmanager
    def transaction(self, create=False):
        candidates = [self.directory,self.path,*[Path(str(self.path)+s) for s in ('-journal','-wal','-shm')]]
        if any(p.is_symlink() for p in candidates):
            raise ProposalError('INVALID_WORKSPACE','提案存储不接受符号链接。')
        if not self.directory.resolve().is_relative_to(self.output):
            raise ProposalError('INVALID_WORKSPACE','提案路径越出工作空间。')
        if create: self.directory.mkdir(exist_ok=True)
        if not create and not self.path.exists(): raise ProposalError('NOT_FOUND','没有提案记录。')
        connection = sqlite3.connect(self.path.as_uri()+('?mode=rwc' if create else '?mode=rw'),
            uri=True, timeout=3, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('BEGIN IMMEDIATE')
            if create:
                connection.execute('CREATE TABLE IF NOT EXISTS proposals (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL, status TEXT NOT NULL, job_id TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL, approved_at TEXT)')
                connection.execute('CREATE TABLE IF NOT EXISTS proposal_events (sequence INTEGER PRIMARY KEY, proposal_id TEXT NOT NULL, action TEXT NOT NULL, at TEXT NOT NULL)')
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback(); raise
        finally: connection.close()

    @staticmethod
    def event(connection, proposal_id, action):
        connection.execute('INSERT INTO proposal_events(proposal_id,action,at) VALUES (?,?,?)', (proposal_id,action,now()))

    @staticmethod
    def decode(row):
        if row is None: raise ProposalError('NOT_FOUND','提案不存在。')
        value = json.loads(row['payload'])
        if digest(value) != row['checksum']:
            raise ProposalError('INVALID_ARTIFACT','提案内容校验失败。')
        return {'proposal_id':row['id'],'request_id':row['request_id'],
            'proposal_digest':row['checksum'],'status':row['status'],'job_id':row['job_id'],
            'created_at':row['created_at'],'approved_at':row['approved_at'],'plan':value}

    def load(self, proposal_id, connection):
        identifier(proposal_id)
        return self.decode(connection.execute('SELECT * FROM proposals WHERE id=?',(proposal_id,)).fetchone())

    def get(self, proposal_id):
        with self.transaction() as connection: return self.load(proposal_id,connection)

    def list(self, limit=30):
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ProposalError('INVALID_ARGUMENT','提案列表每页 1–50 条。')
        if not self.path.exists(): return []
        with self.transaction() as connection:
            return [self.decode(row) for row in connection.execute(
                'SELECT * FROM proposals ORDER BY created_at DESC,id DESC LIMIT ?', (limit,))]

    def create(self, request_id, plan, max_pending):
        identifier(request_id); checksum = digest(plan)
        with self.transaction(create=True) as connection:
            existing = connection.execute('SELECT * FROM proposals WHERE request_id=?',(request_id,)).fetchone()
            if existing is not None:
                result = self.decode(existing)
                if result['proposal_digest'] != checksum:
                    raise ProposalError('CONFLICT','同一请求编号不能用于不同配置、代码或工作空间。')
                return result
            pending = connection.execute("SELECT COUNT(*) FROM proposals WHERE status IN ('pending','approved')").fetchone()[0]
            if pending >= max_pending:
                raise ProposalError('BUDGET_EXCEEDED','待处理提案已达上限；请先处理现有提案。')
            proposal_id = str(uuid4()); job_id = str(uuid4())
            connection.execute('INSERT INTO proposals VALUES (?,?,?,?,?,?,?,NULL)',
                (proposal_id,request_id,encode(plan),checksum,'pending',job_id,now()))
            self.event(connection,proposal_id,'created')
            return self.load(proposal_id,connection)

    def reject(self, proposal_id, expected_digest):
        with self.transaction() as connection:
            record = self.load(proposal_id,connection)
            if record['proposal_digest'] != expected_digest:
                raise ProposalError('STALE_PROPOSAL','显示的提案与当前记录不一致。')
            if record['status'] == 'rejected': return record
            if record['status'] != 'pending':
                raise ProposalError('INVALID_STATE','只能拒绝尚未批准的提案；已入队任务请在原任务页取消。')
            connection.execute("UPDATE proposals SET status='rejected' WHERE id=?", (proposal_id,))
            self.event(connection,proposal_id,'rejected_by_user')
            return self.load(proposal_id,connection)

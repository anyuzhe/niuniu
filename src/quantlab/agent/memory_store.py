"""Append-only research notes, separate from chat and numerical archives."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
import json
import sqlite3
from quantlab.storage.codec import digest, encode


class MemoryError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def identifier(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise MemoryError('INVALID_ARGUMENT', '需要规范 UUID。') from None
    return value


class MemoryStore:
    def __init__(self, output):
        self.output = Path(output).resolve()
        self.directory = self.output / '_assistant'
        self.path = self.directory / 'research_memory.sqlite3'

    @contextmanager
    def connection(self, write=False):
        paths = [self.directory, self.path, *[Path(str(self.path)+s) for s in ('-journal','-wal','-shm')]]
        if not self.output.is_dir() or any(p.is_symlink() for p in paths):
            raise MemoryError('INVALID_WORKSPACE', '研究记忆目录无效或含符号链接。')
        if write:
            self.directory.mkdir(exist_ok=True)
        if not write and not self.path.exists():
            raise MemoryError('NOT_FOUND', '当前工作空间尚无结构化研究记忆。')
        db = sqlite3.connect(self.path.as_uri()+('?mode=rwc' if write else '?mode=ro'), uri=True, timeout=3, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise MemoryError('SCHEMA_VERSION', '研究记忆版本不受支持。')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            if write:
                db.execute('CREATE TABLE IF NOT EXISTS memory_entries (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, input_hash TEXT NOT NULL, kind TEXT NOT NULL, factor_id TEXT NOT NULL, status TEXT NOT NULL, hypothesis_id TEXT, supersedes TEXT UNIQUE, created_at TEXT NOT NULL, search_text TEXT NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL)')
                db.execute('CREATE INDEX IF NOT EXISTS memory_lookup ON memory_entries(kind,factor_id,status,created_at)')
                db.execute('PRAGMA user_version=1')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def decode(row):
        if row is None:
            raise MemoryError('NOT_FOUND', '研究记忆不存在。')
        value = json.loads(row['payload'])
        columns = {'memory_id':'id', 'request_id':'request_id', 'input_hash':'input_hash',
                   'kind':'kind', 'factor_id':'factor_id', 'status':'status',
                   'hypothesis_id':'hypothesis_id', 'supersedes':'supersedes', 'created_at':'created_at'}
        if digest(value) != row['checksum'] or any(value.get(k) != row[c] for k,c in columns.items()):
            raise MemoryError('CORRUPT_MEMORY', '研究记忆内容或索引校验失败。')
        return value

    def get(self, memory_id):
        identifier(memory_id)
        with self.connection() as db:
            value = self.decode(db.execute('SELECT * FROM memory_entries WHERE id=?', (memory_id,)).fetchone())
            newer = db.execute('SELECT id FROM memory_entries WHERE supersedes=?', (memory_id,)).fetchone()
            return {**value, 'superseded_by': newer['id'] if newer else None}

    def request(self, request_id, input_hash):
        identifier(request_id)
        if self.path.is_symlink(): raise MemoryError('INVALID_WORKSPACE','记忆文件不能为符号链接。')
        if not self.path.exists(): return None
        with self.connection() as db:
            # Another writer may have created the file but not committed its schema.
            # The subsequent write transaction waits and rechecks the same request.
            if db.execute('PRAGMA user_version').fetchone()[0]==0: return None
            row = db.execute('SELECT * FROM memory_entries WHERE request_id=?', (request_id,)).fetchone()
            if row is None: return None
            value = self.decode(row)
            if value['input_hash'] != input_hash:
                raise MemoryError('CONFLICT', '同一请求编号不能保存不同研究内容。')
            return value

    def create(self, request_id, input_hash, content):
        identifier(request_id)
        with self.connection(write=True) as db:
            row = db.execute('SELECT * FROM memory_entries WHERE request_id=?', (request_id,)).fetchone()
            if row is not None:
                value = self.decode(row)
                if value['input_hash'] != input_hash:
                    raise MemoryError('CONFLICT', '重复请求的研究内容发生变化。')
                return value
            if db.execute('SELECT COUNT(*) FROM memory_entries').fetchone()[0] >= 10000:
                raise MemoryError('BUDGET_EXCEEDED', '当前工作空间研究记忆已达一万条；不会静默删减。')
            if content['hypothesis_id']:
                parent = self.decode(db.execute('SELECT * FROM memory_entries WHERE id=?', (content['hypothesis_id'],)).fetchone())
                if parent['kind'] != 'hypothesis' or parent['candidate_id'] != content['candidate_id']:
                    raise MemoryError('INVALID_PARENT', '结论必须关联相同候选的研究假设。')
            if content['supersedes']:
                old = self.decode(db.execute('SELECT * FROM memory_entries WHERE id=?', (content['supersedes'],)).fetchone())
                if any(old[k] != content[k] for k in ('kind','candidate_id','hypothesis_id')):
                    raise MemoryError('INVALID_REVISION', '修订不能替换其他类型、候选或假设的记录。')
                if db.execute('SELECT 1 FROM memory_entries WHERE supersedes=?', (old['memory_id'],)).fetchone():
                    raise MemoryError('STALE_REVISION', '该记录已有后续修订，请读取最新记录。')
            value = {**content, 'memory_id':str(uuid4()), 'request_id':request_id, 'input_hash':input_hash,
                     'created_at':datetime.now(timezone.utc).isoformat()}
            search = ' '.join(str(value.get(k,'')) for k in ('title','statement','mechanism','falsification','limitations','next_action','factor_id')).casefold()
            db.execute('INSERT INTO memory_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (value['memory_id'],request_id,input_hash,value['kind'],value['factor_id'],value['status'],value['hypothesis_id'],value['supersedes'],value['created_at'],search,encode(value),digest(value)))
            return value

    def search(self, query='', kind='', factor_id='', status='', include_superseded=False, offset=0, limit=20):
        if any(not isinstance(v,str) or len(v)>200 for v in (query,kind,factor_id,status)):
            raise MemoryError('INVALID_ARGUMENT', '检索字段必须为不超过200字的文本。')
        if kind not in ('','hypothesis','finding') or status not in ('','hypothesis','supported','contradicted','inconclusive','unavailable','implementation_failure'):
            raise MemoryError('INVALID_ARGUMENT', '未知记录类型或结论分类。')
        if type(include_superseded) is not bool or type(offset) is not int or not 0<=offset<=100000 or type(limit) is not int or not 1<=limit<=20:
            raise MemoryError('INVALID_ARGUMENT', '分页或历史选项无效。')
        empty = {'records':[], 'total':0, 'offset':offset, 'next_offset':None}
        if self.path.is_symlink(): raise MemoryError('INVALID_WORKSPACE','记忆文件不能为符号链接。')
        if not self.path.exists(): return empty
        clauses = ['instr(m.search_text,?)>0']; values = [query.casefold()]
        for column, value in [('kind',kind),('factor_id',factor_id),('status',status)]:
            if value:
                clauses.append('m.'+column+'=?'); values.append(value)
        if not include_superseded:
            clauses.append('NOT EXISTS (SELECT 1 FROM memory_entries n WHERE n.supersedes=m.id)')
        where = ' WHERE '+' AND '.join(clauses)
        with self.connection() as db:
            total = db.execute('SELECT COUNT(*) FROM memory_entries m'+where, values).fetchone()[0]
            rows = db.execute('SELECT m.* FROM memory_entries m'+where+' ORDER BY m.created_at DESC,m.id DESC LIMIT ? OFFSET ?', [*values,limit,offset])
            keys = ('memory_id','kind','title','statement','status','factor_id','factor_version','candidate_id','hypothesis_id','supersedes','created_at','origin')
            records = [{k:v for k,v in self.decode(row).items() if k in keys} for row in rows]
        return {'records':records,'total':total,'offset':offset,
                'next_offset':offset+limit if offset+limit<total else None,
                'evidence_policy':'搜索仅返回历史笔记；引用前调用 get_research_memory 复核来源。'}

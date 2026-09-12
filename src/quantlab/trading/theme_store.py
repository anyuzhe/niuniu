"""Append-only checksum-verified Theme Matrix snapshot store."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID,uuid4
import json,sqlite3
from quantlab.storage.codec import digest,encode
from .decision import FRAMES
from .theme_state import THEME_STATES,normalize_theme_snapshot


class ThemeError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def identifier(value,name='编号'):
    try:
        if not isinstance(value,str) or str(UUID(value))!=value:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise ThemeError('INVALID_ARGUMENT',f'{name}需要规范 UUID。') from None
    return value


class ThemeStore:
    def __init__(self,output):
        self.output=Path(output).resolve();self.directory=self.output/'_trading';self.path=self.directory/'theme_matrix.sqlite3'

    @contextmanager
    def connection(self,write=False):
        paths=[self.directory,self.path,*[Path(str(self.path)+s) for s in ('-journal','-wal','-shm')]]
        if not self.output.is_dir() or any(p.is_symlink() for p in paths):raise ThemeError('INVALID_WORKSPACE','Theme Matrix 目录无效或包含符号链接。')
        if write:self.directory.mkdir(exist_ok=True)
        if not write and not self.path.exists():raise ThemeError('NOT_FOUND','当前工作空间尚无 Theme Snapshot。')
        db=sqlite3.connect(self.path.as_uri()+('?mode=rwc' if write else '?mode=ro'),uri=True,timeout=3,isolation_level=None);db.row_factory=sqlite3.Row
        try:
            version=db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,1):raise ThemeError('SCHEMA_VERSION','Theme Matrix 版本不受支持。')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            if write:
                db.execute('CREATE TABLE IF NOT EXISTS theme_snapshots (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, input_hash TEXT NOT NULL, theme TEXT NOT NULL, trading_day TEXT NOT NULL, frame TEXT NOT NULL, machine_state TEXT NOT NULL, ai_state TEXT NOT NULL, revision_of TEXT UNIQUE, submitted_at TEXT NOT NULL, frozen_at TEXT NOT NULL, search_text TEXT NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL)')
                db.execute('CREATE INDEX IF NOT EXISTS theme_matrix_idx ON theme_snapshots(trading_day,frame,theme,submitted_at)');db.execute('PRAGMA user_version=1')
            yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    @staticmethod
    def decode(row):
        if row is None:raise ThemeError('NOT_FOUND','Theme Snapshot 不存在。')
        value=json.loads(row['payload']);indexed={'snapshot_id':'id','request_id':'request_id','input_hash':'input_hash','theme':'theme','trading_day':'trading_day','frame':'frame','machine_state':'machine_state','ai_state':'ai_state','revision_of':'revision_of','submitted_at':'submitted_at','frozen_at':'frozen_at'}
        if digest(value)!=row['checksum'] or any(value.get(k)!=row[c] for k,c in indexed.items()):raise ThemeError('CORRUPT_SNAPSHOT','Theme Snapshot 内容或索引校验失败。')
        return value

    def get(self,snapshot_id):
        identifier(snapshot_id,'snapshot_id ')
        with self.connection() as db:
            value=self.decode(db.execute('SELECT * FROM theme_snapshots WHERE id=?',(snapshot_id,)).fetchone());newer=db.execute('SELECT id FROM theme_snapshots WHERE revision_of=?',(snapshot_id,)).fetchone()
            return {**value,'superseded_by':newer['id'] if newer else None}

    def create(self,request_id,content):
        identifier(request_id,'request_id ')
        try:normalized=normalize_theme_snapshot(content)
        except ValueError as exc:raise ThemeError('INVALID_ARGUMENT',str(exc)) from None
        input_hash=digest(normalized);now=datetime.now(timezone.utc).isoformat()
        with self.connection(write=True) as db:
            row=db.execute('SELECT * FROM theme_snapshots WHERE request_id=?',(request_id,)).fetchone()
            if row is not None:
                value=self.decode(row)
                if value['input_hash']!=input_hash:raise ThemeError('CONFLICT','重复请求的 Theme Snapshot 内容发生变化。')
                return value
            if db.execute('SELECT COUNT(*) FROM theme_snapshots').fetchone()[0]>=100000:raise ThemeError('BUDGET_EXCEEDED','Theme Snapshot 已达十万条。')
            if normalized['revision_of']:
                identifier(normalized['revision_of'],'revision_of ');parent=self.decode(db.execute('SELECT * FROM theme_snapshots WHERE id=?',(normalized['revision_of'],)).fetchone())
                if any(parent[k]!=normalized[k] for k in ('theme','trading_day','frame')):raise ThemeError('INVALID_REVISION','修订只能替换同一主题、交易日和 Frame。')
                if db.execute('SELECT 1 FROM theme_snapshots WHERE revision_of=?',(parent['snapshot_id'],)).fetchone():raise ThemeError('STALE_REVISION','该 Theme Snapshot 已有后续修订。')
            value={**normalized,'snapshot_id':str(uuid4()),'request_id':request_id,'input_hash':input_hash,'submitted_at':now,'frozen_at':now}
            search=' '.join(str(value.get(k,'')) for k in ('theme','trading_day','frame','machine_state','ai_state','ai_thesis','risk_review','facts_source')).casefold()
            db.execute('INSERT INTO theme_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(value['snapshot_id'],request_id,input_hash,value['theme'],value['trading_day'],value['frame'],value['machine_state'],value['ai_state'],value['revision_of'],value['submitted_at'],value['frozen_at'],search,encode(value),digest(value)))
            return value

    def list(self,query='',theme='',start='',end='',frame='',include_superseded=False,offset=0,limit=500):
        if any(not isinstance(v,str) or len(v)>200 for v in (query,theme,start,end,frame)):raise ThemeError('INVALID_ARGUMENT','检索字段无效。')
        if frame and frame not in FRAMES:raise ThemeError('INVALID_ARGUMENT','未知 Decision Frame。')
        if type(include_superseded) is not bool or type(offset) is not int or not 0<=offset<=100000 or type(limit) is not int or not 1<=limit<=2000:raise ThemeError('INVALID_ARGUMENT','分页参数无效。')
        empty={'records':[],'total':0,'offset':offset,'next_offset':None}
        if self.path.is_symlink():raise ThemeError('INVALID_WORKSPACE','Theme Matrix 不能为符号链接。')
        if not self.path.exists():return empty
        clauses=['instr(t.search_text,?)>0'];values=[query.casefold()]
        for column,value in [('theme',theme),('frame',frame)]:
            if value:clauses.append('t.'+column+'=?');values.append(value)
        if start:clauses.append('t.trading_day>=?');values.append(start)
        if end:clauses.append('t.trading_day<=?');values.append(end)
        if not include_superseded:clauses.append('NOT EXISTS (SELECT 1 FROM theme_snapshots n WHERE n.revision_of=t.id)')
        where=' WHERE '+' AND '.join(clauses)
        with self.connection() as db:
            total=db.execute('SELECT COUNT(*) FROM theme_snapshots t'+where,values).fetchone()[0]
            rows=db.execute('SELECT t.* FROM theme_snapshots t'+where+' ORDER BY t.trading_day DESC,t.submitted_at DESC,t.id DESC LIMIT ? OFFSET ?',[*values,limit,offset])
            records=[self.decode(row) for row in rows]
        return {'records':records,'total':total,'offset':offset,'next_offset':offset+limit if offset+limit<total else None}

    def matrix(self,limit=2000):
        records=self.list(limit=limit)['records'];themes=sorted({r['theme'] for r in records})
        columns=sorted({(r['trading_day'],r['frame']) for r in records},reverse=True)
        lookup={(r['theme'],r['trading_day'],r['frame']):r for r in records}
        return {'themes':themes,'columns':columns,'lookup':lookup,'records':records,
            'states':list(THEME_STATES),'policy':'没有 Theme Snapshot 的格子保持 UNKNOWN，不从 Decision 标签自动推导主线强弱。'}

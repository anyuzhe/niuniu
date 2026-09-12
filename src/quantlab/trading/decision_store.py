"""Append-only, checksum-verified Decision Ledger."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
import json
import sqlite3

from quantlab.storage.codec import digest, encode
from .decision import ACTIONS, FRAMES, normalize_decision
from .frame_policy import FramePolicyStore, assess_submission

FRAME_ORDER_SQL="CASE d.frame WHEN 'PREP' THEN 0 WHEN 'AUCTION' THEN 1 WHEN 'R1' THEN 2 WHEN 'R2' THEN 3 WHEN 'R3' THEN 4 WHEN 'D1' THEN 5 WHEN 'D2' THEN 6 WHEN 'D3_PLUS' THEN 7 ELSE -1 END"


class DecisionError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def identifier(value, name='编号'):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise DecisionError('INVALID_ARGUMENT', f'{name}需要规范 UUID。') from None
    return value


class DecisionStore:
    def __init__(self, output, now_fn=None):
        self.output = Path(output).resolve()
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.directory = self.output / '_trading'
        self.path = self.directory / 'decision_ledger.sqlite3'

    @contextmanager
    def connection(self, write=False):
        paths = [self.directory, self.path, *[Path(str(self.path)+s) for s in ('-journal','-wal','-shm')]]
        if not self.output.is_dir() or any(path.is_symlink() for path in paths):
            raise DecisionError('INVALID_WORKSPACE','决策账本目录无效或包含符号链接。')
        if write:
            self.directory.mkdir(exist_ok=True)
        if not write and not self.path.exists():
            raise DecisionError('NOT_FOUND','当前工作空间尚无 Decision Ledger。')
        mode = '?mode=rwc' if write else '?mode=ro'
        db = sqlite3.connect(self.path.as_uri()+mode, uri=True, timeout=3, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,1):
                raise DecisionError('SCHEMA_VERSION','Decision Ledger 版本不受支持。')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            if write:
                db.execute('CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, input_hash TEXT NOT NULL, symbol TEXT NOT NULL, trading_day TEXT NOT NULL, frame TEXT NOT NULL, action TEXT NOT NULL, revision_of TEXT UNIQUE, submitted_at TEXT NOT NULL, frozen_at TEXT NOT NULL, search_text TEXT NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL)')
                db.execute('CREATE INDEX IF NOT EXISTS decision_timeline ON decisions(symbol,trading_day,frame,submitted_at)')
                db.execute('CREATE INDEX IF NOT EXISTS decision_action ON decisions(action,trading_day,submitted_at)')
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
            raise DecisionError('NOT_FOUND','Decision 不存在。')
        value = json.loads(row['payload'])
        indexed = {
            'decision_id':'id','request_id':'request_id','input_hash':'input_hash',
            'symbol':'symbol','trading_day':'trading_day','frame':'frame','action':'action',
            'revision_of':'revision_of','submitted_at':'submitted_at','frozen_at':'frozen_at',
        }
        if digest(value) != row['checksum'] or any(value.get(key) != row[column] for key,column in indexed.items()):
            raise DecisionError('CORRUPT_DECISION','Decision 内容或索引校验失败。')
        return value

    def get(self, decision_id):
        identifier(decision_id,'decision_id ')
        with self.connection() as db:
            value = self.decode(db.execute('SELECT * FROM decisions WHERE id=?',(decision_id,)).fetchone())
            newer = db.execute('SELECT id FROM decisions WHERE revision_of=?',(decision_id,)).fetchone()
            return {**value,'superseded_by':newer['id'] if newer else None}

    def request(self, request_id, input_hash):
        identifier(request_id,'request_id ')
        if self.path.is_symlink():
            raise DecisionError('INVALID_WORKSPACE','Decision Ledger 不能为符号链接。')
        if not self.path.exists():
            return None
        with self.connection() as db:
            if db.execute('PRAGMA user_version').fetchone()[0] == 0:
                return None
            row = db.execute('SELECT * FROM decisions WHERE request_id=?',(request_id,)).fetchone()
            if row is None:
                return None
            value = self.decode(row)
            if value['input_hash'] != input_hash:
                raise DecisionError('CONFLICT','同一请求编号不能保存不同 Decision。')
            return value

    def create(self, request_id, content):
        identifier(request_id,'request_id ')
        try:
            normalized = normalize_decision(content)
        except ValueError as exc:
            raise DecisionError('INVALID_ARGUMENT',str(exc)) from None
        input_hash = digest(normalized)
        now_dt = self.now_fn()
        if not isinstance(now_dt, datetime) or now_dt.tzinfo is None:
            raise DecisionError('INVALID_CLOCK','DecisionStore 时钟必须返回带时区时间。')
        now = now_dt.astimezone(timezone.utc).isoformat()
        with self.connection(write=True) as db:
            row = db.execute('SELECT * FROM decisions WHERE request_id=?',(request_id,)).fetchone()
            if row is not None:
                value = self.decode(row)
                if value['input_hash'] != input_hash:
                    raise DecisionError('CONFLICT','重复请求的 Decision 内容发生变化。')
                return value
            if db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0] >= 100000:
                raise DecisionError('BUDGET_EXCEEDED','当前工作空间 Decision 已达十万条；不会静默删除。')
            parent = None
            if normalized['revision_of']:
                identifier(normalized['revision_of'],'revision_of ')
                parent = self.decode(db.execute('SELECT * FROM decisions WHERE id=?',(normalized['revision_of'],)).fetchone())
                if any(parent[key] != normalized[key] for key in ('symbol','trading_day','frame')):
                    raise DecisionError('INVALID_REVISION','修订只能替换同一证券、交易日和 Frame 的 Decision。')
                if db.execute('SELECT 1 FROM decisions WHERE revision_of=?',(parent['decision_id'],)).fetchone():
                    raise DecisionError('STALE_REVISION','该 Decision 已有后续修订，请从最新版本继续。')
            reference = normalized.get('reference_decision_id')
            if normalized['frame'] in ('D1','D2','D3_PLUS') and not reference:
                raise DecisionError('MISSING_REFERENCE','D1/D2/D3+ 必须关联更早的原始 Decision。')
            if reference:
                identifier(reference,'reference_decision_id ')
                source = self.decode(db.execute('SELECT * FROM decisions WHERE id=?',(reference,)).fetchone())
                if source['symbol'] != normalized['symbol'] or source['trading_day'] >= normalized['trading_day']:
                    raise DecisionError('INVALID_REFERENCE','后续 Decision 只能关联同一证券、更早交易日的 Decision。')
                if source['frame'] not in ('PREP','AUCTION','R1','R2','R3'):
                    raise DecisionError('INVALID_REFERENCE','D1/D2/D3+ 只能关联更早交易日的原始盘前/盘中 Decision。')
            if normalized.get('effective_at'):
                effective = datetime.fromisoformat(normalized['effective_at'])
                if effective.astimezone(timezone.utc) > now_dt.astimezone(timezone.utc):
                    raise DecisionError('FUTURE_EFFECTIVE_AT','effective_at 不能晚于真实提交时间。')
            try:
                assessment=assess_submission(normalized['trading_day'],normalized['frame'],now_dt,FramePolicyStore(self.output).load())
            except (ValueError,OSError,json.JSONDecodeError) as exc:
                raise DecisionError('FRAME_POLICY_INVALID',str(exc)) from None
            value = {
                **normalized,**assessment,
                'decision_id':str(uuid4()),
                'request_id':request_id,
                'input_hash':input_hash,
                'submitted_at':now,
                'frozen_at':now,
            }
            search = ' '.join(str(value.get(key,'')) for key in (
                'symbol','trading_day','frame','action','theme','theme_role','machine_state','ai_thesis',
                'hold_reason','invalidation','exit_condition','agent_id','role_id','submission_status')).casefold()
            db.execute('INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(
                value['decision_id'],request_id,input_hash,value['symbol'],value['trading_day'],value['frame'],
                value['action'],value['revision_of'],value['submitted_at'],value['frozen_at'],search,encode(value),digest(value)))
            return value

    def list(self, query='', symbol='', trading_day='', frame='', action='', include_superseded=False, offset=0, limit=50):
        if any(not isinstance(value,str) or len(value)>200 for value in (query,symbol,trading_day,frame,action)):
            raise DecisionError('INVALID_ARGUMENT','检索字段必须为不超过 200 字的文本。')
        if frame and frame not in FRAMES:
            raise DecisionError('INVALID_ARGUMENT','未知 Decision Frame。')
        if action and action not in ACTIONS:
            raise DecisionError('INVALID_ARGUMENT','未知策略动作。')
        if type(include_superseded) is not bool or type(offset) is not int or not 0<=offset<=100000 or type(limit) is not int or not 1<=limit<=200:
            raise DecisionError('INVALID_ARGUMENT','分页或历史选项无效。')
        empty = {'records':[],'total':0,'offset':offset,'next_offset':None}
        if self.path.is_symlink():
            raise DecisionError('INVALID_WORKSPACE','Decision Ledger 不能为符号链接。')
        if not self.path.exists():
            return empty
        clauses = ['instr(d.search_text,?)>0']; values = [query.casefold()]
        for column,value in [('symbol',symbol.lower()),('trading_day',trading_day),('frame',frame),('action',action)]:
            if value:
                clauses.append('d.'+column+'=?'); values.append(value)
        if not include_superseded:
            clauses.append('NOT EXISTS (SELECT 1 FROM decisions n WHERE n.revision_of=d.id)')
        where = ' WHERE '+' AND '.join(clauses)
        with self.connection() as db:
            total = db.execute('SELECT COUNT(*) FROM decisions d'+where,values).fetchone()[0]
            rows = db.execute('SELECT d.* FROM decisions d'+where+' ORDER BY d.trading_day DESC,d.submitted_at DESC,d.id DESC LIMIT ? OFFSET ?',[*values,limit,offset])
            records = [self.decode(row) for row in rows]
        return {'records':records,'total':total,'offset':offset,'next_offset':offset+limit if offset+limit<total else None}

    def timeline(self, symbol, include_superseded=True, limit=500):
        return self.list(symbol=symbol,include_superseded=include_superseded,limit=min(limit,200))

    def current_timeline(self,symbol,limit=5000):
        symbol=symbol.lower()
        if self.path.is_symlink():raise DecisionError('INVALID_WORKSPACE','Decision Ledger 不能为符号链接。')
        if not self.path.exists():return []
        with self.connection() as db:
            rows=db.execute('SELECT d.* FROM decisions d WHERE d.symbol=? AND NOT EXISTS (SELECT 1 FROM decisions n WHERE n.revision_of=d.id) ORDER BY d.trading_day ASC,'+FRAME_ORDER_SQL+' ASC,d.submitted_at ASC,d.id ASC LIMIT ?', (symbol,limit))
            return [self.decode(row) for row in rows]

    def latest_current(self,symbol):
        rows=self.current_timeline(symbol)
        return rows[-1] if rows else None

    def latest_by_symbol(self, limit=200):
        if self.path.is_symlink():raise DecisionError('INVALID_WORKSPACE','Decision Ledger 不能为符号链接。')
        if not self.path.exists():return []
        with self.connection() as db:
            rows=db.execute('SELECT d.* FROM decisions d WHERE NOT EXISTS (SELECT 1 FROM decisions n WHERE n.revision_of=d.id) ORDER BY d.symbol ASC,d.trading_day DESC,'+FRAME_ORDER_SQL+' DESC,d.submitted_at DESC,d.id DESC')
            latest={}
            for row in rows:
                value=self.decode(row);latest.setdefault(value['symbol'],value)
                if len(latest)>=limit:break
        return sorted(latest.values(),key=lambda r:(r['trading_day'],r.get('frame',''),r['symbol']),reverse=True)

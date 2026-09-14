"""Immutable checksum-verified market snapshots for Trading Desk / Playbook scans."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
import json
import math
import re
import sqlite3

from quantlab.storage.codec import digest, encode
from .decision import FRAMES, SYMBOL
from .frame_policy import FramePolicyStore, assess_submission

SNAPSHOT_COMPLETENESS=('UNKNOWN','PARTIAL','FULL')
EXECUTION_PROFILES=('STANDARD_ACCESS','QUEUE_DEPENDENT','UNKNOWN')
HASH=re.compile(r'^[0-9a-f]{64}$')


class MarketSnapshotError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def _identifier(value,name='id'):
    try:
        if not isinstance(value,str) or str(UUID(value))!=value:raise ValueError()
    except (ValueError,TypeError,AttributeError):
        raise MarketSnapshotError('INVALID_ARGUMENT',name+' 必须是规范 UUID。') from None
    return value


def _text(value,name,maximum=4000,required=False):
    value='' if value is None else value
    if not isinstance(value,str):raise ValueError(name+' 必须是文本。')
    value=value.strip()
    if required and not value:raise ValueError(name+' 不能为空。')
    if len(value)>maximum:raise ValueError(name+f' 不能超过 {maximum} 字。')
    return value


def _moment(value,name):
    if not isinstance(value,str):raise ValueError(name+' 必须为 ISO 8601 时间。')
    try:parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:raise ValueError(name+' 必须为 ISO 8601 时间。') from None
    if parsed.tzinfo is None:raise ValueError(name+' 必须包含时区。')
    return parsed.isoformat()


def _day(value):
    if not isinstance(value,str):raise ValueError('trading_day 必须为 YYYY-MM-DD。')
    try:return date.fromisoformat(value).isoformat()
    except ValueError:raise ValueError('trading_day 必须为 YYYY-MM-DD。') from None


def _number(value,name,positive=False,nonnegative=False):
    if value is None:return None
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError(name+' 必须是有限数。')
    value=float(value)
    if positive and value<=0:raise ValueError(name+' 必须大于0。')
    if nonnegative and value<0:raise ValueError(name+' 不能小于0。')
    return value


def _json_object(value,name,maximum=32000):
    value={} if value is None else value
    if not isinstance(value,dict):raise ValueError(name+' 必须是 JSON 对象。')
    try:size=len(encode(value).encode('utf-8'))
    except (TypeError,ValueError):raise ValueError(name+' 必须是可序列化且不含非有限数的 JSON 对象。') from None
    if size>maximum:raise ValueError(name+f' 不能超过 {maximum} 字节。')
    return value


def _instrument(item):
    allowed={'symbol','name','previous_close','last','open','high','low','volume','amount',
        'auction_price','limit_up_price','limit_down_price','tradable','execution_profile','metrics'}
    if not isinstance(item,dict) or set(item)-allowed:raise ValueError('instrument 字段无效。')
    symbol=_text(item.get('symbol'),'symbol',16,True).lower()
    if not SYMBOL.fullmatch(symbol):raise ValueError('symbol 必须是 sh/sz/bj.XXXXXX。')
    tradable=item.get('tradable',True)
    if type(tradable) is not bool:raise ValueError('tradable 必须是布尔值。')
    profile=_text(item.get('execution_profile','UNKNOWN'),'execution_profile',40,True).upper()
    if profile not in EXECUTION_PROFILES:raise ValueError('execution_profile 取值无效。')
    result={'symbol':symbol,'name':_text(item.get('name'),'name',100),
        'tradable':tradable,'execution_profile':profile,'metrics':_json_object(item.get('metrics'),'metrics',16000)}
    for key in ('previous_close','last','open','high','low','auction_price','limit_up_price','limit_down_price'):
        result[key]=_number(item.get(key),key,positive=True)
    for key in ('volume','amount'):
        result[key]=_number(item.get(key),key,nonnegative=True)
    values=[result[k] for k in ('open','high','low','last')]
    if all(v is not None for v in values):
        o,h,l,c=values
        if h<max(o,l,c) or l>min(o,h,c):raise ValueError('OHLC 价格关系无效。')
    return result


def normalize_market_snapshot(content):
    allowed={'trading_day','frame','as_of','provider','provider_ref','source_hash','completeness',
        'instruments','market_metrics','notes'}
    if not isinstance(content,dict) or set(content)-allowed:raise ValueError('MarketSnapshot 字段无效。')
    frame=_text(content.get('frame'),'frame',20,True).upper()
    if frame not in FRAMES:raise ValueError('未知 Decision Frame。')
    completeness=_text(content.get('completeness','UNKNOWN'),'completeness',20,True).upper()
    if completeness not in SNAPSHOT_COMPLETENESS:raise ValueError('completeness 取值无效。')
    raw=content.get('instruments') or []
    if not isinstance(raw,list) or len(raw)>5000:raise ValueError('instruments 必须是不超过5000项的数组。')
    instruments=[_instrument(item) for item in raw]
    symbols=[item['symbol'] for item in instruments]
    if len(symbols)!=len(set(symbols)):raise ValueError('MarketSnapshot 不能包含重复证券。')
    source_hash=_text(content.get('source_hash'),'source_hash',64).lower()
    if source_hash and not HASH.fullmatch(source_hash):raise ValueError('source_hash 必须是64位小写SHA256。')
    provider_ref=_text(content.get('provider_ref'),'provider_ref',2000)
    if completeness=='FULL' and (not source_hash or not provider_ref):
        raise ValueError('FULL MarketSnapshot 必须保存 provider_ref 与 source_hash。')
    result={'trading_day':_day(content.get('trading_day')),'frame':frame,
        'as_of':_moment(content.get('as_of'),'as_of'),'provider':_text(content.get('provider'),'provider',100,True),
        'provider_ref':provider_ref,'source_hash':source_hash,'completeness':completeness,
        'instruments':instruments,'market_metrics':_json_object(content.get('market_metrics'),'market_metrics'),
        'notes':_text(content.get('notes'),'notes',6000)}
    if completeness=='FULL':_validate_frame_payload(result)
    return result


def _validate_frame_payload(value):
    frame=value['frame'];items=value['instruments']
    if frame in ('AUCTION','R1','R2','R3') and not items:
        raise ValueError(frame+' FULL MarketSnapshot 至少需要一个证券。')
    if frame=='AUCTION':
        for item in items:
            if item['previous_close'] is None or item['auction_price'] is None:
                raise ValueError('AUCTION FULL MarketSnapshot 每只证券需要 previous_close 与 auction_price。')
    if frame in ('R1','R2','R3'):
        required=('previous_close','open','high','low','last','volume','amount')
        for item in items:
            if any(item[key] is None for key in required):
                raise ValueError(frame+' FULL MarketSnapshot 缺少完整 OHLC/量额。')


def _capture_status(output,value,now):
    as_of=datetime.fromisoformat(value['as_of']).astimezone(timezone.utc)
    now_utc=now.astimezone(timezone.utc)
    if as_of>now_utc:raise MarketSnapshotError('FUTURE_SNAPSHOT','MarketSnapshot as_of 不能晚于真实捕获时间。')
    lag=(now_utc-as_of).total_seconds()
    try:assessment=assess_submission(value['trading_day'],value['frame'],as_of,
        FramePolicyStore(output).load())
    except (ValueError,OSError,json.JSONDecodeError) as exc:
        raise MarketSnapshotError('FRAME_POLICY_INVALID',str(exc)) from None
    live=lag<=600 and assessment['submission_status']=='ON_TIME'
    return ('LIVE_NEAR_REALTIME' if live else 'BACKFILL',lag,assessment)


class MarketSnapshotStore:
    def __init__(self,output,now_fn=None):
        self.output=Path(output).resolve();self.now_fn=now_fn or (lambda:datetime.now(timezone.utc))
        self.directory=self.output/'_trading';self.path=self.directory/'market_snapshots.sqlite3'

    @contextmanager
    def connection(self,write=False):
        paths=[self.directory,self.path,*[Path(str(self.path)+s) for s in ('-journal','-wal','-shm')]]
        if not self.output.is_dir() or any(path.is_symlink() for path in paths):
            raise MarketSnapshotError('INVALID_WORKSPACE','MarketSnapshot 目录无效或包含符号链接。')
        if write:self.directory.mkdir(exist_ok=True)
        if not write and not self.path.exists():raise MarketSnapshotError('NOT_FOUND','当前工作空间尚无 MarketSnapshot。')
        db=sqlite3.connect(self.path.as_uri()+('?mode=rwc' if write else '?mode=ro'),uri=True,timeout=3,isolation_level=None)
        db.row_factory=sqlite3.Row
        try:
            version=db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,1):raise MarketSnapshotError('SCHEMA_VERSION','MarketSnapshot 版本不受支持。')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            if write:
                db.execute('CREATE TABLE IF NOT EXISTS market_snapshots (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, input_hash TEXT NOT NULL, trading_day TEXT NOT NULL, frame TEXT NOT NULL, as_of TEXT NOT NULL, provider TEXT NOT NULL, completeness TEXT NOT NULL, capture_status TEXT NOT NULL, frozen_at TEXT NOT NULL, search_text TEXT NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL)')
                db.execute('CREATE INDEX IF NOT EXISTS market_snapshot_idx ON market_snapshots(trading_day,frame,as_of,provider)')
                db.execute('PRAGMA user_version=1')
            yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    @staticmethod
    def decode(row):
        if row is None:raise MarketSnapshotError('NOT_FOUND','MarketSnapshot 不存在。')
        value=json.loads(row['payload'])
        indexed={'snapshot_id':'id','request_id':'request_id','input_hash':'input_hash','trading_day':'trading_day',
            'frame':'frame','as_of':'as_of','provider':'provider','completeness':'completeness',
            'capture_status':'capture_status','frozen_at':'frozen_at'}
        if digest(value)!=row['checksum'] or any(value.get(k)!=row[c] for k,c in indexed.items()):
            raise MarketSnapshotError('CORRUPT_SNAPSHOT','MarketSnapshot 内容或索引校验失败。')
        return value

    def get(self,snapshot_id):
        _identifier(snapshot_id,'snapshot_id')
        with self.connection() as db:
            return self.decode(db.execute('SELECT * FROM market_snapshots WHERE id=?',(snapshot_id,)).fetchone())

    def create(self,request_id,content):
        _identifier(request_id,'request_id')
        try:normalized=normalize_market_snapshot(content)
        except ValueError as exc:raise MarketSnapshotError('INVALID_ARGUMENT',str(exc)) from None
        input_hash=digest(normalized);now=self.now_fn()
        if not isinstance(now,datetime) or now.tzinfo is None:raise MarketSnapshotError('INVALID_CLOCK','MarketSnapshotStore 时钟必须带时区。')
        capture_status,lag,assessment=_capture_status(self.output,normalized,now)
        frozen_at=now.astimezone(timezone.utc).isoformat()
        strict=bool(normalized['completeness']=='FULL' and capture_status=='LIVE_NEAR_REALTIME')
        with self.connection(write=True) as db:
            row=db.execute('SELECT * FROM market_snapshots WHERE request_id=?',(request_id,)).fetchone()
            if row is not None:
                value=self.decode(row)
                if value['input_hash']!=input_hash:raise MarketSnapshotError('CONFLICT','重复 request_id 的 MarketSnapshot 内容变化。')
                return value
            if db.execute('SELECT COUNT(*) FROM market_snapshots').fetchone()[0]>=200000:
                raise MarketSnapshotError('BUDGET_EXCEEDED','MarketSnapshot 已达二十万条；不会静默删除。')
            value={**normalized,'snapshot_id':str(uuid4()),'request_id':request_id,'input_hash':input_hash,
                'capture_status':capture_status,'capture_lag_seconds':lag,'frame_assessment':assessment,
                'strict_pit_eligible':strict,'frozen_at':frozen_at}
            search=' '.join([value['trading_day'],value['frame'],value['provider'],
                *[item['symbol'] for item in value['instruments']]]).casefold()
            db.execute('INSERT INTO market_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(
                value['snapshot_id'],request_id,input_hash,value['trading_day'],value['frame'],value['as_of'],
                value['provider'],value['completeness'],value['capture_status'],value['frozen_at'],search,
                encode(value),digest(value)))
            return value

    def list(self,trading_day='',frame='',symbol='',provider='',offset=0,limit=500):
        if any(not isinstance(v,str) or len(v)>200 for v in (trading_day,frame,symbol,provider)):
            raise MarketSnapshotError('INVALID_ARGUMENT','检索参数无效。')
        if frame and frame not in FRAMES:raise MarketSnapshotError('INVALID_ARGUMENT','未知 Decision Frame。')
        if type(offset) is not int or not 0<=offset<=200000 or type(limit) is not int or not 1<=limit<=2000:
            raise MarketSnapshotError('INVALID_ARGUMENT','分页参数无效。')
        empty={'records':[],'total':0,'offset':offset,'next_offset':None}
        if self.path.is_symlink():raise MarketSnapshotError('INVALID_WORKSPACE','MarketSnapshot 数据库不能为符号链接。')
        if not self.path.exists():return empty
        clauses=['instr(search_text,?)>0'];values=[symbol.lower()]
        for column,value in (('trading_day',trading_day),('frame',frame),('provider',provider)):
            if value:clauses.append(column+'=?');values.append(value)
        where=' WHERE '+' AND '.join(clauses)
        with self.connection() as db:
            total=db.execute('SELECT COUNT(*) FROM market_snapshots'+where,values).fetchone()[0]
            rows=db.execute('SELECT * FROM market_snapshots'+where+' ORDER BY as_of DESC,id DESC LIMIT ? OFFSET ?',
                [*values,limit,offset])
            records=[self.decode(row) for row in rows]
        return {'records':records,'total':total,'offset':offset,
            'next_offset':offset+limit if offset+limit<total else None}

    def latest(self,trading_day,frame):
        rows=self.list(trading_day=trading_day,frame=frame,limit=1)['records']
        return rows[0] if rows else None

    def overview(self):
        if not self.path.exists():return {'snapshots':0,'live_near_realtime':0,'full':0,'strict_pit_eligible':0}
        with self.connection() as db:
            snapshots=db.execute('SELECT COUNT(*) FROM market_snapshots').fetchone()[0]
            live=db.execute("SELECT COUNT(*) FROM market_snapshots WHERE capture_status='LIVE_NEAR_REALTIME'").fetchone()[0]
            full=db.execute("SELECT COUNT(*) FROM market_snapshots WHERE completeness='FULL'").fetchone()[0]
            rows=db.execute('SELECT payload FROM market_snapshots')
            strict=sum(bool(json.loads(row['payload']).get('strict_pit_eligible')) for row in rows)
        return {'snapshots':snapshots,'live_near_realtime':live,'full':full,'strict_pit_eligible':strict}


__all__=['SNAPSHOT_COMPLETENESS','EXECUTION_PROFILES','MarketSnapshotError','MarketSnapshotStore',
    'normalize_market_snapshot']

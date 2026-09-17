"""Personal-research TDX lake: immutable source pages, Parquet and the existing DuckDB catalog.

Network acquisition is a separate opt-in CLI. This module never imports eltdx.
Empty, failed, partial and unfinished jobs are distinct; no PIT or execution upgrade.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import date,datetime,timezone
from pathlib import Path
import dataclasses,gzip,hashlib,json,math,os,re,shutil,sqlite3
from uuid import uuid4
import duckdb
import polars as pl

FAMILIES=('securities','bars_1m','bars_5m','bars_daily','trades','opening_match','auction','quotes','depth','finance','capital_changes','topics','limit_ladder')
READ_COLUMNS={'date':pl.Date,'code':pl.String,'event_time':pl.String,'observed_at':pl.String,
    'open':pl.Float64,'high':pl.Float64,'low':pl.Float64,'close':pl.Float64,
    'price':pl.Float64,'volume':pl.Float64,'volume_unit':pl.String,'amount':pl.Float64,
    'record_json':pl.String,'source_id':pl.String,'record_index':pl.Int64,'plan_id':pl.String,
    'qualification':pl.String}
QUALIFICATION='vendor_observation_personal_research_not_pit'

def now():return datetime.now(timezone.utc).isoformat()
def clean(value):
    if dataclasses.is_dataclass(value):return clean(dataclasses.asdict(value))
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    if isinstance(value,bytes):return {'hex':value.hex(),'bytes':len(value)}
    if isinstance(value,(datetime,date)):return value.isoformat()
    if isinstance(value,float) and not math.isfinite(value):raise ValueError('Nonfinite provider value; original response must be inspected')
    return value

def encode(value):return json.dumps(clean(value),ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(data):return hashlib.sha256(data).hexdigest()
def digest(value):return sha(encode(value).encode())

def safe(root,path):
    root=Path(root).resolve();path=Path(path)
    if not path.is_relative_to(root):raise ValueError('TDX path outside configured root')
    current=path
    while current!=root:
        if current.is_symlink():raise ValueError('TDX symlink rejected')
        current=current.parent
    if not path.resolve().is_relative_to(root):raise ValueError('TDX escaped root')
    return path

def write_json(path,value):
    temporary=path.with_name('.'+path.name+'.'+str(uuid4())+'.tmp')
    temporary.write_text(encode(value),encoding='utf-8');os.replace(temporary,path)

def _num(value):return float(value) if type(value) in (int,float) and math.isfinite(value) else None

def rows_for(family,result):
    if result is None:return []
    if family in ('securities','quotes'):return result if isinstance(result,list) else result.get('records',[])
    key={'bars_1m':'bars','bars_5m':'bars','bars_daily':'bars','trades':'ticks','auction':'points',
         'finance':'records','capital_changes':'records','depth':'records','limit_ladder':'rows'}.get(family)
    if key:
        if not isinstance(result,dict) or key not in result:raise ValueError('Missing response data key: '+key)
        return result[key]
    if family=='opening_match':return result if isinstance(result,list) else [result]
    if family=='topics':
        if not isinstance(result,dict) or 'result_sets' not in result:raise ValueError('Missing topics result_sets')
        return [row for rs in result['result_sets'] for row in rs.get('rows',[])]
    raise ValueError('Unknown family')

def frame_for(family,rows,job,observed,source_id):
    flat=[]
    for index,row in enumerate(rows):
        code=job.get('symbol','')
        if family in ('securities','limit_ladder'):
            exchange=row.get('exchange') or row.get('market') or {0:'sz',1:'sh',2:'bj'}.get(row.get('market_id'))
            if exchange and row.get('code'):code=exchange+'.'+row['code']
        event=row.get('time') or row.get('trade_datetime') or row.get('time_label') or row.get('date')
        day_text=(str(event)[:10] if event and re.match(r'^\d{4}-\d{2}-\d{2}',str(event)) else job.get('day'))
        if family=='limit_ladder' and row.get('trading_date_value'):
            value=str(row['trading_date_value']);day_text=value[:4]+'-'+value[4:6]+'-'+value[6:8]
        if family in ('securities','quotes','depth','finance','topics'):
            from zoneinfo import ZoneInfo
            day_text=datetime.fromisoformat(observed).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
        day=date.fromisoformat(day_text) if day_text else None
        volume=_num(row.get('volume'));unit='provider_unspecified'
        if family.startswith('bars_'):
            volume=_num(row.get('volume_wire_value'));unit='shares_wire_value'
        elif family in ('trades','opening_match'):
            unit='lots_provider';volume=_num(row.get('volume'))
        elif family=='auction':
            volume=_num(row.get('matched_volume'));unit='auction_matched_provider_units_unverified'
        flat.append({'date':day,'code':code,'event_time':str(event) if event else None,'observed_at':observed,
            **{k:_num(row.get(k)) for k in ('open','high','low','close')},
            'price':_num(row.get('price',row.get('last_price'))),'volume':volume,'volume_unit':unit,
            'amount':_num(row.get('amount')),'record_json':encode(row),'source_id':source_id,
            'record_index':index,'plan_id':job['plan_id'],'qualification':QUALIFICATION})
    return pl.DataFrame(flat,schema=READ_COLUMNS) if flat else pl.DataFrame(schema=READ_COLUMNS)

class TdxLake:
    def __init__(self,data_root,*,create=False):
        supplied=Path(data_root)
        if supplied.is_symlink() or not supplied.is_dir():raise ValueError('TDX data root must be existing, non-symlink directory')
        self.root=supplied.resolve();self.base=safe(self.root,self.root/'lake/bronze/provider=tdx')
        self.catalog=safe(self.root,self.root/'catalog/mqc.duckdb')
        self.queue=safe(self.root,self.root/'catalog/tdx_ingestion.sqlite3')
        if create:self.initialize()
    @contextmanager
    def db(self,*,readonly=False):
        con=sqlite3.connect(('file:'+str(self.queue)+'?mode=ro') if readonly else str(self.queue),uri=readonly,timeout=30)
        con.row_factory=sqlite3.Row
        try:yield con
        finally:con.close()
    def initialize(self):
        self.base.mkdir(parents=True,exist_ok=True);self.queue.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as con:
            con.execute('PRAGMA journal_mode=WAL');con.execute('PRAGMA busy_timeout=30000')
            con.executescript("""
            CREATE TABLE IF NOT EXISTS plans(plan_id TEXT PRIMARY KEY, body TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, family TEXT NOT NULL,
              symbol TEXT NOT NULL, day TEXT NOT NULL, offset INTEGER NOT NULL, priority INTEGER NOT NULL,
              state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, rows INTEGER NOT NULL DEFAULT 0,
              chunk TEXT, error TEXT, updated_at TEXT NOT NULL, UNIQUE(plan_id,family,symbol,day,offset));
            CREATE INDEX IF NOT EXISTS job_pending ON jobs(plan_id,state,priority);
            CREATE TABLE IF NOT EXISTS publications(source_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,family TEXT NOT NULL,
              symbol TEXT NOT NULL,day TEXT NOT NULL,rows INTEGER NOT NULL,chunk TEXT NOT NULL,observed_at TEXT NOT NULL);
            """)
            con.commit()
        for family in FAMILIES:
            folder=safe(self.root,self.base/family);folder.mkdir(exist_ok=True)
            schemafile=folder/'schema.parquet'
            if not schemafile.exists():pl.DataFrame(schema=READ_COLUMNS).write_parquet(schemafile)
        # Add only namespaced views. Never replace old daily/5m tables or views.
        with duckdb.connect(str(self.catalog)) as con:
            con.execute('BEGIN TRANSACTION')
            for family in FAMILIES:
                pattern=str(self.base/family/'**/*.parquet').replace("'","''")
                name='tdx_'+family
                existing=con.execute('SELECT view_name,sql FROM duckdb_views() WHERE view_name=?',[name]).fetchall()
                if existing and 'provider=tdx' not in existing[0][1]:raise ValueError('Existing unrelated TDX view name; refusing overwrite')
                projection="* REPLACE ((timezone('Asia/Shanghai',observed_at::TIMESTAMPTZ))::DATE AS date)" if family in ('securities','quotes','depth','finance','topics') else '*'
                con.execute('CREATE OR REPLACE VIEW '+name+" AS SELECT "+projection+" FROM read_parquet('"+pattern+"',union_by_name=true,hive_partitioning=false)")
            con.execute('COMMIT')
    def add_plan(self,body):
        pid=digest(body)
        with self.db() as con:
            con.execute('INSERT OR IGNORE INTO plans VALUES (?,?,?)',(pid,encode(body),now()));con.commit()
        return pid
    def plan(self,pid):
        with self.db(readonly=True) as con:row=con.execute('SELECT body FROM plans WHERE plan_id=?',(pid,)).fetchone()
        if row is None:raise ValueError('Plan not found')
        return json.loads(row[0])
    def enqueue(self,pid,family,symbol='',day='',offset=0,priority=0,con=None):
        if family not in FAMILIES or symbol and not re.fullmatch(r'(?:sh|sz|bj)\.\d{6}',symbol):raise ValueError('Invalid job identity')
        if day:date.fromisoformat(day)
        if type(offset) is not int or not 0<=offset<=1_000_000:raise ValueError('Offset out of budget')
        jid=digest([pid,family,symbol,day,offset])
        values=(jid,pid,family,symbol,day,offset,priority,'PENDING',now())
        sql='INSERT OR IGNORE INTO jobs(job_id,plan_id,family,symbol,day,offset,priority,state,updated_at) VALUES (?,?,?,?,?,?,?,?,?)'
        if con is not None:con.execute(sql,values)
        else:
            with self.db() as db:db.execute(sql,values);db.commit()
        return jid
    def next_jobs(self,pid,count=1):
        with self.db() as con:
            con.execute('BEGIN IMMEDIATE')
            rows=con.execute("SELECT * FROM jobs WHERE plan_id=? AND state='PENDING' ORDER BY priority,rowid LIMIT ?",(pid,count)).fetchall()
            for r in rows:con.execute("UPDATE jobs SET state='RUNNING',attempts=attempts+1,updated_at=? WHERE job_id=?",(now(),r['job_id']))
            con.commit();return [dict(r) for r in rows]
    def recover(self,pid,retry_errors=False):
        with self.db() as con:
            states="('RUNNING','STORED','ERROR')" if retry_errors else "('RUNNING','STORED')"
            con.execute("UPDATE jobs SET state='PENDING' WHERE plan_id=? AND state IN "+states+" AND attempts<3",(pid,));con.commit()
    def mark(self,job,state,*,rows=0,chunk=None,error=None):
        with self.db() as con:
            con.execute('UPDATE jobs SET state=?,rows=?,chunk=?,error=?,updated_at=? WHERE job_id=?',
                        (state,rows,chunk,error,now(),job['job_id']));con.commit()
    def save_page(self,job,result,*,observed_at=None,origin='live_network',finalize=True):
        observed=observed_at or now();result=clean(result);family=job['family']
        if family not in FAMILIES:raise ValueError('Unknown family')
        if isinstance(result,dict) and result.get('error_code') not in (None,0,'0'):raise ValueError('Vendor error_code='+str(result['error_code']))
        if result is None:raise ValueError('Provider returned None; not proof of no data')
        rows=rows_for(family,result)
        if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):raise ValueError('Unexpected response schema')
        if family in ('bars_1m','bars_5m','bars_daily','trades','auction','finance','capital_changes') and isinstance(result,dict):
            identity=result.get('exchange','')+'.'+result.get('code','')
            if result.get('code') and identity!=job['symbol']:raise ValueError('Wrong response security')
            actual=result.get('trading_date')
            if actual and job['day'] and actual!=job['day']:raise ValueError('Wrong response trading day')
        sid=digest({'job':job['job_id'],'body':result})
        destination=safe(self.root,self.base/family/'pages'/sid)
        if destination.exists():
            manifest=self.verify_page(family,sid)
        else:
            if shutil.disk_usage(self.root).free<30*1024**3:raise ValueError('DISK_RESERVE: less than 30GiB free')
            staging=safe(self.root,self.base/'_staging'/sid);staging.parent.mkdir(exist_ok=True)
            if staging.exists():shutil.rmtree(staging)
            staging.mkdir()
            body={'request':{k:job[k] for k in ('job_id','plan_id','family','symbol','day','offset')},
                  'observed_at':observed,'origin':origin,'parser':'eltdx==3.2.2','result':result}
            raw=gzip.compress(encode(body).encode(),mtime=0);(staging/'response.json.gz').write_bytes(raw)
            frame=frame_for(family,rows,job,observed,sid);frame.write_parquet(staging/'data.parquet',compression='zstd')
            manifest={'source_id':sid,'plan_id':job['plan_id'],'family':family,'symbol':job['symbol'],'day':job['day'],
                'offset':job['offset'],'rows':len(rows),'observed_at':observed,'origin':origin,
                'raw_sha256':sha(raw),'parquet_sha256':sha((staging/'data.parquet').read_bytes()),
                'qualification':QUALIFICATION,'complete_history':False,'empty_means':'this_exact_request_only',
                'license':'ELTDX Research-Only; personal noncommercial research only; not for order execution/production service'}
            (staging/'manifest.json').write_text(encode({**manifest,'checksum':digest(manifest)}))
            destination.parent.mkdir(parents=True,exist_ok=True);staging.rename(destination)
        with self.db() as con:
            con.execute('INSERT OR IGNORE INTO publications VALUES (?,?,?,?,?,?,?,?)',
                        (sid,job['plan_id'],family,job['symbol'],job['day'],manifest['rows'],str(destination.relative_to(self.root)),manifest['observed_at']))
            con.commit()
        self.mark(job,('SAVED' if rows else 'EMPTY') if finalize else 'STORED',rows=len(rows),chunk=str(destination.relative_to(self.root)))
        return manifest,rows
    def verify_page(self,family,sid):
        if family not in FAMILIES or not re.fullmatch('[a-f0-9]{64}',sid):raise ValueError('Invalid page')
        folder=safe(self.root,self.base/family/'pages'/sid)
        value=json.loads(safe(self.root,folder/'manifest.json').read_text());core={k:v for k,v in value.items() if k!='checksum'}
        if digest(core)!=value['checksum'] or core['source_id']!=sid:raise ValueError('Page manifest changed')
        for filename,key in (('response.json.gz','raw_sha256'),('data.parquet','parquet_sha256')):
            if sha(safe(self.root,folder/filename).read_bytes())!=core[key]:raise ValueError('Page bytes changed: '+filename)
        return core
    def status(self):
        if not self.queue.exists():return {'configured':False,'families':[]}
        with self.db(readonly=True) as con:
            jobs=[dict(r) for r in con.execute('SELECT plan_id,family,state,count(*) tasks,sum(rows) rows FROM jobs GROUP BY plan_id,family,state')]
            stored=[dict(r) for r in con.execute('SELECT family,count(*) pages,count(DISTINCT CASE WHEN length(symbol)>0 THEN symbol END) requested_securities,sum(rows) rows,min(day) first_requested_day,max(day) last_requested_day FROM publications GROUP BY family')]
            plans=[{'plan_id':r['plan_id'],**json.loads(r['body'])} for r in con.execute('SELECT * FROM plans ORDER BY created_at')]
        return {'configured':True,'catalog':'catalog/mqc.duckdb','tables':['tdx_'+f for f in FAMILIES],
            'families':stored,'jobs':jobs,'plans':plans,'history_complete':False,'qualification':QUALIFICATION,
            'limitations':['Snapshot families are observation-time versions, not historical daily snapshots.','SAVED page is not a complete history; inspect pending/deferred jobs and exact requested range.','No PIT, official MarketRules, order-queue or financial restatement certification.']}
    def read(self,family,symbol='',start='',end='',offset=0,limit=20):
        if family not in FAMILIES or type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:raise ValueError('Invalid read bounds')
        if symbol and not re.fullmatch(r'(sh|sz|bj)\.\d{6}',symbol):raise ValueError('Invalid symbol')
        for day in (start,end):
            if day:date.fromisoformat(day)
        terms=[];args=[]
        for expr,val in [('code = ?',symbol),('date >= ?::DATE',start),('date <= ?::DATE',end)]:
            if val:terms.append(expr);args.append(val)
        where=' WHERE '+' AND '.join(terms) if terms else ''
        with duckdb.connect(str(self.catalog),read_only=True) as con:
            rows=con.execute('SELECT * FROM tdx_'+family+where+' ORDER BY date,code,source_id,record_index LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
            columns=[d[0] for d in con.description]
        return {'family':family,'rows':[dict(zip(columns,r)) for r in rows],'offset':offset,'limit':limit,
                'qualification':QUALIFICATION,'more_may_exist':len(rows)==limit}

"""Explicit one-time personal-research acquisition into niuniu-data; resumable, no trading.

Use the previously verified isolated eltdx==3.2.2 environment. Never install it as
an application default or turn collection into a commercial/production service.
"""
from __future__ import annotations
import argparse,bisect,concurrent.futures,contextlib,hashlib,importlib.metadata,json,os,re,shutil,sys,threading,time
from datetime import date,datetime,timezone
from pathlib import Path
from uuid import uuid4
import polars as pl
from quantlab.data.tdx_lake import TdxLake,FAMILIES,clean,encode,digest,now,safe,write_json

HOSTS=('116.205.183.150:7709','116.205.171.132:7709')
DEDICATED=('180.153.18.170:7709','58.34.106.207:7709')
PER_SYMBOL=('finance','capital_changes','topics','quotes','depth','auction','trades','bars_1m','bars_5m','bars_daily')
RETRYABLE_ERROR_MARKERS=(
    'connectionclosederror','connectionerror','connection closed','tcp stream closed','connection reset','broken pipe','timed out','timeout',
    'temporarily unavailable','http error 502','http error 503','http error 504','network is unreachable','no route to host')
ACCESS_LIMIT_MARKERS=('429','rate limit','forbidden','denied')
AUTO_HALT='AUTO_HALT.json'
SCHEDULER_POLICY='scheduler-policy.json'
POLICY_FORMAT='tdx-scheduler-policy-v2'

def retryable_error(message):
    text=str(message).casefold()
    return any(marker in text for marker in RETRYABLE_ERROR_MARKERS)

def access_limit_error(message):
    text=str(message).casefold()
    return any(marker in text for marker in ACCESS_LIMIT_MARKERS)

def _sha_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    return h.hexdigest()

def _policy_path(lake):return safe(lake.root,lake.base/SCHEDULER_POLICY)

def load_scheduler_policy(lake,pid):
    path=_policy_path(lake)
    if not path.exists():return {'format':POLICY_FORMAT,'plan_id':pid,'policy_id':None,'lifecycle_bounds':{},'family_market_history_floors':{},'request_interval_seconds':None}
    if path.is_symlink() or not path.is_file() or path.stat().st_size>2_000_000:raise ValueError('Invalid TDX scheduler policy file')
    value=json.loads(path.read_text(encoding='utf-8'))
    return validate_scheduler_policy(value,pid)

def validate_scheduler_policy(value,pid):
    if not isinstance(value,dict):raise ValueError('TDX scheduler policy schema invalid')
    core={k:v for k,v in value.items() if k!='policy_id'}
    if value.get('format')!=POLICY_FORMAT or value.get('plan_id')!=pid or value.get('policy_id')!=digest(core):
        raise ValueError('TDX scheduler policy identity/checksum mismatch')
    bounds=value.get('lifecycle_bounds');floors=value.get('family_market_history_floors')
    if not isinstance(bounds,dict) or not isinstance(floors,dict):raise ValueError('TDX scheduler policy schema invalid')
    for symbol,row in bounds.items():
        if not re.fullmatch(r'(sh|sz|bj)\.\d{6}',symbol) or not isinstance(row,dict) or not isinstance(row.get('listed'),str):raise ValueError('TDX scheduler lifecycle row invalid')
        if date.fromisoformat(row['listed']).isoformat()!=row['listed']:raise ValueError('Noncanonical listing date')
        if row.get('delisted'):
            if date.fromisoformat(row['delisted']).isoformat()!=row['delisted'] or row['delisted']<row['listed']:raise ValueError('Invalid delisting date')
    for family,markets in floors.items():
        if family not in ('auction',) or not isinstance(markets,dict):raise ValueError('Unsupported scheduler history floor')
        for market,day in markets.items():
            if market not in ('sh','sz') or not isinstance(day,str):raise ValueError('Unsupported scheduler market history floor; v2 has no verified BSE floor')
            if date.fromisoformat(day).isoformat()!=day:raise ValueError('Noncanonical retention date')
    interval=value.get('request_interval_seconds')
    if interval is not None and (type(interval) not in (int,float) or not .1<=interval<=2):raise ValueError('Invalid scheduler request interval')
    return value

def _verify_auction_retention_evidence(directory,trading_days):
    root=Path(directory).resolve()
    if root.is_symlink() or not root.is_dir():raise ValueError('Retention evidence directory invalid')
    boundary_path=root/'auction-boundary.json';cross_path=root/'auction-host-crosscheck.json'
    if any(p.is_symlink() or not p.is_file() or p.stat().st_size>2_000_000 for p in (boundary_path,cross_path)):
        raise ValueError('Retention evidence files missing or invalid')
    boundary=json.loads(boundary_path.read_text());cross=json.loads(cross_path.read_text())
    records=boundary.get('records');symbols=boundary.get('symbols')
    if not isinstance(records,list) or not isinstance(symbols,list) or len(set(symbols))<4:raise ValueError('Auction boundary evidence too small')
    if not {'sh','sz'}<=set(s[:2] for s in symbols) or any(s.startswith('bj') for s in symbols):
        raise ValueError('Auction boundary anchors must cover Shanghai and Shenzhen only')
    dates=sorted(set(str(r.get('day')) for r in records))
    def state(day):
        rows=[r for r in records if r.get('day')==day]
        if len(rows)!=len(set(symbols)) or {r.get('symbol') for r in rows}!=set(symbols) or any(r.get('error') is not None for r in rows):return None
        values=[r.get('rows') for r in rows]
        if all(type(v) is int and v>0 for v in values):return 'NONEMPTY'
        if all(v==0 for v in values):return 'EMPTY'
        return None
    states={d:state(d) for d in dates}
    candidates=[d for d in dates if states[d]=='NONEMPTY' and all(states[x]=='NONEMPTY' for x in dates if x>=d) and all(states[x]=='EMPTY' for x in dates if x<d)]
    if not candidates:raise ValueError('Auction retention evidence has no clean empty/nonempty boundary')
    floor=min(candidates);days=list(trading_days);idx=bisect.bisect_left(days,floor)
    if idx<=0 or idx>=len(days) or days[idx]!=floor:raise ValueError('Auction floor is not in plan calendar')
    previous=days[idx-1]
    cross_records=cross.get('records')
    if not isinstance(cross_records,list):raise ValueError('Auction host crosscheck missing records')
    hosts=sorted(set(r.get('dedicated_host') for r in cross_records));cross_symbols=sorted(set(r.get('symbol') for r in cross_records))
    shsz=[s for s in cross_symbols if s[:2] in ('sh','sz')];bj=[s for s in cross_symbols if s.startswith('bj')]
    if len(hosts)<2 or not set(hosts)<=set(DEDICATED) or len(shsz)<4 or len(bj)<2:raise ValueError('Auction cross-market host check too small')
    for host in hosts:
        for day,want_nonempty in ((previous,False),(floor,True)):
            rows=[r for r in cross_records if r.get('dedicated_host')==host and r.get('day')==day and r.get('symbol') in shsz]
            if len(rows)!=len(shsz) or {r.get('symbol') for r in rows}!=set(shsz) or any(r.get('error') is not None for r in rows):raise ValueError('Auction SH/SZ host crosscheck incomplete')
            if want_nonempty and not all(type(r.get('rows')) is int and r['rows']>0 for r in rows):raise ValueError('Auction SH/SZ floor not reproduced on all hosts')
            if not want_nonempty and not all(r.get('rows')==0 for r in rows):raise ValueError('Auction SH/SZ pre-floor emptiness not reproduced on all hosts')
        bj_prev=[r for r in cross_records if r.get('dedicated_host')==host and r.get('day')==previous and r.get('symbol') in bj]
        if len(bj_prev)!=len(bj) or {r.get('symbol') for r in bj_prev}!=set(bj) or any(r.get('error') is not None for r in bj_prev) or not all(type(r.get('rows')) is int and r['rows']>0 for r in bj_prev):
            raise ValueError('Auction BSE market difference not reproduced; refusing universal floor')
    return {'market_floors':{'sh':floor,'sz':floor},'markets_without_floor':['bj'],'previous_trading_day':previous,
        'anchor_symbols':sorted(set(symbols)),'crosscheck_symbols':cross_symbols,'dedicated_hosts':hosts,
        'boundary_sha256':_sha_file(boundary_path),'host_crosscheck_sha256':_sha_file(cross_path),
        'evidence_directory':str(root),'scope':'Sampled provider-retention boundary for SH/SZ acquisition scheduling; BSE deliberately has no floor because it retained pre-boundary data.'}

def _verify_rate_evidence(directory):
    path=Path(directory).resolve()/'rate-benchmark-020.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_size>2_000_000:raise ValueError('Rate benchmark evidence missing or invalid')
    value=json.loads(path.read_text());summary=value.get('summary',{})
    if summary.get('interval')!=0.2 or summary.get('workers')!=2 or (summary.get('requests') or 0)<80 or summary.get('errors')!=0 or (summary.get('rps') or 0)<4:
        raise ValueError('Rate benchmark does not support 0.20-second scheduler interval')
    return {'interval':0.2,'workers':2,'requests':summary['requests'],'errors':0,'rps':summary['rps'],'sha256':_sha_file(path),
        'scope':'Bounded personal-research benchmark only; runtime access-limit and recovery guards remain authoritative.'}

def build_scheduler_policy(lake,pid,retention_evidence_dir=None,*,request_interval_seconds=.35):
    plan=lake.plan(pid);symbols=list(plan.get('symbols') or ());days=list(plan.get('trading_days') or ())
    if not symbols or not days:raise ValueError('Plan lacks symbols/trading_days required for scheduler optimization')
    if len(symbols)!=len(set(symbols)) or days!=sorted(set(days)):raise ValueError('Plan symbols/calendar are not unique and ordered')
    if type(request_interval_seconds) not in (int,float) or not .2<=request_interval_seconds<=2:raise ValueError('Invalid request interval')
    basic_path=lake.root/'lake/bronze/provider=baostock/stock_basic/stock_basic.parquet'
    basic={};basic_sha=None
    if basic_path.is_file() and not basic_path.is_symlink():
        basic_sha=_sha_file(basic_path)
        frame=pl.read_parquet(basic_path,columns=['code','ipoDate','outDate','type'])
        for row in frame.iter_rows(named=True):
            if row.get('type')=='1' and row.get('code') in symbols and row.get('ipoDate'):
                old=basic.get(row['code'])
                if old and (old['ipoDate'],old.get('outDate'))!=(row['ipoDate'],row.get('outDate')):raise ValueError('Conflicting stock_basic lifecycle for '+row['code'])
                basic[row['code']]=row
    import duckdb
    finance={};finance_sources=[]
    with duckdb.connect(str(lake.catalog),read_only=True) as con:
        for code,raw,source_id in con.execute('SELECT code,record_json,source_id FROM tdx_finance WHERE plan_id=?',[pid]).fetchall():
            if code not in symbols:continue
            row=json.loads(raw);ipo=row.get('ipo_date')
            if ipo:
                date.fromisoformat(ipo)
                if code in finance and finance[code]!=ipo:raise ValueError('Conflicting TDX finance IPO dates for '+code)
                finance[code]=ipo;finance_sources.append(source_id)
    bounds={};unknown=[]
    for symbol in symbols:
        row=basic.get(symbol);listed=(row or {}).get('ipoDate') or finance.get(symbol);delisted=(row or {}).get('outDate') or None
        if not listed:unknown.append(symbol);continue
        if row and finance.get(symbol) and finance[symbol]!=listed:raise ValueError('Conflicting provider listing dates for '+symbol)
        date.fromisoformat(listed)
        if delisted:
            date.fromisoformat(delisted)
            if delisted<listed:raise ValueError('Delisting before listing for '+symbol)
        bounds[symbol]={'listed':listed,'delisted':delisted,'source':'baostock_stock_basic' if row else 'tdx_finance_ipo'}
    floors={};retention=None;rate=None
    if retention_evidence_dir:
        retention=_verify_auction_retention_evidence(retention_evidence_dir,days);floors['auction']=retention['market_floors'];rate=_verify_rate_evidence(retention_evidence_dir)
    def count_window(symbol,family=None):
        row=bounds.get(symbol);lower=row.get('listed') if row else None;upper=row.get('delisted') if row else None
        market=symbol[:2] if symbol else None;floor=(floors.get(family,{}) or {}).get(market) if family else None
        if floor and (not lower or floor>lower):lower=floor
        lo=bisect.bisect_left(days,lower) if lower else 0;hi=bisect.bisect_right(days,upper) if upper else len(days)
        return max(0,hi-lo)
    unbounded=len(symbols)*len(days);lifecycle=sum(count_window(s) for s in symbols)
    auction=sum(count_window(s,'auction') for s in symbols) if 'auction' in floors else lifecycle
    core={'format':POLICY_FORMAT,'plan_id':pid,'created_at':now(),'qualification':'scheduler_optimization_only_not_pit',
        'lifecycle_bounds':bounds,'lifecycle_known':len(bounds),'lifecycle_unknown':unknown,
        'lifecycle_sources':{'baostock_stock_basic_path':str(basic_path) if basic_sha else None,'baostock_stock_basic_sha256':basic_sha,
            'tdx_finance_source_ids_digest':digest(sorted(set(finance_sources))),'tdx_finance_ipo_count':len(finance)},
        'family_market_history_floors':floors,'auction_retention_evidence':retention,'rate_benchmark_evidence':rate,
        'request_interval_seconds':request_interval_seconds,
        'request_estimate':{'unbounded_symbol_days_per_family':unbounded,'lifecycle_bounded_symbol_days_per_family':lifecycle,
            'auction_bounded_symbol_days':auction,'effective_request_interval_seconds':request_interval_seconds,'lifecycle_reduction_pct':round((1-lifecycle/unbounded)*100,2) if unbounded else 0},
        'limitations':['Listing/delisting dates are retrospective acquisition bounds, not PIT Universe evidence.',
            'Auction SH/SZ floor is a sampled provider retention boundary reproduced on approved dedicated hosts; BSE has no retention floor because cross-checks found older data.',
            'The 0.20-second benchmark was single-node only; deployment defaults to 0.35 seconds per node. Runtime access-limit and recovery guards remain authoritative.',
            'No history floor is applied to trades because sparse probes remained nonempty back to 2002; completeness still requires continued collection.']}
    value={**core,'policy_id':digest(core)}
    return validate_scheduler_policy(value,pid)

def _history_window(policy,family,symbol):
    row=policy.get('lifecycle_bounds',{}).get(symbol,{}) if symbol else {}
    lower=row.get('listed');upper=row.get('delisted');floor=(policy.get('family_market_history_floors',{}).get(family,{}) or {}).get(symbol[:2] if symbol else '')
    if floor and (not lower or floor>lower):lower=floor
    return lower,upper

def _latest_allowed_day(days,family,symbol,day,policy,*,strictly_before=False):
    idx=(bisect.bisect_left(days,day)-1) if strictly_before else (bisect.bisect_right(days,day)-1)
    lower,upper=_history_window(policy,family,symbol)
    if upper:idx=min(idx,bisect.bisect_right(days,upper)-1)
    if idx<0:return None
    candidate=days[idx]
    return candidate if not lower or candidate>=lower else None

def _scheduler_changes(con,days,pid,policy):
    rows=[dict(r) for r in con.execute("SELECT * FROM jobs WHERE plan_id=? AND state IN ('PENDING','SKIPPED_POLICY') AND family IN ('auction','trades') AND offset=0 AND chunk IS NULL ORDER BY job_id",(pid,))]
    changes=[]
    for job in rows:
        target=_latest_allowed_day(days,job['family'],job['symbol'],job['day'],policy)
        if target!=job['day'] or job['state']=='SKIPPED_POLICY':changes.append({'job':job,'target_day':target})
    return changes,digest({'plan_id':pid,'policy':policy,'eligible_jobs':rows})

def preview_scheduler_policy(lake,pid,policy):
    days=list(lake.plan(pid)['trading_days'])
    with lake.db(readonly=True) as con:changes,snapshot=_scheduler_changes(con,days,pid,policy)
    pruned=[c for c in changes if c['target_day']!=c['job']['day']]
    return {'snapshot_id':snapshot,'pending_pruned':len(pruned),'pending_retargeted':sum(bool(c['target_day']) for c in pruned),
        'restored':len(changes)-len(pruned),'sample':changes[:12],'dry_run':True}

def apply_scheduler_policy_to_pending(lake,pid,policy,*,expected_snapshot=None):
    days=list(lake.plan(pid)['trading_days']);moved=0;pruned=0;policy_id=policy.get('policy_id') or 'unversioned'
    with lake.db() as con:
        con.execute('BEGIN IMMEDIATE')
        changes,snapshot=_scheduler_changes(con,days,pid,policy)
        if expected_snapshot is not None and snapshot!=expected_snapshot:raise ValueError('Scheduler preview is stale; re-preview before apply')
        con.execute('CREATE TABLE IF NOT EXISTS scheduler_policy_audit(event_id TEXT PRIMARY KEY,policy_id TEXT NOT NULL,job_id TEXT NOT NULL,before_json TEXT NOT NULL,target_day TEXT,created_at TEXT NOT NULL)')
        for change in changes:
            job=change['job'];target=change['target_day']
            con.execute('INSERT OR IGNORE INTO scheduler_policy_audit VALUES (?,?,?,?,?,?)',
                (digest([policy_id,job]),policy_id,job['job_id'],encode(job),target,now()))
            if target==job['day']:
                con.execute("UPDATE jobs SET state='PENDING',error=NULL,updated_at=? WHERE job_id=?",(now(),job['job_id']));continue
            con.execute("UPDATE jobs SET state='SKIPPED_POLICY',error=?,updated_at=? WHERE job_id=?",('Outside scheduler lifecycle/retention window; policy='+policy_id,now(),job['job_id']));pruned+=1
            if target:
                lake.enqueue(pid,job['family'],job['symbol'],target,0,job['priority'],con=con);moved+=1
        con.commit()
    return {'pending_pruned':pruned,'pending_retargeted':moved}

class Source:
    def __init__(self,cache,host=None):
        if importlib.metadata.version('eltdx')!='3.2.2':raise ValueError('Only verified eltdx==3.2.2 is permitted')
        from eltdx import TdxClient
        os.environ['ELTDX_DATA_DIR']=str(cache)
        self.host=host or HOSTS[0]
        if self.host not in HOSTS:raise ValueError('Unapproved TDX quote host')
        self.client=TdxClient(host=self.host,probe_hosts=False,heartbeat_interval=None,timeout=5,
            server_count=1,connections_per_server=1,runtime_workers=1,connect_concurrency=1)
        self.client._dedicated_hosts=DEDICATED
        self.client.connect()
    def close(self):self.client.close()
    def request(self,job):
        c=self.client;symbol=job['symbol'].replace('.','');offset=job['offset'];day=job['day'];f=job['family']
        if f.startswith('bars_'):
            return c.bars.get(symbol,period={'bars_1m':'1m','bars_5m':'5m','bars_daily':'day'}[f],start=offset,count=800,adjust='none',anchor_date=day,include_raw=True)
        if f=='trades':return c.trades.history(symbol,day,start=offset,count=1800,include_raw=True)
        if f=='auction':return c.auctions.series(symbol,day,include_raw=True)
        if f=='finance':return c.corporate.finance_batch(symbol,include_raw=True)
        if f=='capital_changes':return c.corporate.capital_changes(symbol,include_raw=True)
        if f=='topics':return c.f10.hot_topics(symbol[2:])
        if f=='quotes':return c.quotes.legacy(symbol)
        if f=='depth':return c.quotes.get_depth(symbol)
        if f=='limit_ladder':return c.f10.limit_up_down_list(day,day,include_summary=False)
        raise ValueError('Unsupported source family')

def prepare(lake,*,personal=False):
    if personal is not True:raise ValueError('Explicit --personal-research-only required; no production/commercial/automated-trading use')
    calendar_path=lake.root/'lake/bronze/provider=baostock/trade_calendar/calendar.parquet'
    raw=calendar_path.read_bytes();calendar=pl.read_parquet(calendar_path)
    if 'calendar_date' not in calendar.columns:raise ValueError('Existing calendar schema unsupported')
    days=[str(d) for d in calendar.filter(pl.col('is_trading_day').cast(pl.String)=='1')['calendar_date'].to_list()]
    source=Source(lake.root/'cache/tdx-personal')
    try:
        handshake=clean(source.client.session.handshake())
        end=handshake.get('server_date_1')
        if not end:raise ValueError('No explicit server trading date; not guessing latest session')
        date.fromisoformat(end)
        # Do not pretend an intraday response is a stable historical snapshot.
        from zoneinfo import ZoneInfo
        clock=datetime.now(ZoneInfo('Asia/Shanghai'))
        if clock.date().isoformat()==end and clock.hour<16:raise ValueError('Initial historical batch must start after the selected session has closed')
        days=sorted(set(d for d in days if d<=end))
        calendar_extension=None
        if days and days[-1]<end:
            # The user's old lake calendar is immutable. Archive the bounded new calendar query separately.
            from datetime import timedelta
            from quantlab.data.retro_daily import _Session,_query_all,CALENDAR_FIELDS
            first=(date.fromisoformat(days[-1])+timedelta(days=1)).isoformat()
            with _Session(None) as sdk:
                extra=_query_all(sdk.query_trade_dates(start_date=first,end_date=end),CALENDAR_FIELDS,'TDX collection calendar extension')
            expected=(date.fromisoformat(end)-date.fromisoformat(first)).days+1
            if len(extra)!=expected or len({r[0] for r in extra})!=expected or any(r[1] not in ('0','1') or not first<=r[0]<=end for r in extra):
                raise ValueError('Calendar extension incomplete; not guessing weekdays/holidays')
            calendar_extension={'provider':'baostock.query_trade_dates','start':first,'end':end,'rows':extra,'observed_at':now()}
            ref=lake.base/'references';ref.mkdir(exist_ok=True)
            write_json(ref/('calendar-'+digest(calendar_extension)+'.json'),calendar_extension)
            days=sorted(set(days+[r[0] for r in extra if r[1]=='1']))
        if not days or days[-1]!=end:raise ValueError('Archived calendar does not cover server session')
        code_pages=[];members={};excluded=0
        for exchange in ('sh','sz','bj'):
            start=0
            for page in range(50):
                response=clean(source.client.codes.list(exchange,start=start,limit=1600));time.sleep(.2)
                if not isinstance(response,list):raise ValueError('Unexpected security list response')
                code_pages.append((exchange,start,response))
                for row in response:
                    if row.get('exchange')!=exchange:raise ValueError('Security list exchange mismatch')
                    if row.get('category')=='a_share':members[exchange+'.'+row['code']]=row
                    else:excluded+=1
                if not response:break
                start+=len(response)
            else:raise ValueError('Security listing exceeded budget; universe remains partial')
        if not members:raise ValueError('No source A shares')
        # Include already-owned historical A-share identifiers, without inventing current status.
        source_work=Path(__file__).resolve().parents[3]/'artifacts'
        from quantlab.data.retro_daily import RetroDailyStore
        historical=[]
        try:
            store=RetroDailyStore(source_work)
            captures=store.list()
            for item in captures:
                if 'error' not in item:
                    historical.extend(store.plan(item['capture_id'],with_symbols=True)['symbols'])
        except (OSError,ValueError):historical=[]
        symbols=sorted(set(members)|set(historical),key=lambda s:digest(s))
        body={'format':'tdx-personal-collection-v1','library':'eltdx==3.2.2','created_at':now(),'server_handshake':handshake,
            'snapshot_session':end,'calendar_sha256':digest({'raw_sha256':__import__('hashlib').sha256(raw).hexdigest()}),
            'calendar_extension':calendar_extension,'history_start':days[0],'history_end':end,'trading_days':days,'symbols':symbols,'server_a_shares':len(members),
            'historical_identifiers_added':len(set(historical)-set(members)),'excluded_non_stocks':excluded,
            'families':list(FAMILIES),'scope':'Full current provider A-share list plus existing owned historical identifiers; server-retained bar pages and date-addressed history.',
            'snapshot_history':'quotes/depth/topics/finance are collected now; not backfilled historical snapshots',
            'history_policy':'auction/trades/limit_ladder traverse known calendar dates backwards; empty individual requests do not prove entire earlier history empty',
            'max_offset':1_000_000,'request_interval_seconds':0.35,'personal_research_only':True,
            'license':'ELTDX Research-Only License','commercial_or_trading_use':False,'full_history_complete':False,
            'potential_symbol_date_requests_per_family':len(symbols)*len(days)}
        pid=lake.add_plan(body)
        for exchange,offset,response in code_pages:
            jid=lake.enqueue(pid,'securities',day=end,offset=offset,priority=-100)
            # Market-specific identity must not collide in the queue.
            job={'job_id':digest([pid,'securities',exchange,offset]),'plan_id':pid,'family':'securities','symbol':'','day':end,'offset':offset}
            lake.save_page(job,response,origin='initial_security_list_'+exchange)
        with lake.db() as con:
            # Paged code responses have already been archived; no runtime securities jobs.
            con.execute("DELETE FROM jobs WHERE plan_id=? AND family='securities'",(pid,))
            lake.enqueue(pid,'limit_ladder',day=end,priority=-1,con=con)
            for i,symbol in enumerate(symbols):
                for f in PER_SYMBOL:lake.enqueue(pid,f,symbol,end,priority=0,con=con)
            con.commit()
        write_json(lake.base/'active-plan.json',{'plan_id':pid,'created_at':body['created_at']})
        return {'plan_id':pid,'symbols':len(symbols),'server_a_shares':len(members),'families':list(FAMILIES),
                'history_start':days[0],'history_end':end,'tasks_initial':len(symbols)*len(PER_SYMBOL)+1,'full_history_complete':False}
    finally:source.close()

class Runner:
    def __init__(self,lake,pid,workers=2,*,request_retries=3,retry_backoff=1.0,transient_burst=8,
                 recovery_cycles=6,cooldown_seconds=60,max_job_attempts=12):
        for name,value,low,high in (
                ('request_retries',request_retries,0,10),('transient_burst',transient_burst,1,100),
                ('recovery_cycles',recovery_cycles,0,20),('cooldown_seconds',cooldown_seconds,0,300),
                ('max_job_attempts',max_job_attempts,1,100)):
            if type(value) is not int or not low<=value<=high:raise ValueError(name+' out of supported range')
        if type(retry_backoff) not in (int,float) or not 0<=retry_backoff<=30:raise ValueError('retry_backoff out of supported range')
        self.lake=lake;self.pid=pid;self.plan=lake.plan(pid);self.workers=workers
        self.request_retries=request_retries;self.retry_backoff=float(retry_backoff);self.transient_burst=transient_burst
        self.max_recovery_cycles=recovery_cycles;self.cooldown_seconds=cooldown_seconds;self.max_job_attempts=max_job_attempts
        self.local=threading.local();self.sources=[];self.source_lock=threading.Lock();self.source_generation=0;self.host_cursor=0
        self.rate_lock=threading.Lock();self.last_request=0.
        self.days=tuple(self.plan['trading_days']);self.policy=load_scheduler_policy(lake,pid)
        self.policy_id=self.policy.get('policy_id')
        from quantlab.data.tdx_sharding import load_worker_assignment,validate_worker_queue
        self.assignment=load_worker_assignment(lake,pid,self.policy_id)
        validate_worker_queue(lake,self.assignment)
        self.metrics_lock=threading.Lock();self.network_attempts=0;self.network_errors=0;self.reused_pages=0
    def _previous_history_day(self,family,symbol,day):
        return _latest_allowed_day(self.days,family,symbol,day,self.policy,strictly_before=True)
    def _next_host(self):
        with self.source_lock:
            host=HOSTS[self.host_cursor%len(HOSTS)];self.host_cursor+=1;return host
    def _source(self):
        if getattr(self.local,'generation',None)!=self.source_generation or not hasattr(self.local,'source'):
            old=getattr(self.local,'source',None)
            if old is not None:
                with contextlib.suppress(Exception):old.close()
            source=Source(self.lake.root/'cache/tdx-personal',host=self._next_host())
            self.local.source=source;self.local.generation=self.source_generation
            with self.source_lock:self.sources.append(source)
        return self.local.source
    def _drop_local_source(self):
        source=getattr(self.local,'source',None)
        if source is not None:
            with contextlib.suppress(Exception):source.close()
        for name in ('source','generation'):
            with contextlib.suppress(AttributeError):delattr(self.local,name)
    def _reset_sources(self):
        with self.source_lock:
            self.source_generation+=1;sources=self.sources;self.sources=[]
        for source in sources:
            with contextlib.suppress(Exception):source.close()
    def _request_slot(self):
        with self.rate_lock:
            interval=self.policy.get('request_interval_seconds') or self.plan.get('request_interval_seconds',.35)
            wait=interval-(time.monotonic()-self.last_request)
            if wait>0:time.sleep(wait)
            self.last_request=time.monotonic()
    def _sleep_interruptible(self,seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if (self.lake.base/'STOP').exists():return False
            time.sleep(min(1,max(0,end-time.monotonic())))
        return True
    def fetch(self,job):
        from quantlab.data.tdx_sharding import require_owned_job
        require_owned_job(self.assignment,job)
        try:
            if job.get('chunk'):
                # Resume the exact saved bytes after a crash between publication and cursor scheduling.
                folder=safe(self.lake.root,self.lake.root/job['chunk'])
                manifest=json.loads((folder/'manifest.json').read_text())
                self.lake.verify_page_at(folder,job['family'],manifest['source_id'])
                value=json.loads(gzip_decompress(folder/'response.json.gz'))
                with self.metrics_lock:self.reused_pages+=1
                return job,value['result'],value['observed_at'],None
        except Exception as error:return job,None,now(),type(error).__name__+': '+str(error)[:400]
        last_error=None
        for attempt in range(self.request_retries+1):
            try:
                with self.metrics_lock:self.network_attempts+=1
                source=self._source();self._request_slot();observed=now();value=clean(source.request(job))
                return job,value,observed,None
            except Exception as error:
                with self.metrics_lock:self.network_errors+=1
                last_error=type(error).__name__+': '+str(error)[:400]
                if access_limit_error(last_error) or not retryable_error(last_error) or attempt>=self.request_retries:
                    return job,None,now(),last_error
                # Exact request is retried; no cursor/page is advanced before a valid response is saved.
                self._drop_local_source()
                if self.retry_backoff:time.sleep(min(5,self.retry_backoff*(2**attempt)))
        return job,None,now(),last_error or 'Unknown transient request failure'
    def validate_page_chain(self,job,rows):
        if not (job['family'].startswith('bars_') or job['family']=='trades') or not job['offset']:return
        with self.lake.db(readonly=True) as con:
            previous=con.execute("SELECT * FROM jobs WHERE plan_id=? AND family=? AND symbol=? AND day=? AND offset<? AND chunk IS NOT NULL AND state IN ('SAVED','CHECKPOINT') ORDER BY offset DESC LIMIT 1",(self.pid,job['family'],job['symbol'],job['day'],job['offset'])).fetchone()
        if not previous or previous['offset']+previous['rows']!=job['offset']:
            raise ValueError('MISSING_CHECKPOINT: exact preceding saved page required before advancing pagination')
        folder=safe(self.lake.root,self.lake.root/previous['chunk'])
        metadata=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        self.lake.verify_page_at(folder,job['family'],metadata['source_id'])
        payload=json.loads(gzip_decompress(folder/'response.json.gz'))
        from quantlab.data.tdx_lake import rows_for
        strip=lambda rr:[{k:v for k,v in r.items() if k not in ('index','absolute_index')} for r in rr]
        if rows and digest(strip(rows_for(job['family'],payload['result'])))==digest(strip(rows)):
            raise ValueError('REPEATED_PAGE: provider repeated the preceding page; history incomplete')

    def follow(self,job,manifest,rows):
        f=job['family'];symbol=job['symbol'];day=job['day'];offset=job['offset']
        if f=='trades':
            matches=[r for r in rows if r.get('event_kind')=='opening_match']
            if matches:
                child_id=self.lake.enqueue(self.pid,'opening_match',symbol,day,offset,priority=999999)
                child={**job,'job_id':child_id,'family':'opening_match'}
                self.lake.save_page(child,matches,observed_at=manifest['observed_at'],origin='exact_rows_from_trade_page:'+manifest['source_id'])
        if f.startswith('bars_') or f=='trades':
            if rows:
                if offset+len(rows)>self.plan['max_offset']:
                    self.lake.mark(job,'PAGE_LIMIT',rows=len(rows),chunk=job.get('chunk'),error='Max offset reached; history incomplete');return
                self.lake.enqueue(self.pid,f,symbol,day,offset+len(rows),priority=100)
                return
        if f in ('trades','auction','limit_ladder'):
            earlier=self._previous_history_day(f,symbol,day)
            if earlier:self.lake.enqueue(self.pid,f,symbol,earlier,priority=1000)
    def run(self,seconds,max_requests,max_new_gib):
        started=time.monotonic();initial_free=shutil.disk_usage(self.lake.root).free;count=0;reason='QUEUE_DRAINED'
        transient_failures=0;recovery_cycles=0;last_transient=None
        self.lake.reconcile_publications();self.lake.recover(self.pid)
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            while True:
                if (self.lake.base/'STOP').exists():reason='USER_STOP';break
                if time.monotonic()-started>=seconds:reason='TIME_BUDGET';break
                if count>=max_requests:reason='REQUEST_BUDGET';break
                free=shutil.disk_usage(self.lake.root).free
                if free<30*1024**3 or initial_free-free>=max_new_gib*1024**3:reason='DISK_BUDGET';break
                jobs=self.lake.next_jobs(self.pid,min(self.workers,max_requests-count))
                if not jobs:break
                for job,value,observed,error in pool.map(self.fetch,jobs):
                    count+=1
                    if error:
                        self.lake.mark(job,'ERROR',error=error)
                        if access_limit_error(error):reason='PROVIDER_ACCESS_LIMIT';break
                        if retryable_error(error):
                            transient_failures+=1;last_transient=error
                        else:
                            # A bad payload stays explicit and does not trip the network circuit breaker for unrelated securities.
                            transient_failures=0
                    else:
                        try:
                            from quantlab.data.tdx_lake import rows_for
                            self.validate_page_chain(job,rows_for(job['family'],value))
                            manifest,rows=self.lake.save_page(job,value,observed_at=observed,finalize=False)
                            with self.lake.db(readonly=True) as db:job['chunk']=db.execute('SELECT chunk FROM jobs WHERE job_id=?',(job['job_id'],)).fetchone()[0]
                            self.follow(job,manifest,rows)
                            with self.lake.db(readonly=True) as db:
                                state=db.execute('SELECT state FROM jobs WHERE job_id=?',(job['job_id'],)).fetchone()[0]
                            if state=='STORED':self.lake.commit_saved_page(job)
                            transient_failures=0;last_transient=None
                        except Exception as exc:
                            error=type(exc).__name__+': '+str(exc)[:400]
                            state='STALLED' if 'REPEATED_PAGE:' in error or 'MISSING_CHECKPOINT:' in error else 'ERROR'
                            self.lake.mark(job,state,chunk=job.get('chunk'),error=error)
                            if state=='STALLED':
                                rejected=self.lake.base/'_rejected';rejected.mkdir(exist_ok=True)
                                write_json(rejected/(job['job_id']+'.json'),{'job':job,'observed_at':observed,'error':error,'result':value,'history_complete':False})
                            if retryable_error(error):transient_failures+=1;last_transient=error
                            else:transient_failures=0
                    if count%50==0:
                        progress={'plan_id':self.pid,'pid':os.getpid(),'processed_this_run':count,'elapsed_seconds':round(time.monotonic()-started),
                            'recovery_cycles':recovery_cycles,'transient_failures':transient_failures,'scheduler_policy_id':self.policy_id,
                            'network_attempts':self.network_attempts,'network_errors':self.network_errors,'reused_pages':self.reused_pages,
                            'shard_id':self.assignment['shard_id'] if self.assignment else None,'updated_at':now(),'state':'RUNNING'}
                        write_json(self.lake.base/'progress.json',progress);print(encode(progress),flush=True)
                if reason=='PROVIDER_ACCESS_LIMIT':break
                if transient_failures>=self.transient_burst:
                    if recovery_cycles>=self.max_recovery_cycles:reason='RECOVERY_EXHAUSTED';break
                    recovery_cycles+=1;cooldown=min(300,self.cooldown_seconds*(2**(recovery_cycles-1)))
                    progress={'plan_id':self.pid,'pid':os.getpid(),'processed_this_run':count,'elapsed_seconds':round(time.monotonic()-started),
                        'recovery_cycles':recovery_cycles,'cooldown_seconds':cooldown,'last_error':last_transient,'scheduler_policy_id':self.policy_id,'updated_at':now(),'state':'COOLDOWN'}
                    write_json(self.lake.base/'progress.json',progress);print(encode(progress),flush=True)
                    self._reset_sources()
                    self.lake.recover(self.pid,retry_errors=True,max_attempts=self.max_job_attempts,error_markers=RETRYABLE_ERROR_MARKERS)
                    if not self._sleep_interruptible(cooldown):reason='USER_STOP';break
                    transient_failures=0;last_transient=None
        self._reset_sources()
        result={'plan_id':self.pid,'processed_this_run':count,'stop_reason':reason,
            'state':'HALTED' if reason in ('RECOVERY_EXHAUSTED','PROVIDER_ACCESS_LIMIT','DISK_BUDGET') else 'STOPPED',
            'recovery_cycles':recovery_cycles,'scheduler_policy_id':self.policy_id,'finished_at':now(),'full_history_complete':False,
            'elapsed_seconds':round(time.monotonic()-started,3),'network_attempts':self.network_attempts,'network_errors':self.network_errors,
            'reused_pages':self.reused_pages,'shard_id':self.assignment['shard_id'] if self.assignment else None}
        if result['state']=='HALTED':
            write_json(self.lake.base/AUTO_HALT,{'plan_id':self.pid,'reason':reason,'last_error':last_transient,'recovery_cycles':recovery_cycles,'halted_at':result['finished_at']})
        write_json(self.lake.base/'progress.json',result);return result

def gzip_decompress(path):
    import gzip
    return gzip.decompress(path.read_bytes())

@contextlib.contextmanager
def writer_lease(lake):
    path=safe(lake.root,lake.base/'writer.lock');stream=path.open('a+b');locked=False
    try:
        try:
            if os.name=='nt':
                import msvcrt
                stream.seek(0,2)
                if not stream.tell():stream.write(b'0');stream.flush()
                stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            locked=True
        except OSError as exc:raise ValueError('Another collector owns the TDX writer lease; not starting duplicate worker') from exc
        yield
    finally:
        if locked and os.name=='nt':
            import msvcrt
            stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
        stream.close()

def recover_for_resume(lake,pid,max_job_attempts):
    # Automatic or manual transport recovery never reclassifies/retries known protocol corruption.
    lake.recover(pid,retry_errors=True,max_attempts=max_job_attempts,error_markers=RETRYABLE_ERROR_MARKERS)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',required=True);p.add_argument('action',choices=('prepare','optimize','run','status','resume','autoresume','stop'))
    p.add_argument('--plan-id');p.add_argument('--personal-research-only',action='store_true')
    p.add_argument('--retention-evidence-dir');p.add_argument('--policy-file')
    mode=p.add_mutually_exclusive_group();mode.add_argument('--apply',action='store_true');mode.add_argument('--dry-run',action='store_true')
    p.add_argument('--expected-snapshot');p.add_argument('--request-interval',type=float,default=.35)
    p.add_argument('--seconds',type=int,default=300);p.add_argument('--max-requests',type=int,default=100000)
    p.add_argument('--max-new-gib',type=int,default=100);p.add_argument('--workers',type=int,choices=(1,2),default=2)
    p.add_argument('--request-retries',type=int,default=3);p.add_argument('--transient-burst',type=int,default=8)
    p.add_argument('--recovery-cycles',type=int,default=6);p.add_argument('--cooldown-seconds',type=int,default=60)
    p.add_argument('--max-job-attempts',type=int,default=12)
    a=p.parse_args(argv)
    if a.action in ('prepare','optimize','run','resume','autoresume') and not a.personal_research_only:p.error('Explicit --personal-research-only required')
    if not 1<=a.seconds<=86400 or not 1<=a.max_requests<=1000000 or not 1<=a.max_new_gib<=500:p.error('Budget out of supported range')
    if not 0<=a.request_retries<=10 or not 1<=a.transient_burst<=100 or not 0<=a.recovery_cycles<=20 or not 0<=a.cooldown_seconds<=300 or not 1<=a.max_job_attempts<=100:
        p.error('Recovery policy out of supported range')
    lake=TdxLake(a.data_root,create=a.action=='prepare')
    if a.action=='status':print(encode(lake.status()));return 0
    if a.action=='stop':(lake.base/'STOP').write_text(now());print('Stop requested; current bounded request may finish.');return 0
    if a.action=='autoresume':
        if (lake.base/'STOP').exists():print(encode({'state':'AUTO_DISABLED_USER_STOP'}));return 0
        halt=lake.base/AUTO_HALT
        if halt.exists():print(encode({'state':'AUTO_HALTED','detail':json.loads(halt.read_text())}));return 0
    from quantlab.data.tdx_sharding import read_role
    role=read_role(lake)
    if role and role.get('role')=='coordinator' and a.action in ('prepare','run','resume','autoresume'):
        raise ValueError('Canonical coordinator collection is disabled; run its assigned worker data root')
    with writer_lease(lake):
        if a.action=='prepare':result=prepare(lake,personal=a.personal_research_only)
        elif a.action=='optimize':
            pid=a.plan_id or json.loads((lake.base/'active-plan.json').read_text())['plan_id']
            policy=validate_scheduler_policy(json.loads(Path(a.policy_file).read_text(encoding='utf-8')),pid) if a.policy_file else build_scheduler_policy(lake,pid,a.retention_evidence_dir,request_interval_seconds=a.request_interval)
            adjusted=preview_scheduler_policy(lake,pid,policy)
            if a.apply:
                if not a.policy_file or not a.expected_snapshot:p.error('--apply requires --policy-file and --expected-snapshot from the reviewed dry-run')
                if not (lake.base/'STOP').exists():raise ValueError('Stop collection before applying scheduler policy')
                if adjusted['snapshot_id']!=a.expected_snapshot:raise ValueError('Scheduler preview is stale; re-preview before apply')
                backup_dir=lake.base/'policy-history';backup_dir.mkdir(exist_ok=True)
                write_json(backup_dir/(policy['policy_id']+'.json'),policy)
                # Atomically persist the reviewed policy before queue edits: crash recovery remains bounded by this policy.
                write_json(_policy_path(lake),policy)
                adjusted={**apply_scheduler_policy_to_pending(lake,pid,policy,expected_snapshot=a.expected_snapshot),'dry_run':False}
            result={'plan_id':pid,'policy_id':policy['policy_id'],'lifecycle_known':policy['lifecycle_known'],
                'lifecycle_unknown':len(policy['lifecycle_unknown']),'family_market_history_floors':policy['family_market_history_floors'],'request_interval_seconds':policy['request_interval_seconds'],
                'request_estimate':policy['request_estimate'],**adjusted}
        else:
            pid=a.plan_id or json.loads((lake.base/'active-plan.json').read_text())['plan_id']
            if a.action=='resume':
                (lake.base/'STOP').unlink(missing_ok=True);(lake.base/AUTO_HALT).unlink(missing_ok=True)
                recover_for_resume(lake,pid,a.max_job_attempts)
            elif a.action=='autoresume':recover_for_resume(lake,pid,a.max_job_attempts)
            result=Runner(lake,pid,a.workers,request_retries=a.request_retries,transient_burst=a.transient_burst,
                recovery_cycles=a.recovery_cycles,cooldown_seconds=a.cooldown_seconds,max_job_attempts=a.max_job_attempts).run(
                    a.seconds,a.max_requests,a.max_new_gib)
        print(encode(result))
    return 0
if __name__=='__main__':raise SystemExit(main())

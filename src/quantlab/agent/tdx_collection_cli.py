"""Explicit one-time personal-research acquisition into niuniu-data; resumable, no trading.

Use the previously verified isolated eltdx==3.2.2 environment. Never install it as
an application default or turn collection into a commercial/production service.
"""
from __future__ import annotations
import argparse,concurrent.futures,contextlib,fcntl,importlib.metadata,json,os,shutil,sys,threading,time
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

def retryable_error(message):
    text=str(message).casefold()
    return any(marker in text for marker in RETRYABLE_ERROR_MARKERS)

def access_limit_error(message):
    text=str(message).casefold()
    return any(marker in text for marker in ACCESS_LIMIT_MARKERS)

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
        self.previous={b:a for a,b in zip(self.plan['trading_days'],self.plan['trading_days'][1:])}
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
            wait=self.plan.get('request_interval_seconds',.35)-(time.monotonic()-self.last_request)
            if wait>0:time.sleep(wait)
            self.last_request=time.monotonic()
    def _sleep_interruptible(self,seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if (self.lake.base/'STOP').exists():return False
            time.sleep(min(1,max(0,end-time.monotonic())))
        return True
    def fetch(self,job):
        try:
            if job.get('chunk'):
                # Resume the exact saved bytes after a crash between publication and cursor scheduling.
                folder=safe(self.lake.root,self.lake.root/job['chunk'])
                manifest=json.loads((folder/'manifest.json').read_text())
                self.lake.verify_page(job['family'],manifest['source_id'])
                value=json.loads(gzip_decompress(folder/'response.json.gz'))
                return job,value['result'],value['observed_at'],None
        except Exception as error:return job,None,now(),type(error).__name__+': '+str(error)[:400]
        last_error=None
        for attempt in range(self.request_retries+1):
            try:
                source=self._source();self._request_slot();observed=now();value=clean(source.request(job))
                return job,value,observed,None
            except Exception as error:
                last_error=type(error).__name__+': '+str(error)[:400]
                if access_limit_error(last_error) or not retryable_error(last_error) or attempt>=self.request_retries:
                    return job,None,now(),last_error
                # Exact request is retried; no cursor/page is advanced before a valid response is saved.
                self._drop_local_source()
                if self.retry_backoff:time.sleep(min(5,self.retry_backoff*(2**attempt)))
        return job,None,now(),last_error or 'Unknown transient request failure'
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
                # Detect repeated server pages instead of looping forever.
                if offset:
                    with self.lake.db(readonly=True) as con:
                        previous=con.execute('SELECT chunk FROM jobs WHERE plan_id=? AND family=? AND symbol=? AND day=? AND offset<? AND chunk IS NOT NULL ORDER BY offset DESC LIMIT 1',(self.pid,f,symbol,day,offset)).fetchone()
                    if previous:
                        payload=json.loads(gzip_decompress(self.lake.root/previous[0]/'response.json.gz'))
                        from quantlab.data.tdx_lake import rows_for
                        old=rows_for(f,payload['result'])
                        strip=lambda rr:[{k:v for k,v in r.items() if k not in ('index','absolute_index')} for r in rr]
                        if digest(strip(old))==digest(strip(rows)):
                            self.lake.mark(job,'STALLED',rows=len(rows),error='Repeated provider page; incomplete history');return
                self.lake.enqueue(self.pid,f,symbol,day,offset+len(rows),priority=100)
                return
        if f in ('trades','auction','limit_ladder'):
            earlier=self.previous.get(day)
            if earlier:self.lake.enqueue(self.pid,f,symbol,earlier,priority=1000)
    def run(self,seconds,max_requests,max_new_gib):
        started=time.monotonic();initial_free=shutil.disk_usage(self.lake.root).free;count=0;reason='QUEUE_DRAINED'
        transient_failures=0;recovery_cycles=0;last_transient=None
        self.lake.recover(self.pid)
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
                            manifest,rows=self.lake.save_page(job,value,observed_at=observed,finalize=False)
                            job['chunk']=str((self.lake.base/job['family']/'pages'/manifest['source_id']).relative_to(self.lake.root))
                            self.follow(job,manifest,rows)
                            with self.lake.db(readonly=True) as db:
                                state=db.execute('SELECT state FROM jobs WHERE job_id=?',(job['job_id'],)).fetchone()[0]
                            if state=='STORED':self.lake.mark(job,'SAVED' if rows else 'EMPTY',rows=len(rows),chunk=job['chunk'])
                            transient_failures=0;last_transient=None
                        except Exception as exc:
                            error=type(exc).__name__+': '+str(exc)[:400];self.lake.mark(job,'ERROR',error=error)
                            if retryable_error(error):transient_failures+=1;last_transient=error
                            else:transient_failures=0
                    if count%50==0:
                        progress={'plan_id':self.pid,'pid':os.getpid(),'processed_this_run':count,'elapsed_seconds':round(time.monotonic()-started),
                            'recovery_cycles':recovery_cycles,'transient_failures':transient_failures,'updated_at':now(),'state':'RUNNING'}
                        write_json(self.lake.base/'progress.json',progress);print(encode(progress),flush=True)
                if reason=='PROVIDER_ACCESS_LIMIT':break
                if transient_failures>=self.transient_burst:
                    if recovery_cycles>=self.max_recovery_cycles:reason='RECOVERY_EXHAUSTED';break
                    recovery_cycles+=1;cooldown=min(300,self.cooldown_seconds*(2**(recovery_cycles-1)))
                    progress={'plan_id':self.pid,'pid':os.getpid(),'processed_this_run':count,'elapsed_seconds':round(time.monotonic()-started),
                        'recovery_cycles':recovery_cycles,'cooldown_seconds':cooldown,'last_error':last_transient,'updated_at':now(),'state':'COOLDOWN'}
                    write_json(self.lake.base/'progress.json',progress);print(encode(progress),flush=True)
                    self._reset_sources()
                    self.lake.recover(self.pid,retry_errors=True,max_attempts=self.max_job_attempts,error_markers=RETRYABLE_ERROR_MARKERS)
                    if not self._sleep_interruptible(cooldown):reason='USER_STOP';break
                    transient_failures=0;last_transient=None
        self._reset_sources()
        result={'plan_id':self.pid,'processed_this_run':count,'stop_reason':reason,
            'state':'HALTED' if reason in ('RECOVERY_EXHAUSTED','PROVIDER_ACCESS_LIMIT','DISK_BUDGET') else 'STOPPED',
            'recovery_cycles':recovery_cycles,'finished_at':now(),'full_history_complete':False}
        if result['state']=='HALTED':
            write_json(self.lake.base/AUTO_HALT,{'plan_id':self.pid,'reason':reason,'last_error':last_transient,'recovery_cycles':recovery_cycles,'halted_at':result['finished_at']})
        write_json(self.lake.base/'progress.json',result);return result

def gzip_decompress(path):
    import gzip
    return gzip.decompress(path.read_bytes())

@contextlib.contextmanager
def writer_lease(lake):
    path=lake.base/'writer.lock';stream=path.open('a+')
    try:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB);yield
    except BlockingIOError:raise ValueError('Another collector owns the TDX writer lease; not starting duplicate worker')
    finally:stream.close()

def recover_for_resume(lake,pid,max_job_attempts):
    # Permanent/protocol failures get only three queue attempts; transient transport failures may recover longer.
    lake.recover(pid,retry_errors=True,max_attempts=3)
    lake.recover(pid,retry_errors=True,max_attempts=max_job_attempts,error_markers=RETRYABLE_ERROR_MARKERS)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',required=True);p.add_argument('action',choices=('prepare','run','status','resume','autoresume','stop'))
    p.add_argument('--plan-id');p.add_argument('--personal-research-only',action='store_true')
    p.add_argument('--seconds',type=int,default=300);p.add_argument('--max-requests',type=int,default=100000)
    p.add_argument('--max-new-gib',type=int,default=100);p.add_argument('--workers',type=int,choices=(1,2),default=2)
    p.add_argument('--request-retries',type=int,default=3);p.add_argument('--transient-burst',type=int,default=8)
    p.add_argument('--recovery-cycles',type=int,default=6);p.add_argument('--cooldown-seconds',type=int,default=60)
    p.add_argument('--max-job-attempts',type=int,default=12)
    a=p.parse_args(argv)
    if a.action in ('prepare','run','resume','autoresume') and not a.personal_research_only:p.error('Explicit --personal-research-only required')
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
    with writer_lease(lake):
        if a.action=='prepare':result=prepare(lake,personal=a.personal_research_only)
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

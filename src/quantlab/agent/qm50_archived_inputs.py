"""Read-only bridge to existing retrospective raw captures, including packed bytes.

No data downloads, price-limit reconstruction, source upgrades or candidate selection.
The host chooses the source workspace; the model supplies only verified capture IDs.
"""
from __future__ import annotations
from collections import Counter
from datetime import date
from pathlib import Path
import gzip
import io
import json
import re
import polars as pl
from quantlab.data.retro_daily import RetroDailyStore,FIELDS,PACK_PARTS,SCHEMA,normalize_symbol_rows
from quantlab.data.session_coverage import calendar_sessions
from quantlab.agent.research_specs import sha,regular_bytes
from quantlab.storage.codec import digest,encode

VERSION='qm50-archived-daily-inputs-v1'
MAX_INPUT_BYTES=64_000_000
MAX_SYMBOLS=10
MAX_DAYS=371
SOURCE_FIELDS={'preclose':'vendor_previous_close','turn':'vendor_turnover_percent',
               'isST':'vendor_is_st','tradestatus':'vendor_trade_status'}
MISSING_FIELDS=['reference_price','upper_limit_price','lower_limit_price','tick_size','float_shares_asof',
                'board_asof','delisting_arrangement','normal_price_limit_regime','historical_available_at']
LIMITATIONS=[
    'Read-only original provider observations; symbol source hashes verified, not historical PIT certification.',
    'preclose is retained as vendor_previous_close, never silently upgraded to the required reference_price.',
    'turn is a provider percentage, not amount, explicit historical float shares or a verified P06 implementation.',
    'isST/tradestatus preserve each row, not the latest state; missing rows remain missing, never normal.',
    'No inferred upper/lower limits, P01 height, candidate set, Q, rankings, future-return labels or orders.',
]


def safe_path(root,path):
    current=path
    if not path.is_relative_to(root):raise ValueError('Archive escaped host-selected workspace')
    while current!=root:
        if current.is_symlink():raise ValueError('Archive symlink rejected')
        current=current.parent
    if not path.resolve().is_relative_to(root):raise ValueError('Archive path escaped workspace')
    return path


class ArchivedDailyBridge:
    def __init__(self,source_workspace):
        source=Path(source_workspace)
        if source.is_symlink() or not source.is_dir():raise ValueError('Host-selected source workspace missing or symlink')
        self.root=source.resolve();self.store=RetroDailyStore(self.root)
        safe_path(self.root,self.store.root)
    def list_sources(self):
        rows=self.store.list()
        if len(rows)>50:raise ValueError('More than 50 captures; source inventory requires pagination')
        return {'captures':rows,'source_type':'archived_retro_daily','may_be_packed':True,
                'source_scope':'host_selected_workspace_only','limitations':LIMITATIONS}
    def _source(self,capture_id):
        folder=self.store._capture_dir(capture_id);safe_path(self.root,folder)
        for rel in ('plan.json','reference/stock_basic.json.gz','reference/trade_calendar.json.gz','packs/index.json'):
            safe_path(self.root,folder/rel)
        plan=self.store.plan(capture_id,with_symbols=True)
        refs=self.store.reference(capture_id)
        return folder,plan,refs
    def inspect_symbols(self,capture_id,offset,limit,filter_kind):
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=20:
            raise ValueError('Archive pagination requires offset>=0 and 1<=limit<=20')
        if filter_kind not in ('all','has_st','has_suspension'):raise ValueError('Unknown archive diagnostic filter')
        _,plan,_=self._source(capture_id);records=[]
        for symbol in plan['symbols']:
            m=self.store.symbol_manifest(capture_id,symbol,deep=False)
            if m is None:row={'symbol':symbol,'status':'NOT_CAPTURED'}
            else:row={k:m[k] for k in ('symbol','status','rows','first_date','last_date','st_rows','tradable_rows','fetched_at','parquet_sha256')}
            if filter_kind=='has_st' and (m is None or m['st_rows']==0):continue
            if filter_kind=='has_suspension' and (m is None or m['rows']==m['tradable_rows']):continue
            records.append(row)
        return {'capture_id':capture_id,'filter':filter_kind,'records':records[offset:offset+limit],
                'total':len(records),'offset':offset,'next_offset':offset+limit if offset+limit<len(records) else None,
                'qualification':'provider_retrospective','data_bytes_verified':False,
                'note':'Metadata-only discovery; filters find diagnostic examples over the entire capture, never a historical candidate universe.',
                'fields':list(FIELDS),'missing_qm50_fields':MISSING_FIELDS,'limitations':LIMITATIONS}
    def load(self,capture_id,symbols_text,start_text,end_text):
        symbols=symbols_text.replace(',',' ').split();start,end=date.fromisoformat(start_text),date.fromisoformat(end_text)
        if not 1<=len(symbols)<=MAX_SYMBOLS or len(set(symbols))!=len(symbols):raise ValueError('Select 1–10 distinct archive symbols')
        if not 0<=(end-start).days<MAX_DAYS:raise ValueError('Select at most 371 calendar days')
        folder,plan,refs=self._source(capture_id)
        if not set(symbols)<=set(plan['symbols']):raise ValueError('Symbols not present in frozen archive plan')
        if not date.fromisoformat(plan['start'])<=start<=end<=date.fromisoformat(plan['end']):raise ValueError('Dates outside capture plan')
        calendar=pl.DataFrame(refs['trade_calendar'],schema=['calendar_date','is_trading_day'],orient='row')
        days=calendar_sessions(calendar,date.fromisoformat(plan['start']),end)
        if not any(start<=day<=end for day in days):raise ValueError('No observed calendar trading sessions')
        index=self.store.pack_index(capture_id);payloads={};manifests={};total=0
        for symbol in symbols:
            m=self.store.symbol_manifest(capture_id,symbol,deep=False)
            if m is None:raise ValueError('Requested symbol has no completed archive: '+symbol)
            if m['rows']>20000:raise ValueError('Archive row budget exceeded')
            manifests[symbol]=m
            if index is not None:
                entry=index['symbols'][symbol]
                refs_=[]
                for part,_,_ in PACK_PARTS:
                    name,offset,length=entry[part];safe_path(self.root,folder/'packs'/name)
                    if type(length) is not int or length<0 or total+length>MAX_INPUT_BYTES:raise ValueError('Archive byte budget exceeded')
                    total+=length;refs_.append((part,entry[part]))
                parts=self.store._read_slices(capture_id,index,refs_)
            else:
                parts={}
                for part,name,_ in PACK_PARTS:
                    path=safe_path(self.root,self.store._symbol_dir(capture_id,symbol)/name)
                    value=regular_bytes(path,MAX_INPUT_BYTES)
                    total+=len(value)
                    if total>MAX_INPUT_BYTES:raise ValueError('Archive byte budget exceeded')
                    parts[part]=value
            for part,_,key in PACK_PARTS:
                if sha(parts[part])!=m[key]:raise ValueError('Archive data changed: '+symbol+' '+part)
            with gzip.GzipFile(fileobj=io.BytesIO(parts['raw'])) as stream:raw_bytes=stream.read(32_000_001)
            if len(raw_bytes)>32_000_000:raise ValueError('Raw archive inflation budget exceeded')
            raw=json.loads(raw_bytes)
            if raw.get('symbol')!=symbol or tuple(raw.get('fields',()))!=FIELDS or digest(raw)!=m['content_hash']:
                raise ValueError('Raw archive identity/schema does not match manifest')
            normalized=normalize_symbol_rows(raw['rows'],symbol,date.fromisoformat(plan['start']),date.fromisoformat(plan['end']),{d for d,f in refs['trade_calendar'] if f=='1'})
            raw_frame=pl.DataFrame(normalized,schema=SCHEMA) if normalized else pl.DataFrame(schema=SCHEMA)
            saved=pl.read_parquet(io.BytesIO(parts['daily']))
            if saved.height!=m['rows'] or not saved.equals(raw_frame):raise ValueError('Raw response and typed daily archive disagree')
            payloads[symbol]=parts
        files={name:regular_bytes(safe_path(self.root,folder/name),MAX_INPUT_BYTES) for name in ('plan.json','reference/stock_basic.json.gz','reference/trade_calendar.json.gz')}
        evidence={'capture_id':capture_id,'capture_plan_sha256':sha(files['plan.json']),
                  'symbols':manifests,'input_bytes':total,'packed':index is not None,
                  'calendar_sha256':sha(files['reference/trade_calendar.json.gz']),
                  'stock_basic_sha256':sha(files['reference/stock_basic.json.gz'])}
        return payloads,files,evidence,days,start,end
    def inspect(self,capture_id,symbols,start,end):
        payloads,_,evidence,days,lo,hi=self.load(capture_id,symbols,start,end)
        summaries=[]
        for symbol,parts in payloads.items():
            frame=pl.read_parquet(io.BytesIO(parts['daily'])).filter(pl.col('date').is_between(lo,hi))
            summaries.append({'symbol':symbol,'rows':frame.height,'null_counts':{k:frame[k].null_count() for k in FIELDS},
                'st_rows':frame.filter(pl.col('isST')==1).height,'suspended_rows':frame.filter(pl.col('tradestatus')==0).height,
                'examples':frame.head(2).to_dicts()+frame.tail(2).to_dicts()})
        return {'capture_id':capture_id,'start':start,'end':end,'symbols':summaries,'source_evidence':evidence,
                'raw_and_typed_bytes_verified':True,'strict_pit_qualified':False,'missing_qm50_fields':MISSING_FIELDS,'limitations':LIMITATIONS}


def materialize_rows(payloads,manifests,calendar,start,end):
    """Keep one row per requested symbol-session, including explicit absence.

    PREP dependencies use exact D-1/D-2 from calendar. Current-day close is never
    promoted to PREP; separately named vendor fields are retrospective observations.
    """
    records=[];positions={day:i for i,day in enumerate(calendar)}
    for symbol,parts in payloads.items():
        frame=pl.read_parquet(io.BytesIO(parts['daily']));by_day={r['date']:r for r in frame.to_dicts()}
        m=manifests[symbol]
        for day in (d for d in calendar if start<=d<=end):
            pos=positions[day];previous=calendar[pos-1] if pos else None;prior=by_day.get(previous)
            row={'symbol':symbol,'decision_date':day.isoformat(),'previous_session':previous.isoformat() if previous else None,
                'row_status':'PRESENT_RETROSPECTIVE' if prior else 'MISSING_SOURCE',
                'source_capture_id':m['capture_id'],'source_daily_sha256':m['parquet_sha256'],'source_fetched_at':m['fetched_at'],
                'historical_available_at':None,'strict_pit_qualified':False,'candidate_for_D':None,'P01':None,'P06':None,
                'reference_price':None,'upper_limit_price':None,'lower_limit_price':None,'tick_size':None,
                'P07_raw':None,'P07_status':'MISSING_SOURCE','score':None,'Q':None}
            for key in FIELDS:
                if key not in ('date','code'):row['previous_'+SOURCE_FIELDS.get(key,key)]=prior.get(key) if prior else None
            if prior:
                # These labels concern D-1's actual provider row, never D eligibility.
                row['previous_provider_state']='SUSPENDED' if prior['tradestatus']==0 else ('ST' if prior['isST']==1 else 'TRADING_NON_ST')
            else:row['previous_provider_state']='UNKNOWN'
            past=calendar[max(0,pos-21):pos]
            values=[by_day.get(d) for d in past]
            if len(past)<21:row['P07_status']='INSUFFICIENT_HISTORY'
            elif all(v is not None and v['tradestatus']==1 and v['volume'] is not None and v['volume']>0 for v in values):
                from quantlab.trading.qm50_contract import previous_relative_amount
                value=previous_relative_amount(values[-1]['amount'],[v['amount'] for v in values[:-1]])
                row.update(P07_raw=value['value'],P07_status=value['status'])
            records.append(row)
    return pl.DataFrame(records)


def materialize(bridge,capture_id,symbols,start,end,folder):
    payloads,files,evidence,days,lo,hi=bridge.load(capture_id,symbols,start,end)
    frozen=folder/'inputs';frozen.mkdir()
    saved={}
    for name,payload in files.items():
        path=frozen/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payload);saved[name]=sha(payload)
    for symbol,parts in payloads.items():
        for part,filename,_ in PACK_PARTS:
            name='symbols/'+symbol+'/'+filename;path=frozen/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(parts[part]);saved[name]=sha(parts[part])
    (frozen/'source-manifests.json').write_text(encode(evidence));saved['source-manifests.json']=sha((frozen/'source-manifests.json').read_bytes())
    rows=materialize_rows(payloads,evidence['symbols'],days,lo,hi)
    rows.write_parquet(folder/'observations.parquet')
    return {'method':VERSION,'status':'MATERIALIZED_RETROSPECTIVE_INPUTS','capture_id':capture_id,
        'symbols':symbols.replace(',', ' ').split(),'start':start,'end':end,'rows':rows.height,'calendar_sessions':len([d for d in days if lo<=d<=hi]),
        'previous_state_counts':dict(Counter(rows['previous_provider_state'].to_list())),
        'P07_counts':dict(Counter(rows['P07_status'].to_list())),
        'input_fields_loaded':list(FIELDS),'source_evidence':evidence,'frozen_files':saved,
        'examples':rows.head(2).to_dicts()+rows.tail(2).to_dicts(),'missing_qm50_fields':MISSING_FIELDS,
        'candidate_rows_generated':False,'full_model_backtest':False,'strict_pit_qualified':False,'limitations':LIMITATIONS}


def replay(folder,detail):
    folder=Path(folder)
    if folder.is_symlink():raise ValueError('Test folder symlink')
    folder=folder.resolve()
    frozen=folder/'inputs'
    for name,expected in detail['frozen_files'].items():
        path=safe_path(folder,frozen/name)
        if sha(regular_bytes(path,MAX_INPUT_BYTES))!=expected:raise ValueError('Frozen input changed: '+name)
    evidence=json.loads((frozen/'source-manifests.json').read_text())
    plan=json.loads((frozen/'plan.json').read_text());calendar=json.loads(gzip.decompress((frozen/'reference/trade_calendar.json.gz').read_bytes()))
    frame=pl.DataFrame(calendar['rows'],schema=['calendar_date','is_trading_day'],orient='row')
    days=calendar_sessions(frame,date.fromisoformat(plan['start']),date.fromisoformat(detail['end']))
    requested=detail['symbols']
    if len(requested)!=len(set(requested)) or set(requested)!=set(evidence['symbols']):raise ValueError('Frozen requested symbol list differs from input manifest')
    payloads={s:{part:(frozen/'symbols'/s/name).read_bytes() for part,name,_ in PACK_PARTS} for s in requested}
    recomputed=materialize_rows(payloads,evidence['symbols'],days,date.fromisoformat(detail['start']),date.fromisoformat(detail['end']))
    stored=pl.read_parquet(folder/'observations.parquet')
    return {'method':VERSION,'rows':stored.height,'equal':recomputed.equals(stored),'external_source_required':False,
            'compares':'all materialized rows, provider fields, exact D-1 mapping, nulls and P07 formula; not Alpha'}

"""Explicit research-only view of DATA-published qfq and retrospective daily status.

Copies exact published source bytes. Does not adjudicate corporate actions, fill
prices/volume, certify PIT, fetch data, or supply account valuation marks.
"""
from __future__ import annotations
from datetime import date, time
from pathlib import Path
import hashlib
import io
import json
import os
import re
import stat

import polars as pl
import pyarrow.parquet as pq
from quantlab.data.base import DataBatch, DataRequest, DataSnapshot
from quantlab.data.dataset_registry import load_registry
from quantlab.data.validation import PUBLISHED_RESEARCH_CONTRACT, ordered_bars
from quantlab.domain import Timeframe
from quantlab.storage.codec import digest, encode

MARKER = 'published-daily-research.json'
PENDING = 'published-daily-research.pending.json'
FORMAT = 'niuniu-published-qfq-research-v1'
MAX_SYMBOLS = 200
MAX_DAYS = 1100
MAX_ROWS = 220000
MAX_FILE = 64_000_000
MAX_TOTAL = 512_000_000
QFQ = 'lake/silver/qfq_kline_daily_v2'
STATUS = 'lake/bronze/provider=baostock/daily_status_v2'
SNAPSHOT = 'lake/bronze/provider=baostock/reference_snapshots/snapshot=2026-09-23'
LIMITATIONS = [
    'DATA published retrospective qfq and daily status; research_only, not Strict PIT.',
    'Current survivor universe and DATA coverage selection can bias the sample; no blind-holdout certification.',
    'tradestatus=0 masks research OHLC, retains every session and exact original source bytes; no filling or compression.',
    'No vendor_previous_close is available in this publication; this input is forbidden for account valuation or execution.',
    'isST is retained, not filtered or certified tradable. Nominal 15:00 availability is not publication-time evidence.',
    'No raw fallback, factor reconstruction, corporate-action adjudication, or alternate-source discovery.',
]


def _root(root):
    path=Path(root).absolute()
    for p in (path,*path.parents):
        if p.is_symlink():raise ValueError('Published research paths cannot contain symlinks')
    if not path.is_dir():raise ValueError('Published research root is not a directory')
    return path


def _read(root, relative, maximum=MAX_FILE):
    rel=Path(relative)
    if rel.is_absolute() or '..' in rel.parts or '\\' in str(relative):raise ValueError('Invalid published input relative path')
    path=root/rel
    for p in (path,*path.parents):
        if p==root.parent:break
        if p.is_symlink():raise ValueError('Published input symlink refused')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size>maximum:raise ValueError('Published file size/type exceeds budget')
        with os.fdopen(fd,'rb',closefd=False) as f:payload=f.read(maximum+1)
        after=os.fstat(fd);current=path.stat()
        identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        if len(payload)!=before.st_size or identity(before)!=identity(after) or identity(before)!=identity(current):raise ValueError('Published source changed while reading')
        return payload
    finally:os.close(fd)


def _request(symbols, start, end):
    if not isinstance(start,date):start=date.fromisoformat(start)
    if not isinstance(end,date):end=date.fromisoformat(end)
    symbols=tuple(symbols)
    if not 1<=len(symbols)<=MAX_SYMBOLS or len(set(symbols))!=len(symbols):raise ValueError('Published research requires 1-200 unique securities')
    if any(not isinstance(s,str) or not re.fullmatch(r'(?:sh|sz)\.\d{6}',s) for s in symbols):raise ValueError('Invalid published security code')
    if not 1<=(end-start).days+1<=MAX_DAYS:raise ValueError('Published research interval exceeds 1100 days')
    return tuple(sorted(symbols)),start,end


def _table(content):
    metadata=pq.ParquetFile(io.BytesIO(content)).metadata
    if metadata.num_rows>50000 or metadata.num_columns>64 or sum(metadata.row_group(i).total_byte_size for i in range(metadata.num_row_groups))>256_000_000:
        raise ValueError('Published parquet decoded size exceeds budget')
    return pl.read_parquet(io.BytesIO(content))


def _normalize(payloads,symbols,start,end):
    calendar=_table(payloads['calendar.parquet'])
    required={'calendar_date','is_trading_day'}
    if not required<=set(calendar.columns):raise ValueError('Published calendar schema mismatch')
    selected=calendar.filter(pl.col('calendar_date').is_between(pl.lit(start.isoformat()),pl.lit(end.isoformat())))
    if selected['calendar_date'].null_count() or selected['calendar_date'].n_unique()!=selected.height:raise ValueError('Duplicate/missing calendar key')
    if selected.height!=(end-start).days+1 or selected.filter(~pl.col('is_trading_day').is_in(['0','1'])|pl.col('is_trading_day').is_null()).height:raise ValueError('Published calendar does not cover full requested interval')
    sessions=selected.filter(pl.col('is_trading_day')=='1')['calendar_date'].to_list()
    expected=set(sessions)
    if not sessions or len(symbols)*len(sessions)>MAX_ROWS:raise ValueError('Published normalized row budget exceeded')
    coverage=_table(payloads['coverage.parquet'])
    if not {'code','valid_from','history_truncated'}<=set(coverage.columns):raise ValueError('Published coverage schema mismatch')
    if coverage['code'].null_count() or coverage['code'].n_unique()!=coverage.height:raise ValueError('Duplicate/missing coverage code')
    cov={r['code']:r for r in coverage.to_dicts()};frames=[]
    for symbol in symbols:
        c=cov.get(symbol)
        if not c or type(c['history_truncated']) is not bool:raise ValueError('Published coverage missing/invalid for '+symbol)
        first=date.fromisoformat(c['valid_from'])
        if first>start:raise ValueError('DATA qfq unavailable for requested start: '+symbol)
        bar=_table(payloads['bars/'+symbol+'.parquet'])
        state=_table(payloads['status/'+symbol+'.parquet'])
        if not {'date','code','open','high','low','close','volume','amount','factor'}<=set(bar.columns):raise ValueError('Published qfq schema mismatch: '+symbol)
        if not {'date','code','tradestatus','isST'}<=set(state.columns):raise ValueError('Published status schema mismatch: '+symbol)
        for frame in (bar,state):
            if frame['code'].null_count() or frame.filter(pl.col('code')!=symbol).height:raise ValueError('Published file security identity mismatch')
        bar_date=pl.col('date').str.to_date() if bar.schema['date']==pl.String else pl.col('date').cast(pl.Date)
        state_date=pl.col('date').str.to_date() if state.schema['date']==pl.String else pl.col('date').cast(pl.Date)
        bar=bar.with_columns(bar_date).filter(pl.col('date').is_between(start,end))
        state=state.with_columns(state_date).filter(pl.col('date').is_between(start,end))
        for frame in (bar,state):
            if frame['date'].null_count() or frame['date'].n_unique()!=frame.height or {d.isoformat() for d in frame['date']}!=expected:raise ValueError('Published session coverage mismatch: '+symbol)
        joined=bar.join(state.select('date','code','tradestatus','isST'),on=['date','code'],validate='1:1')
        for name in ('tradestatus','isST'):
            if joined[name].null_count() or joined.filter(~pl.col(name).cast(pl.String).is_in(['0','1'])).height:raise ValueError('Published daily status is unknown: '+symbol)
        if joined['factor'].null_count() or joined.filter(~pl.col('factor').is_finite()|(pl.col('factor')<=0)).height:raise ValueError('Invalid published qfq factor')
        if joined.filter(pl.any_horizontal([pl.col(k).is_not_null() & (~pl.col(k).is_finite() | (pl.col(k)<=0)) for k in ('open','high','low','close')])).height:
            raise ValueError('Invalid published source OHLC')
        suspended=pl.col('tradestatus').cast(pl.UInt8)==0
        if joined.filter(suspended & pl.any_horizontal([pl.col(k).is_not_null()&(pl.col(k)!=0) for k in ('volume','amount')])).height:raise ValueError('Suspended source has nonzero activity: '+symbol)
        stamp=pl.col('date').dt.combine(time(15)).dt.replace_time_zone('Asia/Shanghai')
        frames.append(joined.select(pl.col('code').alias('symbol'),pl.lit(symbol[:2]).alias('exchange'),stamp.alias('datetime'),stamp.alias('available_at'),pl.lit('1d').alias('timeframe'),
            *[pl.when(suspended).then(None).otherwise(pl.col(k)).cast(pl.Float64).alias(k) for k in ('open','high','low','close')],
            pl.col('volume').cast(pl.Float64),pl.col('amount').cast(pl.Float64).alias('turnover'),pl.col('factor').cast(pl.Float64).alias('adj_factor'),
            pl.col('tradestatus').cast(pl.UInt8).alias('bs_trade_status'),pl.col('isST').cast(pl.UInt8).alias('bs_is_st'),pl.lit(PUBLISHED_RESEARCH_CONTRACT).alias('input_contract')))
    return ordered_bars(pl.concat(frames))


def _build(source_root,symbols,start,end):
    root=_root(source_root);symbols,start,end=_request(symbols,start,end)
    registry=load_registry(root)
    if registry is None:raise ValueError('Published input requires the DATA registry')
    qfq=registry.entry('bars.daily.qfq')
    if qfq.get('status')!='current' or qfq.get('qualification')!='research_only' or qfq.get('path')!=QFQ:raise ValueError('DATA published qfq contract changed; do not fall back')
    paths={'coverage.parquet':QFQ+'/_meta/coverage.parquet','calendar.parquet':SNAPSHOT+'/trade_calendar.parquet'}
    for s in symbols:
        paths['bars/'+s+'.parquet']=QFQ+'/'+s.replace('.','_')+'.parquet'
        paths['status/'+s+'.parquet']=STATUS+'/'+s.replace('.','_')+'.parquet'
    payloads={};entries=[];total=0
    for rel,source in paths.items():
        blob=_read(root,source);total+=len(blob)
        if total>MAX_TOTAL:raise ValueError('Published input total byte budget exceeded')
        payloads[rel]=blob;entries.append({'path':rel,'source_path':str(root/source),'sha256':hashlib.sha256(blob).hexdigest(),'bytes':len(blob)})
    bars=_normalize(payloads,symbols,start,end)
    if load_registry(root).sha256!=registry.sha256:raise ValueError('DATA registry changed during preview')
    plan={'format':FORMAT,'symbols':list(symbols),'start':start.isoformat(),'end':end.isoformat(),'adjustment':'qfq','qualification':'research_only','input_contract':PUBLISHED_RESEARCH_CONTRACT,
          'source_registry_sha256':registry.sha256,'files':entries,'source_bytes':total,'rows':bars.height,'suspended_rows':bars.filter(pl.col('bs_trade_status')==0).height,'st_rows':bars.filter(pl.col('bs_is_st')==1).height,
          'execution_allowed':False,'limitations':LIMITATIONS}
    plan['dataset_id']=digest(plan)
    return plan,payloads


def preview(source_root,symbols,start,end):
    return _build(source_root,symbols,start,end)[0]


def export(source_root,symbols,start,end,destination,*,expected_digest,confirm_create=False):
    if confirm_create is not True:raise ValueError('Explicit host confirmation required')
    plan,payloads=_build(source_root,symbols,start,end)
    if plan['dataset_id']!=expected_digest:raise ValueError('Published input changed since preview')
    target=Path(destination).absolute();_root(target.parent)
    if target.is_relative_to(_root(source_root)):raise ValueError('Export must not write inside the DATA source root')
    target.mkdir(exist_ok=False)
    with (target/PENDING).open('x') as f:f.write('Input export incomplete; never use MQC fallback.')
    for rel,blob in payloads.items():
        file=target/rel;file.parent.mkdir(parents=True,exist_ok=True)
        with file.open('xb') as f:f.write(blob)
    with (target/MARKER).open('x',encoding='utf-8') as f:f.write(encode(plan))
    (target/PENDING).unlink()
    inspect(target)  # Independent readback, still no research or authority changes.
    return plan


def inspect(root):
    root=_root(root)
    if (root/PENDING).exists() or (root/PENDING).is_symlink():raise ValueError('Published input export incomplete')
    blob=_read(root,MARKER,2_000_000);manifest=json.loads(blob)
    if manifest.get('format')!=FORMAT or manifest.get('adjustment')!='qfq' or manifest.get('qualification')!='research_only' or manifest.get('execution_allowed') is not False or manifest.get('input_contract')!=PUBLISHED_RESEARCH_CONTRACT:raise ValueError('Invalid published input contract')
    body=dict(manifest);stored=body.pop('dataset_id',None)
    if stored!=digest(body):raise ValueError('Published manifest checksum changed')
    symbols,start,end=_request(manifest['symbols'],manifest['start'],manifest['end'])
    expected={'calendar.parquet','coverage.parquet'}|{'bars/'+s+'.parquet' for s in symbols}|{'status/'+s+'.parquet' for s in symbols}
    entries=manifest['files']
    if not isinstance(entries,list) or len(entries)!=len(expected) or {e['path'] for e in entries}!=expected:raise ValueError('Published input file set mismatch')
    payloads={};total=0
    for e in entries:
        content=_read(root,e['path']);total+=len(content)
        if total>MAX_TOTAL or len(content)!=e['bytes'] or hashlib.sha256(content).hexdigest()!=e['sha256']:raise ValueError('Published input file hash/size changed')
        payloads[e['path']]=content
    bars=_normalize(payloads,symbols,start,end)
    if total!=manifest['source_bytes'] or bars.height!=manifest['rows'] or bars.filter(pl.col('bs_trade_status')==0).height!=manifest['suspended_rows'] or bars.filter(pl.col('bs_is_st')==1).height!=manifest['st_rows']:raise ValueError('Published input inventory changed')
    if blob!=_read(root,MARKER,2_000_000):raise ValueError('Published manifest changed while reading')
    return manifest,bars


class PublishedDailyResearchProvider:
    def __init__(self,root,adjustment='qfq'):
        self.root=_root(root)
        if adjustment!='qfq':raise ValueError('Published research input only supports declared qfq; no raw fallback')
    def load(self,request:DataRequest):
        manifest,bars=inspect(self.root)
        if request.timeframe!=Timeframe.DAILY or not set(request.symbols)<=set(manifest['symbols']) or request.start<date.fromisoformat(manifest['start']) or request.end>date.fromisoformat(manifest['end']):raise ValueError('Request outside published input contract')
        frame=bars.filter(pl.col('symbol').is_in(request.symbols)&pl.col('datetime').dt.date().is_between(request.start,request.end))
        frame=ordered_bars(frame)
        if json.loads(_read(self.root,MARKER,2_000_000))!=manifest:raise ValueError('Published manifest changed after normalization')
        files=tuple({**e,'path':str(self.root/e['path']),'input_contract':PUBLISHED_RESEARCH_CONTRACT} for e in manifest['files'])+({'path':str(self.root/MARKER),'sha256':hashlib.sha256(_read(self.root,MARKER,2_000_000)).hexdigest(),'input_contract':PUBLISHED_RESEARCH_CONTRACT},)
        return DataBatch(frame,DataSnapshot(digest({'dataset_id':manifest['dataset_id'],'request':request,'contract':PUBLISHED_RESEARCH_CONTRACT}),'data_published_qfq_research','qfq',files))


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description='Host-only published qfq/status research package; no downloads or execution')
    parser.add_argument('operation',choices=('preview','export','inspect'))
    parser.add_argument('--source-root');parser.add_argument('--symbols');parser.add_argument('--start');parser.add_argument('--end')
    parser.add_argument('--destination');parser.add_argument('--expected-digest');parser.add_argument('--confirm-create',action='store_true')
    args=parser.parse_args(argv)
    if args.operation=='inspect':
        if not args.destination:parser.error('inspect requires --destination')
        result=inspect(args.destination)[0]
    else:
        if not all((args.source_root,args.symbols,args.start,args.end)):parser.error('preview/export require source-root, symbols, start and end')
        symbols=tuple(args.symbols.replace(',',' ').split())
        if args.operation=='preview':result=preview(args.source_root,symbols,args.start,args.end)
        else:
            if not args.destination or not args.expected_digest or not args.confirm_create:parser.error('export requires destination, expected-digest and confirm-create')
            result=export(args.source_root,symbols,args.start,args.end,args.destination,expected_digest=args.expected_digest,confirm_create=args.confirm_create)
    print(encode(result));return 0


if __name__=='__main__':raise SystemExit(main())

"""Build a read-only research lake plus provenance-preserving reference tables."""
from datetime import date, timedelta
from pathlib import Path
import hashlib
import io
import json
import math
import polars as pl
from quantlab.storage.codec import encode, digest

FEATURES={'peTTM':'bs_pe_ttm','pbMRQ':'bs_pb_mrq','psTTM':'bs_ps_ttm',
    'pcfNcfTTM':'bs_pcf_ncf_ttm','turn':'bs_turn_pct',
    'tradestatus':'bs_trade_status','isST':'bs_is_st'}


def responses(directory,manifest):
    seen=set()
    for entry in manifest['responses']:
        relative=Path(entry['file'])
        if relative.is_absolute() or len(relative.parts)!=2 or relative.parts[0]!='raw' or '..' in relative.parts or entry['file'] in seen:
            raise ValueError('无效或重复原始响应路径')
        seen.add(entry['file']);path=directory/relative
        if path.is_symlink() or (directory/'raw').is_symlink():raise ValueError('原始响应不接受符号链接')
        if path.stat().st_size>100_000_000:raise ValueError('原始响应超过大小预算')
        raw=path.read_bytes();record=json.loads(raw)
        if hashlib.sha256(raw).hexdigest()!=entry['sha256'] or len(record['rows'])!=entry['rows']:
            raise ValueError('原始响应校验失败')
        if record['status']!=entry['status'] or record['query']['kind']!=entry['kind']:
            raise ValueError('响应状态或类别不一致')
        yield entry,record


def number(value,*,optional=False):
    if optional and value in ('',None):return None
    result=float(value)
    if not math.isfinite(result):raise ValueError('供应商返回非有限数值')
    return result


def daily_frame(rows,symbol,flag,start,end):
    normalized=[];seen=set()
    for row in rows:
        day=date.fromisoformat(row['date'])
        if row['code']!=symbol or row['adjustflag']!=flag or not start<=day<=end or day in seen:
            raise ValueError('日线证券、日期、复权标记或重复行不一致')
        seen.add(day)
        for key in ('tradestatus','isST'):
            if row[key] not in ('0','1'):raise ValueError('无效日线交易状态')
        normalized.append({**row,'date':day,
            **{k:number(row[k]) for k in ('open','high','low','close','volume','amount')},
            **{v:number(row.get(k),optional=True) for k,v in FEATURES.items()}})
    if not normalized:return None
    frame=pl.DataFrame(normalized).with_columns(*[pl.col(k).cast(pl.Float64) for k in FEATURES.values()])
    prices=['open','high','low','close']
    invalid=frame.filter((pl.min_horizontal(prices)<=0)|(pl.col('volume')<0)|(pl.col('amount')<0)
        |(pl.col('high')<pl.max_horizontal(prices))|(pl.col('low')>pl.min_horizontal(prices)))
    if invalid.height:raise ValueError('无效OHLCV原始值，未替换或填补')
    return frame.sort('date')


def build_dataset(directory,manifest):
    plan=manifest['plan'];raw_records=list(responses(directory,manifest))
    target=directory/'dataset';target.mkdir(exist_ok=False);files={};tables={};daily={}
    def save(path,frame):
        source=target/path;source.parent.mkdir(parents=True,exist_ok=True);frame.write_parquet(source)
        payload=source.read_bytes();files[path]={'sha256':hashlib.sha256(payload).hexdigest(),'bytes':len(payload),'rows':frame.height}
    for entry,record in raw_records:
        if entry['status'] not in ('received','no_data'):continue
        kind=entry['kind']
        if kind in ('daily_raw','daily_qfq'):
            daily[(kind,entry['symbol'])]=daily_frame(record['rows'],entry['symbol'],
                '3' if kind=='daily_raw' else '2',date.fromisoformat(plan['start']),date.fromisoformat(plan['end']))
        rows=[{**row,'_requested_date':record['query']['params'].get('date',record['query']['params'].get('day')),
            '_fetched_at':record['fetched_at'],'_historical_available_at':None,
            '_response_sha256':entry['sha256']} for row in record['rows']]
        if rows:tables.setdefault(kind,[]).append(pl.DataFrame(rows,infer_schema_length=None))
    for kind,parts in tables.items():save('research/'+kind+'.parquet',pl.concat(parts,how='diagonal_relaxed'))
    ready='daily_raw' in plan['datasets'];coverage=[]
    for symbol in plan['symbols']:
        base=daily.get(('daily_raw',symbol));adjusted=daily.get(('daily_qfq',symbol))
        if base is None:ready=False
        if 'daily_qfq' in plan['datasets'] and adjusted is None:ready=False
        item={'symbol':symbol,'raw_rows':0 if base is None else base.height,
            'qfq_rows':0 if adjusted is None else adjusted.height}
        coverage.append(item)
        if base is None:continue
        filename=symbol.replace('.','_')+'.parquet'
        save('lake/bronze/provider=baostock/stock_kline_daily/'+filename,base)
        if adjusted is not None:
            if adjusted['date'].to_list()!=base['date'].to_list():raise ValueError('原始和前复权日期不一致')
            # Ratios and trading flags always come from the unadjusted response.
            adjusted=adjusted.drop(list(FEATURES.values())).join(
                base.select('date',*FEATURES.values()),on='date',validate='1:1')
            save('lake/silver/qfq_kline_daily/'+filename,adjusted)
    calendar_ready=False
    if 'calendar' in tables:
        calendar=pl.concat(tables['calendar'],how='diagonal_relaxed')
        dates=calendar['calendar_date'].to_list()
        start=date.fromisoformat(plan['start']);end=date.fromisoformat(plan['end'])
        expected=[(start+timedelta(days=i)).isoformat() for i in range((end-start).days+1)]
        if sorted(dates)!=expected or any(v not in ('0','1') for v in calendar['is_trading_day']):
            raise ValueError('交易日历未完整覆盖请求日期，不能推断未知日期为休市')
        calendar_ready=True
        trading=set(calendar.filter(pl.col('is_trading_day')=='1')['calendar_date'].to_list())
        for item in coverage:
            frame=daily.get(('daily_raw',item['symbol']))
            received=set() if frame is None else set(frame['date'].cast(pl.String).to_list())
            item['absent_calendar_sessions']=sorted(trading-received)
    payload={'format':'baostock-dataset-v1','import_id':manifest['import_id'],'ready':ready,
        'plan':plan,'files':files,'features':FEATURES,'coverage':coverage,'calendar_ready':calendar_ready,
        'retrospective':True,'strict_pit':False,'daily_market_cap':False,'official_limits':False,
        'source_response_hashes':[r['sha256'] for r in manifest['responses']],
        'valuation_policy':'Raw daily provider figures; BAO factors must lag at least one observed bar.'}
    payload['checksum']=digest(payload);(target/'baostock-dataset.json').write_text(encode(payload))
    return {'ready':ready,'calendar_ready':calendar_ready,'path':str(target.resolve()),
        'tables':{k:sum(p.height for p in parts) for k,parts in tables.items()},'coverage':coverage}


def dataset_manifest(root):
    path=Path(root)/'baostock-dataset.json'
    if path.is_symlink() or path.stat().st_size>2_000_000:raise ValueError('无效数据集清单')
    raw=path.read_bytes();value=json.loads(raw)
    if value.get('format')!='baostock-dataset-v1' or value.get('checksum')!=digest({k:v for k,v in value.items() if k!='checksum'}):
        raise ValueError('Baostock数据集清单校验失败')
    if value.get('features')!=FEATURES:raise ValueError('不支持的数据字段版本')
    return value,{'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),
        'knowledge_policy':'retrospective_provider_data_not_strict_PIT'}


def check_dataset_file(root,path,payload,manifest):
    root=Path(root).resolve();path=Path(path)
    relative=path.relative_to(root).as_posix()
    if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('数据文件路径越出数据集')
    expected=manifest['files'].get(relative)
    if expected is None or expected['bytes']!=len(payload) or expected['sha256']!=hashlib.sha256(payload).hexdigest():
        raise ValueError('Baostock数据文件缺失或校验值变化：'+relative)


def read_table(dataset,kind):
    manifest,_=dataset_manifest(dataset);path=Path(dataset)/'research'/(kind+'.parquet')
    if 'research/'+kind+'.parquet' not in manifest['files']:raise ValueError('本批没有该数据表')
    payload=read_dataset_bytes(dataset,'research/'+kind+'.parquet',manifest)
    return pl.read_parquet(io.BytesIO(payload))


def read_dataset_bytes(root, relative, manifest):
    """Check a manifest path before reading, then verify exactly the decoded bytes."""
    import stat
    root = Path(root).resolve()
    if not isinstance(relative,str) or '\\' in relative:
        raise ValueError('无效数据集相对路径')
    parts = Path(relative)
    if parts.is_absolute() or '..' in parts.parts or parts.as_posix()!=relative:
        raise ValueError('数据文件路径越出数据集')
    expected = manifest['files'].get(relative)
    if not isinstance(expected,dict):raise ValueError('本批没有该数据文件')
    path = root
    for part in parts.parts:
        path = path/part
        if path.is_symlink():raise ValueError('数据路径不能包含符号链接')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size>150_000_000:
        raise ValueError('数据文件类型或大小超过预算')
    payload = path.read_bytes()
    check_dataset_file(root,path,payload,manifest)
    return payload

"""Read-only Strict PIT evidence coverage and retrospective-source inventory.

Coverage is diagnostic evidence presence, never a dataset-wide PIT certificate.
Only request-scoped qualification may claim strict_pit for a concrete study.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date,datetime
from pathlib import Path
import hashlib

import polars as pl
import pyarrow.parquet as pq

from quantlab.data.pit_evidence import KINDS,audit_pit_evidence

FORMAT='niuniu-strict-pit-coverage-v1'
SILVER_TABLES=('security_status','industry_membership','index_membership','security_master','market_rule_history','trading_calendar')


def _day(value):
    if isinstance(value,datetime):return value.date()
    if isinstance(value,date):return value
    if isinstance(value,str):return datetime.fromisoformat(value.replace('Z','+00:00')).date()
    raise ValueError('coverage date must be ISO date/datetime')


def _range(values):
    values=list(values)
    return {'min':min(values).isoformat(),'max':max(values).isoformat()} if values else {'min':None,'max':None}


def _receipt_summary(records,kind,symbols,start,end,limit):
    selected=[]
    for record in records:
        if record['kind']!=kind:continue
        row=record['statement'];effective=_day(row['effective_at'])
        if symbols and row['symbol'] not in symbols:continue
        if start and effective<start:continue
        if end and effective>end:continue
        selected.append((record,effective))
    years=defaultdict(list);all_symbols=set();published=[]
    for record,effective in selected:
        years[effective.year].append(record);all_symbols.add(record['statement']['symbol'])
        published.append(_day(record['published_at']))
    year_rows=[]
    for year in sorted(years):
        rows=years[year];names=sorted({r['statement']['symbol'] for r in rows})
        year_rows.append({'year':year,'statements':len(rows),'unique_symbols':len(names),
            'symbols':names[:limit],'symbols_omitted':max(0,len(names)-limit)})
    requested=sorted(symbols or ());covered=sorted(all_symbols & set(requested)) if requested else []
    return {'verified_statements':len(selected),'unique_symbols':len(all_symbols),
        'symbols':sorted(all_symbols)[:limit],'symbols_omitted':max(0,len(all_symbols)-limit),
        'effective_date_range':_range(effective for _,effective in selected),
        'publication_date_range':_range(published),'years':year_rows,
        'requested_symbols':len(requested) if requested else None,
        'requested_symbols_with_evidence':covered if requested else None,
        'requested_symbols_missing_evidence':sorted(set(requested)-all_symbols)[:limit] if requested else None,
        'missing_symbols_omitted':max(0,len(set(requested)-all_symbols)-limit) if requested else None}


def _metadata_date_range(files,column):
    mins=[];maxs=[]
    for path in files:
        pf=pq.ParquetFile(path);names=pf.schema_arrow.names
        if column not in names:continue
        idx=names.index(column)
        for rg in range(pf.metadata.num_row_groups):
            stats=pf.metadata.row_group(rg).column(idx).statistics
            if stats and stats.has_min_max:
                mins.append(stats.min);maxs.append(stats.max)
    return {'min':str(min(mins)) if mins else None,'max':str(max(maxs)) if maxs else None}


def _bars_inventory(root):
    folder=root/'lake/bronze/provider=baostock/stock_kline_daily'
    files=sorted(folder.glob('*.parquet')) if folder.is_dir() else []
    if len(files)>10000:raise ValueError('historical bar inventory exceeds 10000-file budget')
    catalog=root/'catalog/mqc.duckdb'
    if catalog.is_file() and not catalog.is_symlink():
        try:
            import duckdb
            with duckdb.connect(str(catalog),read_only=True) as con:
                tables={r[0] for r in con.execute('show tables').fetchall()}
                if 'bronze_stock_kline_daily' in tables:
                    names=[r[0] for r in con.execute("select column_name from information_schema.columns where table_name='bronze_stock_kline_daily' order by ordinal_position").fetchall()]
                    row=con.execute("select count(*), count(distinct code), min(date), max(date), min(fetch_ts), max(fetch_ts) from bronze_stock_kline_daily").fetchone()
                    return {'files':len(files),'rows':int(row[0]),'symbols':int(row[1]),
                        'date_range':{'min':str(row[2]) if row[2] else None,'max':str(row[3]) if row[3] else None},
                        'fetch_ts_range':{'min':row[4],'max':row[5]},'fields':names,
                        'files_with_tradestatus':len(files) if 'tradestatus' in names else 0,
                        'files_with_isST':len(files) if 'isST' in names else 0,
                        'files_with_fetch_ts':len(files) if 'fetch_ts' in names else 0,
                        'inventory_source':'read_only_catalog/mqc.duckdb',
                        'knowledge_policy':'historical OHLCV inventory only; fetch_ts is collection time, not historical publication time',
                        'strict_pit_certified':False}
        except (OSError,ValueError,TypeError):pass
    rows=0;tradestatus=0;isst=0;fetch_ts=0;common=None
    for path in files:
        pf=pq.ParquetFile(path);rows+=pf.metadata.num_rows;names=set(pf.schema_arrow.names)
        common=names if common is None else common&names
        tradestatus+=int('tradestatus' in names);isst+=int('isST' in names);fetch_ts+=int('fetch_ts' in names)
    return {'files':len(files),'rows':rows,'date_range':_metadata_date_range(files,'date'),
        'fields_present_in_all_files':sorted(common or ()),
        'files_with_tradestatus':tradestatus,'files_with_isST':isst,'files_with_fetch_ts':fetch_ts,
        'inventory_source':'parquet_metadata_fallback',
        'knowledge_policy':'historical OHLCV inventory only; fetch_ts is collection time, not historical publication time',
        'strict_pit_certified':False}


def _small_table(root,relative,kind):
    path=root/relative
    if path.is_symlink():raise ValueError(kind+' inventory path cannot be symlink')
    if not path.is_file():return {'present':False,'rows':0}
    if path.stat().st_size>150_000_000:raise ValueError(kind+' inventory file exceeds 150MB')
    frame=pl.read_parquet(path);result={'present':True,'rows':frame.height,'fields':frame.columns,
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    if 'code' in frame.columns:result['unique_codes']=frame['code'].n_unique()
    if kind=='stock_basic':
        dates=[date.fromisoformat(v) for v in frame['ipoDate'].to_list() if isinstance(v,str) and v]
        result.update(ipo_date_range=_range(dates),out_date_known=frame.filter(pl.col('outDate')!='').height,
            knowledge_policy='retrospective listing metadata; no historical known_at/publication chain')
    elif kind=='industry':
        snapshots=sorted(set(v for v in frame['updateDate'].to_list() if v))
        result.update(snapshot_dates=snapshots,nonempty_industry_rows=frame.filter(pl.col('industry')!='').height,
            knowledge_policy='provider snapshot(s), not a complete historical industry change log')
    return result


def _silver_inventory(root):
    result={}
    for name in SILVER_TABLES:
        folder=root/'lake/silver'/name
        files=sorted(folder.glob('**/*.parquet')) if folder.is_dir() else []
        result[name]={'files':len(files),'present':bool(files)}
        if files:
            result[name]['rows']=sum(pq.ParquetFile(path).metadata.num_rows for path in files)
    return result


def strict_pit_coverage(data_root,*,symbols=None,start=None,end=None,detail_limit=100):
    root=Path(data_root).resolve()
    if not root.is_dir():raise ValueError('Strict PIT coverage data root missing')
    symbols=tuple(dict.fromkeys(symbols or ()))
    if len(symbols)>5000 or any(not isinstance(s,str) or not s.strip() for s in symbols):
        raise ValueError('coverage symbols must contain at most 5000 nonempty strings')
    if type(detail_limit) is not int or not 1<=detail_limit<=500:raise ValueError('detail_limit must be 1–500')
    start=_day(start) if start is not None else None;end=_day(end) if end is not None else None
    if start and end and start>end:raise ValueError('coverage start cannot exceed end')
    audit=audit_pit_evidence(root);records=audit['records']
    from quantlab.data.pit_universe import audit_pit_universe
    universe_audit=audit_pit_universe(root)
    by_kind={kind:_receipt_summary(records,kind,set(symbols),start,end,detail_limit) for kind in KINDS}
    retrospective={'bars':_bars_inventory(root),
        'stock_basic':_small_table(root,'lake/bronze/provider=baostock/stock_basic/stock_basic.parquet','stock_basic'),
        'industry':_small_table(root,'lake/bronze/provider=baostock/industry/industry.parquet','industry'),
        'silver':_silver_inventory(root)}
    gaps=[]
    labels={'universe_eligibility':'历史市场资格','security_status':'历史 ST/*ST/停复牌状态','industry_membership':'历史行业变更','daily_market_cap':'每日真实市值'}
    for kind in KINDS:
        if by_kind[kind]['verified_statements']==0:
            gaps.append({'code':'NO_VERIFIED_'+kind.upper(),'kind':kind,'priority':'high',
                'message':'没有命中当前范围的严格回执：'+labels[kind]})
        missing=by_kind[kind]['requested_symbols_missing_evidence']
        if symbols and missing:
            gaps.append({'code':'REQUESTED_SYMBOLS_MISSING_'+kind.upper(),'kind':kind,'priority':'high',
                'count':len(missing)+by_kind[kind]['missing_symbols_omitted'],'sample':missing[:20]})
    if universe_audit['verified_receipts']==0:
        gaps.append({'code':'NO_VERIFIED_PIT_UNIVERSE_RECEIPTS','kind':'pit_universe_snapshot','priority':'high',
            'message':'没有完整逐交易日 PIT Universe v1 回执；零散 eligibility statement 不能证明全集无遗漏。'})
    if universe_audit['invalid_receipts']:
        gaps.append({'code':'INVALID_PIT_UNIVERSE_RECEIPTS','priority':'critical','count':universe_audit['invalid_receipts']})
    if audit['invalid_records']:
        gaps.append({'code':'INVALID_PIT_EVIDENCE_RECEIPTS','priority':'critical','count':audit['invalid_records']})
    bars=retrospective['bars']
    if bars['files'] and (bars['files_with_tradestatus']<bars['files'] or bars['files_with_isST']<bars['files']):
        gaps.append({'code':'HISTORICAL_STATUS_FIELDS_NOT_IN_BAR_LAKE','priority':'high',
            'message':'历史日线库不能替代 ST/停牌 eligibility 证据。'})
    industry=retrospective['industry']
    if industry.get('present') and len(industry.get('snapshot_dates',[]))<=1:
        gaps.append({'code':'INDUSTRY_SOURCE_IS_SNAPSHOT_ONLY','priority':'high',
            'message':'现有行业表不是历史变更链，禁止向过去回填。'})
    evidence_counts={kind:by_kind[kind]['verified_statements'] for kind in KINDS}
    total=sum(evidence_counts.values())+universe_audit['verified_receipts']
    status='NO_STRICT_EVIDENCE' if total==0 else ('PARTIAL_EVIDENCE' if any(v==0 for v in evidence_counts.values()) or universe_audit['verified_receipts']==0 else 'EVIDENCE_PRESENT_NOT_CERTIFIED_COMPLETE')
    return {'format':FORMAT,'status':status,'scope':{'symbols':list(symbols),'start':start.isoformat() if start else None,
        'end':end.isoformat() if end else None,'detail_limit':detail_limit},
        'strict_evidence':{'stored_records':audit['stored_records'],'verified_records':audit['verified_records'],
            'invalid_records':audit['invalid_records'],'by_kind':by_kind,'pit_universe_archive':universe_audit},'retrospective_inventory':retrospective,
        'gaps':gaps,'overall_strict_pit_coverage_ratio':None,'dataset_strict_pit_certified':False,
        'qualification_required_for_claim':True,
        'limitations':['Coverage reports evidence presence and source inventory, not event-history completeness.',
            'A statement receipt proves only one fact; complete-universe claims additionally require an exact-session PIT Universe v1 receipt.',
            'Only request-scoped qualify_research_data may certify a concrete study as strict_pit.',
            'Retrospective listing, current industry snapshots and bar collection timestamps never count as historical publication evidence.']}


__all__=['FORMAT','SILVER_TABLES','strict_pit_coverage']

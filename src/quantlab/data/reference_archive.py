"""Verified public reference archives; never infer historical publication times."""
import json
from pathlib import Path
from datetime import date,datetime
import polars as pl
from quantlab.storage.codec import digest


def load_reference_archive(manifest_path):
    path=Path(manifest_path).resolve();manifest=json.loads(path.read_text())
    if manifest.get('provider')!='baostock' or manifest.get('status')!='completed':raise ValueError('需要已完成的 Baostock 资料归档')
    records=[];seen=set()
    for entry in manifest['files']:
        relative=Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts or relative in seen:raise ValueError('资料清单路径无效或重复')
        seen.add(relative);source=(path.parent/relative).resolve()
        if not source.is_relative_to(path.parent):raise ValueError('资料文件越出归档目录')
        record=json.loads(source.read_text())
        if digest(record)!=entry['sha256'] or len(record['rows'])!=entry['rows']:raise ValueError('资料校验值或记录数不匹配：'+str(relative))
        if any(row.get('code')!=record['symbol'] for row in record['rows']):raise ValueError('资料响应证券不匹配')
        fetched=datetime.fromisoformat(record['fetched_at'])
        if fetched.tzinfo is None:raise ValueError('资料抓取时间缺少时区')
        if record.get('historical_available_at') is not None and datetime.fromisoformat(record['historical_available_at']).tzinfo is None:raise ValueError('历史发布时间缺少时区')
        records.append({**record,'source':str(source),'sha256':entry['sha256']})
    return manifest,records


def listing_reference(manifest_path,symbols):
    manifest,records=load_reference_archive(manifest_path);rows={}
    for record in records:
        if record['kind']!='basic' or record['symbol'] not in symbols:continue
        if len(record['rows'])!=1:raise ValueError('每只证券需要唯一基本资料')
        row=record['rows'][0]
        if row.get('type')!='1':raise ValueError('历史股票池仅接受股票基本资料')
        if record['symbol'] in rows and rows[record['symbol']]!=row:raise ValueError('基本资料冲突')
        date.fromisoformat(row['ipoDate'])
        if row.get('outDate'):date.fromisoformat(row['outDate'])
        rows[record['symbol']]=row
    if set(rows)!=set(symbols):raise ValueError('归档缺少所选股票基本资料：'+', '.join(sorted(set(symbols)-set(rows))))
    return pl.DataFrame([rows[s] for s in symbols]),{'reference_manifest':str(Path(manifest_path).resolve()),'reference_hash':digest(manifest),
        'knowledge_policy':'retrospective_listing_dates_NOT_point_in_time','daily_capitalization_ready':False,
        'limitations':'Uses only sourced IPO/delisting dates. Daily ST, suspension and industry remain retrospective observations; quarterly shares are never used as daily shares.'}


def reference_coverage(manifest_path):
    manifest,records=load_reference_archive(manifest_path);coverage={s:{'symbol':s,'basic':False,'industry_dates':set(),'status_dates':set(),'quarterly_reports':0,'publication_checks':[]} for s in manifest['symbols']}
    for record in records:
        if record['symbol'] not in coverage:raise ValueError('归档包含清单外证券')
        item=coverage[record['symbol']]
        if record['rows']:item['publication_checks'].append(record.get('historical_available_at') is not None)
        if record['kind']=='basic':item['basic']=bool(record['rows'])
        elif record['kind']=='industry' and record['rows']:item['industry_dates'].add(record['request']['date'])
        elif record['kind']=='daily_status':
            for row in record['rows']:
                date.fromisoformat(row['date'])
                if row.get('tradestatus') not in ('0','1') or row.get('isST') not in ('0','1'):raise ValueError('无效历史状态')
                item['status_dates'].add(row['date'])
        elif record['kind']=='quarterly_shares':item['quarterly_reports']+=len(record['rows'])
    return {'manifest':str(Path(manifest_path).resolve()),'reference_hash':digest(manifest),
        'daily_capitalization_ready':False,'official_price_bounds_ready':False,
        'symbols':[{**{k:v for k,v in item.items() if k!='publication_checks'},'historical_publication_known':bool(item['publication_checks']) and all(item['publication_checks']),'industry_dates':sorted(item['industry_dates']),'status_dates':sorted(item['status_dates']),
            'industry_unqueried_status_dates':len(item['status_dates']-item['industry_dates'])} for item in coverage.values()]}

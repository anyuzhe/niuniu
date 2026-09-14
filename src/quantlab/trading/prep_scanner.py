"""Conservative all-market PREP universe scan and versioned market-node routing."""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib, io, math

import polars as pl
import pyarrow.parquet as pq

from quantlab.storage.codec import digest
from quantlab.execution.rules import MarketRules
from quantlab.data.daily_market_archive import DailyMarketArchive,DailyMarketArchiveError
from .playbook_reconstruction import default_limit_rate

ROUTER_VERSION='market-node-router-v1-20260914'
ROUTER_ORIGIN='host_engineering_policy_not_expert_rule'


class PrepScanError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def _round_bound(previous, rate, up=True):
    value=Decimal(str(previous))*(Decimal('1')+(Decimal(str(rate)) if up else -Decimal(str(rate))))
    return float(value.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))


def _day(value,name):
    if isinstance(value,date):return value
    try:return date.fromisoformat(value)
    except (TypeError,ValueError):raise PrepScanError('INVALID_ARGUMENT',name+' 必须为 YYYY-MM-DD。') from None


def _symbol_from_path(path):
    name=path.stem
    if len(name)!=9 or name[2]!='_' or name[:2] not in ('sh','sz','bj') or not name[3:].isdigit():
        return None
    return name[:2]+'.'+name[3:]


def route_market_node(metrics):
    required=('breadth_up','breadth_down','limit_up_count','limit_down_count','max_limit_streak')
    if not isinstance(metrics,dict) or any(type(metrics.get(k)) is not int or metrics[k]<0 for k in required):
        return {'router_version':ROUTER_VERSION,'router_origin':ROUTER_ORIGIN,
            'market_node':'UNKNOWN','target_streak':None,'action':'UNKNOWN','reasons':['required_market_metrics_missing']}
    total=metrics['breadth_up']+metrics['breadth_down']
    if total<=0:
        return {'router_version':ROUTER_VERSION,'router_origin':ROUTER_ORIGIN,
            'market_node':'UNKNOWN','target_streak':None,'action':'UNKNOWN','reasons':['breadth_population_empty']}
    down_ratio=metrics['breadth_down']/total
    if metrics['limit_down_count']>=30 and down_ratio>=0.75:
        return {'router_version':ROUTER_VERSION,'router_origin':ROUTER_ORIGIN,
            'market_node':'EXTREME_RISK','target_streak':None,'action':'NO_TRADE',
            'reasons':[f"limit_down_count={metrics['limit_down_count']}",f'down_ratio={down_ratio:.4f}']}
    if metrics['limit_down_count']>=15 and down_ratio>=0.65 and metrics['max_limit_streak']<=4:
        return {'router_version':ROUTER_VERSION,'router_origin':ROUTER_ORIGIN,
            'market_node':'RETREAT_HIGH_RISK','target_streak':2,'action':'SCAN_TARGET_STREAK',
            'reasons':[f"limit_down_count={metrics['limit_down_count']}",f'down_ratio={down_ratio:.4f}',
                f"max_limit_streak={metrics['max_limit_streak']}"]}
    return {'router_version':ROUTER_VERSION,'router_origin':ROUTER_ORIGIN,
        'market_node':'UNKNOWN','target_streak':None,'action':'UNKNOWN',
        'reasons':['v1_policy_only_routes_extreme_or_retreat_high_risk']}


def _parquet_max_date(path):
    if path.is_symlink():raise PrepScanError('DATA_SCHEMA','日线文件不能是符号链接。')
    try:metadata=pq.ParquetFile(path).metadata
    except Exception as exc:raise PrepScanError('DATA_SCHEMA','无法读取Parquet元数据：'+str(path)) from exc
    maxima=[]
    for rg in range(metadata.num_row_groups):
        group=metadata.row_group(rg)
        for index in range(group.num_columns):
            column=group.column(index)
            if column.path_in_schema=='date' and column.statistics is not None and column.statistics.has_min_max:
                maxima.append(column.statistics.max)
    return max(maxima) if maxima else None


def _read_payload(path,managed_root=None,managed_manifest=None):
    if managed_manifest is not None:
        from quantlab.data.baostock_dataset import read_dataset_bytes
        relative=path.relative_to(managed_root).as_posix();payload=read_dataset_bytes(managed_root,relative,managed_manifest)
    else:payload=path.read_bytes()
    return payload,hashlib.sha256(payload).hexdigest()


def _load_symbol_rows(path,as_of,lookback,managed_root=None,managed_manifest=None):
    payload,sha=_read_payload(path,managed_root,managed_manifest)
    table=pq.read_table(io.BytesIO(payload))
    names=set(table.schema.names)
    required={'date','code','close','volume'}
    if not required<=names:raise PrepScanError('DATA_SCHEMA','日线文件缺少 date/code/close/volume。')
    columns=['date','code','close','volume']
    for optional in ('bs_trade_status','bs_is_st','tradestatus','isST','preclose','fetch_ts'):
        if optional in names:columns.append(optional)
    frame=pl.from_arrow(table.select(columns)).filter(pl.col('date')<=as_of).sort('date').tail(lookback)
    rows=frame.to_dicts()
    symbol=_symbol_from_path(path)
    if symbol is None or any(row['code']!=symbol for row in rows):
        raise PrepScanError('DATA_SCHEMA','证券文件名与 code 不一致。')
    managed_status=bool({'bs_trade_status','bs_is_st'}<=set(frame.columns) or {'tradestatus','isST'}<=set(frame.columns))
    return symbol,rows,sha,managed_status


def _has_status(row):
    return (('bs_trade_status' in row and 'bs_is_st' in row) or
        ('tradestatus' in row and 'isST' in row))


def _status(row):
    if _has_status(row):
        trade=row.get('bs_trade_status',row.get('tradestatus'))
        st=row.get('bs_is_st',row.get('isST'))
        tradable=bool(trade==1 or trade==1.0 or trade=='1')
        is_st=bool(st==1 or st==1.0 or st=='1')
        return tradable,is_st
    volume=row.get('volume')
    return bool(volume is not None and float(volume)>0),False


def _rule_for(rules,symbol,day):
    if rules is None:return None
    opening=datetime.combine(day,time(9,30),ZoneInfo('Asia/Shanghai'))
    return rules.at(symbol,opening)


def _annotate(rows,symbol,rules):
    annotated=[];previous=None;rule_gaps=0
    for row in rows:
        day=row['date'];tradable,is_st=_status(row)
        close_value=row.get('close');close=float(close_value) if close_value is not None else None
        explicit_pre=row.get('preclose')
        reference=float(explicit_pre) if explicit_pre not in (None,'') and float(explicit_pre)>0 else previous
        rule=_rule_for(rules,symbol,day)
        if rules is not None:
            if rule is None:rule_gaps+=1;tradable=False;limit_up=limit_down=None
            else:
                tradable=not rule['suspended'];limit_up=rule['limit_up'];limit_down=rule['limit_down']
        elif reference is not None and tradable:
            rate=0.05 if is_st else default_limit_rate(symbol)
            limit_up=_round_bound(reference,rate,True);limit_down=_round_bound(reference,rate,False)
        else:limit_up=limit_down=None
        is_up=bool(tradable and close is not None and limit_up is not None and math.isclose(close,float(limit_up),abs_tol=1e-9))
        is_down=bool(tradable and close is not None and limit_down is not None and math.isclose(close,float(limit_down),abs_tol=1e-9))
        annotated.append({**row,'tradable':tradable,'is_st':is_st,'previous_trade_close':reference,
            'limit_up_price':limit_up,'limit_down_price':limit_down,'is_limit_up_close':is_up,'is_limit_down_close':is_down})
        if tradable and close is not None:previous=close
    return annotated,rule_gaps


def _trailing_streak(rows):
    streak=0
    for row in reversed(rows):
        if not row['tradable']:continue
        if row['is_limit_up_close']:streak+=1
        else:break
    return streak


def _active_as_of(rows,as_of):
    return next((row for row in reversed(rows) if row['date']==as_of),None)


def _candidate(symbol,row,streak,quality):
    return {'symbol':symbol,'eligibility_reasons':[f'{row["date"].isoformat()}收盘连续{streak}板'],
        'features':{'prior_streak':streak,'last_close':float(row['close']),
            'previous_trade_close':row['previous_trade_close'],'limit_up_price':row['limit_up_price'],
            'tradable':row['tradable'],'rule_quality':quality},'evidence_ids':[]}


def _daily_directory(root):
    return root/'lake/bronze/provider=baostock/stock_kline_daily'


def _daily_market_overlay(output,as_of,lookback_sessions):
    if output is None:return {},[],[]
    try:store=DailyMarketArchive(output)
    except DailyMarketArchiveError as exc:raise PrepScanError(exc.code,str(exc)) from None
    selected=[]
    for item in store.list_days(limit=min(5000,max(lookback_sessions*4,40))):
        day=date.fromisoformat(item['date'])
        if day<=as_of:selected.append(item)
        if len(selected)>=lookback_sessions:break
    selected.sort(key=lambda row:row['date'])
    by_symbol={};evidence=[]
    for item in selected:
        try:frame,manifest=store.read_frame(item['date'],item['snapshot_id'])
        except DailyMarketArchiveError as exc:raise PrepScanError(exc.code,str(exc)) from None
        evidence.append({'date':item['date'],'snapshot_id':item['snapshot_id'],
            'content_hash':manifest['content_hash'],'fetched_at':manifest['fetched_at'],'rows':manifest['rows']})
        for row in frame.select('date','code','close','preclose','volume','tradestatus','isST').to_dicts():
            by_symbol.setdefault(row['code'],[]).append(row)
    return by_symbol,selected,evidence


def scan_prep_universe(data_root,as_of_session,*,target_streak=None,market_rules=None,
        universe_symbols=None,universe_pit_verified=False,lookback_sessions=12,daily_market_output=None):
    root=Path(data_root).resolve();as_of=_day(as_of_session,'as_of_session')
    if type(lookback_sessions) is not int or not 3<=lookback_sessions<=60:
        raise PrepScanError('INVALID_ARGUMENT','lookback_sessions 必须为3–60。')
    if target_streak is not None and (type(target_streak) is not int or not 1<=target_streak<=10):
        raise PrepScanError('INVALID_ARGUMENT','target_streak 必须为1–10或None。')
    rules=MarketRules(market_rules) if isinstance(market_rules,list) else market_rules
    if rules is not None and not isinstance(rules,MarketRules):
        raise PrepScanError('INVALID_ARGUMENT','market_rules 必须是 MarketRules 或规则数组。')
    directory=_daily_directory(root)
    if directory.is_symlink() or not directory.is_dir():
        raise PrepScanError('DATA_NOT_FOUND','找不到原始日线目录。')
    managed_manifest=None
    if (root/'baostock-dataset.json').is_file():
        from quantlab.data.baostock_dataset import dataset_manifest
        managed_manifest,_=dataset_manifest(root)
    overlay_by_symbol,overlay_days,overlay_evidence=_daily_market_overlay(
        daily_market_output,as_of,lookback_sessions)
    overlay_symbols=set(overlay_by_symbol)
    if universe_symbols is None:
        path_map={}
        for path in sorted(directory.glob('*.parquet')):
            symbol=_symbol_from_path(path)
            if symbol:path_map[symbol]=path
        for symbol in overlay_symbols:path_map.setdefault(symbol,directory/(symbol.replace('.','_')+'.parquet'))
        paths=sorted(path_map.items())
        universe_mode='DISCOVERED_FILES_PLUS_DAILY_MARKET' if overlay_symbols else 'DISCOVERED_FILES'
    else:
        if not isinstance(universe_symbols,list) or not universe_symbols:
            raise PrepScanError('INVALID_ARGUMENT','universe_symbols 必须为非空数组或None。')
        seen=[]
        for symbol in universe_symbols:
            if not isinstance(symbol,str) or _symbol_from_path(Path(symbol.replace('.','_')+'.parquet'))!=symbol:
                raise PrepScanError('INVALID_ARGUMENT','universe_symbols 含无效证券。')
            if symbol not in seen:seen.append(symbol)
        paths=[(symbol,directory/(symbol.replace('.','_')+'.parquet')) for symbol in seen]
        universe_mode='EXPLICIT'
    if len(paths)>10000:
        raise PrepScanError('BUDGET_EXCEEDED','全市场证券数超过10000，拒绝静默截断。')
    stat_dates=[]
    for _,path in paths:
        if path.is_file():
            maximum=_parquet_max_date(path)
            if maximum is not None:stat_dates.append(maximum)
    stat_dates.extend(date.fromisoformat(item['date']) for item in overlay_days)
    latest_available_session=max(stat_dates) if stat_dates else None
    if latest_available_session is not None and latest_available_session<as_of:
        raise PrepScanError('DATA_NOT_UPDATED',
            f'全市场日线最新日期为 {latest_available_session.isoformat()}，尚未更新到 {as_of.isoformat()}。')

    official_rules_verified=False;official_rule_receipt=None;unofficial_rule_sources=[]
    if rules is not None:
        from quantlab.data.qualification import _official_rule_receipt,_official_source
        unofficial_rule_sources=sorted({r['source'] for r in rules.records if not _official_source(r['source'])})
        official_rule_receipt=_official_rule_receipt(root,rules.snapshot_id)
        official_rules_verified=not unofficial_rule_sources and bool(official_rule_receipt.get('verified'))
    file_hashes=[];records=[];missing_files=[];stale_as_of_symbols=[];managed_status_count=0;rule_gaps=0
    for symbol,path in paths:
        rows=[];base_sha=None
        if path.is_file():
            loaded_symbol,rows,base_sha,_=_load_symbol_rows(
                path,as_of,lookback_sessions,root if managed_manifest is not None else None,managed_manifest)
            if loaded_symbol!=symbol:raise PrepScanError('DATA_SCHEMA','证券路径与解析结果不一致。')
            file_hashes.append({'symbol':symbol,'sha256':base_sha})
        overlay_rows=overlay_by_symbol.get(symbol,[])
        if not rows and not overlay_rows:
            missing_files.append(symbol);continue
        merged={row['date']:dict(row) for row in rows}
        for overlay in overlay_rows:
            old=merged.get(overlay['date'])
            if old is not None:
                for key in ('close','volume'):
                    left=old.get(key);right=overlay.get(key)
                    if left is not None and right is not None and not math.isclose(float(left),float(right),rel_tol=0,abs_tol=1e-9):
                        raise PrepScanError('DATA_REVISION_CONFLICT',f'{symbol} {overlay["date"]} 旧湖与DailyMarket {key} 不一致。')
                merged[overlay['date']]={**old,**overlay}
            else:merged[overlay['date']]=dict(overlay)
        rows=[merged[k] for k in sorted(merged) if k<=as_of][-lookback_sessions:]
        status_complete=bool(rows) and all(_has_status(row) for row in rows)
        managed_status_count+=int(status_complete)
        annotated,gaps=_annotate(rows,symbol,rules);rule_gaps+=gaps
        current=_active_as_of(annotated,as_of)
        if current is None:
            rule=_rule_for(rules,symbol,as_of)
            if not (rule is not None and rule['suspended']):stale_as_of_symbols.append(symbol)
            continue
        streak=_trailing_streak(annotated);previous=current['previous_trade_close']
        records.append({'symbol':symbol,'rows':annotated,'current':current,'streak':streak,
            'managed_status':status_complete,'previous':previous})

    if not records:
        raise PrepScanError('NO_AS_OF_DATA','指定 as_of_session 没有任何可扫描日线。')
    source_hash=digest({'files':file_hashes,'daily_market':overlay_evidence,
        'as_of_session':as_of.isoformat(),'lookback_sessions':lookback_sessions})
    breadth_up=breadth_down=limit_up_count=limit_down_count=0;max_streak=0
    candidate_counts={};candidates=[]
    for item in records:
        row=item['current'];streak=item['streak'];max_streak=max(max_streak,streak)
        if row['tradable'] and item['previous'] is not None:
            close=float(row['close']);previous=float(item['previous'])
            if close>previous:breadth_up+=1
            elif close<previous:breadth_down+=1
            limit_up_count+=int(row['is_limit_up_close']);limit_down_count+=int(row['is_limit_down_close'])
        if streak>0:candidate_counts[str(streak)]=candidate_counts.get(str(streak),0)+1
    metrics={'breadth_up':breadth_up,'breadth_down':breadth_down,'limit_up_count':limit_up_count,
        'limit_down_count':limit_down_count,'max_limit_streak':max_streak,
        'active_symbol_rows':len(records),'candidate_counts_by_streak':candidate_counts}
    route=route_market_node(metrics)
    status_known_all=managed_status_count==len(records)
    blockers=[]
    if missing_files:blockers.append('universe_files_missing')
    if stale_as_of_symbols:blockers.append('as_of_session_data_incomplete')
    if rules is None:
        blockers.append('official_market_rules_missing')
        if not status_known_all:blockers.append('historical_st_tradestatus_missing')
    else:
        if rule_gaps:blockers.append('official_market_rule_sessions_incomplete')
        if unofficial_rule_sources:blockers.append('market_rule_source_not_official_exchange_url')
        if official_rule_receipt is not None and not official_rule_receipt.get('verified'):
            blockers.append(official_rule_receipt.get('reason','official_rule_receipt_unverified'))
    if universe_mode!='EXPLICIT' or not universe_pit_verified:
        blockers.append('pit_universe_not_certified')
    completeness='FULL' if not blockers else 'PARTIAL'
    pit_status='STRICT_PIT' if not blockers else 'RETROSPECTIVE_REFERENCE'
    quality='OFFICIAL_RULES' if rules is not None and not rule_gaps and official_rules_verified else (
        'EXPLICIT_RULES_UNVERIFIED' if rules is not None and not rule_gaps else (
        'DAILY_MARKET_RETROSPECTIVE' if status_known_all and overlay_evidence else (
        'MANAGED_RETROSPECTIVE' if status_known_all else 'LEGACY_RETROSPECTIVE_ESTIMATE')))
    route={**route,'evidence_quality':pit_status}
    if route['action']=='NO_TRADE':
        effective_target=None;target_source='ROUTER_NO_TRADE'
    elif target_streak is not None:
        effective_target=target_streak;target_source='HOST_OVERRIDE'
    else:
        effective_target=route['target_streak'];target_source='ROUTER'
    if effective_target is not None:
        for item in records:
            if item['streak']==effective_target and item['current']['tradable']:
                candidates.append(_candidate(item['symbol'],item['current'],effective_target,quality))
    candidates.sort(key=lambda row:row['symbol'])
    return {'as_of_session':as_of.isoformat(),'latest_available_session':latest_available_session.isoformat() if latest_available_session else None,
        'universe_mode':universe_mode,'universe_file_count':len(paths),'active_symbol_rows':len(records),
        'missing_files':missing_files,'stale_as_of_symbols':stale_as_of_symbols,'managed_status_rows':managed_status_count,
        'daily_market_days':[item['date'] for item in overlay_days],
        'daily_market_snapshots':overlay_evidence,'daily_market_symbol_rows':sum(len(v) for v in overlay_by_symbol.values()),
        'source_hash':source_hash,'source_file_count':len(file_hashes),'rule_snapshot_id':rules.snapshot_id if rules else None,
        'rule_gaps':rule_gaps,'official_rules_verified':official_rules_verified,
        'official_rule_receipt':official_rule_receipt,'unofficial_rule_sources':unofficial_rule_sources,
        'quality':quality,'completeness':completeness,'pit_status':pit_status,
        'blockers':blockers,'market_metrics':metrics,'route':route,'target_streak':effective_target,
        'target_source':target_source,
        'candidates':candidates,'candidate_count':len(candidates),
        'scope':'PREP candidate generation only; router v1 is host engineering policy created 2026-09-14, not an extracted expert rule.'}


def prep_market_snapshot_content(scan,trading_day,as_of,data_root):
    trading=_day(trading_day,'trading_day').isoformat()
    if not isinstance(as_of,str):raise PrepScanError('INVALID_ARGUMENT','as_of 必须为带时区ISO时间。')
    try:moment=datetime.fromisoformat(as_of.replace('Z','+00:00'))
    except ValueError:raise PrepScanError('INVALID_ARGUMENT','as_of 必须为带时区ISO时间。') from None
    if moment.tzinfo is None:raise PrepScanError('INVALID_ARGUMENT','as_of 必须包含时区。')
    instruments=[]
    for item in scan['candidates']:
        f=item['features'];instruments.append({'symbol':item['symbol'],'previous_close':f['previous_trade_close'],
            'last':f['last_close'],'limit_up_price':f['limit_up_price'],'tradable':f['tradable'],
            'execution_profile':'UNKNOWN','metrics':{'prior_streak':f['prior_streak'],'rule_quality':f['rule_quality']}})
    metrics={**scan['market_metrics'],'route':scan['route'],'blockers':scan['blockers'],
        'quality':scan['quality'],'target_streak':scan['target_streak'],'target_source':scan['target_source']}
    return {'trading_day':trading,'frame':'PREP','as_of':moment.isoformat(),
        'provider':'niuniu-prep-universe-scan','provider_ref':str(Path(data_root).resolve()),
        'source_hash':scan['source_hash'],'completeness':scan['completeness'],'instruments':instruments,
        'market_metrics':metrics,'notes':'PREP全市场扫描；规则/Universe不足时保持PARTIAL/RETROSPECTIVE。'}


def build_prep_forward_payload(scan,snapshot,definition):
    if scan['route']['action']=='UNKNOWN' and scan['target_streak'] is None:
        raise PrepScanError('ROUTE_UNKNOWN','市场节点Router未给出目标身位；可保存PREP快照，但不能冻结CandidateSet。')
    evidence=['market_snapshot:'+snapshot['snapshot_id']]
    candidates=[]
    for item in scan['candidates']:
        candidates.append({**item,'evidence_ids':list(dict.fromkeys(item.get('evidence_ids',[])+evidence))})
    pit='STRICT_PIT' if scan['pit_status']=='STRICT_PIT' and snapshot.get('strict_pit_eligible') else 'RETROSPECTIVE_REFERENCE'
    action=scan['route']['action'];target=scan['target_streak']
    if action=='NO_TRADE' and target is None:candidates=[]
    return {'definition_id':definition['definition_id'],'trading_day':snapshot['trading_day'],'frame':'PREP',
        'as_of':snapshot['as_of'],'source_ids':definition['source_ids'],
        'market_snapshot_ids':[snapshot['snapshot_id']],
        'summary':f"PREP自动扫描：node={scan['route']['market_node']} target={target} action={action}",
        'notes':f"router={ROUTER_VERSION}; origin={ROUTER_ORIGIN}; blockers={','.join(scan['blockers']) or 'none'}",
        'candidate_set':{'completeness':scan['completeness'],'pit_status':pit,
            'universe_source':f"prep_universe_scan:{scan['source_hash']}",
            'generation_method':f"{ROUTER_VERSION}; target_source={scan['target_source']}",
            'candidates':candidates,'evidence_ids':evidence},
        'prediction':{'selected_symbols':[],'ranked_symbols':[], 'reasons':{},'evidence_ids':evidence,
            'notes':'PREP只冻结市场节点、目标身位和完整候选；不提前选择具体股票。'}}

__all__=['ROUTER_VERSION','ROUTER_ORIGIN','PrepScanError','route_market_node','scan_prep_universe',
    'prep_market_snapshot_content','build_prep_forward_payload']

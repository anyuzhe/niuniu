"""Read-only QM50 foundation evidence inspection; no receipt creation or fallback.

Global archive integrity is separated from exact-session/symbol coverage and from
QM50 field-contract completeness. Ordinary OHLCV is never a PIT certificate.
"""
from __future__ import annotations
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import io
import json
import re
import polars as pl

from quantlab.data.pit_evidence import audit_pit_evidence
from quantlab.data.pit_universe import audit_pit_universe, list_pit_universe_snapshots
from quantlab.data.security_status_coverage import audit_security_status_coverage, list_security_status_coverage_snapshots
from quantlab.data.official_rule_archive import audit_official_rule_archive
from quantlab.data.official_rule_reference import audit_official_rule_references
from quantlab.data.session_coverage import calendar_sessions
from quantlab.execution.rules import MarketRules
from quantlab.agent.local_data_tools import LocalMarketDataTools, MAX_TOTAL_BYTES
from quantlab.agent.research_specs import regular_bytes, sha
from quantlab.storage.codec import digest

ZONE=ZoneInfo('Asia/Shanghai')
SYMBOL=re.compile(r'(?:sh|sz)\.\d{6}')
ARCHIVES=('pit_evidence','pit_universe','security_status_coverage','official_market_rules','official_market_rule_references','official_rules')
MISSING_RULE_FIELDS=('reference_price','tick_size','board_asof','instrument_type_asof',
                     'delisting_arrangement','new_listing_no_limit_flag','normal_price_limit_regime')


def _aware(value):
    t=datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
    if not isinstance(t,datetime) or t.tzinfo is None:raise ValueError('Evidence timestamp must be timezone-aware')
    return t


def _safe(root,path):
    if not path.is_relative_to(root):raise ValueError('Evidence path outside configured data root')
    current=path
    while current!=root:
        if current.is_symlink():raise ValueError('Evidence archive symlink rejected')
        current=current.parent
    if not path.resolve().is_relative_to(root):raise ValueError('Evidence archive escaped data root')
    return path


def _archive_fingerprint(root):
    """Bound all receipt/document reads, including ancestors, before deep auditors."""
    files={};size=0
    for name in ARCHIVES:
        folder=_safe(root,root/'research'/name)
        if folder.exists() and not folder.is_dir():raise ValueError('Evidence archive is not a directory: '+name)
        for path in sorted(folder.rglob('*')) if folder.is_dir() else []:
            _safe(root,path)
            if path.is_dir():continue
            if path.name.startswith('.') or path.suffix in ('.tmp','.pending','.lock'):continue
            if not path.is_file():raise ValueError('Unsupported evidence file type')
            payload=regular_bytes(path,32_000_000)
            size+=len(payload)
            if len(files)>=5000 or size>256_000_000:raise ValueError('Evidence inspection exceeds 5000-file/256MB budget')
            files[path.relative_to(root).as_posix()]=sha(payload)
    legacy=_safe(root,root/'research/official_market_rules.json')
    if legacy.exists():files[legacy.relative_to(root).as_posix()]=sha(regular_bytes(legacy,32_000_000))
    return files


def _failure(name,exc):
    return {'status':'AUDIT_ERROR','audit_error':{'type':type(exc).__name__,'message':str(exc)[:240]},
            'verified_receipts':None,'invalid_receipts':None,'scope':name}


def _read_audits(root):
    functions={'pit_statements':audit_pit_evidence,'pit_universe':audit_pit_universe,
        'daily_security_status':audit_security_status_coverage,'official_rules':audit_official_rule_archive,
        'retrospective_rule_references':audit_official_rule_references}
    audits={}
    for key,function in functions.items():
        try:audits[key]=function(root)
        except (OSError,ValueError,KeyError,TypeError) as exc:audits[key]=_failure(key,exc)
    return audits


def _valid_universes(root,audits):
    a=audits['pit_universe']
    return [] if a.get('audit_error') or a.get('invalid_receipts') else list_pit_universe_snapshots(root)


def _valid_statuses(root,audits):
    a=audits['daily_security_status']
    return [] if a.get('audit_error') or a.get('invalid_receipts') or a.get('ambiguous_sessions') or a.get('branching_previous_snapshots') else list_security_status_coverage_snapshots(root)


def _rules(root,audit):
    if audit.get('audit_error') or audit.get('invalid_receipts'):return []
    if audit.get('snapshots_omitted'):raise ValueError('Official-rule audit list truncated; narrow archive or use a paged adapter')
    rows=[]
    for item in audit['snapshots']:
        path=_safe(root,root/'research/official_market_rules'/(item['rules_snapshot']+'.json'))
        raw=regular_bytes(path,32_000_000);receipt=json.loads(raw)
        rules=MarketRules(receipt['rules'])
        if rules.snapshot_id!=item['rules_snapshot']:raise ValueError('Official rule snapshot changed')
        for record in rules.records:
            rows.append({'record':record,'snapshot':item['rules_snapshot'],'receipt_sha256':sha(raw)})
    return rows


def _exact_universe(receipts,day,decision,exchange):
    matches=[r for r in receipts if r['effective_session']==day and exchange in r['scope']['exchanges']]
    if len(matches)!=1:return None,'MISSING' if not matches else 'AMBIGUOUS'
    r=matches[0]
    if max(_aware(r[k]) for k in ('available_at','created_at','cutoff_at'))>decision:return None,'NOT_YET_AVAILABLE'
    return r,'VERIFIED_EXACT_SESSION'


def _exact_status(receipts,universe,day,decision):
    if universe is None:return None,'MISSING_UNIVERSE_BINDING'
    matches=[r for r in receipts if r['effective_session']==day and r['universe_snapshot']==universe['universe_snapshot']]
    if len(matches)!=1:return None,'MISSING' if not matches else 'AMBIGUOUS'
    r=matches[0]
    if max(_aware(r[k]) for k in ('available_at','created_at','cutoff_at'))>decision:return None,'NOT_YET_AVAILABLE'
    if not r['strict_pit_eligible']:return None,'UNKNOWN_STATUS_IN_UNIVERSE'
    return r,'VERIFIED_EXACT_SESSION'


def _exact_rule(rows,symbol,session):
    day=date.fromisoformat(session);opening=datetime.combine(day,time(9,30),ZONE)
    knowledge_cutoff=datetime.combine(day,time(9,15),ZONE)
    available=[r for r in rows if r['record']['symbol']==symbol and
        r['record']['effective_at'].astimezone(ZONE).date()==day and
        r['record']['effective_at']<=opening and r['record']['available_at']<=knowledge_cutoff]
    if not available:return None,'MISSING'
    latest=max((r['record']['effective_at'],r['record']['available_at']) for r in available)
    matches=[r for r in available if (r['record']['effective_at'],r['record']['available_at'])==latest]
    distinct={digest(r['record']) for r in matches}
    if len(distinct)!=1:return None,'AMBIGUOUS'
    result=sorted(matches,key=lambda r:r['snapshot'])[0]
    if opening>=result['record']['expires_at']:return None,'EXPIRED_NO_OLDER_FALLBACK'
    return result,'VERIFIED_RECORD_NOT_FULL_QM50_CONTRACT'


def _raw_rows(root,symbols,start,end):
    local=LocalMarketDataTools(root);directory=local._directory('1d','raw')
    results={};sources=[];budget=[MAX_TOTAL_BYTES]
    for symbol in symbols:
        try:
            frame,source=local._read(directory/(symbol.replace('.','_')+'.parquet'),budget)
            needed={'date','code','open','high','low','close','volume','amount','adjustflag','fetch_ts'}
            if not needed<=set(frame.columns):raise ValueError('Missing raw daily fields: '+','.join(sorted(needed-set(frame.columns))))
            if frame['date'].null_count() or frame['date'].n_unique()!=frame.height or set(frame['code'])!={symbol}:raise ValueError('Raw daily dates or symbol identity invalid')
            if set(frame['adjustflag'])!={'3'}:raise ValueError('Not raw adjustflag=3')
            subset=frame.filter(pl.col('date').is_between(start,end))
            rows={r['date'].isoformat():r for r in subset.to_dicts()}
            results[symbol]={'rows':rows,'source':source};sources.append({'symbol':symbol,**source})
        except (OSError,ValueError,pl.exceptions.PolarsError) as exc:
            results[symbol]={'rows':{},'error':type(exc).__name__+': '+str(exc)[:200]}
    return results,sources


def inspect_base_coverage(data_root,symbols_text,start_text,end_text):
    supplied=Path(data_root)
    if supplied.is_symlink() or not supplied.is_dir():raise ValueError('Configured data root missing or symlink')
    root=supplied.resolve();symbols=symbols_text.replace(',',' ').split()
    if not 1<=len(symbols)<=10 or len(set(symbols))!=len(symbols) or any(not SYMBOL.fullmatch(s) for s in symbols):
        raise ValueError('Specify 1–10 unique Shanghai/Shenzhen symbols from actual local inventory')
    start,end=date.fromisoformat(start_text),date.fromisoformat(end_text)
    if not 0<=(end-start).days<31:raise ValueError('Foundation inspection requires 1–31 calendar days')
    before=_archive_fingerprint(root);audits=_read_audits(root)
    universes=_valid_universes(root,audits);statuses=_valid_statuses(root,audits);rules=_rules(root,audits['official_rules'])
    cal_path=_safe(root,root/'lake/bronze/provider=baostock/trade_calendar/calendar.parquet')
    cal_raw=regular_bytes(cal_path,32_000_000);cal=pl.read_parquet(io.BytesIO(cal_raw))
    sessions=calendar_sessions(cal,start-timedelta(days=30),end)
    requested=[d for d in sessions if start<=d<=end]
    if not requested:raise ValueError('No known trading sessions in selected range')
    indices={d:i for i,d in enumerate(sessions)}
    if any(indices[d]<2 for d in requested):raise ValueError('Insufficient calendar prefix for D-1/D-2')
    first=sessions[indices[requested[0]]-2]
    raw,sources=_raw_rows(root,symbols,first,end)
    sparse=audits['pit_statements'].get('records',[])
    matrix=[]
    for day in requested:
        pos=indices[day];previous=sessions[pos-1];day2=sessions[pos-2];decision=datetime.combine(day,time(9,15),ZONE)
        for symbol in symbols:
            exchange='SSE' if symbol.startswith('sh.') else 'SZSE';evidence=[];needed=[];details=[]
            for label,session in (('D',day),('D-1',previous),('D-2',day2)):
                session=session.isoformat();u,us=_exact_universe(universes,session,decision,exchange)
                st,ss=_exact_status(statuses,u,session,decision)
                member=any(m['symbol']==symbol for m in u['members']) if u else None
                state=next((r for r in st['records'] if r['symbol']==symbol),None) if st else None
                rule,rs=_exact_rule(rules,symbol,session)
                detail={'phase':label,'session':session,'universe':us,'status_coverage':ss,'member':member,'rule':rs}
                if u:evidence.append({'kind':'pit_universe','snapshot':u['universe_snapshot'],'session':session})
                if st:evidence.append({'kind':'security_status_coverage','snapshot':st['status_snapshot'],'session':session})
                if rule:evidence.append({'kind':'official_market_rules','snapshot':rule['snapshot'],'receipt_sha256':rule['receipt_sha256'],'session':session})
                if u is None:needed.append(label+':UNIVERSE_'+us)
                elif member is not True:needed.append(label+':NOT_IN_UNIVERSE')
                if state is None:needed.append(label+':DAILY_STATUS_'+ss)
                else:
                    detail.update(tradable=state['tradable'],risk_warning=state['risk_warning'])
                    if state['tradable'] is not True:needed.append(label+':SUSPENDED')
                    if state['risk_warning']!='NONE':needed.append(label+':RISK_WARNING_OUT_OF_SCOPE')
                if rule is None:needed.append(label+':OFFICIAL_RULE_'+rs)
                else:
                    r=rule['record'];detail.update(limit_up=r['limit_up'],limit_down=r['limit_down'],rule_suspended=r['suspended'],rule_st=r['st'])
                    if r['suspended']:needed.append(label+':SUSPENDED_RULE_NO_PRICE_BOUNDS_REQUIRED')
                    elif r['limit_up'] is None:needed.append(label+':UNBOUNDED_OR_UNKNOWN_REGIME')
                    if state and (r['suspended']==state['tradable'] or r['st']!=(state['risk_warning'] in ('ST','STAR_ST'))):needed.append(label+':STATUS_RULE_CONFLICT')
                if label!='D':
                    bar=raw[symbol]['rows'].get(session)
                    detail['raw_bar_status']='PRESENT_NOT_PIT' if bar else 'MISSING_OR_INVALID'
                    if bar:
                        detail['fetch_ts']=bar['fetch_ts']
                        if bar['volume'] is None or bar['volume']<=0:needed.append(label+':ZERO_OR_MISSING_VOLUME')
                    else:needed.append(label+':RAW_DAILY_MISSING_OR_INVALID')
                detail['sparse_status_statements_exact_session']=sum(r.get('kind')=='security_status' and r['statement']['symbol']==symbol and _aware(r['statement']['effective_at']).astimezone(ZONE).date().isoformat()==session for r in sparse)
                details.append(detail)
            needed.extend(['BAR_AVAILABLE_AT_UNVERIFIED','QM50_RULE_FIELDS_NOT_SUPPORTED','P01_STREAK_PREFIX_NOT_ESTABLISHED'])
            matrix.append({'symbol':symbol,'decision_date':day.isoformat(),'previous_session':previous.isoformat(),
                'decision_time':decision.isoformat(),'status':'BLOCKED','prev_limitup_height':None,'candidate_for_D':None,
                'ranking_eligible':False,'reason_codes':sorted(set(needed)),'session_checks':details,'evidence':evidence})
    if _archive_fingerprint(root)!=before:raise ValueError('Evidence archive changed during inspection')
    if sha(cal_path.read_bytes())!=sha(cal_raw):raise ValueError('Calendar changed during inspection')
    for item in sources:
        path=_safe(root,root/item['relative_file'])
        if sha(regular_bytes(path,32_000_000))!=item['sha256']:raise ValueError('Raw source changed during inspection')
    globals_={}
    for key,a in audits.items():
        globals_[key]={k:v for k,v in a.items() if k not in ('records','snapshots','invalid')}
        globals_[key]['snapshots']=a.get('snapshots',[])[:20];globals_[key]['invalid']=a.get('invalid',[])[:20]
        globals_[key]['snapshots_in_summary_omitted']=max(0,len(a.get('snapshots',[]))-20)+a.get('snapshots_omitted',0)
    counts=Counter(code for r in matrix for code in r['reason_codes'])
    summary={'scope':{'symbols':symbols,'start':start_text,'end':end_text,'decision_phase':'PREP_09:15_ASIA_SHANGHAI',
                     'sessions':len(requested),'symbol_sessions':len(matrix)},
        'global_archives':globals_,'requested_status':'BLOCKED','requested_candidate_count':None,
        'reason_counts':dict(counts),'records':matrix[:10],'records_omitted':max(0,len(matrix)-10),
        'raw_sources':sources,'raw_errors':{s:r['error'] for s,r in raw.items() if 'error' in r},
        'calendar_sha256':sha(cal_raw),'calendar_pit_verified':False,
        'archive_fingerprint':digest(before),'archive_files_checked':len(before),'source_bytes_unchanged':True,
        'missing_source_contract_fields':list(MISSING_RULE_FIELDS),
        'data_requests':[
            {'requirement':'exact_daily_universe','archive':'research/pit_universe','acceptance':'D/D-1/D-2 exact-session scope, prospective original bytes and existing deep verifier; no backfill'},
            {'requirement':'daily_security_status','archive':'research/security_status_coverage','acceptance':'Full member coverage bound to Universe; sparse statements do not carry forward'},
            {'requirement':'official_rule_fields','archive':'research/official_market_rules','acceptance':'Verified source records per symbol/session; add separately verified reference_price/tick/board/delisting/regime fields, never infer them from price or names'},
            {'requirement':'bar_available_at','acceptance':'Raw close/vintage and actual known_at before D decision; fetch_ts is collection time only'},
            {'requirement':'P01_prefix','acceptance':'Look back to an observable non-limit-up or defined interruption; leading all-limit-up window is censored, never a known height'}],
        'alpha_verified':False,'core_score_Q':None,'orders':False,'strict_pit_certificate':False,
        'limitations':['Global receipt integrity is not coverage of this request. D-1 and D-2 must not be replaced by calendar minus one/two.',
            'The current MarketRules schema has no reference_price/tick/board/delisting/normal-regime fields. Existing receipt validity does not supply those missing values.',
            'No new files are created in the data root; no downloading, archiving, receipt confirmation, state forward-fill or 1.1 price inference.',
            'D/D-1/D-2 is a dependency probe, not enough by itself to establish an arbitrary full consecutive-limit-up height.']}
    return matrix,summary

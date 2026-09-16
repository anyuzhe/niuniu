"""Complete daily SecurityStatus receipts and continuous transition chains.

The legacy PIT evidence archive proves individual status statements.  This v2
coverage contract proves that every member of one exact PIT Universe snapshot
has an explicit daily tradability and risk-warning state.  It is offline,
append-only, and prospective; absence from a sparse event archive is never
interpreted as a normal state.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date,datetime,time,timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import fcntl,hashlib,os,re

from quantlab.data.pit_universe import load_pit_universe_snapshot
from quantlab.experiments.campaign_state import read_checked,write_checked
from quantlab.storage.codec import digest

FORMAT='niuniu-security-status-coverage-v2'
PLAN_FORMAT='niuniu-security-status-coverage-plan-v2'
AUDIT_FORMAT='niuniu-security-status-coverage-audit-v2'
MAX_DOCUMENT_BYTES=32_000_000
MAX_SOURCES=200
MAX_RECORDS=20_000
DIMENSIONS=('TRADABILITY','RISK_WARNING')
RISK_WARNINGS=('NONE','ST','STAR_ST','UNKNOWN')
SCOPE_NOTE='Complete daily status only for every member of the referenced PIT Universe snapshot; no state is carried across an unlinked session.'
_PREFIX_EXCHANGE={'sh':'SSE','sz':'SZSE','bj':'BSE'}
_SOURCE_FIELDS={'source_id','exchange','url','coverage','published_at','available_at','document','sha256'}
_RECEIPT_SOURCE_FIELDS={'source_id','exchange','url','coverage','published_at','available_at','document'}
_RECORD_FIELDS={'symbol','tradable','risk_warning','source_ids'}
_DOCUMENT_FIELDS={'path','sha256','bytes'}
_TOP_FIELDS={'format','status_snapshot','created_at','effective_session','cutoff_at','available_at',
    'universe_snapshot','universe_member_count','universe_members_digest','scope',
    'previous_status_snapshot','previous_session_contiguous_confirmed','sources','records',
    'record_count','records_digest','unknown_risk_warning_count','publication_time_confirmed',
    'semantic_mapping_confirmed','complete_daily_status_confirmed','strict_pit_eligible','scope_note'}
_ID=re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$')
_SYMBOL=re.compile(r'^(sh|sz|bj)\.[0-9]{6}$')
_TZ=ZoneInfo('Asia/Shanghai')


class SecurityStatusCoverageError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def _aware(value,name):
    try:stamp=datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
    except ValueError:raise SecurityStatusCoverageError('INVALID_TIME',name+' must be timezone-aware ISO time') from None
    if not isinstance(stamp,datetime) or stamp.tzinfo is None:
        raise SecurityStatusCoverageError('INVALID_TIME',name+' must be timezone-aware ISO time')
    return stamp


def _session(value):
    try:return date.fromisoformat(value).isoformat()
    except (TypeError,ValueError):raise SecurityStatusCoverageError('INVALID_SESSION','effective_session must be YYYY-MM-DD') from None


def _snapshot_id(value,name='status_snapshot'):
    if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
        raise SecurityStatusCoverageError('INVALID_SNAPSHOT',name+' must be a lowercase SHA256')
    return value


def _exchange_for_url(value):
    try:
        parsed=urlparse(value);host=(parsed.hostname or '').lower()
    except (TypeError,ValueError):return None
    if parsed.scheme!='https':return None
    if host=='sse.com.cn' or host.endswith('.sse.com.cn'):return 'SSE'
    if host=='szse.cn' or host.endswith('.szse.cn'):return 'SZSE'
    if host=='bse.cn' or host.endswith('.bse.cn'):return 'BSE'
    return None


def _document_bytes(path):
    supplied=Path(path).expanduser()
    if supplied.is_symlink():raise SecurityStatusCoverageError('DOCUMENT_INVALID','status source document cannot be a symlink')
    target=supplied.resolve()
    if not target.is_file():raise SecurityStatusCoverageError('DOCUMENT_MISSING','status source document is missing')
    payload=target.read_bytes()
    if not payload or len(payload)>MAX_DOCUMENT_BYTES:
        raise SecurityStatusCoverageError('DOCUMENT_INVALID','status source document is empty or exceeds 32MB')
    return payload


def _paths(root):
    supplied=Path(root).expanduser()
    if supplied.is_symlink():raise SecurityStatusCoverageError('INVALID_DATA_ROOT','status coverage data root cannot be a symlink')
    root=supplied.resolve();research=root/'research';directory=research/'security_status_coverage';documents=directory/'documents'
    if not root.is_dir():raise SecurityStatusCoverageError('INVALID_DATA_ROOT','status coverage data root does not exist')
    if research.is_symlink() or directory.is_symlink() or documents.is_symlink():
        raise SecurityStatusCoverageError('INVALID_ARCHIVE','status coverage archive cannot be a symlink')
    if directory.exists() and not directory.is_dir():
        raise SecurityStatusCoverageError('INVALID_ARCHIVE','status coverage archive path is invalid')
    return root,directory,documents


@contextmanager
def _archive_lock(directory):
    directory.mkdir(parents=True,exist_ok=True);lock=directory/'.archive.lock'
    if directory.is_symlink() or lock.is_symlink():
        raise SecurityStatusCoverageError('INVALID_ARCHIVE','status coverage lock cannot be a symlink')
    with lock.open('a+b') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(stream,fcntl.LOCK_UN)


def _normalize_plan(root,plan):
    fields={'format','effective_session','cutoff_at','universe_snapshot','previous_status_snapshot','sources','records'}
    if not isinstance(plan,dict) or set(plan)!=fields or plan.get('format')!=PLAN_FORMAT:
        raise SecurityStatusCoverageError('INVALID_PLAN','security-status coverage plan schema is invalid')
    session=_session(plan['effective_session']);cutoff=_aware(plan['cutoff_at'],'cutoff_at')
    prep_close=datetime.combine(date.fromisoformat(session),time(9,15),_TZ)
    if cutoff>prep_close:
        raise SecurityStatusCoverageError('INVALID_CUTOFF','cutoff_at cannot be later than effective-session PREP close 09:15 Asia/Shanghai')
    universe_id=_snapshot_id(plan['universe_snapshot'],'universe_snapshot')
    try:universe=load_pit_universe_snapshot(root,universe_id,effective_session=session)
    except (OSError,ValueError,TypeError,KeyError) as exc:
        raise SecurityStatusCoverageError('UNIVERSE_INVALID','referenced PIT Universe snapshot is invalid: '+str(exc)) from None
    previous=plan.get('previous_status_snapshot')
    if previous is not None:_snapshot_id(previous,'previous_status_snapshot')
    sources=plan.get('sources')
    if not isinstance(sources,list) or not sources or len(sources)>MAX_SOURCES:
        raise SecurityStatusCoverageError('SOURCES_INVALID','one to 200 official status sources are required')
    normalized_sources=[];source_ids=set();coverage_by_exchange={exchange:set() for exchange in universe['scope']['exchanges']}
    for row in sources:
        if not isinstance(row,dict) or set(row)!=_SOURCE_FIELDS:
            raise SecurityStatusCoverageError('SOURCE_INVALID','status source schema is invalid')
        sid=row.get('source_id');exchange=row.get('exchange');coverage=row.get('coverage');url=row.get('url')
        if not isinstance(sid,str) or not _ID.fullmatch(sid) or sid in source_ids:
            raise SecurityStatusCoverageError('SOURCE_INVALID','source_id is invalid or duplicated')
        if exchange not in universe['scope']['exchanges'] or _exchange_for_url(url)!=exchange:
            raise SecurityStatusCoverageError('SOURCE_INVALID','source URL host must match its exchange and Universe scope')
        if (not isinstance(coverage,list) or not coverage or len(coverage)!=len(set(coverage))
                or any(value not in DIMENSIONS for value in coverage)):
            raise SecurityStatusCoverageError('SOURCE_INVALID','source coverage dimensions are invalid')
        coverage=sorted(coverage,key=DIMENSIONS.index)
        published=_aware(row.get('published_at'),'published_at');available=_aware(row.get('available_at'),'available_at')
        if published>available:raise SecurityStatusCoverageError('SOURCE_TIME_INVALID','published_at cannot be later than available_at')
        if available>cutoff:raise SecurityStatusCoverageError('SOURCE_AFTER_CUTOFF','source available_at cannot be later than cutoff_at')
        sha=row.get('sha256')
        if not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):
            raise SecurityStatusCoverageError('SOURCE_HASH_INVALID','source sha256 must be lowercase hexadecimal')
        payload=_document_bytes(row.get('document'))
        if hashlib.sha256(payload).hexdigest()!=sha:
            raise SecurityStatusCoverageError('SOURCE_HASH_MISMATCH','source document does not match plan sha256')
        normalized_sources.append({'source_id':sid,'exchange':exchange,'url':url,'coverage':coverage,
            'published_at':published.isoformat(),'available_at':available.isoformat(),
            'document_source':str(Path(row['document']).expanduser().resolve()),'sha256':sha,'bytes':len(payload)})
        source_ids.add(sid);coverage_by_exchange[exchange].update(coverage)
    if any(coverage_by_exchange[exchange]!=set(DIMENSIONS) for exchange in universe['scope']['exchanges']):
        raise SecurityStatusCoverageError('SOURCE_SCOPE_INCOMPLETE','every Universe exchange requires complete tradability and risk-warning source coverage')
    source_map={row['source_id']:row for row in normalized_sources};records=plan.get('records')
    if not isinstance(records,list) or not records or len(records)>MAX_RECORDS:
        raise SecurityStatusCoverageError('RECORDS_INVALID','status records must be a nonempty list of at most 20000 rows')
    normalized_records=[];symbols=set();used=set()
    for row in records:
        if not isinstance(row,dict) or set(row)!=_RECORD_FIELDS:
            raise SecurityStatusCoverageError('RECORD_INVALID','status record schema is invalid')
        symbol=row.get('symbol');tradable=row.get('tradable');warning=row.get('risk_warning');ids=row.get('source_ids')
        if not isinstance(symbol,str) or not _SYMBOL.fullmatch(symbol) or symbol in symbols or type(tradable) is not bool:
            raise SecurityStatusCoverageError('RECORD_INVALID','status symbol/tradable is invalid or duplicated')
        if warning not in RISK_WARNINGS:
            raise SecurityStatusCoverageError('RECORD_INVALID','risk_warning must be NONE/ST/STAR_ST/UNKNOWN')
        if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)) or any(value not in source_map for value in ids):
            raise SecurityStatusCoverageError('RECORD_INVALID','record source_ids are invalid or duplicated')
        exchange=_PREFIX_EXCHANGE.get(symbol[:2]);bound=[source_map[value] for value in ids]
        if exchange not in universe['scope']['exchanges'] or any(source['exchange']!=exchange for source in bound):
            raise SecurityStatusCoverageError('RECORD_SOURCE_MISMATCH','record source exchange does not match symbol')
        covered=set().union(*(set(source['coverage']) for source in bound))
        if covered!=set(DIMENSIONS):
            raise SecurityStatusCoverageError('RECORD_SOURCE_INCOMPLETE','each record must bind evidence for tradability and risk warning')
        ids=sorted(ids);normalized_records.append({'symbol':symbol,'tradable':tradable,
            'risk_warning':warning,'source_ids':ids});symbols.add(symbol);used.update(ids)
    universe_symbols={row['symbol'] for row in universe['members']}
    if symbols!=universe_symbols:
        missing=len(universe_symbols-symbols);extra=len(symbols-universe_symbols)
        raise SecurityStatusCoverageError('UNIVERSE_MEMBERSHIP_MISMATCH',f'status records must exactly match Universe members; missing={missing} extra={extra}')
    if used!=source_ids:raise SecurityStatusCoverageError('UNUSED_SOURCE','every status source must support at least one record')
    normalized_sources.sort(key=lambda row:row['source_id']);normalized_records.sort(key=lambda row:row['symbol'])
    return session,cutoff,universe,previous,normalized_sources,normalized_records


def _receipt_core(session,cutoff,universe,previous,sources,records,continuity_confirmed):
    receipt_sources=[]
    for row in sources:
        sha=row['sha256'];receipt_sources.append({'source_id':row['source_id'],'exchange':row['exchange'],
            'url':row['url'],'coverage':row['coverage'],'published_at':row['published_at'],'available_at':row['available_at'],
            'document':{'path':(Path('research/security_status_coverage/documents')/(sha+'.bin')).as_posix(),
                'sha256':sha,'bytes':row['bytes']}})
    latest=max(sources,key=lambda row:_aware(row['available_at'],'available_at'))['available_at']
    unknown=sum(row['risk_warning']=='UNKNOWN' for row in records)
    return {'format':FORMAT,'effective_session':session,'cutoff_at':cutoff.isoformat(),'available_at':latest,
        'universe_snapshot':universe['universe_snapshot'],'universe_member_count':universe['member_count'],
        'universe_members_digest':universe['members_digest'],'scope':universe['scope'],
        'previous_status_snapshot':previous,'previous_session_contiguous_confirmed':continuity_confirmed,
        'sources':receipt_sources,'records':records,'record_count':len(records),'records_digest':digest(records),
        'unknown_risk_warning_count':unknown,'publication_time_confirmed':True,
        'semantic_mapping_confirmed':True,'complete_daily_status_confirmed':True,
        'strict_pit_eligible':unknown==0,'scope_note':SCOPE_NOTE}


def _save_documents(root,documents,sources):
    documents.mkdir(parents=True,exist_ok=True)
    if documents.resolve()!=root/'research/security_status_coverage/documents':
        raise SecurityStatusCoverageError('INVALID_ARCHIVE','status document directory escaped data root')
    for row in sources:
        payload=_document_bytes(row['document_source']);target=documents/(row['sha256']+'.bin')
        if target.is_symlink():raise SecurityStatusCoverageError('INVALID_ARCHIVE','status document target cannot be a symlink')
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest()!=row['sha256']:
                raise SecurityStatusCoverageError('DOCUMENT_HASH_CONFLICT','content-addressed status document hash conflict')
            continue
        temporary=target.with_name('.'+row['sha256']+'.pending')
        try:
            with temporary.open('xb') as stream:
                stream.write(payload);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,target)
        finally:temporary.unlink(missing_ok=True)


def archive_security_status_coverage(data_root,plan,*,confirm_publication_times=False,
        confirm_semantic_mapping=False,confirm_complete_daily_status=False,
        confirm_previous_session_continuity=False,now_fn=None):
    """Archive host-prepared official status bytes; never performs network I/O."""
    if confirm_publication_times is not True:
        raise SecurityStatusCoverageError('CONFIRMATION_REQUIRED','host must confirm every publication/availability time')
    if confirm_semantic_mapping is not True:
        raise SecurityStatusCoverageError('CONFIRMATION_REQUIRED','host must confirm status semantic mapping')
    if confirm_complete_daily_status is not True:
        raise SecurityStatusCoverageError('CONFIRMATION_REQUIRED','host must confirm complete status coverage for every Universe member')
    root,directory,documents=_paths(data_root)
    session,cutoff,universe,previous,sources,records=_normalize_plan(root,plan)
    if (previous is None and confirm_previous_session_continuity is not False) or (previous is not None and confirm_previous_session_continuity is not True):
        raise SecurityStatusCoverageError('CONFIRMATION_REQUIRED','previous-session continuity confirmation must exactly match previous_status_snapshot presence')
    if previous is not None:
        prior=load_security_status_coverage_snapshot(root,previous)
        if prior['effective_session']>=session:
            raise SecurityStatusCoverageError('PREVIOUS_SNAPSHOT_INVALID','previous status snapshot must precede effective_session')
    core=_receipt_core(session,cutoff,universe,previous,sources,records,previous is not None)
    snapshot=digest(core);target=directory/(snapshot+'.json')
    with _archive_lock(directory):
        if target.is_symlink():raise SecurityStatusCoverageError('INVALID_ARCHIVE','status coverage receipt cannot be a symlink')
        if target.exists():
            _,existing,_=_verified_map(root);check=existing.get(snapshot)
            if check is None:
                raise SecurityStatusCoverageError('EXISTING_RECEIPT_INVALID','existing status receipt is invalid or has a broken previous link')
            return {'path':str(target),'status_snapshot':snapshot,'effective_session':session,
                'records':len(records),'created':False,'strict_pit_eligible':core['strict_pit_eligible']}
        _,existing,invalid=_verified_map(root)
        if invalid:raise SecurityStatusCoverageError('ARCHIVE_INVALID','existing status coverage archive contains invalid receipts')
        if any(row['effective_session']==session for row in existing.values()):
            raise SecurityStatusCoverageError('SESSION_AMBIGUOUS','a different status snapshot already exists for effective_session')
        if previous is not None and any(row['receipt']['previous_status_snapshot']==previous for row in existing.values()):
            raise SecurityStatusCoverageError('CHAIN_BRANCHING','previous_status_snapshot already has a different confirmed successor')
        created=_aware((now_fn or (lambda:datetime.now(timezone.utc)))(),'archive clock')
        if created>cutoff:
            raise SecurityStatusCoverageError('ARCHIVE_AFTER_CUTOFF','new daily status receipt must be archived no later than cutoff_at; historical backfill is forbidden')
        if _aware(universe['created_at'],'universe.created_at')>created:
            raise SecurityStatusCoverageError('UNIVERSE_NOT_YET_ARCHIVED','PIT Universe created_at cannot be later than status archive time')
        if any(_aware(row['available_at'],'available_at')>created for row in sources):
            raise SecurityStatusCoverageError('SOURCE_NOT_YET_AVAILABLE','source available_at cannot be later than archive time')
        _save_documents(root,documents,sources)
        value={**core,'status_snapshot':snapshot,'created_at':created.isoformat()};write_checked(target,value)
        check=_individual_audit(root,target)
        if not check['verified']:
            raise SecurityStatusCoverageError('SELF_AUDIT_FAILED','status coverage receipt self-audit failed: '+check['reason'])
        return {'path':str(target),'status_snapshot':snapshot,'effective_session':session,
            'records':len(records),'created':True,'strict_pit_eligible':core['strict_pit_eligible'],
            'scope':'Exact daily status coverage for every member of one PIT Universe snapshot; chain continuity requires an explicit previous link.'}


def _check_document(root,value):
    if not isinstance(value,dict) or set(value)!=_DOCUMENT_FIELDS:return False
    path=value.get('path');sha=value.get('sha256');size=value.get('bytes')
    if (not isinstance(path,str) or not isinstance(sha,str) or len(sha)!=64
            or any(c not in '0123456789abcdef' for c in sha) or type(size) is not int
            or size<=0 or size>MAX_DOCUMENT_BYTES):return False
    relative=Path(path);expected=Path('research/security_status_coverage/documents')/(sha+'.bin')
    if relative.is_absolute() or '..' in relative.parts or relative!=expected:return False
    target=Path(root)/relative
    if target.is_symlink():return False
    try:resolved=target.resolve();payload=resolved.read_bytes()
    except OSError:return False
    return resolved.is_relative_to(Path(root).resolve()) and len(payload)==size and hashlib.sha256(payload).hexdigest()==sha


def _individual_audit(root,path):
    try:value=read_checked(path)
    except (OSError,ValueError,TypeError):return {'verified':False,'reason':'status_coverage_receipt_unreadable'}
    if not isinstance(value,dict) or set(value)!=_TOP_FIELDS or value.get('format')!=FORMAT:
        return {'verified':False,'reason':'status_coverage_receipt_schema_invalid'}
    try:
        snapshot=_snapshot_id(value['status_snapshot']);session=_session(value['effective_session'])
        created=_aware(value['created_at'],'created_at');cutoff=_aware(value['cutoff_at'],'cutoff_at')
        available=_aware(value['available_at'],'available_at')
        universe=load_pit_universe_snapshot(root,value['universe_snapshot'],effective_session=session)
    except (SecurityStatusCoverageError,OSError,ValueError,TypeError,KeyError):
        return {'verified':False,'reason':'status_coverage_identity_time_or_universe_invalid'}
    if (path.stem!=snapshot or created>cutoff or available>cutoff
            or _aware(universe['created_at'],'universe.created_at')>created
            or cutoff>datetime.combine(date.fromisoformat(session),time(9,15),_TZ)
            or value.get('universe_member_count')!=universe['member_count']
            or value.get('universe_members_digest')!=universe['members_digest'] or value.get('scope')!=universe['scope']):
        return {'verified':False,'reason':'status_coverage_universe_or_cutoff_mismatch'}
    previous=value.get('previous_status_snapshot');continuity=value.get('previous_session_contiguous_confirmed')
    try:
        if previous is not None:_snapshot_id(previous,'previous_status_snapshot')
    except SecurityStatusCoverageError:return {'verified':False,'reason':'status_coverage_previous_snapshot_invalid'}
    if continuity is not (previous is not None):return {'verified':False,'reason':'status_coverage_continuity_confirmation_invalid'}
    required=('publication_time_confirmed','semantic_mapping_confirmed','complete_daily_status_confirmed')
    if any(value.get(name) is not True for name in required) or value.get('scope_note')!=SCOPE_NOTE:
        return {'verified':False,'reason':'status_coverage_confirmation_invalid'}
    sources=value.get('sources')
    if not isinstance(sources,list) or not sources or len(sources)>MAX_SOURCES:
        return {'verified':False,'reason':'status_coverage_sources_invalid'}
    source_map={};coverage_by_exchange={exchange:set() for exchange in universe['scope']['exchanges']};available_times=[]
    for row in sources:
        if not isinstance(row,dict) or set(row)!=_RECEIPT_SOURCE_FIELDS:
            return {'verified':False,'reason':'status_coverage_source_schema_invalid'}
        sid=row.get('source_id');exchange=row.get('exchange');coverage=row.get('coverage')
        if (not isinstance(sid,str) or not _ID.fullmatch(sid) or sid in source_map
                or exchange not in coverage_by_exchange or _exchange_for_url(row.get('url'))!=exchange
                or not isinstance(coverage,list) or coverage!=sorted(coverage,key=DIMENSIONS.index)
                or not coverage or len(coverage)!=len(set(coverage)) or any(item not in DIMENSIONS for item in coverage)):
            return {'verified':False,'reason':'status_coverage_source_identity_invalid'}
        try:
            published=_aware(row['published_at'],'published_at');source_available=_aware(row['available_at'],'available_at')
        except SecurityStatusCoverageError:return {'verified':False,'reason':'status_coverage_source_time_invalid'}
        if published>source_available or source_available>created or source_available>cutoff:
            return {'verified':False,'reason':'status_coverage_source_time_invalid'}
        if not _check_document(root,row.get('document')):
            return {'verified':False,'reason':'status_coverage_document_invalid'}
        source_map[sid]=row;coverage_by_exchange[exchange].update(coverage);available_times.append(source_available)
    if (sources!=sorted(sources,key=lambda row:row['source_id'])
            or any(coverage_by_exchange[key]!=set(DIMENSIONS) for key in coverage_by_exchange)
            or max(available_times)!=available):
        return {'verified':False,'reason':'status_coverage_source_scope_invalid'}
    records=value.get('records')
    if not isinstance(records,list) or not records or len(records)>MAX_RECORDS:
        return {'verified':False,'reason':'status_coverage_records_invalid'}
    universe_symbols={row['symbol'] for row in universe['members']};seen=set();used=set();unknown=0
    for row in records:
        if not isinstance(row,dict) or set(row)!=_RECORD_FIELDS:return {'verified':False,'reason':'status_coverage_record_schema_invalid'}
        symbol=row.get('symbol');tradable=row.get('tradable');warning=row.get('risk_warning');ids=row.get('source_ids')
        if (not isinstance(symbol,str) or not _SYMBOL.fullmatch(symbol) or symbol in seen or type(tradable) is not bool
                or warning not in RISK_WARNINGS or not isinstance(ids,list) or ids!=sorted(ids)
                or not ids or len(ids)!=len(set(ids)) or any(item not in source_map for item in ids)):
            return {'verified':False,'reason':'status_coverage_record_identity_invalid'}
        exchange=_PREFIX_EXCHANGE.get(symbol[:2]);bound=[source_map[item] for item in ids]
        if any(source['exchange']!=exchange for source in bound) or set().union(*(set(source['coverage']) for source in bound))!=set(DIMENSIONS):
            return {'verified':False,'reason':'status_coverage_record_source_invalid'}
        seen.add(symbol);used.update(ids);unknown+=warning=='UNKNOWN'
    strict=unknown==0
    if (seen!=universe_symbols or used!=set(source_map) or records!=sorted(records,key=lambda row:row['symbol'])
            or value.get('record_count')!=len(records) or value.get('records_digest')!=digest(records)
            or value.get('unknown_risk_warning_count')!=unknown or value.get('strict_pit_eligible') is not strict):
        return {'verified':False,'reason':'status_coverage_record_summary_invalid'}
    core={key:item for key,item in value.items() if key not in {'status_snapshot','created_at'}}
    if digest(core)!=snapshot:return {'verified':False,'reason':'status_coverage_snapshot_mismatch'}
    return {'verified':True,'reason':'verified_complete_daily_security_status','receipt':value,
        'status_snapshot':snapshot,'effective_session':session,'records':len(records),'strict_pit_eligible':strict}


def _verified_map(root):
    root,directory,_=_paths(root)
    paths=sorted(path for path in directory.glob('*.json') if not path.name.startswith('.')) if directory.is_dir() else []
    valid={};invalid=[]
    for path in paths:
        try:check=_individual_audit(root,path)
        except (OSError,ValueError,TypeError,KeyError):check={'verified':False,'reason':'status_coverage_receipt_audit_error'}
        if check.get('verified'):valid[check['status_snapshot']]=check
        else:invalid.append({'file':str(path.relative_to(root)),'reason':check.get('reason','status_coverage_receipt_invalid')})
    changed=True
    while changed:
        changed=False
        for snapshot,check in list(valid.items()):
            previous=check['receipt']['previous_status_snapshot']
            if previous is None:continue
            prior=valid.get(previous)
            if (prior is None or prior['effective_session']>=check['effective_session']
                    or _aware(prior['receipt']['created_at'],'created_at')>_aware(check['receipt']['created_at'],'created_at')):
                invalid.append({'file':f'research/security_status_coverage/{snapshot}.json',
                    'reason':'status_coverage_previous_snapshot_invalid'})
                valid.pop(snapshot);changed=True
    return paths,valid,invalid


def load_security_status_coverage_snapshot(data_root,snapshot_id,*,effective_session=None):
    root,_,_=_paths(data_root);snapshot=_snapshot_id(snapshot_id);_,valid,_=_verified_map(root);check=valid.get(snapshot)
    if check is None:raise SecurityStatusCoverageError('SNAPSHOT_INVALID','security-status coverage snapshot is missing, invalid, or has a broken previous link')
    receipt=check['receipt']
    if effective_session is not None and receipt['effective_session']!=_session(effective_session):
        raise SecurityStatusCoverageError('SESSION_MISMATCH','security-status snapshot does not match required effective session')
    return receipt


def list_security_status_coverage_snapshots(data_root,*,effective_session=None):
    root,_,_=_paths(data_root);_,valid,invalid=_verified_map(root)
    if invalid:raise SecurityStatusCoverageError('ARCHIVE_INVALID','status coverage archive contains invalid receipts')
    session=_session(effective_session) if effective_session is not None else None
    return [valid[key]['receipt'] for key in sorted(valid)
        if session is None or valid[key]['effective_session']==session]


def _record_map(receipt):return {row['symbol']:row for row in receipt['records']}


def _risk_transition(old,new):
    if old=='UNKNOWN' or new=='UNKNOWN':return 'RISK_WARNING_UNKNOWN'
    old_risk=old in ('ST','STAR_ST');new_risk=new in ('ST','STAR_ST')
    if not old_risk and new_risk:return 'RISK_WARNING_ENTERED'
    if old_risk and not new_risk:return 'RISK_WARNING_CLEARED'
    if old_risk and new_risk:return 'RISK_WARNING_CONTINUED' if old==new else 'RISK_WARNING_CHANGED'
    return 'NORMAL_CONTINUED'


def _trade_transition(old,new):
    if old and not new:return 'SUSPENSION_ENTERED'
    if not old and new:return 'SUSPENSION_CLEARED'
    return 'TRADABLE_CONTINUED' if new else 'SUSPENSION_CONTINUED'


def security_status_chain(data_root,symbol):
    if not isinstance(symbol,str) or not _SYMBOL.fullmatch(symbol):
        raise SecurityStatusCoverageError('INVALID_SYMBOL','symbol must be sh/sz/bj plus six digits')
    root,_,_=_paths(data_root);_,valid,invalid=_verified_map(root)
    if invalid:raise SecurityStatusCoverageError('ARCHIVE_INVALID','status coverage archive contains invalid receipts')
    receipts={key:value['receipt'] for key,value in valid.items()}
    sessions={};successors={}
    for snapshot,receipt in receipts.items():
        sessions.setdefault(receipt['effective_session'],[]).append(snapshot)
        if receipt['previous_status_snapshot'] is not None:successors.setdefault(receipt['previous_status_snapshot'],[]).append(snapshot)
    if any(len(values)>1 for values in sessions.values()) or any(len(values)>1 for values in successors.values()):
        raise SecurityStatusCoverageError('CHAIN_AMBIGUOUS','status coverage chain has an ambiguous session or branching previous link')
    rows=[]
    for snapshot,receipt in sorted(receipts.items(),key=lambda item:(item[1]['effective_session'],item[0])):
        current=_record_map(receipt).get(symbol);previous_id=receipt['previous_status_snapshot']
        prior=_record_map(receipts[previous_id]).get(symbol) if previous_id in receipts else None
        if current is not None:
            if previous_id is None:
                universe_transition='INITIAL_UNIVERSE_STATE';trade_transition='INITIAL_TRADABILITY';risk_transition='INITIAL_RISK_WARNING'
                transition_strict=False
            elif prior is None:
                universe_transition='UNIVERSE_ENTERED';trade_transition='INITIAL_TRADABILITY';risk_transition='INITIAL_RISK_WARNING'
                transition_strict=False
            else:
                universe_transition='UNIVERSE_CONTINUED';trade_transition=_trade_transition(prior['tradable'],current['tradable'])
                risk_transition=_risk_transition(prior['risk_warning'],current['risk_warning'])
                transition_strict=bool(receipt['strict_pit_eligible'] and receipts[previous_id]['strict_pit_eligible'])
            rows.append({'effective_session':receipt['effective_session'],'status_snapshot':snapshot,
                'previous_status_snapshot':previous_id,'universe_transition':universe_transition,
                'tradability_transition':trade_transition,'risk_warning_transition':risk_transition,
                'tradable':current['tradable'],'risk_warning':current['risk_warning'],
                'strict_pit_eligible':receipt['strict_pit_eligible'],
                'transition_strict_pit_eligible':transition_strict})
        if prior is not None and current is None:
            rows.append({'effective_session':receipt['effective_session'],'status_snapshot':snapshot,
                'previous_status_snapshot':previous_id,'universe_transition':'UNIVERSE_EXITED',
                'tradability_transition':'NOT_APPLICABLE','risk_warning_transition':'NOT_APPLICABLE',
                'tradable':None,'risk_warning':None,'strict_pit_eligible':receipt['strict_pit_eligible'],
                'transition_strict_pit_eligible':False})
    return {'format':'niuniu-security-status-chain-v2','symbol':symbol,'observations':len(rows),'records':rows,
        'scope':'Transitions exist only across explicitly linked, host-confirmed adjacent trading sessions; roots and Universe entry/exit are not status changes.'}


def audit_security_status_coverage(data_root):
    root,_,_=_paths(data_root);paths,valid,invalid=_verified_map(root);receipts={key:value['receipt'] for key,value in valid.items()}
    sessions={};documents=set();records=sources=strict=links=strict_links=roots=0;transitions={}
    for snapshot,receipt in receipts.items():
        sessions.setdefault(receipt['effective_session'],[]).append(snapshot);records+=receipt['record_count'];sources+=len(receipt['sources'])
        strict+=receipt['strict_pit_eligible'];documents.update(row['document']['path'] for row in receipt['sources'])
        previous=receipt['previous_status_snapshot']
        if previous is None:roots+=1;continue
        links+=1;strict_links+=int(receipt['strict_pit_eligible'] and receipts[previous]['strict_pit_eligible'])
        old=_record_map(receipts[previous]);new=_record_map(receipt)
        for symbol in old.keys()&new.keys():
            for name in (_trade_transition(old[symbol]['tradable'],new[symbol]['tradable']),
                    _risk_transition(old[symbol]['risk_warning'],new[symbol]['risk_warning'])):
                transitions[name]=transitions.get(name,0)+1
        transitions['UNIVERSE_ENTERED']=transitions.get('UNIVERSE_ENTERED',0)+len(new.keys()-old.keys())
        transitions['UNIVERSE_EXITED']=transitions.get('UNIVERSE_EXITED',0)+len(old.keys()-new.keys())
    ambiguous=sorted(day for day,ids in sessions.items() if len(ids)>1)
    successors={}
    for snapshot,receipt in receipts.items():
        if receipt['previous_status_snapshot'] is not None:
            successors.setdefault(receipt['previous_status_snapshot'],[]).append(snapshot)
    branching=sorted(key for key,ids in successors.items() if len(ids)>1)
    summaries=[{'status_snapshot':key,'effective_session':value['effective_session'],
        'universe_snapshot':value['receipt']['universe_snapshot'],'record_count':value['records'],
        'previous_status_snapshot':value['receipt']['previous_status_snapshot'],
        'strict_pit_eligible':value['strict_pit_eligible']} for key,value in sorted(valid.items())]
    return {'format':AUDIT_FORMAT,'receipt_files':len(paths),'verified_receipts':len(valid),
        'invalid_receipts':len(invalid),'strict_pit_eligible_receipts':strict,'effective_sessions':len(sessions),
        'ambiguous_sessions':ambiguous,'branching_previous_snapshots':branching,
        'status_records':records,'source_records':sources,
        'unique_documents':len(documents),'chain_roots':roots,'continuous_links':links,
        'strict_continuous_links':strict_links,
        'transition_counts':dict(sorted(transitions.items())),'snapshots':summaries[-100:],
        'snapshots_omitted':max(0,len(summaries)-100),'invalid':invalid[:100],
        'invalid_omitted':max(0,len(invalid)-100),
        'scope':'Daily completeness and linked transition integrity only; request coverage still requires one exact snapshot for every session.'}


__all__=['FORMAT','PLAN_FORMAT','AUDIT_FORMAT','SecurityStatusCoverageError',
    'archive_security_status_coverage','load_security_status_coverage_snapshot',
    'list_security_status_coverage_snapshots','security_status_chain','audit_security_status_coverage']

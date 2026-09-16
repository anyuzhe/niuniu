"""Append-only, prospective point-in-time universe receipts.

A v1 receipt binds one effective trading session and one complete declared
A-share scope to host-reviewed member records, official exchange bytes,
publication/availability times, and the actual archive time.  The module never
fetches network data and never reconstructs a historical universe from today's
security list.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date,datetime,time,timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import fcntl,hashlib,os,re

from quantlab.experiments.campaign_state import read_checked,write_checked
from quantlab.storage.codec import digest

FORMAT='niuniu-pit-universe-v1'
PLAN_FORMAT='niuniu-pit-universe-plan-v1'
AUDIT_FORMAT='niuniu-pit-universe-audit-v1'
MAX_DOCUMENT_BYTES=32_000_000
MAX_MEMBERS=20_000
MAX_SOURCES=100
EXCHANGES=('SSE','SZSE','BSE')
SCOPE_NOTE='Complete only for the declared exchanges and A_SHARE instrument type; no other market or instrument is implied.'
_EXCHANGE_PREFIX={'SSE':'sh','SZSE':'sz','BSE':'bj'}
_PREFIX_EXCHANGE={value:key for key,value in _EXCHANGE_PREFIX.items()}
_SOURCE_FIELDS={'source_id','exchange','url','published_at','available_at','document','sha256'}
_RECEIPT_SOURCE_FIELDS={'source_id','exchange','url','published_at','available_at','document'}
_DOCUMENT_FIELDS={'path','sha256','bytes'}
_MEMBER_FIELDS={'symbol','source_id'}
_SCOPE_FIELDS={'market','exchanges','instrument_types','completeness'}
_TOP_FIELDS={'format','universe_snapshot','created_at','effective_session','cutoff_at','available_at',
    'scope','sources','members','member_count','members_digest','publication_time_confirmed',
    'semantic_mapping_confirmed','complete_official_universe_confirmed','strict_pit_eligible','scope_note'}
_ID=re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$')
_SYMBOL=re.compile(r'^(sh|sz|bj)\.[0-9]{6}$')
_TZ=ZoneInfo('Asia/Shanghai')


class PITUniverseError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def _aware(value,name):
    try:stamp=datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
    except ValueError:raise PITUniverseError('INVALID_TIME',name+' must be timezone-aware ISO time') from None
    if not isinstance(stamp,datetime) or stamp.tzinfo is None:
        raise PITUniverseError('INVALID_TIME',name+' must be timezone-aware ISO time')
    return stamp


def _session(value):
    try:return date.fromisoformat(value).isoformat()
    except (TypeError,ValueError):raise PITUniverseError('INVALID_SESSION','effective_session must be YYYY-MM-DD') from None


def _snapshot_id(value):
    if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
        raise PITUniverseError('INVALID_SNAPSHOT','universe snapshot must be a lowercase SHA256')
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


def _normalize_scope(value):
    if not isinstance(value,dict) or set(value)!=_SCOPE_FIELDS:
        raise PITUniverseError('INVALID_SCOPE','scope fields must be market/exchanges/instrument_types/completeness')
    exchanges=value.get('exchanges');types=value.get('instrument_types')
    if value.get('market')!='CN_A_SHARE' or value.get('completeness')!='FULL_OFFICIAL_LIST':
        raise PITUniverseError('INVALID_SCOPE','v1 requires CN_A_SHARE and FULL_OFFICIAL_LIST')
    if (not isinstance(exchanges,list) or not exchanges or len(exchanges)!=len(set(exchanges))
            or any(item not in EXCHANGES for item in exchanges)):
        raise PITUniverseError('INVALID_SCOPE','scope exchanges are invalid or duplicated')
    if types!=['A_SHARE']:
        raise PITUniverseError('INVALID_SCOPE','v1 instrument_types must be exactly [A_SHARE]')
    return {'market':'CN_A_SHARE','exchanges':sorted(exchanges,key=EXCHANGES.index),
        'instrument_types':['A_SHARE'],'completeness':'FULL_OFFICIAL_LIST'}


def _document_bytes(path):
    supplied=Path(path).expanduser()
    if supplied.is_symlink():raise PITUniverseError('DOCUMENT_INVALID','official universe document cannot be a symlink')
    target=supplied.resolve()
    if not target.is_file():raise PITUniverseError('DOCUMENT_MISSING','official universe document is missing')
    payload=target.read_bytes()
    if not payload or len(payload)>MAX_DOCUMENT_BYTES:
        raise PITUniverseError('DOCUMENT_INVALID','official universe document is empty or exceeds 32MB')
    return payload


def _normalize_plan(plan):
    if not isinstance(plan,dict) or set(plan)!={'format','effective_session','cutoff_at','scope','sources','members'}:
        raise PITUniverseError('INVALID_PLAN','PIT universe plan schema is invalid')
    if plan.get('format')!=PLAN_FORMAT:raise PITUniverseError('INVALID_PLAN','PIT universe plan format is invalid')
    session=_session(plan['effective_session']);cutoff=_aware(plan['cutoff_at'],'cutoff_at')
    prep_close=datetime.combine(date.fromisoformat(session),time(9,15),_TZ)
    if cutoff>prep_close:
        raise PITUniverseError('INVALID_CUTOFF','cutoff_at cannot be later than effective-session PREP close 09:15 Asia/Shanghai')
    scope=_normalize_scope(plan['scope']);sources=plan.get('sources')
    if not isinstance(sources,list) or not sources or len(sources)>MAX_SOURCES:
        raise PITUniverseError('SOURCE_MISSING','one to 100 official exchange sources are required')
    normalized_sources=[];source_ids=set();source_exchanges=set()
    for row in sources:
        if not isinstance(row,dict) or set(row)!=_SOURCE_FIELDS:
            raise PITUniverseError('SOURCE_INVALID','source schema is invalid')
        source_id=row.get('source_id');exchange=row.get('exchange');url=row.get('url')
        if not isinstance(source_id,str) or not _ID.fullmatch(source_id) or source_id in source_ids:
            raise PITUniverseError('SOURCE_INVALID','source_id is invalid or duplicated')
        if exchange not in scope['exchanges'] or _exchange_for_url(url)!=exchange:
            raise PITUniverseError('SOURCE_INVALID','source URL host must match its declared exchange and scope')
        published=_aware(row.get('published_at'),'published_at');available=_aware(row.get('available_at'),'available_at')
        if published>available:raise PITUniverseError('SOURCE_TIME_INVALID','published_at cannot be later than available_at')
        if available>cutoff:raise PITUniverseError('SOURCE_AFTER_CUTOFF','source available_at cannot be later than cutoff_at')
        sha=row.get('sha256')
        if not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):
            raise PITUniverseError('SOURCE_HASH_INVALID','source sha256 must be lowercase hexadecimal')
        payload=_document_bytes(row.get('document'));actual=hashlib.sha256(payload).hexdigest()
        if actual!=sha:raise PITUniverseError('SOURCE_HASH_MISMATCH','source document does not match plan sha256')
        normalized_sources.append({'source_id':source_id,'exchange':exchange,'url':url,
            'published_at':published.isoformat(),'available_at':available.isoformat(),
            'document_source':str(Path(row['document']).expanduser().resolve()),'sha256':sha,'bytes':len(payload)})
        source_ids.add(source_id);source_exchanges.add(exchange)
    if source_exchanges!=set(scope['exchanges']):
        raise PITUniverseError('SOURCE_SCOPE_INCOMPLETE','every declared exchange requires at least one official source')
    members=plan.get('members')
    if not isinstance(members,list) or not members or len(members)>MAX_MEMBERS:
        raise PITUniverseError('MEMBERS_INVALID','members must be a nonempty list of at most 20000 records')
    source_map={row['source_id']:row for row in normalized_sources};normalized_members=[];symbols=set();used=set()
    for row in members:
        if not isinstance(row,dict) or set(row)!=_MEMBER_FIELDS:
            raise PITUniverseError('MEMBER_INVALID','member schema is invalid')
        symbol=row.get('symbol');source_id=row.get('source_id')
        if not isinstance(symbol,str) or not _SYMBOL.fullmatch(symbol) or symbol in symbols:
            raise PITUniverseError('MEMBER_INVALID','member symbol is invalid or duplicated')
        source=source_map.get(source_id);exchange=_PREFIX_EXCHANGE.get(symbol[:2])
        if source is None or exchange!=source['exchange'] or exchange not in scope['exchanges']:
            raise PITUniverseError('MEMBER_SOURCE_MISMATCH','member source/exchange binding is invalid')
        normalized_members.append({'symbol':symbol,'source_id':source_id});symbols.add(symbol);used.add(source_id)
    if used!=source_ids:
        raise PITUniverseError('UNUSED_SOURCE','every archived source must support at least one member')
    normalized_sources.sort(key=lambda row:row['source_id']);normalized_members.sort(key=lambda row:row['symbol'])
    return session,cutoff,scope,normalized_sources,normalized_members


def _paths(root):
    supplied=Path(root).expanduser()
    if supplied.is_symlink():raise PITUniverseError('INVALID_DATA_ROOT','PIT universe data root cannot be a symlink')
    root=supplied.resolve();research=root/'research';directory=research/'pit_universe';documents=directory/'documents'
    if not root.is_dir():raise PITUniverseError('INVALID_DATA_ROOT','PIT universe data root does not exist')
    if research.is_symlink() or directory.is_symlink() or documents.is_symlink():
        raise PITUniverseError('INVALID_ARCHIVE','PIT universe archive cannot be a symlink')
    if directory.exists() and not directory.is_dir():raise PITUniverseError('INVALID_ARCHIVE','PIT universe archive path is invalid')
    return root,directory,documents


@contextmanager
def _archive_lock(directory):
    directory.mkdir(parents=True,exist_ok=True);lock=directory/'.archive.lock'
    if directory.is_symlink() or lock.is_symlink():raise PITUniverseError('INVALID_ARCHIVE','PIT universe lock path cannot be a symlink')
    with lock.open('a+b') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(stream,fcntl.LOCK_UN)


def _receipt_core(session,cutoff,scope,sources,members):
    receipt_sources=[]
    for row in sources:
        sha=row['sha256'];receipt_sources.append({'source_id':row['source_id'],'exchange':row['exchange'],
            'url':row['url'],'published_at':row['published_at'],'available_at':row['available_at'],
            'document':{'path':(Path('research/pit_universe/documents')/(sha+'.bin')).as_posix(),
                'sha256':sha,'bytes':row['bytes']}})
    latest=max(sources,key=lambda row:_aware(row['available_at'],'available_at'))['available_at']
    return {'format':FORMAT,'effective_session':session,'cutoff_at':cutoff.isoformat(),
        'available_at':latest,'scope':scope,'sources':receipt_sources,
        'members':members,'member_count':len(members),'members_digest':digest(members),
        'publication_time_confirmed':True,'semantic_mapping_confirmed':True,
        'complete_official_universe_confirmed':True,'strict_pit_eligible':True,'scope_note':SCOPE_NOTE}


def _save_documents(root,documents,sources):
    documents.mkdir(parents=True,exist_ok=True)
    if documents.resolve()!=root/'research/pit_universe/documents':
        raise PITUniverseError('INVALID_ARCHIVE','PIT universe document directory escaped data root')
    for row in sources:
        payload=_document_bytes(row['document_source']);target=documents/(row['sha256']+'.bin')
        if target.is_symlink():raise PITUniverseError('INVALID_ARCHIVE','PIT universe document target cannot be a symlink')
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest()!=row['sha256']:
                raise PITUniverseError('DOCUMENT_HASH_CONFLICT','content-addressed universe document hash conflict')
            continue
        temporary=target.with_name('.'+row['sha256']+'.pending')
        try:
            with temporary.open('xb') as stream:
                stream.write(payload);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,target)
        finally:temporary.unlink(missing_ok=True)


def archive_pit_universe(data_root,plan,*,confirm_publication_times=False,
        confirm_semantic_mapping=False,confirm_complete_official_universe=False,now_fn=None):
    """Archive already-downloaded official bytes; this function never uses network I/O."""
    if confirm_publication_times is not True:
        raise PITUniverseError('CONFIRMATION_REQUIRED','host must explicitly confirm every publication/availability time')
    if confirm_semantic_mapping is not True:
        raise PITUniverseError('CONFIRMATION_REQUIRED','host must explicitly confirm source-to-symbol semantic mapping')
    if confirm_complete_official_universe is not True:
        raise PITUniverseError('CONFIRMATION_REQUIRED','host must explicitly confirm complete official universe coverage')
    root,directory,documents=_paths(data_root)
    session,cutoff,scope,sources,members=_normalize_plan(plan);core=_receipt_core(session,cutoff,scope,sources,members)
    snapshot=digest(core);target=directory/(snapshot+'.json')
    with _archive_lock(directory):
        if target.is_symlink():raise PITUniverseError('INVALID_ARCHIVE','PIT universe receipt cannot be a symlink')
        if target.exists():
            check=_audit_receipt(root,target)
            if not check['verified']:
                raise PITUniverseError('EXISTING_RECEIPT_INVALID','existing PIT universe receipt is invalid: '+check['reason'])
            return {'path':str(target),'universe_snapshot':snapshot,'effective_session':session,
                'members':len(members),'sources':len(sources),'created':False,'strict_pit_eligible':True}
        created=_aware((now_fn or (lambda:datetime.now(timezone.utc)))(),'archive clock')
        if created>cutoff:
            raise PITUniverseError('ARCHIVE_AFTER_CUTOFF','new PIT universe receipt must be archived no later than cutoff_at; historical backfill is forbidden')
        if any(_aware(row['available_at'],'available_at')>created for row in sources):
            raise PITUniverseError('SOURCE_NOT_YET_AVAILABLE','source available_at cannot be later than archive time')
        _save_documents(root,documents,sources)
        value={**core,'universe_snapshot':snapshot,'created_at':created.isoformat()}
        write_checked(target,value);check=_audit_receipt(root,target)
        if not check['verified']:
            raise PITUniverseError('SELF_AUDIT_FAILED','PIT universe receipt self-audit failed: '+check['reason'])
        return {'path':str(target),'universe_snapshot':snapshot,'effective_session':session,
            'members':len(members),'sources':len(sources),'created':True,'strict_pit_eligible':True,
            'scope':'Prospective, publication-bound official universe for exactly one effective session and declared scope.'}


def _check_document(root,value):
    if not isinstance(value,dict) or set(value)!=_DOCUMENT_FIELDS:return False
    path=value.get('path');sha=value.get('sha256');size=value.get('bytes')
    if (not isinstance(path,str) or not isinstance(sha,str) or len(sha)!=64
            or any(c not in '0123456789abcdef' for c in sha) or type(size) is not int
            or size<=0 or size>MAX_DOCUMENT_BYTES):return False
    relative=Path(path);expected=Path('research/pit_universe/documents')/(sha+'.bin')
    if relative.is_absolute() or '..' in relative.parts or relative!=expected:return False
    candidate=Path(root)/relative
    if candidate.is_symlink():return False
    try:
        resolved=candidate.resolve();payload=resolved.read_bytes()
    except OSError:return False
    return (resolved.is_relative_to(Path(root).resolve()) and len(payload)==size
        and hashlib.sha256(payload).hexdigest()==sha)


def _audit_receipt(root,path):
    try:value=read_checked(path)
    except (OSError,ValueError,TypeError):return {'verified':False,'reason':'pit_universe_receipt_unreadable'}
    if not isinstance(value,dict) or set(value)!=_TOP_FIELDS or value.get('format')!=FORMAT:
        return {'verified':False,'reason':'pit_universe_receipt_schema_invalid'}
    try:
        snapshot=_snapshot_id(value['universe_snapshot']);session=_session(value['effective_session'])
        created=_aware(value['created_at'],'created_at');cutoff=_aware(value['cutoff_at'],'cutoff_at')
        available=_aware(value['available_at'],'available_at');scope=_normalize_scope(value['scope'])
    except PITUniverseError:return {'verified':False,'reason':'pit_universe_identity_or_time_invalid'}
    if path.stem!=snapshot or value['scope']!=scope or created>cutoff or available>cutoff:
        return {'verified':False,'reason':'pit_universe_snapshot_or_cutoff_invalid'}
    prep_close=datetime.combine(date.fromisoformat(session),time(9,15),_TZ)
    if cutoff>prep_close:return {'verified':False,'reason':'pit_universe_cutoff_after_prep'}
    confirmations=('publication_time_confirmed','semantic_mapping_confirmed','complete_official_universe_confirmed','strict_pit_eligible')
    if any(value.get(name) is not True for name in confirmations) or value.get('scope_note')!=SCOPE_NOTE:
        return {'verified':False,'reason':'pit_universe_confirmation_invalid'}
    sources=value.get('sources')
    if not isinstance(sources,list) or not sources or len(sources)>MAX_SOURCES:return {'verified':False,'reason':'pit_universe_sources_invalid'}
    source_map={};source_exchanges=set();available_times=[]
    for row in sources:
        if not isinstance(row,dict) or set(row)!=_RECEIPT_SOURCE_FIELDS:
            return {'verified':False,'reason':'pit_universe_source_schema_invalid'}
        sid=row.get('source_id');exchange=row.get('exchange')
        if (not isinstance(sid,str) or not _ID.fullmatch(sid) or sid in source_map
                or exchange not in scope['exchanges'] or _exchange_for_url(row.get('url'))!=exchange):
            return {'verified':False,'reason':'pit_universe_source_identity_invalid'}
        try:
            published=_aware(row['published_at'],'published_at');source_available=_aware(row['available_at'],'available_at')
        except PITUniverseError:return {'verified':False,'reason':'pit_universe_source_time_invalid'}
        if published>source_available or source_available>created or source_available>cutoff:
            return {'verified':False,'reason':'pit_universe_source_time_invalid'}
        if not _check_document(root,row.get('document')):
            return {'verified':False,'reason':'pit_universe_document_invalid'}
        source_map[sid]=row;source_exchanges.add(exchange);available_times.append(source_available)
    if sources!=sorted(sources,key=lambda row:row['source_id']) or source_exchanges!=set(scope['exchanges']):
        return {'verified':False,'reason':'pit_universe_source_scope_invalid'}
    if max(available_times)!=available:
        return {'verified':False,'reason':'pit_universe_available_at_mismatch'}
    members=value.get('members')
    if not isinstance(members,list) or not members or len(members)>MAX_MEMBERS:
        return {'verified':False,'reason':'pit_universe_members_invalid'}
    seen=set();used=set()
    for row in members:
        if not isinstance(row,dict) or set(row)!=_MEMBER_FIELDS:
            return {'verified':False,'reason':'pit_universe_member_schema_invalid'}
        symbol=row.get('symbol');sid=row.get('source_id');source=source_map.get(sid)
        if (not isinstance(symbol,str) or not _SYMBOL.fullmatch(symbol) or symbol in seen or source is None
                or _PREFIX_EXCHANGE.get(symbol[:2])!=source['exchange']):
            return {'verified':False,'reason':'pit_universe_member_identity_invalid'}
        seen.add(symbol);used.add(sid)
    if (members!=sorted(members,key=lambda row:row['symbol']) or used!=set(source_map)
            or value.get('member_count')!=len(members) or value.get('members_digest')!=digest(members)):
        return {'verified':False,'reason':'pit_universe_member_summary_invalid'}
    core={k:v for k,v in value.items() if k not in {'universe_snapshot','created_at'}}
    if digest(core)!=snapshot:return {'verified':False,'reason':'pit_universe_snapshot_mismatch'}
    return {'verified':True,'reason':'verified_prospective_pit_universe','receipt':value,
        'universe_snapshot':snapshot,'effective_session':session,'members':len(members),
        'sources':len(sources),'exchanges':scope['exchanges'],'strict_pit_eligible':True}


def load_pit_universe_snapshot(data_root,snapshot_id,*,effective_session=None):
    root,directory,_=_paths(data_root);snapshot=_snapshot_id(snapshot_id);path=directory/(snapshot+'.json')
    if path.is_symlink() or not path.is_file():raise PITUniverseError('SNAPSHOT_MISSING','PIT universe snapshot receipt is missing')
    check=_audit_receipt(root,path)
    if not check['verified']:
        raise PITUniverseError('SNAPSHOT_INVALID','PIT universe snapshot verification failed: '+check['reason'])
    receipt=check['receipt']
    if effective_session is not None and receipt['effective_session']!=_session(effective_session):
        raise PITUniverseError('SESSION_MISMATCH','PIT universe snapshot does not match the required effective session')
    return receipt


def list_pit_universe_snapshots(data_root,*,effective_session=None):
    root,directory,_=_paths(data_root)
    if not directory.exists():return []
    session=_session(effective_session) if effective_session is not None else None;result=[]
    for path in sorted(directory.glob('*.json')):
        if path.name.startswith('.'):continue
        check=_audit_receipt(root,path)
        if check['verified'] and (session is None or check['effective_session']==session):result.append(check['receipt'])
    return result


def audit_pit_universe(data_root):
    root,directory,_=_paths(data_root)
    if not directory.exists():paths=[]
    else:paths=sorted(path for path in directory.glob('*.json') if not path.name.startswith('.'))
    verified=[];invalid=[];members=sources=0;sessions=set();documents=set()
    for path in paths:
        try:check=_audit_receipt(root,path)
        except (OSError,ValueError,TypeError,KeyError):check={'verified':False,'reason':'pit_universe_receipt_audit_error'}
        if not check.get('verified'):
            invalid.append({'file':str(path.relative_to(root)),'reason':check.get('reason','pit_universe_receipt_invalid')});continue
        receipt=check['receipt'];members+=check['members'];sources+=check['sources'];sessions.add(check['effective_session'])
        documents.update(row['document']['path'] for row in receipt['sources'])
        verified.append({'universe_snapshot':check['universe_snapshot'],'effective_session':check['effective_session'],
            'member_count':check['members'],'source_count':check['sources'],'exchanges':check['exchanges'],
            'available_at':receipt['available_at'],'cutoff_at':receipt['cutoff_at'],'created_at':receipt['created_at']})
    return {'format':AUDIT_FORMAT,'receipt_files':len(paths),'verified_receipts':len(verified),
        'invalid_receipts':len(invalid),'effective_sessions':len(sessions),'member_records':members,
        'source_records':sources,'unique_documents':len(documents),'snapshots':verified[-100:],
        'snapshots_omitted':max(0,len(verified)-100),'invalid':invalid[:100],
        'invalid_omitted':max(0,len(invalid)-100),
        'scope':'Global receipt integrity inventory only; request/session coverage must still be checked explicitly.'}


__all__=['FORMAT','PLAN_FORMAT','AUDIT_FORMAT','PITUniverseError','archive_pit_universe',
    'load_pit_universe_snapshot','list_pit_universe_snapshots','audit_pit_universe']

"""Archived authoritative evidence for point-in-time eligibility and controls.

A receipt binds one or more normalized statements to local document bytes, an
authoritative HTTPS source and a host-confirmed publication timestamp. It does
not infer facts from documents or certify unrelated market data.
"""
from __future__ import annotations

from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse
import hashlib,math

from quantlab.experiments.campaign_state import read_checked,write_checked
from quantlab.storage.codec import digest

FORMAT='niuniu-pit-evidence-v1'
KINDS=('universe_eligibility','industry_membership','daily_market_cap')
AUTHORITATIVE_PIT_HOSTS={'sse.com.cn','www.sse.com.cn','star.sse.com.cn','szse.cn','www.szse.cn',
    'bse.cn','www.bse.cn','cninfo.com.cn','www.cninfo.com.cn'}
MAX_DOCUMENT_BYTES=8_000_000


def authoritative_pit_source(value):
    try:
        parsed=urlparse(value);host=(parsed.hostname or '').lower()
        return parsed.scheme=='https' and host in AUTHORITATIVE_PIT_HOSTS
    except (TypeError,ValueError):return False


def _moment(value,name):
    if isinstance(value,str):value=datetime.fromisoformat(value.replace('Z','+00:00'))
    if not isinstance(value,datetime) or value.tzinfo is None:raise ValueError(name+' must be timezone-aware')
    return value.isoformat()


def normalize_statement(kind,value):
    if kind not in KINDS or not isinstance(value,dict):raise ValueError('invalid PIT evidence kind/statement')
    if kind=='universe_eligibility':
        if set(value)!={'symbol','effective_at','available_at','eligible'} or type(value['eligible']) is not bool:
            raise ValueError('universe statement requires symbol/effective_at/available_at/eligible')
        result={'symbol':str(value['symbol']).strip(),'effective_at':_moment(value['effective_at'],'effective_at'),
            'available_at':_moment(value['available_at'],'available_at'),'eligible':value['eligible']}
    elif kind=='industry_membership':
        if set(value)!={'symbol','sector','effective_at','available_at','source'}:
            raise ValueError('industry statement fields invalid')
        result={'symbol':str(value['symbol']).strip(),'sector':str(value['sector']).strip(),
            'effective_at':_moment(value['effective_at'],'effective_at'),'available_at':_moment(value['available_at'],'available_at'),
            'source':str(value['source']).strip()}
    else:
        if set(value)!={'symbol','market_cap','effective_at','available_at','expires_at','source'}:
            raise ValueError('market-cap statement fields invalid')
        cap=value['market_cap']
        if type(cap) not in (int,float) or not math.isfinite(cap) or cap<=0:raise ValueError('market_cap must be positive finite')
        result={'symbol':str(value['symbol']).strip(),'market_cap':float(cap),
            'effective_at':_moment(value['effective_at'],'effective_at'),'available_at':_moment(value['available_at'],'available_at'),
            'expires_at':_moment(value['expires_at'],'expires_at'),'source':str(value['source']).strip()}
    if not result['symbol']:raise ValueError('PIT statement symbol missing')
    return result


def statement_id(kind,value):return digest({'kind':kind,'statement':normalize_statement(kind,value)})


def _paths(root):
    root=Path(root).resolve();folder=root/'research/pit_evidence'
    return root,folder,folder/'receipts.json',folder/'documents'


def _load(root):
    root,folder,path,_=_paths(root)
    if folder.is_symlink() or path.is_symlink():raise ValueError('PIT evidence path cannot be symlink')
    if not path.exists():return {'format':FORMAT,'records':[]}
    value=read_checked(path)
    if value.get('format')!=FORMAT or not isinstance(value.get('records'),list):raise ValueError('PIT evidence receipt format invalid')
    return value


def _verified_record(root,record,kind,statement):
    required={'evidence_id','statement_id','kind','statement','source_url','published_at','fetched_at',
        'document_path','document_sha256','publication_time_confirmed'}
    if not isinstance(record,dict) or set(record)!=required or record.get('kind')!=kind:return False
    if record.get('publication_time_confirmed') is not True:return False
    normalized=normalize_statement(kind,statement)
    if record.get('statement')!=normalized or record.get('statement_id')!=statement_id(kind,normalized):return False
    if not authoritative_pit_source(record.get('source_url')):return False
    if kind!='universe_eligibility' and normalized['source']!=record['source_url']:return False
    try:
        published=datetime.fromisoformat(record['published_at']);fetched=datetime.fromisoformat(record['fetched_at'])
        available=datetime.fromisoformat(normalized['available_at'])
    except (TypeError,ValueError):return False
    if published.tzinfo is None or fetched.tzinfo is None or published>available:return False
    relative=Path(record['document_path'])
    if relative.is_absolute() or '..' in relative.parts:return False
    path=(Path(root).resolve()/relative).resolve()
    if not path.is_relative_to(Path(root).resolve()) or path.is_symlink() or not path.is_file():return False
    payload=path.read_bytes()
    return len(payload)<=MAX_DOCUMENT_BYTES and hashlib.sha256(payload).hexdigest()==record['document_sha256']


def verify_pit_statements(root,kind,statements):
    rows=[normalize_statement(kind,row) for row in statements]
    value=_load(root);records=value['records'];matched=[];missing=[]
    for row in rows:
        candidates=[r for r in records if r.get('statement_id')==statement_id(kind,row)]
        valid=next((r for r in candidates if _verified_record(root,r,kind,row)),None)
        if valid is None:missing.append(statement_id(kind,row))
        else:matched.append(valid['evidence_id'])
    return {'format':'niuniu-pit-evidence-verification-v1','kind':kind,'verified':bool(rows) and not missing,
        'statements':len(rows),'verified_statements':len(matched),'missing_statement_ids':missing,
        'evidence_ids':matched,'scope':'Archived authoritative document + host-confirmed historical publication time; statement semantics remain host-audited.'}


def archive_pit_evidence(data_root,kind,statements,source_url,published_at,document_path,*,confirm_publication_time=False):
    if confirm_publication_time is not True:raise ValueError('host must explicitly confirm the historical publication timestamp')
    if kind not in KINDS or not authoritative_pit_source(source_url):raise ValueError('PIT evidence requires an authoritative HTTPS source')
    published=_moment(published_at,'published_at');rows=[normalize_statement(kind,row) for row in statements]
    if not rows:raise ValueError('PIT evidence requires at least one statement')
    for row in rows:
        if kind!='universe_eligibility' and row['source']!=source_url:raise ValueError('statement source must match archived source URL')
        if datetime.fromisoformat(row['available_at'])<datetime.fromisoformat(published):
            raise ValueError('statement available_at cannot precede confirmed publication time')
    document=Path(document_path).expanduser().resolve()
    if document.is_symlink() or not document.is_file():raise ValueError('PIT evidence document missing or symlink')
    payload=document.read_bytes()
    if not payload or len(payload)>MAX_DOCUMENT_BYTES:raise ValueError('PIT evidence document empty or too large')
    sha=hashlib.sha256(payload).hexdigest();root,folder,path,documents=_paths(data_root)
    if not root.is_dir() or folder.is_symlink() or documents.is_symlink():raise ValueError('PIT evidence data root invalid')
    documents.mkdir(parents=True,exist_ok=True);relative=Path('research/pit_evidence/documents')/(sha+'.bin');target=root/relative
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=sha:raise ValueError('PIT evidence document hash conflict')
    if not target.exists():target.write_bytes(payload)

    value=_load(root);existing={r.get('evidence_id') for r in value['records']};created=[]
    fetched=datetime.now(timezone.utc).isoformat()
    for row in rows:
        sid=statement_id(kind,row)
        identity={'statement_id':sid,'kind':kind,'statement':row,'source_url':source_url,'published_at':published,
            'document_path':relative.as_posix(),'document_sha256':sha,'publication_time_confirmed':True}
        evidence_id=digest(identity);record={'evidence_id':evidence_id,**identity,'fetched_at':fetched}
        if evidence_id not in existing:value['records'].append(record);existing.add(evidence_id);created.append(evidence_id)
    if len(value['records'])>100000:raise ValueError('PIT evidence receipt budget exceeded')
    path.parent.mkdir(parents=True,exist_ok=True);write_checked(path,value)
    check=verify_pit_statements(root,kind,rows)
    if not check['verified']:raise ValueError('PIT evidence self-verification failed')
    return {'path':str(path),'kind':kind,'statements':len(rows),'created':len(created),
        'evidence_ids':check['evidence_ids'],'document_sha256':sha,'publication_at':published,
        'scope':'Host-confirmed publication timestamp bound to archived authoritative document bytes; no facts inferred from document content.'}


def list_pit_evidence(root):
    value=_load(root);counts={kind:0 for kind in KINDS}
    for row in value['records']:
        if row.get('kind') in counts:counts[row['kind']]+=1
    return {'format':FORMAT,'records':len(value['records']),'counts':counts,
        'evidence_ids':[r.get('evidence_id') for r in value['records'][-100:]],'omitted':max(0,len(value['records'])-100)}


def audit_pit_evidence(root):
    """Deep-verify every stored receipt and referenced document byte stream."""
    value=_load(root);valid=[];invalid=[]
    for record in value['records']:
        try:
            kind=record.get('kind');statement=record.get('statement')
            ok=kind in KINDS and _verified_record(root,record,kind,statement)
        except (OSError,ValueError,TypeError,KeyError):ok=False
        if ok:valid.append(record)
        else:invalid.append(record.get('evidence_id'))
    return {'format':'niuniu-pit-evidence-audit-v1','stored_records':len(value['records']),
        'verified_records':len(valid),'invalid_records':len(invalid),'records':valid,
        'invalid_evidence_ids':invalid[:100],'invalid_omitted':max(0,len(invalid)-100)}


__all__=['FORMAT','KINDS','AUTHORITATIVE_PIT_HOSTS','authoritative_pit_source','normalize_statement','statement_id',
    'verify_pit_statements','archive_pit_evidence','list_pit_evidence','audit_pit_evidence']

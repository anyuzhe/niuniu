"""Append-only, explicitly non-qualifying references for exact MarketRules derivation gaps.

This archive preserves official historical quote responses and recomputes candidate
price bounds, but never treats a response fetched after the session as proof of
what bytes were available before that session opened.
"""
from __future__ import annotations

from datetime import date,datetime,time,timezone
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qs,urlparse
from zoneinfo import ZoneInfo
import hashlib,json,os

from quantlab.data.pit_evidence import audit_pit_evidence
from quantlab.data.qualification import _official_source
from quantlab.experiments.campaign_state import read_checked,write_checked
from quantlab.storage.codec import digest

FORMAT='niuniu-official-market-rule-reference-v1'
MAX_BYTES=8_000_000
REFERENCE_BLOCKER='historical_reference_price_publication_receipt_missing'
_DOC_FIELDS={'path','sha256','bytes'}
_RECORD_FIELDS={
    'symbol','session','official_name','announcement_evidence_id','announcement_source_url',
    'announcement_published_at','announcement_document_path','announcement_document_sha256',
    'announcement_limit_rate','historical_quote_source_url','historical_quote_observed_at',
    'historical_quote_document','historical_quote_headers_document','official_previous_close',
    'official_open','official_high','official_low','official_close','official_reported_pct_change',
    'price_tick','rounding','derived_limit_up','derived_limit_down',
    'observed_low_matches_derived_limit_down','observed_high_within_derived_limit_up',
    'historical_reference_publication_verified_before_open','market_rules_eligible','blockers'}
_TOP_FIELDS={'format','created_at','scope','formula_evidence','records','records_count',
    'exact_arithmetic_verified','strict_pit_eligible','market_rules_snapshot_appended',
    'blockers','limitations','reference_snapshot'}
_FORMULA_PLAN_FIELDS={'title','source_url','notice_metadata_url','published_at','document','notice_document','clauses'}
_CASE_PLAN_FIELDS={'symbol','session','announcement_evidence_id','limit_rate','quote_source_url',
    'quote_document','quote_headers_document'}
_FORMULA_FIELDS={'title','source_url','notice_metadata_url','published_at','publication_value_origin',
    'document','notice_document','clauses'}
_EXPECTED_COLS={'jyrq':'交易日期','zqdm':'证券代码','zqjc':'证券简称','qss':'前收',
    'ks':'开盘','zg':'最高','zd':'最低','ss':'今收'}


def _aware(value,name):
    try:stamp=datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
    except ValueError:raise ValueError(name+' must be timezone-aware') from None
    if not isinstance(stamp,datetime) or stamp.tzinfo is None:raise ValueError(name+' must be timezone-aware')
    return stamp


def _decimal(value,name,*,positive=True):
    try:number=Decimal(str(value).replace(',',''))
    except (InvalidOperation,ValueError):raise ValueError(name+' must be decimal') from None
    if not number.is_finite() or (positive and number<=0):raise ValueError(name+' must be positive finite')
    return number


def _document(root,path):
    if not isinstance(path,str):raise ValueError('reference document path invalid')
    relative=Path(path);root=Path(root).resolve()
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('reference document path invalid')
    candidate=root/relative
    if candidate.is_symlink():raise ValueError('reference document missing or symlink')
    target=candidate.resolve()
    if not target.is_relative_to(root) or not target.is_file():raise ValueError('reference document missing or symlink')
    payload=target.read_bytes()
    if not payload or len(payload)>MAX_BYTES:return None
    return payload


def _check_document(root,value):
    if not isinstance(value,dict) or set(value)!=_DOC_FIELDS:return False
    sha=value.get('sha256');path=value.get('path');size=value.get('bytes')
    if (not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha)
            or type(size) is not int or size<=0 or size>MAX_BYTES):return False
    try:payload=_document(root,path)
    except (OSError,ValueError):return False
    expected=Path('research/official_market_rule_references/documents')/(sha+'.bin')
    return payload is not None and Path(path)==expected and len(payload)==size and hashlib.sha256(payload).hexdigest()==sha


def _save_document(root,source):
    supplied=Path(source).expanduser()
    if supplied.is_symlink():raise ValueError('reference source document cannot be symlink')
    source=supplied.resolve()
    if not source.is_file():raise ValueError('reference source document missing')
    payload=source.read_bytes()
    if not payload or len(payload)>MAX_BYTES:raise ValueError('reference source document empty or too large')
    sha=hashlib.sha256(payload).hexdigest();relative=Path('research/official_market_rule_references/documents')/(sha+'.bin')
    root=Path(root).resolve();target=root/relative
    if target.parent.is_symlink():raise ValueError('reference document directory cannot be symlink')
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.parent.resolve()!=root/'research/official_market_rule_references/documents' or target.is_symlink():
        raise ValueError('reference document target cannot be symlink')
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=sha:raise ValueError('reference document hash collision')
    if not target.exists():
        temporary=target.with_suffix('.tmp');temporary.write_bytes(payload);os.replace(temporary,target)
    return {'path':relative.as_posix(),'sha256':sha,'bytes':len(payload)},payload


def _http_date(payload):
    try:lines=payload.decode('latin-1').splitlines()
    except UnicodeDecodeError:raise ValueError('quote header bytes invalid') from None
    values=[]
    for line in lines:
        if line.lower().startswith('date:'):
            try:values.append(parsedate_to_datetime(line.split(':',1)[1].strip()))
            except (TypeError,ValueError):raise ValueError('quote HTTP Date invalid') from None
    if len(values)!=1 or values[0].tzinfo is None:raise ValueError('quote headers require exactly one timezone-aware HTTP Date')
    return values[0]


def _quote_url(value,symbol,session):
    if not _official_source(value):raise ValueError('quote source must be an official exchange HTTPS URL')
    parsed=urlparse(value);query=parse_qs(parsed.query,keep_blank_values=True)
    if parsed.hostname!='www.szse.cn' or parsed.path!='/api/report/ShowReport/data':
        raise ValueError('only the official SZSE ShowReport data endpoint is supported')
    one=lambda name:query.get(name)==[{'SHOWTYPE':'JSON','TABKEY':'tab1','txtDMorJC':symbol.split('.')[1]}[name]]
    if not all(one(name) for name in ('SHOWTYPE','TABKEY','txtDMorJC')):raise ValueError('quote source query does not match case')
    catalog=query.get('CATALOGID')
    if catalog==['1815_stock']:
        if query.get('txtBeginDate')!=[session]:raise ValueError('archive quote query does not match session')
    elif catalog==['1815_stock_snapshot']:
        try:start=date.fromisoformat(query['txtBeginDate'][0]);end=date.fromisoformat(query['txtEndDate'][0])
        except (KeyError,IndexError,ValueError):raise ValueError('snapshot quote query date range invalid') from None
        if not start<=date.fromisoformat(session)<=end:raise ValueError('snapshot quote query does not cover session')
    else:raise ValueError('unsupported official quote catalog')


def _quote_row(payload,symbol,session):
    try:value=json.loads(payload)
    except (UnicodeDecodeError,json.JSONDecodeError):raise ValueError('official quote response JSON invalid') from None
    if not isinstance(value,list):raise ValueError('official quote response must be a report list')
    tabs=[item for item in value if isinstance(item,dict) and isinstance(item.get('metadata'),dict)
        and item['metadata'].get('tabkey')=='tab1']
    if len(tabs)!=1 or tabs[0].get('error') is not None:raise ValueError('official stock report tab missing or errored')
    metadata=tabs[0]['metadata'];cols=metadata.get('cols')
    if not isinstance(cols,dict) or any(cols.get(key)!=label for key,label in _EXPECTED_COLS.items()):
        raise ValueError('official quote column labels changed')
    code=symbol.split('.')[1];rows=tabs[0].get('data')
    if not isinstance(rows,list):raise ValueError('official quote report rows invalid')
    matched=[row for row in rows if isinstance(row,dict) and row.get('jyrq')==session and row.get('zqdm')==code]
    if len(matched)!=1:raise ValueError('official quote target row missing or duplicated')
    return matched[0]


def _pit_records(root):
    audit=audit_pit_evidence(root)
    return {row['evidence_id']:row for row in audit['records'] if row.get('kind')=='security_status'}


def archive_official_rule_references(data_root,plan,*,confirm_retrospective_only=False,now_fn=None):
    """Import already-fetched official bytes; never downloads or creates MarketRules."""
    if confirm_retrospective_only is not True:
        raise ValueError('host must confirm that this is retrospective reference only')
    root=Path(data_root).expanduser()
    if root.is_symlink():raise ValueError('reference data root cannot be symlink')
    root=root.resolve()
    if not root.is_dir():raise ValueError('reference data root missing')
    directory=root/'research/official_market_rule_references';documents=directory/'documents'
    if directory.is_symlink() or documents.is_symlink():raise ValueError('reference archive cannot be symlink')
    if directory.exists() and not directory.is_dir():raise ValueError('reference archive path invalid')
    if not isinstance(plan,dict) or set(plan)!={'formula','cases'} or not isinstance(plan['formula'],dict) or set(plan['formula'])!=_FORMULA_PLAN_FIELDS:
        raise ValueError('reference plan schema invalid')
    if not isinstance(plan['cases'],list) or not plan['cases']:raise ValueError('reference plan cases missing')
    formula=plan['formula'];clauses=formula['clauses']
    if not isinstance(clauses,dict) or set(clauses)!={'price_tick','formula','rounding'} or any(not isinstance(v,str) or not v for v in clauses.values()):
        raise ValueError('formula clauses invalid')
    if not _official_source(formula['source_url']) or not _official_source(formula['notice_metadata_url']):
        raise ValueError('formula sources must be official exchange HTTPS URLs')
    published=_aware(formula['published_at'],'formula published_at')
    formula_doc,formula_payload=_save_document(root,formula['document']);notice_doc,notice_payload=_save_document(root,formula['notice_document'])
    if not formula_payload.startswith(b'%PDF'):raise ValueError('formula document is not PDF')
    try:notice=json.loads(notice_payload);milliseconds=notice['data']['pubTime'];content=notice['data']['content']
    except (UnicodeDecodeError,json.JSONDecodeError,KeyError,TypeError):raise ValueError('formula notice metadata invalid') from None
    if type(milliseconds) not in (int,float) or not isinstance(content,str):raise ValueError('formula notice publication metadata invalid')
    stated=datetime.fromtimestamp(milliseconds/1000,timezone.utc).astimezone(ZoneInfo('Asia/Shanghai'))
    if stated!=published.astimezone(ZoneInfo('Asia/Shanghai')):raise ValueError('formula publication time does not match notice metadata')
    if formula['source_url'].replace('https://','http://') not in content and formula['source_url'] not in content:
        raise ValueError('formula notice does not link supplied document')

    evidence=_pit_records(root);records=[];seen=set()
    for case in plan['cases']:
        if not isinstance(case,dict) or set(case)!=_CASE_PLAN_FIELDS:raise ValueError('reference case schema invalid')
        symbol=case['symbol'];session=case['session']
        if (not isinstance(symbol,str) or not isinstance(session,str) or not symbol.startswith('sz.') or len(symbol)!=9
                or not symbol[3:].isdigit()):raise ValueError('reference case symbol/session duplicate or invalid')
        key=(symbol,session)
        if key in seen:raise ValueError('reference case symbol/session duplicate or invalid')
        try:day=date.fromisoformat(session)
        except (TypeError,ValueError):raise ValueError('reference case session invalid') from None
        seen.add(key);announcement=evidence.get(case['announcement_evidence_id'])
        statement=announcement.get('statement') if announcement else None
        if (not announcement or statement.get('symbol')!=symbol or statement.get('tradable') is not True
                or statement.get('risk_warning')!='ST' or datetime.fromisoformat(statement['effective_at']).date()!=day):
            raise ValueError('case requires matching verified ST resumption evidence')
        announcement_published=_aware(announcement['published_at'],'announcement published_at')
        opening=datetime.combine(day,time(9,30),ZoneInfo('Asia/Shanghai'))
        if announcement_published>opening or published>opening:raise ValueError('announcement/formula was not published by session open')
        _quote_url(case['quote_source_url'],symbol,session)
        quote_doc,quote_payload=_save_document(root,case['quote_document'])
        header_doc,header_payload=_save_document(root,case['quote_headers_document'])
        observed=_http_date(header_payload)
        if observed<=datetime.combine(day,time(15),ZoneInfo('Asia/Shanghai')):
            raise ValueError('reference archive only accepts quote responses observed after the target session')
        row=_quote_row(quote_payload,symbol,session);previous=_decimal(row.get('qss'),'official previous close')
        tick=Decimal('0.01');rate=_decimal(case['limit_rate'],'announcement limit rate')
        if rate>=1:raise ValueError('announcement limit rate must be below one')
        up=(previous*(Decimal(1)+rate)).quantize(tick,rounding=ROUND_HALF_UP)
        down=(previous*(Decimal(1)-rate)).quantize(tick,rounding=ROUND_HALF_UP)
        low=_decimal(row.get('zd'),'official low');high=_decimal(row.get('zg'),'official high')
        if low!=down or high>up:raise ValueError('official quote does not corroborate the derived bounds')
        for name in ('ks','ss'):_decimal(row.get(name),'official '+name)
        records.append({'symbol':symbol,'session':session,'official_name':str(row.get('zqjc') or ''),
            'announcement_evidence_id':announcement['evidence_id'],'announcement_source_url':announcement['source_url'],
            'announcement_published_at':announcement['published_at'],'announcement_document_path':announcement['document_path'],
            'announcement_document_sha256':announcement['document_sha256'],'announcement_limit_rate':str(rate),
            'historical_quote_source_url':case['quote_source_url'],'historical_quote_observed_at':observed.isoformat(),
            'historical_quote_document':quote_doc,'historical_quote_headers_document':header_doc,
            'official_previous_close':str(previous),'official_open':row['ks'],'official_high':row['zg'],
            'official_low':row['zd'],'official_close':row['ss'],'official_reported_pct_change':str(row.get('sdf','')),
            'price_tick':str(tick),'rounding':'ROUND_HALF_UP','derived_limit_up':str(up),'derived_limit_down':str(down),
            'observed_low_matches_derived_limit_down':low==down,'observed_high_within_derived_limit_up':high<=up,
            'historical_reference_publication_verified_before_open':False,'market_rules_eligible':False,
            'blockers':[REFERENCE_BLOCKER]})
    observed_days=sorted({datetime.fromisoformat(row['historical_quote_observed_at']).date().isoformat() for row in records})
    observed_label=observed_days[0] if len(observed_days)==1 else observed_days[0]+' through '+observed_days[-1]
    value={'format':FORMAT,'created_at':_aware((now_fn or (lambda:datetime.now(timezone.utc)))(),'archive time').isoformat(),
        'scope':'Official SZSE announcement rates + 2023 trading-rule formula/rounding + official historical quote values, archived only as a retrospective derivation reference.',
        'formula_evidence':{'title':formula['title'],'source_url':formula['source_url'],
            'notice_metadata_url':formula['notice_metadata_url'],'published_at':published.isoformat(),
            'publication_value_origin':f'official notice JSON pubTime={int(milliseconds)}','document':formula_doc,
            'notice_document':notice_doc,'clauses':clauses},
        'records':records,'records_count':len(records),
        'exact_arithmetic_verified':all(r['observed_low_matches_derived_limit_down'] and r['observed_high_within_derived_limit_up'] for r in records),
        'strict_pit_eligible':False,'market_rules_snapshot_appended':False,'blockers':[REFERENCE_BLOCKER],
        'limitations':[f'The ShowReport response bytes and HTTP Date were observed on {observed_label}, after every target session.',
            'An official retrospective qss value proves the value now served by SZSE, not the exact pre-open byte vintage available on the historical session.',
            'This bundle must not be accepted by official-market-rules-v2, Qualification, PREP or execution as official_rule_covered.',
            'Commission/tax/transfer fees are outside this evidence bundle.']}
    snapshot=digest({k:v for k,v in value.items() if k!='created_at'});value['reference_snapshot']=snapshot
    target=directory/(snapshot+'.json')
    if directory.is_symlink() or target.is_symlink():raise ValueError('reference receipt path cannot be symlink')
    if target.exists():
        existing=read_checked(target)
        if digest({k:v for k,v in existing.items() if k not in {'created_at','reference_snapshot'}})!=snapshot:
            raise ValueError('existing reference receipt identity mismatch')
        check=_audit_receipt(root,target,evidence)
        if not check['verified']:raise ValueError('existing reference receipt invalid: '+check['reason'])
        return {'path':str(target),'reference_snapshot':snapshot,'records':len(records),'created':False,
            'strict_pit_eligible':False,'market_rules_snapshot_appended':False}
    directory.mkdir(parents=True,exist_ok=True);write_checked(target,value)
    check=_audit_receipt(root,target,evidence)
    if not check['verified']:raise ValueError('reference receipt self-audit failed: '+check['reason'])
    return {'path':str(target),'reference_snapshot':snapshot,'records':len(records),'created':True,
        'strict_pit_eligible':False,'market_rules_snapshot_appended':False}


def _audit_receipt(root,path,pit=None):
    try:value=read_checked(path)
    except (OSError,ValueError,TypeError):return {'verified':False,'reason':'reference_receipt_unreadable'}
    if not isinstance(value,dict) or set(value)!=_TOP_FIELDS or value.get('format')!=FORMAT:
        return {'verified':False,'reason':'reference_receipt_schema_invalid'}
    snapshot=value.get('reference_snapshot')
    if (not isinstance(snapshot,str) or path.stem!=snapshot
            or digest({k:v for k,v in value.items() if k not in {'created_at','reference_snapshot'}})!=snapshot):
        return {'verified':False,'reason':'reference_snapshot_mismatch'}
    try:_aware(value['created_at'],'created_at')
    except ValueError:return {'verified':False,'reason':'reference_created_at_invalid'}
    if (value.get('strict_pit_eligible') is not False or value.get('market_rules_snapshot_appended') is not False
            or value.get('blockers')!=[REFERENCE_BLOCKER] or not isinstance(value.get('scope'),str)
            or not isinstance(value.get('limitations'),list) or not value['limitations']):
        return {'verified':False,'reason':'reference_nonqualifying_boundary_invalid'}
    formula=value.get('formula_evidence')
    if (not isinstance(formula,dict) or set(formula)!=_FORMULA_FIELDS or not _official_source(formula.get('source_url'))
            or not _official_source(formula.get('notice_metadata_url')) or not isinstance(formula.get('clauses'),dict)
            or set(formula['clauses'])!={'price_tick','formula','rounding'}):
        return {'verified':False,'reason':'reference_formula_invalid'}
    if not _check_document(root,formula.get('document')) or not _check_document(root,formula.get('notice_document')):
        return {'verified':False,'reason':'reference_formula_document_invalid'}
    try:
        formula_published=_aware(formula['published_at'],'published_at')
        formula_payload=_document(root,formula['document']['path']);notice_payload=_document(root,formula['notice_document']['path'])
        notice=json.loads(notice_payload);milliseconds=notice['data']['pubTime'];content=notice['data']['content']
        stated=datetime.fromtimestamp(milliseconds/1000,timezone.utc).astimezone(ZoneInfo('Asia/Shanghai'))
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError):
        return {'verified':False,'reason':'reference_formula_time_invalid'}
    if (not formula_payload.startswith(b'%PDF') or stated!=formula_published.astimezone(ZoneInfo('Asia/Shanghai'))
            or formula.get('publication_value_origin')!=f'official notice JSON pubTime={int(milliseconds)}'
            or (formula['source_url'].replace('https://','http://') not in content and formula['source_url'] not in content)):
        return {'verified':False,'reason':'reference_formula_metadata_mismatch'}
    records=value.get('records');pit=pit if pit is not None else _pit_records(root)
    if not isinstance(records,list) or not records or value.get('records_count')!=len(records):
        return {'verified':False,'reason':'reference_records_invalid'}
    seen=set();exact=True
    for row in records:
        if not isinstance(row,dict) or set(row)!=_RECORD_FIELDS:
            return {'verified':False,'reason':'reference_record_schema_invalid'}
        symbol=row.get('symbol');session=row.get('session')
        if not isinstance(symbol,str) or not isinstance(session,str):
            return {'verified':False,'reason':'reference_record_values_invalid'}
        key=(symbol,session)
        if key in seen:return {'verified':False,'reason':'reference_record_duplicate'}
        seen.add(key);announcement=pit.get(row.get('announcement_evidence_id'))
        if (not announcement or announcement.get('source_url')!=row.get('announcement_source_url')
                or announcement.get('published_at')!=row.get('announcement_published_at')
                or announcement.get('document_path')!=row.get('announcement_document_path')
                or announcement.get('document_sha256')!=row.get('announcement_document_sha256')):
            return {'verified':False,'reason':'reference_announcement_evidence_invalid'}
        statement=announcement.get('statement') or {}
        if (statement.get('symbol')!=row.get('symbol') or statement.get('tradable') is not True
                or statement.get('risk_warning')!='ST' or not isinstance(row.get('official_name'),str) or not row['official_name']):
            return {'verified':False,'reason':'reference_announcement_semantics_invalid'}
        if not _official_source(row.get('historical_quote_source_url')):
            return {'verified':False,'reason':'reference_quote_source_invalid'}
        if not _check_document(root,row.get('historical_quote_document')) or not _check_document(root,row.get('historical_quote_headers_document')):
            return {'verified':False,'reason':'reference_quote_document_invalid'}
        try:
            day=date.fromisoformat(row['session']);opening=datetime.combine(day,time(9,30),ZoneInfo('Asia/Shanghai'))
            if datetime.fromisoformat(statement['effective_at']).date()!=day:raise ValueError('status session mismatch')
            announcement_time=_aware(row['announcement_published_at'],'announcement published_at')
            observed=_aware(row['historical_quote_observed_at'],'quote observed_at')
            _quote_url(row['historical_quote_source_url'],row['symbol'],row['session'])
            payload=_document(root,row['historical_quote_document']['path']);parsed=_quote_row(payload,row['symbol'],row['session'])
            header_payload=_document(root,row['historical_quote_headers_document']['path'])
            if _http_date(header_payload)!=observed:raise ValueError('HTTP Date mismatch')
            previous=_decimal(row['official_previous_close'],'previous close');rate=_decimal(row['announcement_limit_rate'],'rate')
            tick=_decimal(row['price_tick'],'tick')
            if rate>=1 or tick!=Decimal('0.01'):raise ValueError('rate/tick invalid')
            up=(previous*(Decimal(1)+rate)).quantize(tick,rounding=ROUND_HALF_UP)
            down=(previous*(Decimal(1)-rate)).quantize(tick,rounding=ROUND_HALF_UP)
            low=_decimal(row['official_low'],'low');high=_decimal(row['official_high'],'high')
        except (OSError,ValueError,KeyError):return {'verified':False,'reason':'reference_record_values_invalid'}
        fields={'qss':'official_previous_close','ks':'official_open','zg':'official_high','zd':'official_low','ss':'official_close','sdf':'official_reported_pct_change'}
        if any(str(parsed.get(source,''))!=str(row[target]) for source,target in fields.items()):
            return {'verified':False,'reason':'reference_quote_row_mismatch'}
        if (formula_published>opening or announcement_time>opening or observed<=datetime.combine(day,time(15),ZoneInfo('Asia/Shanghai'))
                or row.get('rounding')!='ROUND_HALF_UP' or row.get('derived_limit_up')!=str(up)
                or row.get('derived_limit_down')!=str(down)):
            return {'verified':False,'reason':'reference_derivation_invalid'}
        low_match=low==down;high_within=high<=up;exact=exact and low_match and high_within
        if (row.get('observed_low_matches_derived_limit_down') is not low_match
                or row.get('observed_high_within_derived_limit_up') is not high_within
                or row.get('historical_reference_publication_verified_before_open') is not False
                or row.get('market_rules_eligible') is not False or row.get('blockers')!=[REFERENCE_BLOCKER]):
            return {'verified':False,'reason':'reference_record_boundary_invalid'}
    if value.get('exact_arithmetic_verified') is not exact:
        return {'verified':False,'reason':'reference_arithmetic_summary_invalid'}
    return {'verified':True,'reason':'verified_retrospective_official_rule_reference','reference_snapshot':snapshot,
        'records':len(records),'strict_pit_eligible':False,'market_rules_snapshot_appended':False}


def audit_official_rule_references(data_root):
    supplied=Path(data_root).expanduser()
    if supplied.is_symlink():raise ValueError('reference data root cannot be symlink')
    root=supplied.resolve();directory=root/'research/official_market_rule_references'
    if directory.is_symlink():raise ValueError('reference archive cannot be symlink')
    if not directory.exists():paths=[]
    elif not directory.is_dir():raise ValueError('reference archive path invalid')
    else:paths=sorted(path for path in directory.glob('*.json') if not path.name.startswith('.'))
    pit=_pit_records(root);verified=[];invalid=[];records=0
    for path in paths:
        try:check=_audit_receipt(root,path,pit)
        except (OSError,ValueError,TypeError,KeyError):check={'verified':False,'reason':'reference_receipt_audit_error'}
        if check['verified']:verified.append(check);records+=check['records']
        else:invalid.append({'file':str(path.relative_to(root)),'reason':check['reason']})
    return {'format':'niuniu-official-market-rule-reference-audit-v1','receipt_files':len(paths),
        'verified_receipts':len(verified),'invalid_receipts':len(invalid),'reference_records':records,
        'strict_pit_eligible_records':0,'market_rules_snapshots_appended':0,'snapshots':verified[-100:],
        'invalid':invalid[:100],'scope':'Retrospective reference inventory only; never accepted as Official MarketRules or Strict PIT publication evidence.'}


__all__=['FORMAT','REFERENCE_BLOCKER','archive_official_rule_references','audit_official_rule_references']

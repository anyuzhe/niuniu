"""Conservative per-request data qualification; never upgrades retrospective data by inference."""
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime
import hashlib,json
import polars as pl

LEVELS=('research_only','retrospective_reference','strict_pit','official_rule_covered')
BAR_FIELDS={'open','high','low','close','volume','turnover','adj_factor'}
OFFICIAL_HOSTS={'sse.com.cn','www.sse.com.cn','star.sse.com.cn','szse.cn','www.szse.cn','bse.cn','www.bse.cn'}
AUTHORITATIVE_PIT_HOSTS=OFFICIAL_HOSTS|{'cninfo.com.cn','www.cninfo.com.cn'}


def requested_level(spec):
    level=spec.get('qualification','research_only') if isinstance(spec,dict) else 'research_only'
    if level not in LEVELS:raise ValueError('qualification须为 '+', '.join(LEVELS))
    return level


def _component(status,reason='',evidence=None,limitations=None):
    return {'status':status,'reason':reason,'evidence':evidence or [],'limitations':limitations or []}


def _official_source(value):
    try:
        parsed=urlparse(value);host=(parsed.hostname or '').lower()
        return parsed.scheme=='https' and host in OFFICIAL_HOSTS
    except (TypeError,ValueError):return False


def _authoritative_pit_source(value):
    try:
        parsed=urlparse(value);host=(parsed.hostname or '').lower()
        return parsed.scheme=='https' and host in AUTHORITATIVE_PIT_HOSTS
    except (TypeError,ValueError):return False



def _official_rule_receipt(root,snapshot_id):
    path=Path(root)/'research/official_market_rules.json'
    if path.is_symlink() or not path.is_file():return {'verified':False,'reason':'official_rule_receipt_missing'}
    try:value=json.loads(path.read_text())
    except (OSError,ValueError,TypeError):return {'verified':False,'reason':'official_rule_receipt_invalid_json'}
    if not isinstance(value,dict) or set(value)!={'format','rules_snapshot','sources'} or value['format']!='official-market-rules-v1':
        return {'verified':False,'reason':'official_rule_receipt_schema_invalid'}
    if value['rules_snapshot']!=snapshot_id:return {'verified':False,'reason':'official_rule_snapshot_mismatch'}
    if not isinstance(value['sources'],list) or not value['sources']:return {'verified':False,'reason':'official_rule_sources_missing'}
    evidence=[]
    for item in value['sources']:
        if not isinstance(item,dict) or set(item)!={'url','path','sha256','fetched_at'} or not _official_source(item['url']):
            return {'verified':False,'reason':'official_rule_source_invalid'}
        fetched=datetime.fromisoformat(item['fetched_at'])
        if fetched.tzinfo is None:return {'verified':False,'reason':'official_rule_fetch_time_missing_timezone'}
        relative=Path(item['path'])
        if relative.is_absolute() or '..' in relative.parts:return {'verified':False,'reason':'official_rule_document_path_invalid'}
        document=(Path(root)/relative).resolve()
        if not document.is_relative_to(Path(root).resolve()) or not document.is_file():return {'verified':False,'reason':'official_rule_document_missing'}
        payload=document.read_bytes()
        if hashlib.sha256(payload).hexdigest()!=item['sha256']:return {'verified':False,'reason':'official_rule_document_hash_mismatch'}
        evidence.append({'url':item['url'],'path':str(relative),'sha256':item['sha256'],'fetched_at':item['fetched_at']})
    return {'verified':True,'reason':'verified_official_rule_documents','sources':evidence}

def qualify_research(data_root,spec):
    from quantlab.workbench.jobs import prepare
    from quantlab.data.provider import local_data_provider
    from quantlab.app import default_registry
    level=requested_level(spec);submission=prepare(spec);config=submission.config
    result={'required_level':level,'qualified':True,'components':{},'blockers':[],'warnings':[],
        'scope':'Qualification is request-scoped; it does not permanently certify a dataset or provider.'}
    if level=='research_only':
        result['components']['contract']=_component('research_only','No PIT or official-rule certification requested.')
        result['warnings'].append('research_only允许回溯资料；结果不得表述为strict PIT或official-rule covered。')
        return result
    root=Path(data_root).resolve()
    provider=local_data_provider(root,submission.adjustment);batch=provider.load(config.data);bars=batch.bars
    file_entries=[v for v in batch.snapshot.files if isinstance(v,dict) and v.get('path')]
    bar_pit_verified=bool(file_entries) and all(v.get('historical_available_at_verified') is True for v in file_entries)
    result['components']['bars']=_component('strict_pit' if bar_pit_verified else 'retrospective_reference',
        'Requested bars loaded and frozen by snapshot identity; strict PIT additionally requires every input file to carry verified historical availability evidence.',
        [{'snapshot_id':batch.snapshot.snapshot_id,'source':batch.snapshot.source,'adjustment':batch.snapshot.adjustment,
          'historical_available_at_verified':bar_pit_verified}])
    if not bar_pit_verified:result['blockers'].append('historical_bar_vintage_not_certified')
    if bars.is_empty():result['blockers'].append('requested_bars_empty')
    for column in ('datetime','available_at'):
        if column not in bars.columns or not isinstance(bars.schema[column],pl.Datetime) or bars.schema[column].time_zone is None:
            result['blockers'].append('bars_missing_timezone_'+column)
    if {'datetime','available_at'}<=set(bars.columns) and bars.filter(pl.col('available_at')<pl.col('datetime')).height:
        result['blockers'].append('bars_available_before_event_time')
    if submission.adjustment!='raw':
        result['blockers'].append('adjusted_price_historical_availability_unverified')
        result['components']['adjustment']=_component('retrospective_reference',
            'qfq is reproducible in the saved snapshot but historical availability of adjustment information is not certified.')
    else:result['components']['adjustment']=_component('timing_contract_passed','raw price path selected')
    factor=default_registry().get(config.factor_id,config.factor_version);definition=factor.definition
    required=set(definition.required_fields);retrospective_fields=sorted(f for f in required if f.startswith('bs_'))
    if retrospective_fields or 'retrospective' in definition.tags:
        result['blockers'].append('factor_first_publication_or_revision_history_unverified')
        result['components']['factor_information_time']=_component('retrospective_reference',
            'Factor depends on provider fields whose historical first-publication/revision timeline is not certified.',
            [{'factor_id':definition.factor_id,'fields':retrospective_fields}])
    else:
        result['components']['factor_information_time']=_component('timing_contract_passed',
            'Factor uses only bar fields or other inputs without an explicit retrospective tag in its registered definition.')
    processor=config.processor
    if hasattr(processor,'steps'):
        methods={step['method'] for step in processor.steps}
        if methods & {'industry_neutralization','neutralization'}:
            from quantlab.data.industry import IndustryHistory
            history=IndustryHistory(processor.industry_events);missing=0
            for row in bars.select('symbol','datetime').iter_rows(named=True):
                if history.at(row['symbol'],row['datetime']) is None:missing+=1
            bad=sorted({r['source'] for r in history.records if not _authoritative_pit_source(r['source'])})
            from quantlab.data.pit_evidence import verify_pit_statements
            proof=verify_pit_statements(root,'industry_membership',history.records)
            if missing:result['blockers'].append('industry_history_missing_at_requested_bar_times')
            if bad:result['blockers'].append('industry_history_source_not_authoritative')
            if not proof['verified']:result['blockers'].append('industry_history_publication_evidence_unverified')
            result['components']['industry_history']=_component('strict_pit' if not missing and not bad and proof['verified'] else 'incomplete',
                'Industry neutralization requires contemporaneously available membership plus archived authoritative publication evidence.',
                [{'records':len(history.records),'missing_bar_rows':missing,'non_authoritative_sources':bad},proof])
        if methods & {'size_neutralization','neutralization'}:
            from quantlab.processing.neutralization import SizeHistory
            history=SizeHistory(processor.size_events);missing=0
            for row in bars.select('symbol','datetime').iter_rows(named=True):
                if history.at(row['symbol'],row['datetime']) is None:missing+=1
            bad=sorted({r['source'] for r in history.records if not _authoritative_pit_source(r['source'])})
            from quantlab.data.pit_evidence import verify_pit_statements
            proof=verify_pit_statements(root,'daily_market_cap',history.records)
            if missing:result['blockers'].append('daily_market_cap_missing_or_expired_at_requested_bar_times')
            if bad:result['blockers'].append('market_cap_source_not_authoritative')
            if not proof['verified']:result['blockers'].append('market_cap_publication_evidence_unverified')
            result['components']['daily_market_cap']=_component('strict_pit' if not missing and not bad and proof['verified'] else 'incomplete',
                'Size neutralization requires point-in-time market cap plus archived authoritative publication evidence.',
                [{'records':len(history.records),'missing_bar_rows':missing,'non_authoritative_sources':bad},proof])
    universe=submission.universe
    if universe.mode=='explicit':
        result['components']['universe']=_component('fixed_cohort',
            'Explicit symbols are valid for a fixed-cohort question but do not certify a point-in-time market population.',
            limitations=['Do not generalize this qualification to an all-market survivorship-free universe.'])
    elif universe.mode=='listing':
        result['blockers'].append('listing_universe_is_retrospective_not_pit')
        result['components']['universe']=_component('retrospective_reference',
            'IPO/delisting dates are retrospective reference metadata, not historical eligibility decisions with known_at timestamps.')
    else:
        from quantlab.data.universe import build_universe
        built=build_universe(root,config.data.symbols,universe);built.mask(bars)
        provenance=(getattr(built,'metadata',{}) or {})
        if not provenance.get('official_source') and not provenance.get('historical_publication_verified'):
            result['blockers'].append('pit_universe_timing_present_but_provenance_not_certified')
            status='timing_contract_only'
        else:status='strict_pit'
        result['components']['universe']=_component(status,
            'PIT universe uses effective_at and available_at; provenance certification is evaluated separately.',[provenance])
    if level=='official_rule_covered':
        if submission.mode!='execution':
            result['blockers'].append('official_rule_covered_requires_execution_mode')
            result['components']['official_rules']=_component('not_applicable','Official execution-rule coverage requires execution mode.')
        elif not submission.market_rules:
            result['blockers'].append('official_market_rules_missing')
            result['components']['official_rules']=_component('missing','No explicit per-session market rules were supplied.')
        else:
            from quantlab.execution.rules import MarketRules
            from quantlab.execution.rules_audit import audit_market_rules
            rules=MarketRules(submission.market_rules)
            dates=bars['datetime'].dt.date().unique().sort().to_list()
            audit=audit_market_rules(rules,config.data.symbols,dates)
            unofficial=sorted({r['source'] for r in rules.records if not _official_source(r['source'])})
            receipt=_official_rule_receipt(root,rules.snapshot_id)
            if audit['status']!='covered':result['blockers'].append('official_market_rule_sessions_incomplete')
            if unofficial:result['blockers'].append('market_rule_source_not_official_exchange_url')
            if not receipt['verified']:result['blockers'].append(receipt['reason'])
            result['components']['official_rules']=_component(
                'official_rule_covered' if audit['status']=='covered' and not unofficial and receipt['verified'] else 'incomplete',
                'Exact supplied per-session bounds/status must be fully covered and tied to hashed locally archived official exchange documents.',
                [audit,{'unofficial_sources':unofficial},receipt],
                ['This certifies the supplied price/status rule record coverage only; brokerage fee assumptions remain separate.'])
    strict_blockers=list(result['blockers'])
    if level=='retrospective_reference':
        result['qualified']=not bars.is_empty()
        result['status']='qualified_retrospective_reference' if result['qualified'] else 'blocked'
        result['strict_pit_blockers']=strict_blockers
        result['blockers']=[] if result['qualified'] else ['requested_bars_empty']
    elif level=='strict_pit':
        result['qualified']=not strict_blockers
        result['status']='qualified_strict_pit' if result['qualified'] else 'blocked'
    else:
        result['qualified']=not strict_blockers
        result['status']='qualified_official_rule_covered' if result['qualified'] else 'blocked'
    if not result['qualified']:
        result['warnings'].append('请求的资格级别未满足；不得静默降级后继续以原资格名称解释结果。')
    return result


def qualify_spec(data_root,spec):
    if isinstance(spec,dict) and spec.get('mode')=='campaign':
        nodes=spec.get('nodes') or [];reports={};blockers=[]
        for node in nodes:
            node_id=node.get('node_id','?');report=qualify_research(data_root,node.get('spec') or {})
            reports[node_id]=report
            if not report['qualified']:
                blockers.extend(node_id+':'+value for value in report.get('blockers',[]))
        required=sorted({r['required_level'] for r in reports.values()})
        return {'required_level':'campaign_mixed','qualified':not blockers,'status':'qualified' if not blockers else 'blocked',
            'node_reports':reports,'required_levels':required,'blockers':blockers,
            'scope':'Every campaign node is qualified independently; a strict node is never downgraded by a research-only sibling.'}
    return qualify_research(data_root,spec)

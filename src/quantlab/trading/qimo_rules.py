"""Source-led Qimo hypotheses. Numeric translations are explicit engineering proxies."""
from datetime import datetime, timedelta, timezone
from .theme_store import ThemeStore

ENGINE='qimo-source-rules-v2'
RULES={
    'joint_initiative_and_leadership': ['102483587','101823181','101779598','102877892'],
    'market_and_sector_context': ['101958742','102579520','102592739','102130578'],
    'not_fixed_two_to_three': ['101889713'],
    'hold_when_expectations_intact': ['101993475','102303642','102560387'],
    'exit_after_sector_weakness_and_failed_reseal': ['102643774','102187756'],
    'persistent_failure_to_turn_positive': ['102116194'],
    'position_sizing_not_disclosed': ['102665056'],
    'rest_when_unclear': ['102887357'],
}


def _pct(item):
    previous=item.get('previous_close')
    last=item.get('last',item.get('auction_price'))
    if last is None:last=item.get('auction_price')
    return (last/previous-1)*100 if last is not None and previous else None


def _theme_rows(output,day,frame,as_of):
    rows=ThemeStore(output).list(start=day,end=day,frame=frame,include_superseded=True,limit=2000)['records']
    result={}
    for row in rows:
        facts=row['facts'];at=row.get('facts_as_of')
        if not at or not row.get('facts_source'):continue
        at=datetime.fromisoformat(at)
        if not timedelta(0)<=as_of-at<=timedelta(minutes=10):continue
        if datetime.fromisoformat(row['submitted_at'])>as_of:continue
        if not {'leader_symbol','leader_return','breadth_up','breadth_down','limit_up_count'}<=facts.keys():continue
        if row['theme'] not in result:result[row['theme']]=row
    return result


def assess(item,prior,themes,previous_themes):
    """Only market facts, never AI state labels. Missing context is not an exit."""
    symbol=item['symbol'];current=_pct(item);before=_pct(prior) if prior else None
    relevant=[(name,t) for name,t in themes.items() if t['facts']['leader_symbol']==symbol
        or previous_themes.get(name,{}).get('facts',{}).get('leader_symbol')==symbol]
    if not relevant or current is None or before is None:
        return {'action':'WAIT_CONTEXT','score':0.,'reason':'缺少可追溯板块事实或前一观察点','rule_ids':[]}
    outcomes=[]
    for name,theme in relevant:
        f=theme['facts'];old=previous_themes.get(name);p=old['facts'] if old else None
        support=f['breadth_up']>f['breadth_down'] and f['limit_up_count']>0 and f['leader_return']>0
        fading=bool(p and (f['breadth_up']<p['breadth_up'] or f['limit_up_count']<p['limit_up_count'])
            and f['leader_return']<p['leader_return'])
        bound=item.get('limit_up_price')
        prior_last=prior.get('last') if prior.get('last') is not None else prior.get('auction_price')
        failed_reseal=bool(bound and item.get('high') is not None and item['high']>=bound-.005
            and item.get('last',bound)<bound-.005 and prior_last is not None and prior_last<bound-.005)
        persistent_weak=current<=0 and before<=0
        passive=f['leader_symbol']!=symbol and current<before
        evidence=[theme['snapshot_id']]+([old['snapshot_id']] if old else [])
        if fading and (failed_reseal or persistent_weak or passive):
            outcomes.append({'action':'EXIT','score':0.,'theme':name,'evidence_ids':evidence,
                'reason':'板块事实走弱，个股回封未确认/持续不红/相对被动',
                'rule_ids':['exit_after_sector_weakness_and_failed_reseal','persistent_failure_to_turn_positive']})
            continue
        one_price=all(item.get(k) is not None for k in ('open','high','low','last')) and item['high']==item['low']
        initiative=current>0 and current>before
        if p and support and not fading and f['leader_symbol']==symbol and initiative:
            accessible=item.get('tradable') and item.get('execution_profile')=='STANDARD_ACCESS' and not one_price
            # Continuous comparison proxy, not an author's position-size formula.
            breadth=f['breadth_up']/max(1,f['breadth_up']+f['breadth_down'])
            outcomes.append({'action':'BUY' if accessible else 'QUEUE_OBSERVE','score':(current-before)*breadth,
                'theme':name,'evidence_ids':evidence,'reason':'相对主动增强且板块核心获得助攻' if accessible else '有信号但队列成交不可证',
                'rule_ids':['joint_initiative_and_leadership','market_and_sector_context']})
        else:
            outcomes.append({'action':'HOLD','score':0.,'theme':name,'evidence_ids':evidence,
                'reason':'未触发有证据的退出；允许等待修复，不按持有天数清仓',
                'rule_ids':['hold_when_expectations_intact']})
    # A strengthening valid theme takes precedence over another theme's decline;
    # conflicting evidence otherwise defers an exit instead of manufacturing certainty.
    buys=[x for x in outcomes if x['action']=='BUY']
    if buys:return max(buys,key=lambda x:x['score'])
    if all(x['action']=='EXIT' for x in outcomes):return outcomes[0]
    return next((x for x in outcomes if x['action']!='EXIT'),outcomes[0])


def scan_source_rules(output,base,case,definition,snapshot,previous):
    stamp=datetime.fromisoformat(snapshot['as_of']);prior_stamp=datetime.fromisoformat(previous['as_of'])
    themes=_theme_rows(output,base['trading_day'],snapshot['frame'],stamp)
    older=_theme_rows(output,base['trading_day'],previous['frame'],prior_stamp)
    items={r['symbol']:r for r in snapshot['instruments']};old={r['symbol']:r for r in previous['instruments']}
    complete=base['completeness']=='FULL' and snapshot['completeness']=='FULL' and previous['completeness']=='FULL'
    missing=[c['symbol'] for c in base['candidates'] if c['symbol'] not in items or c['symbol'] not in old]
    complete=complete and not missing;candidates=[];selected=[];reasons={};evidence=[
        'market_snapshot:'+snapshot['snapshot_id'],'market_snapshot:'+previous['snapshot_id']]
    for c in base['candidates']:
        symbol=c['symbol']
        result=assess(items[symbol],old[symbol],themes,older) if complete else {
            'action':'WAIT_CONTEXT','score':0.,'reason':'候选或行情快照不完整','rule_ids':[]}
        features={**c['features'],'qimo_assessment':result}
        candidates.append({**c,'features':features})
        if result['action']=='BUY':selected.append(symbol)
        reasons[symbol]=[result['reason']]
        evidence.extend('theme_snapshot:'+x for x in result.get('evidence_ids',[]))
    scores={c['symbol']:c['features']['qimo_assessment']['score'] for c in candidates}
    ranked=sorted(scores,key=lambda s:(scores[s],s),reverse=True)
    selected=[s for s in ranked if s in selected]
    note='本人定性逻辑的显式工程近似；不截取第一名；板块事实缺失不编造信号；不是已验证复刻。'
    payload={'definition_id':definition['definition_id'],'trading_day':base['trading_day'],'frame':snapshot['frame'],
        'as_of':snapshot['as_of'],'source_ids':definition['source_ids'],
        'market_snapshot_ids':[snapshot['snapshot_id'],previous['snapshot_id']],
        'summary':'主动性+板块核心/助攻联合比较；条件式持有/退出','notes':note,
        'candidate_set':{'completeness':'FULL' if complete else 'PARTIAL','pit_status':'UNKNOWN',
            'universe_source':'base_candidate_set:'+base['candidate_set_id'],'generation_method':ENGINE,
            'candidates':candidates,'evidence_ids':list(dict.fromkeys(evidence))},
        'prediction':{'selected_symbols':selected,'ranked_symbols':ranked,'reasons':reasons,
            'evidence_ids':list(dict.fromkeys(evidence)),'notes':note}}
    return {'scanner_version':ENGINE,'base_candidate_set_id':base['candidate_set_id'],'frame':snapshot['frame'],
        'trading_day':base['trading_day'],'complete':complete,'missing_symbols':missing,
        'selected_symbols':selected,'ranked_symbols':ranked,'forward_payload':payload}


def portfolio_targets(previous,assessments,*,allow_entries=True):
    """Preserve existing allocation unless an explicit exit fires; allocate free
    cash by relative signal strength. No position count or fixed weight ceiling.
    This sizing translation is engineering, not a disclosed author formula.
    """
    weights=dict(previous)
    for symbol,a in assessments.items():
        if a['action']=='EXIT':weights.pop(symbol,None)
    available=max(0.,1.-sum(weights.values()))
    buys={s:a['score'] for s,a in assessments.items() if a['action']=='BUY' and a['score']>0} if allow_entries else {}
    total=sum(buys.values())
    if total:
        for symbol,score in buys.items():weights[symbol]=weights.get(symbol,0.)+available*score/total
    return weights

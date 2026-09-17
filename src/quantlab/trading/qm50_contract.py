"""QM50-SCLA v0.2 component contracts. NOT a complete 60-field strategy/backtester.

These pure functions support auditable definition/guard tests. No broker, network,
account persistence or registry substitution is provided.
"""
from datetime import datetime,timedelta
from math import isfinite,log
from statistics import median


def number(value):
    return type(value) in (int,float) and isfinite(value)

def timestamp(value):
    stamp=datetime.fromisoformat(value) if isinstance(value,str) else value
    if not isinstance(stamp,datetime) or stamp.tzinfo is None:raise ValueError('Timestamp must include timezone')
    return stamp

def observable(event_time,available_at,decision_time):
    e,a,d=map(timestamp,(event_time,available_at,decision_time))
    return e<=a<=d

def mid_cdf(value,history):
    if not number(value) or not history or not all(number(v) for v in history):return None
    return 100*(sum(v<value for v in history)+.5*sum(v==value for v in history))/len(history)

def previous_relative_amount(previous_amount,earlier_twenty):
    if len(earlier_twenty)!=20:return {'value':None,'status':'INSUFFICIENT_HISTORY'}
    if not number(previous_amount) or previous_amount<=0 or any(not number(v) or v<=0 for v in earlier_twenty):
        return {'value':None,'status':'MISSING_SOURCE'}
    return {'value':previous_amount/median(earlier_twenty),'status':'OK'}

def known_lead(trigger_at,theme_trigger_at,decision_at,*,feed_complete):
    if not feed_complete:return {'value':None,'score':None,'status':'MISSING_SOURCE'}
    now=timestamp(decision_at)
    if trigger_at is None or timestamp(trigger_at)>now:
        return {'value':0.,'score':0.,'status':'NO_EVENT','censored':False}
    future=theme_trigger_at is None or timestamp(theme_trigger_at)>now
    end=now if future else timestamp(theme_trigger_at)
    return {'value':(end-timestamp(trigger_at)).total_seconds(),'score':None,'status':'OK','censored':future}

def pullback(high,low,last,tick,*,completed_minutes):
    if completed_minutes<3:return {'value':None,'status':'NOT_YET_OBSERVABLE'}
    if not all(number(v) for v in (high,low,last,tick)) or tick<=0 or not low<=last<=high:return {'value':None,'status':'MISSING_SOURCE'}
    if high==low:return {'value':.5,'score':50.,'status':'OK','flat':True}
    raw=min(1.,max(0.,1-(high-last)/max(high-low,tick)))
    return {'value':raw,'score':100*raw,'status':'OK','flat':False}

def historical_response(scores,*,feed_complete):
    if not feed_complete or any(not number(v) or not 0<=v<=100 for v in scores):return {'value':None,'status':'MISSING_SOURCE'}
    values=scores[-20:];n=len(values)
    return {'value':50. if n==0 else 50+n/(n+5)*(sum(values)/n-50),'status':'COLD_START' if n==0 else 'OK'}

def response_amount_score(score,peer_excess):
    if not number(score) or not number(peer_excess):return None
    return min(score,50.) if peer_excess<=0 else score

def weighted(values,weights):
    selected={k:values.get(k.removesuffix('_reversed')) for k in weights}
    if any(not number(v) or not 0<=v<=100 for v in selected.values()):return None
    return sum(selected[k]*weight for k,weight in weights.items())

def base_score(S,A,Lpre):
    return (0.25*S+0.22*A+0.16*Lpre)/.63 if all(number(v) for v in (S,A,Lpre)) else None

def components(spec,scores,phase,completed_minutes):
    if phase not in ('AUCTION_RESULT','INTRADAY'):raise ValueError('Unsupported score phase')
    actual='AUCTION_RESULT' if completed_minutes<3 else phase
    w=spec['weights'];result={'score_phase':actual}
    for name in ('S','Lpre','Lreal','C','Tbase','N','D'):result[name]=weighted(scores,w[name])
    result['A']=weighted(scores,w['A_auction' if actual=='AUCTION_RESULT' else 'A_intraday'])
    result['B']=base_score(result['S'],result['A'],result['Lpre'])
    tb,overheat=result['Tbase'],scores.get('T06')
    result['T']=min(100,max(0,tb-max(overheat-80,0))) if number(tb) and number(overheat) else None
    parts=[result[k] for k in ('S','A','Lpre','C','T','N')]
    result['Q']=sum(a*b for a,b in zip(parts,(.25,.22,.16,.12,.10,.08)))/.93 if all(number(v) for v in parts) else None
    result['PrevStrength']=sum(scores[k] for k in ('P02','P03','P04','P05'))/4 if all(number(scores.get(k)) for k in ('P02','P03','P04','P05')) else None
    return result

def competition_raw(base_values,symbol):
    if symbol not in base_values or any(not number(v) for v in base_values.values()):return None
    peers=[v for k,v in base_values.items() if k!=symbol]
    if not peers:return {'raw_gap':0.,'neutral_score':50.,'flag':'NO_COMPARABLE_PEER'}
    return {'raw_gap':base_values[symbol]-max(peers),'neutral_score':None,'flag':'OK'}

def choose_target(q_by_symbol,*,complete,locked=None,market_n=100,fillable=None,thresholds):
    fail=lambda code:{'locked_target':locked,'selected':None,'reason':code,'gap':None}
    if not complete or any(not number(q) for q in q_by_symbol.values()):return fail('MISSING_CRITICAL_DATA')
    if len(q_by_symbol)<2:return fail('NO_UNIQUE_LEADER')
    ranks=sorted(q_by_symbol,key=lambda s:q_by_symbol[s],reverse=True);top=ranks[0]
    gap=q_by_symbol[top]-q_by_symbol[ranks[1]]
    if gap==0:return fail('NO_UNIQUE_LEADER')
    if locked is not None and locked!=top:return fail('LOCKED_TARGET_LOST_TOP1_NO_REPLACEMENT')
    if q_by_symbol[top]<thresholds['q_min']:return fail('SCORE_BELOW_THRESHOLD')
    if gap<thresholds['top1_gap_min']:return fail('INSUFFICIENT_GAP')
    if market_n<thresholds['market_N_min']:return fail('MARKET_RISK_GATE')
    locked=top
    if fillable is None or fillable.get(top) is not True:return fail('UNFILLABLE_TOP1')
    return {'locked_target':locked,'selected':top,'reason':'SCORE_AND_ACCESS_ONLY_NOT_AN_ORDER','gap':gap}

def is_candidate(previous_close,upper,previous_height,volume,eligible):
    return eligible is True and number(volume) and volume>0 and previous_height>=1 and previous_close==upper

def one_price(ohlc,upper,volume):
    return number(volume) and volume>0 and all(number(v) and v==upper for v in ohlc)

def episode_drawdown(upper,observations,start,end,decision):
    if timestamp(decision)<timestamp(end):return None
    eligible=[price for at,available,price in observations if timestamp(start)<=timestamp(at)<=timestamp(end)
              and observable(at,available,decision)]
    return (upper-min(eligible))/upper if upper>0 and eligible else None

def sellable(lots,day):
    return sum(max(0,lot['filled']-lot.get('sold',0)-lot.get('frozen',0)) for lot in lots if lot['buy_day']<day)

def pending_exit(quantity,bid_available):
    return {'filled':quantity if bid_available else 0,'remaining':0 if bid_available else quantity}

def entry_trigger(last,upper,tick):
    return all(number(v) for v in (last,upper,tick)) and tick>0 and upper-tick<=last<=upper

def reseal_gate(D,seconds,drawdown,amount_ratio,t):
    return all(number(v) for v in (D,seconds,drawdown,amount_ratio)) and D>=t['reseal_D_min'] and 0<=seconds<=t['reseal_seconds_max'] and 0<=drawdown<=t['reseal_drawdown_max'] and amount_ratio>=t['reseal_amount_ratio_min']

def exit_confirmed(snapshots,t):
    if len(snapshots)<2:return False
    (at1,score1,complete1),(at2,score2,complete2)=snapshots[-2:]
    return complete1 and complete2 and number(score1) and number(score2) and score1<t['hold_exit_below'] and score2<t['hold_exit_below'] and (timestamp(at2)-timestamp(at1)).total_seconds()>=t['hold_exit_snapshot_spacing_seconds']

def contract_checks(spec):
    """Synthetic executable component cases; no actual market or account claims."""
    t=spec['research_thresholds'];checks=[];day='2024-01-02';at=lambda h:day+'T'+h+'+08:00'
    def check(key,actual,expected):
        passed=actual==expected
        if number(actual) and number(expected):passed=abs(actual-expected)<1e-9
        checks.append({'check_id':key,'passed':passed,'actual':actual,'expected':expected,'evidence_type':'SYNTHETIC_COMPONENT_TEST'})
    check('auction_result_no_backfill',observable(at('09:25:00'),at('09:25:01'),at('09:25:00')),False)
    scores={f['id']:80. for f in spec['factors']}
    check('early_0931_no_full_intraday_A',components(spec,scores,'INTRADAY',1)['score_phase'],'AUCTION_RESULT')
    check('future_LR_not_entry_feature',observable(at('09:40:00'),at('09:40:01'),at('09:30:00')),False)
    lead=known_lead(at('09:30:00'),at('09:40:00'),at('09:32:00'),feed_complete=True)
    check('A05_future_theme_censored',(lead['value'],lead['censored']),(120.,True))
    selection=choose_target({'A':90.,'B':80.},complete=True,fillable={'A':False,'B':True},thresholds=t)
    check('unfillable_top1_never_replace',(selection['locked_target'],selection['selected'],selection['reason']),('A',None,'UNFILLABLE_TOP1'))
    check('single_candidate_gap_unavailable',choose_target({'A':90.},complete=True,thresholds=t)['gap'],None)
    check('missing_competitor_never_dropped',choose_target({'A':90.,'B':None},complete=True,thresholds=t)['reason'],'MISSING_CRITICAL_DATA')
    check('previous_first_board_is_candidate',is_candidate(11.,11.,1,100.,True),True)
    check('previous_last_seal_not_known_earlier',observable(at('14:55:00'),at('15:01:00'),at('10:00:00')),False)
    obs=[(at('09:31:00'),at('09:31:00'),10.8),(at('09:32:00'),at('09:32:00'),11.),(at('14:00:00'),at('14:00:00'),9.)]
    check('D02_uses_episode_not_full_day_low',episode_drawdown(11.,obs,at('09:30:00'),at('09:32:00'),at('09:32:00')),.2/11)
    check('new_lot_not_sellable_same_day',sellable([{'buy_day':day,'filled':100}],day),0)
    check('limitdown_no_bid_retains_position',pending_exit(100,False),{'filled':0,'remaining':100})
    check('partial_fill_cancel_only_filled_enters_position',sellable([{'buy_day':'2024-01-01','ordered':100,'filled':40,'cancelled_unfilled':60}],day),40)
    check('later_theme_not_backfilled',observable(at('14:00:00'),at('14:01:00'),at('09:30:00')),False)
    check('suspended_flat_zero_volume_not_one_price',one_price([11.,11.,11.,11.],11.,0),False)
    check('deterministic_same_snapshot',components(spec,scores,'INTRADAY',3),components(spec,dict(reversed(list(scores.items()))),'INTRADAY',3))
    check('B_ignores_Q_and_C',base_score(70.,80.,90.),(17.5+17.6+14.4)/.63)
    check('no_event_vs_missing_history',(historical_response([],feed_complete=True)['status'],historical_response([],feed_complete=False)['status']),('COLD_START','MISSING_SOURCE'))
    check('P07_excludes_previous_day_from_denominator',previous_relative_amount(420.,list(range(1,21)))['value'],40.)
    check('P07_no_epsilon_inflation',previous_relative_amount(100.,[0.]*20)['status'],'MISSING_SOURCE')
    check('historical_mid_CDF_ties',mid_cdf(2.,[1.,2.,2.,3.]),50.)
    check('LP02_shrinkage',historical_response([80.]*5,feed_complete=True)['value'],65.)
    check('A06_flat_neutral',pullback(10.,10.,10.,.01,completed_minutes=3)['score'],50.)
    check('LR04_cap_if_prices_not_positive',response_amount_score(90.,-.01),50.)
    absent={**scores,'S03':None}
    check('required_missing_no_weight_redistribution',components(spec,absent,'AUCTION_RESULT',0)['Q'],None)
    changed={**scores,'E01':0.,'E02':0.,'E03':0.,'E04':0.,'E05':0.,'E06':0.}
    check('E_not_part_of_Q',components(spec,changed,'AUCTION_RESULT',0)['Q'],80.)
    check('Q_normalization_0_93',components(spec,scores,'AUCTION_RESULT',0)['Q'],80.)
    check('no_peer_gap_neutral',competition_raw({'A':80.},'A'),{'raw_gap':0.,'neutral_score':50.,'flag':'NO_COMPARABLE_PEER'})
    check('locked_target_not_replaced_later',choose_target({'A':80.,'B':90.},complete=True,locked='A',fillable={'B':True},thresholds=t)['selected'],None)
    check('entry_trigger_one_tick_boundary',entry_trigger(10.99,11.,.01),True)
    check('reseal_thresholds_inclusive',reseal_gate(70.,300.,.03,.5,t),True)
    check('reseal_301_seconds_rejected',reseal_gate(70.,301.,.03,.5,t),False)
    check('hold_exit_two_snapshots_at_least_60s',exit_confirmed([(at('10:00:00'),49.,True),(at('10:00:59'),49.,True)],t),False)
    check('hold_exit_confirmed_at_60s',exit_confirmed([(at('10:00:00'),49.,True),(at('10:01:00'),49.,True)],t),True)
    return {'checks':checks,'passed':sum(c['passed'] for c in checks),'failed':sum(not c['passed'] for c in checks),
        'status':'PASSED' if all(c['passed'] for c in checks) else 'FAILED',
        'coverage':'18 required logical scenarios exercised through component functions plus numeric boundary cases; NOT full strategy implementation',
        'real_market_backtest':False,'alpha_verified':False}

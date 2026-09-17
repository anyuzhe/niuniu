"""QM50 foundational arithmetic/eligibility contract, without evidence certification.

Callers must obtain contemporaneous facts from verified adapters. These pure
functions do not validate receipt bytes and are NOT exposed as arbitrary-input
model tools. Real-data coverage remains blocked while required facts are absent.
"""
from datetime import date,datetime,time,timedelta
from decimal import Decimal,InvalidOperation
from zoneinfo import ZoneInfo
import math

TZ=ZoneInfo('Asia/Shanghai')

def _at(value):
    value=datetime.fromisoformat(value) if isinstance(value,str) else value
    if not isinstance(value,datetime) or value.tzinfo is None:raise ValueError('Timezone required')
    return value

def _number(value):
    if isinstance(value,bool) or value is None:raise ValueError('Explicit numeric value required')
    try:value=Decimal(str(value))
    except InvalidOperation:raise ValueError('Invalid decimal') from None
    if not value.is_finite():raise ValueError('Nonfinite decimal')
    return value

def eligibility(facts):
    for key in ('board','instrument_type','risk_warning','suspended','delisting_arrangement','has_price_limits','new_listing_no_limit_flag','normal_price_limit_regime'):
        if facts.get(key) is None:return {'eligible':None,'reason':'MISSING_'+key.upper()}
    for key in ('suspended','delisting_arrangement','has_price_limits','new_listing_no_limit_flag','normal_price_limit_regime'):
        if type(facts[key]) is not bool:return {'eligible':None,'reason':'INVALID_'+key.upper()}
    if facts['instrument_type']!='A_SHARE':return {'eligible':False,'reason':'INSTRUMENT_OUT_OF_SCOPE'}
    if facts['new_listing_no_limit_flag']:return {'eligible':False,'reason':'NEW_LISTING_NO_LIMIT_OUT_OF_SCOPE'}
    if facts['normal_price_limit_regime'] is not True:return {'eligible':False,'reason':'NON_NORMAL_REGIME_OUT_OF_SCOPE'}
    if facts['board']!='MAINBOARD':return {'eligible':False,'reason':'BOARD_OUT_OF_SCOPE'}
    if facts['risk_warning'] not in ('NONE','ST','STAR_ST','UNKNOWN'):return {'eligible':None,'reason':'INVALID_RISK_WARNING'}
    if facts['risk_warning']=='UNKNOWN':return {'eligible':None,'reason':'RISK_WARNING_UNKNOWN'}
    if facts['risk_warning']!='NONE':return {'eligible':False,'reason':'RISK_WARNING_OUT_OF_SCOPE'}
    if facts['suspended']:return {'eligible':False,'reason':'SUSPENDED'}
    if facts['delisting_arrangement']:return {'eligible':False,'reason':'DELISTING_OUT_OF_SCOPE'}
    if not facts['has_price_limits']:return {'eligible':False,'reason':'NO_PRICE_LIMIT_OUT_OF_SCOPE'}
    return {'eligible':True,'reason':'EXPLICIT_INPUT_CONTRACT_ONLY'}

def classify_day(row,decision_time):
    blank={'close_is_upper_limit':None,'high_touches_upper_limit':None,'close_is_lower_limit':None,
           'one_price':None,'evidence_certified':False,'eligible':None}
    try:
        decision=_at(decision_time);session=date.fromisoformat(row['session'])
        if datetime.combine(session,time(15),TZ)>decision:return {**blank,'status':'NOT_YET_OBSERVABLE','reason':'DAY_NOT_CLOSED'}
        for name in ('rules_available_at','status_available_at'):
            if _at(row[name])>decision:return {**blank,'status':'NOT_YET_OBSERVABLE','reason':name.upper()}
        scope=eligibility(row)
        if scope['eligible'] is None:return {**blank,'status':'MISSING_SOURCE',**scope}
        if row['suspended'] or not row['has_price_limits']:
            return {**blank,'status':'INTERRUPTION','close_is_upper_limit':False,'one_price':False,**scope}
        if row.get('price_basis')!='raw':return {**blank,'status':'UNSUPPORTED','reason':'RAW_PRICE_REQUIRED'}
        bar_available=_at(row['bar_available_at'])
        if bar_available<datetime.combine(session,time(15),TZ):return {**blank,'status':'INVALID_SOURCE','reason':'BAR_AVAILABLE_BEFORE_CLOSE'}
        if bar_available>decision:return {**blank,'status':'NOT_YET_OBSERVABLE','reason':'BAR_NOT_YET_AVAILABLE'}
        o,h,l,c,up,down,tick,ref,volume=map(_number,(row['open'],row['high'],row['low'],row['close'],
            row['upper_limit_price'],row['lower_limit_price'],row['tick_size'],row['reference_price'],row['volume']))
        if min(o,h,l,c,up,down,tick,ref)<=0 or volume<0 or h<max(o,c,l) or l>min(o,c,h) or not down<up:
            raise ValueError('Invalid OHLC/rule/value relation')
        if any(v%tick!=0 for v in (o,h,l,c,up,down)):raise ValueError('Price is not on the explicit tick grid')
        if h>up or l<down:raise ValueError('Raw prices exceed explicit session limits')
        if volume==0:return {**blank,'status':'ZERO_VOLUME','close_is_upper_limit':False,'one_price':False,'eligible':False,'reason':'ZERO_VOLUME_NOT_SEAL'}
        return {**blank,'status':'OK','close_is_upper_limit':c==up,'high_touches_upper_limit':h==up,
                'close_is_lower_limit':c==down,'one_price':o==h==l==c==up,**scope}
    except (KeyError,ValueError,TypeError) as exc:
        return {**blank,'status':'MISSING_OR_INVALID_SOURCE','reason':str(exc)[:160]}

def previous_height(rows,ordered_sessions,decision_time):
    """No max-height cap and no assumed non-limit baseline at the left boundary."""
    if not ordered_sessions or ordered_sessions!=sorted(set(ordered_sessions)):raise ValueError('Ordered unique calendar sessions required')
    if len({r['session'] for r in rows})!=len(rows):raise ValueError('Duplicate session records')
    if any(r['session'] not in ordered_sessions for r in rows):raise ValueError('Unexpected session in height inputs')
    values={r['session']:r for r in rows};height=0
    for session in reversed(ordered_sessions):
        if session not in values:return {'height':None,'observed_suffix':height,'status':'MISSING_SOURCE','reason':'CALENDAR_GAP'}
        state=classify_day(values[session],decision_time)
        if state['status']=='INTERRUPTION':return {'height':height,'status':'OK','terminated_by':'DECLARED_INTERRUPTION','evidence_certified':False}
        if state['status']!='OK':return {'height':None,'observed_suffix':height,'status':state['status'],'reason':state.get('reason')}
        if state['close_is_upper_limit'] is False:return {'height':height,'status':'OK','terminated_by':'OBSERVED_NON_LIMIT_CLOSE','evidence_certified':False}
        height+=1
    return {'height':None,'observed_suffix':height,'status':'INSUFFICIENT_HISTORY','reason':'LEFT_CENSORED_LIMIT_STREAK'}

def candidate_for_day(height,current_facts,*,complete_universe,decision_time):
    result={'candidate':None,'evidence_certified':False}
    if complete_universe is not True:return {**result,'reason':'MISSING_CRITICAL_UNIVERSE_COVERAGE'}
    try:
        for field in ('rules_available_at','status_available_at'):
            if _at(current_facts[field])>_at(decision_time):return {**result,'reason':'CURRENT_STATUS_NOT_YET_AVAILABLE'}
    except (ValueError,TypeError,KeyError):return {**result,'reason':'CURRENT_STATUS_TIME_MISSING'}
    scope=eligibility(current_facts)
    if scope['eligible'] is not True:return {**result,'candidate':scope['eligible'],'reason':scope['reason']}
    if type(height) is not int or height<0:return {**result,'reason':'PREVIOUS_HEIGHT_UNKNOWN'}
    return {**result,'candidate':height>=1,'reason':'FIRST_BOARD_INCLUDED' if height==1 else 'EXPLICIT_INPUT_CONTRACT_ONLY'}

def fixture(day='2024-01-02',*,limit_close=False,**changes):
    row={'session':day,'symbol':'sh.600000','board':'MAINBOARD','price_basis':'raw','risk_warning':'NONE',
         'suspended':False,'delisting_arrangement':False,'has_price_limits':True,'instrument_type':'A_SHARE',
         'new_listing_no_limit_flag':False,'normal_price_limit_regime':True,'reference_price':'10.00',
         'upper_limit_price':'11.00','lower_limit_price':'9.00','tick_size':'0.01','open':'10.00','high':'11.00',
         'low':'10.00','close':'11.00' if limit_close else '10.50','volume':100.,
         'bar_available_at':day+'T15:01:00+08:00','rules_available_at':day+'T08:00:00+08:00',
         'status_available_at':day+'T08:00:00+08:00'}
    return {**row,**changes}

def run_base_guards():
    tests=[];decision='2024-01-08T09:15:00+08:00';days=['2024-01-02','2024-01-03','2024-01-04','2024-01-05']
    current=fixture('2024-01-08');rows=[fixture(d,limit_close=i>0) for i,d in enumerate(days)]
    def check(name,actual,expected):tests.append({'check_id':name,'actual':actual,'expected':expected,'passed':actual==expected,'evidence_type':'SYNTHETIC_COMPONENT_TEST'})
    check('first_board_not_minimum_two',candidate_for_day(1,current,complete_universe=True,decision_time=decision)['candidate'],True)
    check('three_consecutive_after_observed_break',previous_height(rows,days,decision)['height'],3)
    check('no_artificial_height_cap',candidate_for_day(6,current,complete_universe=True,decision_time=decision)['candidate'],True)
    check('left_censored_streak_not_height',previous_height(rows[1:],days[1:],decision)['height'],None)
    check('calendar_gap_not_skipped',previous_height([rows[0],rows[2],rows[3]],days,decision)['height'],None)
    halted=[rows[0],fixture(days[1],suspended=True),rows[2],rows[3]]
    check('declared_suspension_interrupts',previous_height(halted,days,decision)['height'],2)
    unlimited=[rows[0],fixture(days[1],has_price_limits=False,upper_limit_price=None,lower_limit_price=None),rows[2],rows[3]]
    check('declared_no_limits_interrupts',previous_height(unlimited,days,decision)['height'],2)
    check('zero_volume_not_one_price',classify_day(fixture(open='11.00',low='11.00',close='11.00',volume=0),decision)['one_price'],False)
    check('ST_current_not_candidate',candidate_for_day(2,{**current,'risk_warning':'ST'},complete_universe=True,decision_time=decision)['candidate'],False)
    check('UNKNOWN_risk_not_normal',candidate_for_day(2,{**current,'risk_warning':'UNKNOWN'},complete_universe=True,decision_time=decision)['candidate'],None)
    check('current_suspension_blocks_entry',candidate_for_day(2,{**current,'suspended':True},complete_universe=True,decision_time=decision)['candidate'],False)
    check('delisting_excluded',candidate_for_day(2,{**current,'delisting_arrangement':True},complete_universe=True,decision_time=decision)['candidate'],False)
    check('other_board_not_mixed',candidate_for_day(2,{**current,'board':'STAR'},complete_universe=True,decision_time=decision)['candidate'],False)
    check('qfq_not_raw_limit_test',classify_day(fixture(price_basis='qfq'),decision)['status'],'UNSUPPORTED')
    check('reference_price_not_inferred',classify_day(fixture(reference_price=None),decision)['close_is_upper_limit'],None)
    check('tick_size_not_assumed',classify_day(fixture(tick_size=None),decision)['close_is_upper_limit'],None)
    check('near_limit_not_equal',classify_day(fixture(close='10.99'),decision)['close_is_upper_limit'],False)
    check('tick_off_grid_rejected',classify_day(fixture(close='10.999'),decision)['close_is_upper_limit'],None)
    check('future_bar_not_usable',classify_day(fixture(bar_available_at='2024-01-09T15:01:00+08:00'),decision)['status'],'NOT_YET_OBSERVABLE')
    check('incomplete_universe_not_small_pool',candidate_for_day(2,current,complete_universe=False,decision_time=decision)['candidate'],None)
    check('future_current_status_blocks',candidate_for_day(2,{**current,'status_available_at':'2024-01-08T10:00:00+08:00'},complete_universe=True,decision_time=decision)['candidate'],None)
    check('unknown_height_not_false_zero',candidate_for_day(None,current,complete_universe=True,decision_time=decision)['candidate'],None)
    check('normal_regime_not_guessed',candidate_for_day(2,{**current,'normal_price_limit_regime':None},complete_universe=True,decision_time=decision)['candidate'],None)
    check('non_a_share_not_candidate',candidate_for_day(2,{**current,'instrument_type':'ETF'},complete_universe=True,decision_time=decision)['candidate'],False)
    check('new_listing_no_limit_not_candidate',candidate_for_day(2,{**current,'new_listing_no_limit_flag':True},complete_universe=True,decision_time=decision)['candidate'],False)
    return {'checks':tests,'passed':sum(t['passed'] for t in tests),'failed':sum(not t['passed'] for t in tests),
            'status':'PASSED' if all(t['passed'] for t in tests) else 'FAILED','real_market_backtest':False,
            'coverage':'Pure as-of base/height/eligibility contracts only; no receipt certification or real candidate production'}

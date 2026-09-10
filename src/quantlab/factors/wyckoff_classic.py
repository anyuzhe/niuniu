"""Causal, explicitly parameterized Wyckoff OHLCV A–E research profile.

Both directions use one reflected price state machine. This is a reproducible
operationalization, not a claim to infer institutional intent from daily bars.
"""
import math
from statistics import fmean
import polars as pl
from quantlab.data.validation import ordered_bars
from quantlab.domain import Event,SequenceMatch,FactorType,Timeframe
from quantlab.factors.base import ComputedFactor,FactorDefinition
from quantlab.factors.registry import FactorPack
from quantlab.storage.codec import digest

PROFILE='wyckoff_ohlcv_ae_v1'
EVENTS=('ps','psy','sc','bc','ar_up','ar_down','st_up','st_down','spring','utad','test_up','test_down',
        'sos','sow','lps','lpsy','markup','markdown','exit','invalidated','expired','target_hit')
SCALARS=('phase','direction','market_direction','range_low','range_high','supply_demand','effort_result',
         'cause_columns','price_target','score','position','cycle')
COMPONENTS=(*EVENTS,*SCALARS)
NAMES=dict(zip(COMPONENTS,('初步支撑 PS','初步供应 PSY','卖出高潮 SC','买入高潮 BC','自动反弹 AR','自动回落 AR',
    '吸筹二次测试 ST','派发二次测试 ST','弹簧 Spring','终极上冲 UTAD','吸筹供给测试','派发需求测试','强势信号 SOS','弱势信号 SOW',
    '最后支撑 LPS','最后供应 LPSY','上涨阶段 E','下跌阶段 E','持仓退出','链路失效','链路超时','测量目标到达',
    '阶段编码','链路方向','前置市场方向','冻结区间下沿','冻结区间上沿','供需代理','努力结果代理','固定格点列数','测量目标','规则评分','多头持仓','初始／延续周期')))
DEFAULTS={'lookback':20,'context':60,'trend_threshold':.05,'preliminary_volume':1.2,'climax_volume':1.8,
          'climax_spread':1.3,'ar_atr':2.,'test_fraction':.25,'test_volume':.8,'breakout_volume':1.2,
          'min_bars_b':5,'max_bars':180,'box_pct':.01,'reversal':3,'trailing_atr':3.,'max_hold':120}

class ClassicWyckoffState:
    """Full OHLCV A-E recursion; extending never replays the consumed prefix."""
    def __init__(self,symbol,timeframe,p,key_schema):
        self.symbol=symbol;self.timeframe=timeframe;self.p=p
        self._key_schema=key_schema;self.rows=[];self.columns={k:[] for k in COMPONENTS}
        self.state=None;self.events=[];self.transitions=[]
    @property
    def processed(self): return len(self.rows)
    def dump(self): return {k:v for k,v in self.__dict__.items() if k!='_key_schema'}
    def restore(self,value):
        if set(value)!=set(self.dump()): raise ValueError('Invalid Wyckoff state fields')
        if any(value[k]!=getattr(self,k) for k in ('symbol','timeframe','p')):
            raise ValueError('Wyckoff state identity changed')
        if set(value['columns'])!=set(COMPONENTS) or any(len(v)!=len(value['rows']) for v in value['columns'].values()):
            raise ValueError('Wyckoff state lengths differ')
        self.__dict__.update(value)
    def extend(self,bars):
        if bars.is_empty(): return
        if set(bars['symbol'])!={self.symbol} or set(bars['timeframe'])!={self.timeframe}:
            raise ValueError('Wyckoff continuation symbol/timeframe mismatch')
        if self.rows and bars['datetime'][0]<=self.rows[-1]['datetime']:
            raise ValueError('Wyckoff continuation must append strictly later bars')
        rows=self.rows;columns=self.columns;p=self.p;state=self.state
        events=self.events;transitions=self.transitions
        for r in bars.iter_rows(named=True):
            i=len(rows)
            if i%128==0:
                from quantlab.progress import checkpoint
                checkpoint()
            rows.append(r)
            flags=set();v={k:0. for k in SCALARS};prior=rows[max(0,i-p['lookback']):i]
            if i>=p['context']:
                avg_vol=fmean(x['volume'] for x in prior);avg_spread=fmean(x['high']-x['low'] for x in prior)
                atr=fmean(max(rows[j]['high']-rows[j]['low'],abs(rows[j]['high']-(rows[j-1]['close'] if j else rows[j]['open'])),abs(rows[j]['low']-(rows[j-1]['close'] if j else rows[j]['open']))) for j in range(i-p['lookback'],i))
                atr=max(atr,1e-12);vr=r['volume']/avg_vol if avg_vol>0 else 0.;spread=r['high']-r['low']
                trend=prior[-1]['close']/prior[0]['close']-1;context=prior[-1]['close']/rows[i-p['context']]['close']-1
                v['market_direction']=float((trend>p['trend_threshold'])-(trend<-p['trend_threshold']))
                v['supply_demand']=(2*(r['close']-r['low'])/spread-1)*vr if spread>0 else 0.
                v['effort_result']=(r['close']-prior[-1]['close'])/atr/max(vr,1e-12) if vr else 0.
                def emit(name,status='active',reason=None):
                    flags.add(name);sid=state['id']
                    evidence={k:value for k,value in state.items() if k!='ids'}
                    e=Event(digest({'profile':PROFILE,'episode':sid,'event':name,'at':r['available_at']}),'WYCKOFF.CLASSIC_'+name.upper(),r['symbol'],Timeframe(r['timeframe']),r['datetime'],r['available_at'],direction=state['d'],metadata={'episode':evidence,'reason':reason,'profile':PROFILE,'parameters':p,'volume_ratio':vr,'atr':atr,'market_direction':v['market_direction'],'supply_demand':v['supply_demand'],'effort_result':v['effort_result']})
                    events.append(e);state['ids'].append(e.event_id)
                    transitions.append(SequenceMatch('WYCKOFF.CLASSIC_CHAIN','1.0.0',r['symbol'],tuple(state['ids']),state['at'],r['available_at'],status,sid,Timeframe(r['timeframe']),e.event_id if status=='invalidated' else None))
                def oriented(d):return (r['high'],r['low'],r['close']) if d==1 else (-r['low'],-r['high'],-r['close'])
                def climax(d):
                    h,l,c=oriented(d);old=min(x['low'] if d==1 else -x['high'] for x in prior)
                    return l<=old and vr>=p['climax_volume'] and spread>=avg_spread*p['climax_spread'] and c-l>=spread*.35
                if state is None:
                    d=1 if trend<=-p['trend_threshold'] else -1 if trend>=p['trend_threshold'] else 0
                    if d and vr>=p['preliminary_volume']:
                        h,l,c=oriented(d);is_climax=climax(d)
                        state={'id':digest({'profile':PROFILE,'symbol':r['symbol'],'at':r['available_at'],'parameters':p}),
                            'at':r['datetime'],'start':i,'phase':'SC' if is_climax else 'PS','d':d,'ids':[],
                            'cycle':(2 if context*d>0 else 1)*d,'lo':l,'hi':h,'extreme':l,'volume':r['volume'],'atr':atr,
                            'box':r['close']*p['box_pct'],'pf_extreme':c,'pf_direction':0,'columns':1}
                        emit(('sc' if d==1 else 'bc') if is_climax else ('ps' if d==1 else 'psy'))
                else:
                    d=state['d'];h,l,c=oriented(d);stage=state['phase'];width=state['hi']-state['lo'];tol=max(width*p['test_fraction'],1e-12)
                    # Close-only P&F with frozen box size, no guessed intrabar path.
                    delta=c-state['pf_extreme'];box=state['box'];pf=state['pf_direction']
                    if stage in ('D','LPS','E'):pass  # Freeze the cause count used by the D projection.
                    elif pf==0 and abs(delta)>=box:state['pf_direction']=1 if delta>0 else -1;state['pf_extreme']+=math.trunc(delta/box)*box
                    elif pf*delta>=box:state['pf_extreme']+=math.trunc(delta/box)*box
                    elif pf and pf*delta<=-p['reversal']*box:
                        state['columns']+=1;state['pf_direction']=-pf;state['pf_extreme']+=math.trunc(delta/box)*box
                    terminal=False
                    if stage=='E':
                        state['peak']=max(state['peak'],c);stop=max(state['stop'],state['peak']-p['trailing_atr']*atr);state['stop']=stop
                        reason='target' if c>=state['target'] else 'trailing_stop' if c<stop else 'max_hold' if i-state['entry']>=p['max_hold'] else None
                        if reason:
                            emit('target_hit' if reason=='target' else 'exit',status='completed',reason=reason);state=None;terminal=True
                    elif i-state['start']>p['max_bars']:
                        emit('expired',status='timeout',reason='phase_timeout');state=None;terminal=True
                    elif stage in ('C','TEST','D','LPS') and l<state['extreme']:
                        emit('invalidated',status='invalidated',reason='frozen_extreme_broken');state=None;terminal=True
                    elif stage in ('D','LPS') and c<state['hi']:
                        emit('invalidated',status='invalidated',reason='breakout_failed');state=None;terminal=True
                    if not terminal:
                        if stage=='PS' and climax(d):
                            state.update(phase='SC',lo=l,hi=h,extreme=l,volume=r['volume'],atr=atr);emit('sc' if d==1 else 'bc')
                        elif stage=='SC':
                            if l<state['lo']:
                                emit('invalidated',status='invalidated',reason='climax_extreme_broken_before_AR');state=None
                            elif c-state['lo']>=p['ar_atr']*state['atr']:
                                state.update(phase='AR',hi=h);emit('ar_up' if d==1 else 'ar_down')
                        elif stage=='AR':
                            if l<state['lo']-tol:
                                emit('invalidated',status='invalidated',reason='secondary_test_failed');state=None
                            elif abs(l-state['lo'])<=tol and c>=state['lo'] and r['volume']<state['volume']*p['test_volume']:
                                state.update(phase='B',b_start=i,extreme=min(l,state['lo']),test_volume=r['volume']);emit('st_up' if d==1 else 'st_down')
                        elif stage=='B':
                            if l<state['lo'] and h>state['hi']:
                                emit('invalidated',status='invalidated',reason='ambiguous_outside_range');state=None
                            elif l<state['lo'] and state['lo']<=c<=state['hi']:
                                if i-state['b_start']<p['min_bars_b']:
                                    emit('invalidated',status='invalidated',reason='premature_range_sweep');state=None
                                else:
                                    state.update(phase='C',extreme=l,sweep_volume=r['volume']);emit('spring' if d==1 else 'utad')
                            elif c<state['lo'] or c>state['hi']:
                                emit('invalidated',status='invalidated',reason='untested_range_exit');state=None
                            elif i-state['b_start']>=p['min_bars_b'] and abs(l-state['lo'])<=tol and r['volume']<state['volume']*p['test_volume']:
                                state.update(phase='TEST',test_volume=r['volume'],extreme=min(state['extreme'],l));emit('test_up' if d==1 else 'test_down',reason='no_sweep_variant')
                        elif stage=='C' and abs(l-state['lo'])<=tol and c>=state['lo'] and r['volume']<state['sweep_volume']*p['test_volume']:
                            state.update(phase='TEST',test_volume=r['volume']);emit('test_up' if d==1 else 'test_down',reason='sweep_test')
                        elif stage=='TEST' and c>state['hi'] and vr>=p['breakout_volume']:
                            state.update(phase='D',breakout_high=h,breakout_volume=r['volume'],target=state['hi']+state['columns']*box*p['reversal']);emit('sos' if d==1 else 'sow')
                        elif stage=='D' and abs(l-state['hi'])<=tol and r['volume']<state['breakout_volume']*p['test_volume']:
                            state.update(phase='LPS',retest_volume=r['volume']);emit('lps' if d==1 else 'lpsy')
                        elif stage=='LPS' and c>state['breakout_high'] and r['volume']>state['retest_volume']:
                            if c>=state['target']:
                                emit('target_hit',status='completed',reason='target_exhausted_before_entry');state=None
                            else:
                                state.update(phase='E',entry=i,peak=c,stop=state['hi']);emit('markup' if d==1 else 'markdown')
                if state is not None:
                    phase={'PS':1,'SC':1,'AR':1,'B':2,'C':3,'TEST':3,'D':4,'LPS':4,'E':5}[state['phase']];d=state['d']
                    lo,hi=sorted((d*state['lo'],d*state['hi']));base={1:10,2:25,3:40,4:60,5:80}[phase]
                    score=d*min(100,base+10*(d*v['supply_demand']>0)+10*(d*v['market_direction']>=0))
                    v.update(phase=float(phase*d),direction=float(d),range_low=lo,range_high=hi,cycle=float(state['cycle']),
                        cause_columns=float(state['columns']),price_target=d*state.get('target',0),score=float(score),position=float(d==1 and phase==5 and score>=80))
            for k in COMPONENTS:columns[k].append(None if i<p['context'] else float(k in flags) if k in EVENTS else v[k])
            self.state=state
    def result(self):
        values=(pl.DataFrame({k:pl.Series(k,[r[k] for r in self.rows],dtype=dtype) for k,dtype in self._key_schema.items()})
            if self.rows else pl.DataFrame(schema=self._key_schema))
        return values.with_columns(*[pl.Series(k,v,dtype=pl.Float64) for k,v in self.columns.items()]),self.transitions,self.events


class ClassicWyckoffFactor(ComputedFactor):
    caches_structures=True
    def __init__(self,component,cache=None):
        if component not in COMPONENTS:raise ValueError('Unknown Wyckoff component')
        self.component=component;self._cache=cache if cache is not None else [None]
        self.definition=FactorDefinition('WYCKOFF.CLASSIC_'+component.upper(),'1.0.0','威克夫 A–E · '+NAMES[component],
            'model' if component in ('position','score') else 'market_state' if component in ('market_direction','cycle') else 'structure' if component in SCALARS else 'event',
            FactorType.SCALAR if component in SCALARS else FactorType.BOOLEAN,
            ('open','high','low','close','volume','turnover'),tuple(Timeframe),
            '明确 OHLCV 双向 A–E：初步支撑/供应、高潮、自动反弹/回落、二测、区间、Spring/UTAD 或无扫出测试、强弱突破、LPS/LPSY、趋势及退出；冻结边界，收盘确认。',PROFILE,source_theory=('Wyckoff',))
    def parameters(self,supplied):
        if set(supplied)-set(DEFAULTS):raise ValueError('Unknown classic Wyckoff parameter')
        p={**DEFAULTS,**supplied}
        for k in ('lookback','context','min_bars_b','max_bars','reversal','max_hold'):
            if type(p[k]) is not int or not 1<=p[k]<=100000:raise ValueError('Invalid integer parameter '+k)
        if p['lookback']<2 or p['context']<p['lookback']:raise ValueError('context >= lookback >= 2 required')
        for k in set(p)-{'lookback','context','min_bars_b','max_bars','reversal','max_hold'}:
            if type(p[k]) not in (int,float) or not math.isfinite(p[k]) or p[k]<=0:raise ValueError('Invalid positive parameter '+k)
        if max(p['test_fraction'],p['test_volume'],p['trend_threshold'],p['box_pct'])>1:raise ValueError('Fractions must be <= 1')
        if p['preliminary_volume']>p['climax_volume']:raise ValueError('Preliminary volume exceeds climax volume')
        return p
    def matrix(self,bars,parameters):
        p=self.parameters(parameters);bars=ordered_bars(bars)
        if bars.select(pl.struct('symbol','available_at').is_duplicated().any()).item():raise ValueError('Wyckoff requires unique symbol/available_at')
        cached=self._cache[0]
        if cached is not None and cached[0]==p and cached[1].equals(bars):return cached[2:]
        parts=[];events=[];transitions=[]
        total=bars['symbol'].n_unique()
        for number,(_,group) in enumerate(bars.group_by('symbol',maintain_order=True),1):
            from quantlab.progress import checkpoint
            checkpoint('威克夫 A–E · '+group['symbol'][0],number-1,total)
            from quantlab.factors.continuation import compute_recursive
            factory=lambda:ClassicWyckoffState(group['symbol'][0],group['timeframe'][0],p,
                group.select('symbol','datetime','available_at').schema)
            persistent=getattr(self,'_persistent_cache',None)
            if persistent is not None:
                part,ts,es=compute_recursive(persistent,{'profile':PROFILE,'parameters':p},group,factory)
            else:
                state=factory();state.extend(group);part,ts,es=state.result()
            parts.append(part);transitions.extend(ts);events.extend(es)
        result=(pl.concat(parts),transitions,events);self._cache[0]=(p,bars.clone(),*result);return result
    def compute(self,bars,parameters):return self.matrix(bars,parameters)[0].select('symbol','datetime','available_at',pl.col(self.component).alias('value'))
    def trace(self,bars,parameters):
        matrix,states,events=self.matrix(bars,parameters)
        return matrix.select('symbol','datetime','available_at',pl.col(self.component).alias('value')),states,events


def classic_wyckoff_pack():
    cache=[None]
    return FactorPack('WyckoffClassicPack','1.0.0',tuple(ClassicWyckoffFactor(c,cache) for c in COMPONENTS))

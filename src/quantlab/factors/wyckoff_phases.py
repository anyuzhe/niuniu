"""Observable B/C/D/E price-action proxy, not institutional phase inference."""
import math
from dataclasses import asdict
import polars as pl
from quantlab.data.validation import ordered_bars
from quantlab.domain import Event,SequenceMatch,FactorType,Timeframe
from quantlab.factors.base import ComputedFactor,FactorDefinition
from quantlab.factors.registry import FactorPack
from quantlab.factors.wyckoff import WyckoffComponent
from quantlab.storage.codec import digest


COMPONENTS=('b','c_up','c_down','d_up','d_down','retest_up','retest_down','e_up','e_down',
    'invalidated_up','invalidated_down','expired_up','expired_down','code')


class WyckoffPhaseComponent(ComputedFactor):
    def __init__(self,component):
        if component not in COMPONENTS:raise ValueError('Unknown Wyckoff phase component')
        self.component=component
        self.definition=FactorDefinition('WYCKOFF.PHASE_'+component.upper(),'1.0.0','Wyckoff 阶段代理 '+component,'sequence',
            FactorType.SCALAR if component=='code' else FactorType.BOOLEAN,
            ('open','high','low','close','volume','turnover'),tuple(Timeframe),
            '紧凑区间 B、扫出/测试 C、确认突破 D、缩量回踩再突破 E；E 后链结束，超时/结构破坏重置。未实现阶段 A 或机构行为识别。',
            'observed_phase_chain_v1; B=1,C=+/-2,D=+/-3,E completion=+/-4,idle=0',source_theory=('Wyckoff',))

    def parameters(self,supplied):
        extras={'retest_fraction':.25,'retest_volume_ratio':1.,'follow_bars':60}
        p=WyckoffComponent('sos').parameters({k:v for k,v in supplied.items() if k not in extras})
        p.update({k:supplied.get(k,v) for k,v in extras.items()})
        if type(p['follow_bars']) is not int or not 1<=p['follow_bars']<=100000:raise ValueError('follow_bars must be in [1,100000]')
        for k in ('retest_fraction','retest_volume_ratio'):
            if type(p[k]) not in (int,float) or not math.isfinite(p[k]) or not 0<p[k]<=1:raise ValueError('Retest fractions must be in (0,1]')
        return p

    def trace(self,bars,parameters):
        p=self.parameters(parameters);bars=ordered_bars(bars)
        if bars.select(pl.struct('symbol','available_at').is_duplicated().any()).item():raise ValueError('Wyckoff phases require unique symbol/available_at')
        _,_,base=WyckoffComponent('sos').trace(bars,{k:p[k] for k in ('lookback','max_width','max_bars','test_fraction')})
        by_time={}
        for event in base:by_time.setdefault((event.symbol,event.available_at),{})[event.factor_id.removeprefix('WYCKOFF.')]=event
        values=[];events=[];transitions=[]
        for _,group in bars.group_by('symbol',maintain_order=True):
            state=None
            for index,row in enumerate(group.iter_rows(named=True)):
                known=by_time.get((row['symbol'],row['available_at']),{});flags=set();code=0
                def start(source,phase):
                    return {'id':digest({'source':source.event_id,'parameters':p,'version':'observed_phase_chain_v1'}),
                        'at':row['datetime'],'phase':phase,'direction':0,'ids':[],'origin_at':None}
                def emit(name,status='active',source=None,reason=None):
                    fid='WYCKOFF.PHASE_'+name.upper();identity={'episode':state['id'],'factor_id':fid,'at':row['available_at']}
                    evidence={k:v for k,v in state.items() if k!='ids'}
                    event=Event(digest(identity),fid,row['symbol'],Timeframe(row['timeframe']),row['datetime'],row['available_at'],
                        direction=state['direction'],metadata={'episode':evidence,'parameters':p,'reason':reason,
                            'source_event':asdict(source) if source else None,'confirmation_bar':{k:row[k] for k in ('datetime','open','high','low','close','volume')}})
                    events.append(event);state['ids'].append(event.event_id);flags.add(name)
                    transitions.append(SequenceMatch('WYCKOFF.PHASE_CHAIN','1.0.0',row['symbol'],tuple(state['ids']),state['at'],
                        row['available_at'],status,state['id'],Timeframe(row['timeframe']),event.event_id if status=='invalidated' else None))
                if state is None or state['phase']=='B':
                    sweep=known.get('SPRING') or known.get('UPTHRUST')
                    if sweep:
                        if state is None:state=start(sweep,'C')
                        state.update(phase='C',direction=sweep.direction,origin_at=sweep.metadata['origin_at'],
                            origin_index=index,lower=sweep.metadata['low'],upper=sweep.metadata['high'],
                            extreme=sweep.metadata['extreme'],sweep=asdict(sweep),tested=False)
                        emit('c_up' if sweep.direction==1 else 'c_down',source=sweep)
                    elif 'RANGE' in known:
                        if state is None:state=start(known['RANGE'],'B');emit('b',source=known['RANGE'])
                    elif state is not None:
                        emit('reset',status='invalidated',reason='compact_range_lost');state=None
                elif state['phase']=='C':
                    d=state['direction'];suffix='up' if d==1 else 'down'
                    expired=index-state['origin_index']>p['max_bars']
                    broken=row['low']<state['extreme'] if d==1 else row['high']>state['extreme']
                    if expired or broken:
                        emit(('expired_' if expired else 'invalidated_')+suffix,status='timeout' if expired else 'invalidated',reason='C_timeout' if expired else 'sweep_extreme_broken');state=None
                    else:
                        test=known.get('TEST_UP' if d==1 else 'TEST_DOWN');breakout=known.get('SOS' if d==1 else 'SOW')
                        if test and test.metadata.get('origin_at')==state['origin_at']:
                            state['tested']=True;emit('test_'+suffix,source=test)
                        elif breakout and state['tested'] and breakout.metadata.get('origin_at')==state['origin_at']:
                            state.update(phase='D',breakout_index=index,breakout_volume=row['volume'],
                                breakout_extreme=row['high'] if d==1 else row['low'],breakout=asdict(breakout),retest=None)
                            emit('d_'+suffix,source=breakout)
                else:
                    d=state['direction'];suffix='up' if d==1 else 'down';boundary=state['upper'] if d==1 else state['lower']
                    expired=index-state['breakout_index']>p['follow_bars']
                    broken=(row['low']<state['extreme'] or row['close']<boundary) if d==1 else (row['high']>state['extreme'] or row['close']>boundary)
                    if expired or broken:
                        emit(('expired_' if expired else 'invalidated_')+suffix,status='timeout' if expired else 'invalidated',reason='D_timeout' if expired else 'breakout_failed');state=None
                    elif state['retest'] is None:
                        width=state['upper']-state['lower'];edge=row['low'] if d==1 else row['high']
                        if abs(edge-boundary)<=width*p['retest_fraction'] and row['volume']<state['breakout_volume']*p['retest_volume_ratio']:
                            state['retest']={k:row[k] for k in ('datetime','available_at','high','low','close','volume')}
                            emit('retest_'+suffix)
                    elif d*(row['close']-state['breakout_extreme'])>0 and row['volume']>state['retest']['volume']:
                        state['phase']='E';emit('e_'+suffix,status='completed');code=4*d;state=None
                if state is not None:code={'B':1,'C':2*state['direction'],'D':3*state['direction']}[state['phase']]
                values.append({**{k:row[k] for k in ('symbol','datetime','available_at')},
                    'value':None if index<p['lookback'] else float(code if self.component=='code' else self.component in flags)})
        return pl.DataFrame(values).with_columns(pl.col('value').cast(pl.Float64)),transitions,events

    def compute(self,bars,parameters):return self.trace(bars,parameters)[0]


def wyckoff_phase_pack():return FactorPack('WyckoffPhasePack','1.0.0',tuple(WyckoffPhaseComponent(c) for c in COMPONENTS),('WyckoffBasePack',))

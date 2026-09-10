"""Confirmed alternating three-extreme contraction and reversal proxy."""
from dataclasses import asdict
import math
import polars as pl
from quantlab.data.validation import ordered_bars
from quantlab.domain import Event, SequenceMatch, FactorType, Timeframe
from quantlab.factors.base import ComputedFactor, FactorDefinition
from quantlab.factors.registry import FactorPack
from quantlab.structure.pivots import ConfirmedPivotEngine
from quantlab.storage.codec import digest

COMPONENTS = ('setup', 'confirmed', 'invalidated', 'expired')


class BrooksWedgeComponent(ComputedFactor):
    def __init__(self, component, direction):
        if component not in COMPONENTS or direction not in (1,-1):
            raise ValueError('Unknown wedge component/direction')
        self.component, self.direction = component, direction
        suffix = 'UP' if direction == 1 else 'DOWN'
        self.definition = FactorDefinition(f'BROOKS.WEDGE_{component.upper()}_{suffix}', '1.0.0',
            f'Brooks 三极值收缩规则 {component} {suffix}', 'sequence', FactorType.BOOLEAN,
            ('open','high','low','close','volume','turnover'), tuple(Timeframe),
            '五个交替已确认极值中的三次同向新极值、末次增量缩小；之后另一根收盘突破最近反向极值确认反转。',
            'Confirmed alternating three-extreme contraction, then close-based neckline reversal proxy',
            source_theory=('Brooks',))

    def parameters(self, supplied):
        p = {'left':2, 'right':2, 'contraction_ratio':0.8, 'max_bars':40}
        if set(supplied)-set(p):
            raise ValueError('Unknown wedge parameter')
        p.update(supplied)
        for k in ('left','right','max_bars'):
            if type(p[k]) is not int or not 1 <= p[k] <= 10000:
                raise ValueError(f'{k} must be integer in [1,10000]')
        v = p['contraction_ratio']
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0 < v < 1:
            raise ValueError('contraction_ratio must be finite in (0,1)')
        return p

    def trace(self, bars, parameters):
        p = self.parameters(parameters)
        bars = ordered_bars(bars)
        if bars.select(pl.struct('symbol','available_at').is_duplicated().any()).item():
            raise ValueError('Wedge requires unique symbol/available_at')
        pivots = {}
        for pivot in ConfirmedPivotEngine(p['left'],p['right']).detect(bars):
            pivots.setdefault((pivot.symbol,pivot.available_at),[]).append(pivot)
        output, transitions, events = [], [], []
        d = self.direction
        suffix = 'UP' if d == 1 else 'DOWN'
        target_kind = 'pivot_low' if d == 1 else 'pivot_high'
        for _, group in bars.group_by('symbol',maintain_order=True):
            candidate, state = [], None
            for i,row in enumerate(group.to_dicts()):
                stage, status = None, 'active'
                value = None if i < p['left']+p['right'] else 0.
                if state:
                    if i-state['start_index'] > p['max_bars']:
                        stage,status = 'expired','timeout'
                    elif d*((row['low'] if d==1 else row['high'])-state['extreme']) < 0:
                        stage,status = 'invalidated','invalidated'
                    elif d*(row['close']-state['neckline']) > 0:
                        stage,status = 'confirmed','completed'
                else:
                    arriving = pivots.get((row['symbol'],row['available_at']),[])
                    if len(arriving)>1:
                        # A simultaneous high+low provides no intrabar ordering.
                        candidate=[]
                    elif arriving:
                        pivot=arriving[0]
                        if candidate and candidate[-1].kind==pivot.kind:
                            # Only unpublished candidate tails can be replaced; old events are immutable.
                            better=pivot.price>candidate[-1].price if pivot.kind=='pivot_high' else pivot.price<candidate[-1].price
                            if better:
                                candidate[-1]=pivot
                        else:
                            candidate.append(pivot)
                            candidate=candidate[-5:]
                        if len(candidate)==5 and candidate[-1] is pivot and pivot.kind==target_kind:
                            a,b,c,e,f=candidate
                            first=d*(a.price-c.price)
                            second=d*(c.price-f.price)
                            if first>0 and 0<second<=first*p['contraction_ratio'] and d*(b.price-e.price)>0:
                                stage='setup'
                                sources=[asdict(v) for v in candidate]
                                state={'id':digest({'sources':[v.structure_id for v in candidate],
                                    'direction':d,'parameters':p}),'start_index':i,'started_at':row['datetime'],
                                    'extreme':f.price,'neckline':e.price,'first_increment':first,
                                    'second_increment':second,'sources':sources,'ids':[]}
                                candidate=[]
                if stage:
                    fid=f'BROOKS.WEDGE_{stage.upper()}_{suffix}'
                    eid=digest({'episode':state['id'],'stage':stage,'available_at':row['available_at']})
                    metadata={k:v for k,v in state.items() if k!='ids'}
                    metadata.update(match_id=state['id'],stage=stage,parameters=p,confirmation_bar=dict(row))
                    events.append(Event(eid,fid,row['symbol'],Timeframe(row['timeframe']),row['datetime'],
                        row['available_at'],direction=d,metadata=metadata))
                    state['ids'].append(eid)
                    transitions.append(SequenceMatch(f'BROOKS.WEDGE_CONFIRMED_{suffix}','1.0.0',row['symbol'],
                        tuple(state['ids']),state['started_at'],row['available_at'],status,state['id'],
                        Timeframe(row['timeframe']),eid if status=='invalidated' else None))
                    value=float(stage==self.component)
                    if status!='active':
                        state=None
                        candidate=[]
                output.append({**{k:row[k] for k in ('symbol','datetime','available_at')},'value':value})
        return pl.DataFrame(output,schema_overrides={'value':pl.Float64}),transitions,events

    def compute(self,bars,parameters):
        return self.trace(bars,parameters)[0]


def brooks_wedge_pack():
    return FactorPack('BrooksWedgePack','1.0.0',tuple(BrooksWedgeComponent(c,d)
        for d in (1,-1) for c in COMPONENTS),('BrooksBasePack',))

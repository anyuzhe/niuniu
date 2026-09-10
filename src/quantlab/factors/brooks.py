"""Close-confirmed Brooks-inspired second-entry variant, not discretionary Brooks rules."""
import polars as pl
from quantlab.data.validation import ordered_bars
from quantlab.domain import Event, SequenceMatch, Timeframe, FactorType
from quantlab.factors.base import ComputedFactor, FactorDefinition
from quantlab.factors.registry import FactorPack
from quantlab.storage.codec import digest


class BrooksComponent(ComputedFactor):
    def __init__(self, component, direction):
        self.component, self.direction = component, direction
        suffix = 'UP' if direction == 1 else 'DOWN'
        name = {'trend':'趋势背景','pullback':'回调开始','first':'首次入场确认','failure':'首次尝试失败','second':'二次入场确认'}[component]
        identifier = f'BROOKS.{component.upper()}_{suffix}'
        self.definition = FactorDefinition(identifier,'1.0.0',name+'（'+suffix+'）','sequence',FactorType.BOOLEAN,
            ('open','high','low','close','volume','turnover'),tuple(Timeframe),
            '收盘确认变体：滞后趋势→逆向收盘回调→突破前根极值→收盘穿越首次尝试反侧极值→再次突破前根极值；超时或穿越背景极值失效。',
            component+' of ordered second-entry state machine',source_theory=('Brooks',))

    def parameters(self, supplied):
        if set(supplied)-{'trend_lookback','max_bars'}:
            raise ValueError('Brooks accepts trend_lookback and max_bars')
        params={'trend_lookback':supplied.get('trend_lookback',10),'max_bars':supplied.get('max_bars',20)}
        if any(type(v) is not int or not 1<=v<=10000 for v in params.values()):
            raise ValueError('Brooks windows must be integers in [1,10000]')
        return params

    def trace(self,bars,parameters):
        p=self.parameters(parameters);bars=ordered_bars(bars);direction=self.direction
        if bars.select(pl.struct('symbol','available_at').is_duplicated().any()).item():
            raise ValueError('Brooks requires unique symbol/available_at')
        output=[];events=[];transitions=[]
        for _,group in bars.group_by('symbol',maintain_order=True):
            history=group.to_dicts();state=None
            for i,row in enumerate(history):
                ready=i>p['trend_lookback'];flags={k:0. for k in ('trend','pullback','first','failure','second')}
                if not ready:
                    output.append({**{k:row[k] for k in ('symbol','datetime','available_at')},'value':None});continue
                prev=history[i-1];bull=direction*(prev['close']-history[i-p['trend_lookback']-1]['close'])>0
                flags['trend']=float(bull)
                stage=None;status='active'
                if state and (i-state['start']>p['max_bars'] or direction*(row['close']-state['anchor'])<0):
                    stage='expired' if i-state['start']>p['max_bars'] else 'invalidated';status=stage
                elif state:
                    crossed=row['close']>prev['high'] if direction==1 else row['close']<prev['low']
                    if state['stage']=='pullback' and crossed:
                        stage='first';state['failure_price']=row['low'] if direction==1 else row['high']
                    elif state['stage']=='first' and direction*(row['close']-state['failure_price'])<0:
                        stage='failure'
                    elif state['stage']=='failure' and crossed:
                        stage='second';status='completed'
                elif bull and direction*(row['close']-prev['close'])<0:
                    window=history[i-p['trend_lookback']-1:i]
                    anchor=min(v['low'] for v in window) if direction==1 else max(v['high'] for v in window)
                    if direction*(row['close']-anchor)>=0:
                        state={'start':i,'at':row['datetime'],'stage':'pullback','anchor':anchor,'ids':[],
                            'id':digest({'symbol':row['symbol'],'timeframe':row['timeframe'],'start':row['datetime'],'parameters':p,'direction':direction})}
                        stage='pullback'
                if stage:
                    fid=f'BROOKS.{stage.upper()}_'+('UP' if direction==1 else 'DOWN')
                    event_id=digest({'match':state['id'],'stage':stage,'at':row['available_at']})
                    event=Event(event_id,fid,row['symbol'],Timeframe(row['timeframe']),row['datetime'],row['available_at'],
                        direction=direction,metadata={'match_id':state['id'],'anchor':state['anchor'],'parameters':p,'stage':stage})
                    events.append(event);state['ids'].append(event_id)
                    transitions.append(SequenceMatch('BROOKS.SECOND_'+('UP' if direction==1 else 'DOWN'),'1.0.0',row['symbol'],
                        tuple(state['ids']),state['at'],row['available_at'],status,state['id'],Timeframe(row['timeframe']),
                        event_id if status=='invalidated' else None))
                    if stage in flags:flags[stage]=1.
                    state['stage']=stage
                    if status!='active':state=None
                output.append({**{k:row[k] for k in ('symbol','datetime','available_at')},'value':flags[self.component]})
        return pl.DataFrame(output,schema_overrides={'value':pl.Float64}),transitions,events

    def compute(self,bars,parameters):return self.trace(bars,parameters)[0]


def brooks_pack():
    return FactorPack('BrooksBasePack','1.0.0',tuple(BrooksComponent(c,d) for d in (1,-1)
        for c in ('trend','pullback','first','failure','second')),('TechnicalBasePack',))

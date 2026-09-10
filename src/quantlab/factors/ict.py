"""Explicit OHLC variants of Sweep, Displacement and sweep/displacement/structure shift."""
import math
from dataclasses import replace
from datetime import timedelta
import polars as pl
from quantlab.data.validation import ordered_bars
from quantlab.domain import Event, FactorType, Timeframe
from quantlab.events.failed_breakout import FailedBreakoutEngine
from quantlab.structure.breaks import ConfirmedSwingBreakEngine
from quantlab.factors.base import ComputedFactor, FactorDefinition
from quantlab.factors.registry import FactorPack
from quantlab.sequence.engine import EventSelector, SequenceDefinition, OrderedSequenceEngine
from quantlab.storage.codec import digest


class ICTComponent(ComputedFactor):
    def __init__(self,component,direction):
        self.component,self.direction=component,direction
        suffix='UP' if direction==1 else 'DOWN'
        self.definition=FactorDefinition(f'ICT.{component.upper()}_{suffix}','1.0.0',
            {'sweep':'区间扫出收回','displacement':'ATR 实体位移','mss':'扫出、位移、结构转变'}[component]+'（'+suffix+'）',
            'sequence' if component=='mss' else 'event',FactorType.BOOLEAN,
            ('open','high','low','close','volume','turnover'),tuple(Timeframe),
            'OHLC 明确规则变体：Sweep 为前区间扫出收回，Displacement 为相对前 ATR 的方向实体，MSS 要求 Sweep→Displacement→已确认摆动突破，三个不同可用时点。',
            component+'; no inferred resting orders or intrabar path',source_theory=('ICT','SMC'))

    def parameters(self,supplied):
        defaults={'lookback':20,'left':2,'right':2,'atr_multiple':1.5,'body_fraction':.7,'max_gap_seconds':172800}
        if set(supplied)-set(defaults):raise ValueError('Unknown ICT parameter')
        p={**defaults,**supplied}
        for key in ('lookback','left','right','max_gap_seconds'):
            if type(p[key]) is not int or not 1<=p[key]<=31536000:raise ValueError('ICT windows must be positive integers')
        for key in ('atr_multiple','body_fraction'):
            if type(p[key]) not in (int,float) or not math.isfinite(p[key]) or p[key]<=0:raise ValueError('Invalid displacement threshold')
        if p['body_fraction']>1:raise ValueError('body_fraction exceeds one')
        return p

    def trace(self,bars,parameters):
        p=self.parameters(parameters);bars=ordered_bars(bars);suffix='UP' if self.direction==1 else 'DOWN'
        if bars.select(pl.struct('symbol','available_at').is_duplicated().any()).item():raise ValueError('ICT requires unique symbol/available_at')
        frame=bars.with_columns(pl.col('close').shift(1).over('symbol').alias('_previous'))
        frame=frame.with_columns(pl.max_horizontal(pl.col('high')-pl.col('low'),(pl.col('high')-pl.col('_previous')).abs(),
            (pl.col('low')-pl.col('_previous')).abs()).alias('_tr'))
        frame=frame.with_columns(pl.col('_tr').rolling_mean(p['lookback']).shift(1).over('symbol').alias('_atr'))
        displacement=(self.direction*(pl.col('close')-pl.col('open'))>=pl.col('_atr')*p['atr_multiple']) & \
            ((pl.col('close')-pl.col('open')).abs()>0) & \
            ((pl.col('close')-pl.col('open')).abs()>=(pl.col('high')-pl.col('low'))*p['body_fraction'])
        frame=frame.with_columns(displacement.alias('_displacement'))
        events=[]
        for event in FailedBreakoutEngine(p['lookback']).detect(bars):
            fid='ICT.SWEEP_'+('UP' if event.direction==1 else 'DOWN')
            events.append(replace(event,event_id=digest({'source':event.event_id,'factor_id':fid}),factor_id=fid,
                metadata={**event.metadata,'interpretation':'OHLC range excursion/reclaim; resting liquidity not observed'}))
        for row in frame.filter('_displacement').iter_rows(named=True):
            identity={'factor_id':'ICT.DISPLACEMENT_'+suffix,'symbol':row['symbol'],'at':row['available_at'],'parameters':p,'timeframe':row['timeframe']}
            events.append(Event(digest(identity),identity['factor_id'],row['symbol'],Timeframe(row['timeframe']),row['datetime'],row['available_at'],
                direction=self.direction,metadata={'prior_atr':row['_atr'],'body':row['close']-row['open'],'parameters':p}))
        _,breaks=ConfirmedSwingBreakEngine(p['left'],p['right']).analyze(bars)
        events+=breaks
        definition=SequenceDefinition('ICT.MSS_'+suffix,
            (EventSelector('ICT.SWEEP_'+suffix),EventSelector('ICT.DISPLACEMENT_'+suffix),EventSelector('SMC.BOS_'+suffix)),
            timedelta(seconds=p['max_gap_seconds']),invalidators=(EventSelector('ICT.SWEEP_'+('DOWN' if self.direction==1 else 'UP')),))
        states=OrderedSequenceEngine(definition).advance(events,frame['available_at'].max()) if self.component=='mss' else []
        if self.component=='mss':
            for state in states:
                if state.status=='completed':
                    events.append(Event(digest({'match':state.match_id,'at':state.available_at}),self.definition.factor_id,state.symbol,
                        state.timeframe,state.available_at,state.available_at,direction=self.direction,
                        metadata={'match_id':state.match_id,'event_ids':state.event_ids,'parameters':p}))
        matching={(e.symbol,e.available_at) for e in events if e.factor_id==self.definition.factor_id}
        values=frame.select('symbol','datetime','available_at').with_columns(pl.Series('value',[
            None if row['_atr'] is None else float((row['symbol'],row['available_at']) in matching)
            for row in frame.iter_rows(named=True)],dtype=pl.Float64))
        return values,states,sorted(events,key=lambda e:(e.available_at,e.symbol,e.event_id))

    def compute(self,bars,parameters):return self.trace(bars,parameters)[0]


def ict_pack():
    return FactorPack('ICTBasePack','1.0.0',tuple(ICTComponent(c,d) for d in (1,-1)
        for c in ('sweep','displacement','mss')),('SMCBasePack','ZoneBasePack'))

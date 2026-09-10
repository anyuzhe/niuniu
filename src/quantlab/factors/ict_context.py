"""Explicit OHLC/time variants for ICT concepts with deterministic boundaries."""
from datetime import time
from zoneinfo import ZoneInfo
import polars as pl
from quantlab.domain import FactorType,Timeframe,Event
from quantlab.factors.base import ComputedFactor,FactorDefinition
from quantlab.factors.registry import FactorPack
from quantlab.factors.order_block import OrderBlockComponent
from quantlab.storage.codec import digest

class DealingRange(ComputedFactor):
    def __init__(self,component):
        self.component=component
        self.definition=FactorDefinition('ICT.'+component.upper(),'1.0.0','ICT 区间 · '+component,'context',
            FactorType.SCALAR if component=='range_position' else FactorType.BOOLEAN,('high','low','close'),tuple(Timeframe),
            '前 lookback 根高低区间冻结到本根，位置=(close-low)/(high-low)；premium 为 (0.5,1]，discount 为 [0,0.5)，越界不算区间内。明确的滚动区间变体。',
            'Lagged rolling dealing range, no discretionary swing selection',source_theory=('ICT',))
    def parameters(self,supplied):
        if set(supplied)-{'lookback'}:raise ValueError('Only lookback is supported')
        n=supplied.get('lookback',20)
        if type(n) is not int or not 2<=n<=10000:raise ValueError('lookback must be 2–10000')
        return {'lookback':n}
    def compute(self,bars,parameters):
        n=self.parameters(parameters)['lookback'];high=pl.col('high').rolling_max(n).shift(1).over('symbol');low=pl.col('low').rolling_min(n).shift(1).over('symbol')
        position=pl.when(high>low).then((pl.col('close')-low)/(high-low)).otherwise(None)
        value=position if self.component=='range_position' else ((position>.5)&(position<=1) if self.component=='premium' else (position>=0)&(position<.5)).cast(pl.Float64)
        return bars.sort('symbol','datetime').select('symbol','datetime','available_at',value.alias('value'))

class KillZone(ComputedFactor):
    definition=FactorDefinition('ICT.KILL_ZONE','1.0.0','ICT Kill Zone 时间窗口','context',FactorType.BOOLEAN,(),
        tuple(t for t in Timeframe if t!=Timeframe.DAILY),
        '按指定 IANA 时区转换收盘时间，窗口 start < close <= end，DST 由时区库处理。默认纽约 07:00–10:00；仅表示时间条件，不声称适用于 A 股。',
        'timezone-local intraday close-time window',source_theory=('ICT',))
    def parameters(self,supplied):
        if set(supplied)-{'timezone','start','end'}:raise ValueError('Invalid Kill Zone parameters')
        p={'timezone':'America/New_York','start':'07:00','end':'10:00',**supplied}
        try:
            ZoneInfo(p['timezone']);start=time.fromisoformat(p['start']);end=time.fromisoformat(p['end'])
        except (ValueError,TypeError,KeyError) as exc:raise ValueError('Invalid timezone or window') from exc
        if start.tzinfo or end.tzinfo or not start<end:raise ValueError('Require same-day start < end, without UTC offsets')
        return p
    def compute(self,bars,parameters):
        p=self.parameters(parameters);zone=ZoneInfo(p['timezone']);start=time.fromisoformat(p['start']);end=time.fromisoformat(p['end'])
        return bars.select('symbol','datetime','available_at').with_columns(pl.Series('value',[
            float(start<t.astimezone(zone).time()<=end) for t in bars['datetime']],dtype=pl.Float64))

class Breaker(ComputedFactor):
    def __init__(self,direction):
        self.direction=direction;suffix='UP' if direction==1 else 'DOWN'
        self.definition=FactorDefinition('ICT.BREAKER_RETEST_'+suffix,'1.0.0','ICT Breaker 确认回测 · '+suffix,'event',FactorType.BOOLEAN,
            ('open','high','low','close','volume','turnover'),tuple(Timeframe),
            '已有反向 OB 收盘失效后，在后续独立 K 线首次接触原区间且收盘返回突破侧确认；回穿另一侧失效，按 max_age_bars 超时。明确 OHLC 变体。',
            'Failed opposite order block -> subsequent retest rejection; no same-bar confirmation',source_theory=('ICT','SMC'))
    def parameters(self,supplied):return OrderBlockComponent('invalidated',-self.direction).parameters(supplied)
    def trace(self,bars,parameters):
        p=self.parameters(parameters);_,_,source=OrderBlockComponent('invalidated',-self.direction).trace(bars,p)
        invalid={}
        for e in source:
            if '.OB_INVALIDATED_' in e.factor_id:invalid.setdefault((e.symbol,e.available_at),[]).append(e)
        events=[];values=[]
        for _,group in bars.sort('symbol','datetime').group_by('symbol',maintain_order=True):
            active=[]
            for i,row in enumerate(group.iter_rows(named=True)):
                keep=[];signal=0.
                for created,origin in active:
                    lower=origin.metadata['lower'];upper=origin.metadata['upper'];d=self.direction
                    if i-created>p['max_age_bars'] or (row['close']<lower if d==1 else row['close']>upper):continue
                    if row['low']<=upper and row['high']>=lower and (row['close']>upper if d==1 else row['close']<lower):
                        metadata={'zone_id':origin.metadata['zone_id'],'lower':lower,'upper':upper,'invalidation_event_id':origin.event_id,'invalidation_available_at':origin.available_at,'status':'completed'}
                        events.append(Event(digest({'origin':origin.event_id,'at':row['available_at'],'factor':self.definition.factor_id}),self.definition.factor_id,row['symbol'],Timeframe(row['timeframe']),row['datetime'],row['available_at'],direction=d,metadata=metadata));signal=1.
                    else:keep.append((created,origin))
                active=keep+[(i,e) for e in invalid.get((row['symbol'],row['available_at']),[])]
                values.append({'symbol':row['symbol'],'datetime':row['datetime'],'available_at':row['available_at'],'value':signal})
        return pl.DataFrame(values),[],sorted([*source,*events],key=lambda e:(e.available_at,e.symbol,e.event_id))
    def compute(self,bars,parameters):return self.trace(bars,parameters)[0]

def ict_context_pack():
    return FactorPack('ICTContextPack','1.0.0',(*[DealingRange(c) for c in ('range_position','premium','discount')],KillZone(),Breaker(1),Breaker(-1)),('ICTOrderBlockPack',))

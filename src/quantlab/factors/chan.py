import polars as pl
from quantlab.adapters.chan import ChanStructureAdapter
from quantlab.domain import Event, FactorType, Timeframe
from quantlab.factors.base import ComputedFactor, FactorDefinition
from quantlab.factors.registry import FactorPack


class ChanComponent(ComputedFactor):
    def __init__(self,component):
        self.component=component
        self.definition=FactorDefinition('CHAN.'+component.upper(),'1.0.0','Chan '+component,'structure',FactorType.BOOLEAN,
            ('open','high','low','close','volume','turnover'),tuple(Timeframe),
            '严格确认分型、保留首端点的交替笔、连续三笔重叠中枢；不含包含处理、线段、背驰或买卖点。',
            'confirmed_alternating_v1',source_theory=('Chan',),available_at_rule='right bars after pivot; structure at final endpoint confirmation')
    def parameters(self,supplied):
        defaults={'left':2,'right':2,'min_separation':3}
        if set(supplied)-set(defaults):raise ValueError('Unknown Chan parameter')
        p={**defaults,**supplied}
        if any(type(v) is not int or v<1 for v in p.values()):raise ValueError('Chan parameters must be positive integers')
        return p
    def trace(self,bars,parameters):
        p=self.parameters(parameters); structures=ChanStructureAdapter(**p).analyze(bars)
        events=[Event(s['structure_id'],'CHAN.'+s['kind'].removeprefix('chan_').upper(),s['symbol'],Timeframe(s['timeframe']),
            s['occurred_at'],s['available_at'],direction=s.get('direction',0),metadata=s) for s in structures]
        known={(e.symbol,e.available_at) for e in events if e.factor_id==self.definition.factor_id}
        return bars.select('symbol','datetime','available_at').with_columns(pl.Series('value',[
            float((r['symbol'],r['available_at']) in known) for r in bars.iter_rows(named=True)],dtype=pl.Float64)),[],events
    def compute(self,bars,parameters):return self.trace(bars,parameters)[0]


def chan_pack():return FactorPack('ChanAdapterPack','1.0.0',tuple(ChanComponent(c) for c in ('pivot_high','pivot_low','bi','center')))

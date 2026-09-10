import polars as pl
from quantlab.adapters.chan import ChanStructureAdapter
from quantlab.adapters.chan_inclusion import finalized_inclusion_bars,center_lifecycle
from quantlab.domain import Event,FactorType,Timeframe
from quantlab.factors.base import ComputedFactor,FactorDefinition
from quantlab.factors.registry import FactorPack
from quantlab.factors.chan import ChanComponent
from quantlab.storage.codec import digest


class ChanInclusionComponent(ComputedFactor):
    def __init__(self,component):
        self.component=component
        self.definition=FactorDefinition('CHAN.INCLUSION_'+component.upper(),'1.0.0','Chan 包含确认 '+component,'structure',FactorType.BOOLEAN,
            ('open','high','low','close','volume','turnover'),tuple(Timeframe),
            '方向合并包含 K 线，仅在后继非包含 K 线到达时发布；首段无方向使用并集包络；再按合并 K 线计数确认分型和交替笔/三笔中枢。',
            'finalized_inclusion_v1; synthetic bars are structure-only',source_theory=('Chan',),
            available_at_rule='non-included successor confirms merged bar; right finalized merged bars confirm pivot')
    def parameters(self,supplied):return ChanComponent('center').parameters(supplied)
    def trace(self,bars,parameters):
        p=self.parameters(parameters);merged,records=finalized_inclusion_bars(bars);events=[]
        for r in records:
            events.append(Event(r['structure_id'],'CHAN.INCLUSION_BAR',r['symbol'],Timeframe(r['timeframe']),r['occurred_at'],r['available_at'],direction=r['direction'],metadata=r))
        if not merged.is_empty():
            adapter=ChanStructureAdapter(**p);adapter.version='finalized_inclusion_v1'
            structures=adapter.analyze(merged)
            for s in structures+center_lifecycle(structures):
                fid='CHAN.INCLUSION_'+s['kind'].removeprefix('chan_').upper()
                events.append(Event(digest({'factor_id':fid,'structure':s}),fid,s['symbol'],Timeframe(s['timeframe']),s['occurred_at'],s['available_at'],direction=s.get('direction',0),metadata=s))
        known={(e.symbol,e.available_at) for e in events if e.factor_id==self.definition.factor_id}
        values=bars.select('symbol','datetime','available_at').with_columns(pl.Series('value',[float((r['symbol'],r['available_at']) in known) for r in bars.iter_rows(named=True)]))
        return values,[],sorted(events,key=lambda e:(e.available_at,e.symbol,e.event_id))
    def compute(self,bars,parameters):return self.trace(bars,parameters)[0]


def chan_inclusion_pack():
    return FactorPack('ChanInclusionPack','1.0.0',tuple(ChanInclusionComponent(c) for c in ('bar','pivot_high','pivot_low','bi','center','active_center','center_extended','center_exit_up','center_exit_down')),('ChanAdapterPack',))

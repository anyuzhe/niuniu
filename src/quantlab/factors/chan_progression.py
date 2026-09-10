import math
import polars as pl
from quantlab.adapters.chan import ChanStructureAdapter
from quantlab.adapters.chan_inclusion import finalized_inclusion_bars,center_lifecycle
from quantlab.adapters.chan_progression import progression_events
from quantlab.domain import Event,FactorType,Timeframe
from quantlab.factors.base import ComputedFactor,FactorDefinition
from quantlab.factors.registry import FactorPack
from quantlab.factors.chan import ChanComponent


COMPONENTS=('segment_up','segment_down','divergence_up','divergence_down','buy1','sell1','buy2','sell2','buy3','sell3')


class ChanProgressionComponent(ComputedFactor):
    def __init__(self,component):
        if component not in COMPONENTS:raise ValueError('Unknown Chan progression component')
        self.component=component
        self.definition=FactorDefinition('CHAN.RULE_'+component.upper(),'1.0.0','Chan 确认推进 '+component,'structure',FactorType.BOOLEAN,
            ('open','high','low','close','volume','turnover'),tuple(Timeframe),
            '包含确认笔的至少三笔推进、反向端点突破确认；同向新极值且归一化价格速度减弱；一类点反转确认、二/三类点首次回踩再突破。非完整特征序列/缺口规则。',
            'confirmed_progression_v1; no discretionary Chan interpretation',source_theory=('Chan',),
            available_at_rule='last required confirmed stroke available; never backfill segment endpoint')
    def parameters(self,supplied):
        extra={'divergence_ratio':.8,'max_follow_strokes':12}
        p=ChanComponent('center').parameters({k:v for k,v in supplied.items() if k not in extra})
        p.update({k:supplied.get(k,v) for k,v in extra.items()})
        if type(p['divergence_ratio']) not in (int,float) or not math.isfinite(p['divergence_ratio']) or not 0<p['divergence_ratio']<=1:raise ValueError('divergence_ratio must be in (0,1]')
        if type(p['max_follow_strokes']) is not int or not 1<=p['max_follow_strokes']<=100000:raise ValueError('Invalid max_follow_strokes')
        return p
    def trace(self,bars,parameters):
        p=self.parameters(parameters);merged,_=finalized_inclusion_bars(bars);events=[]
        if not merged.is_empty():
            adapter=ChanStructureAdapter(**{k:p[k] for k in ('left','right','min_separation')});adapter.version='finalized_inclusion_v1'
            structures=adapter.analyze(merged);pivots={s['structure_id']:s for s in structures if s['kind'] in ('chan_pivot_high','chan_pivot_low')}
            strokes=[{**s,'end_at':pivots[s['components'][-1]]['occurred_at']} for s in structures if s['kind']=='chan_bi']
            positions={(r['symbol'],r['datetime']):i for _,group in bars.sort('symbol','datetime').group_by('symbol') for i,r in enumerate(group.iter_rows(named=True))}
            records=progression_events(strokes,center_lifecycle(structures),positions,p['divergence_ratio'],p['max_follow_strokes'])
            for r in records:
                fid='CHAN.RULE_'+r['kind'].upper()
                events.append(Event(r['structure_id'],fid,r['symbol'],Timeframe(r['timeframe']),r['occurred_at'],r['available_at'],direction=r['direction'],metadata=r))
        known={(e.symbol,e.available_at) for e in events if e.factor_id==self.definition.factor_id}
        values=bars.select('symbol','datetime','available_at').with_columns(pl.Series('value',[float((r['symbol'],r['available_at']) in known) for r in bars.iter_rows(named=True)]))
        return values,[],sorted(events,key=lambda e:(e.available_at,e.symbol,e.event_id))
    def compute(self,bars,parameters):return self.trace(bars,parameters)[0]


def chan_progression_pack():return FactorPack('ChanProgressionPack','1.0.0',tuple(ChanProgressionComponent(c) for c in COMPONENTS),('ChanInclusionPack',))

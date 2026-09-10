from copy import deepcopy
from quantlab.sequence.specification import normalize_steps, sequence_scopes
"""Ordered Chan events using the existing confirmed-inclusion event source."""
from datetime import timedelta
import polars as pl
from quantlab.domain import FactorType,Timeframe
from quantlab.factors.base import ComputedFactor,FactorDefinition
from quantlab.factors.chan_inclusion import ChanInclusionComponent
from quantlab.factors.registry import FactorPack
from quantlab.sequence.engine import SequenceDefinition,EventSelector,OrderedSequenceEngine

class ChanOrderedSequence(ComputedFactor):
    SOURCES=('CHAN.INCLUSION_ACTIVE_CENTER','CHAN.INCLUSION_CENTER_EXTENDED',
        'CHAN.INCLUSION_CENTER_EXIT_UP','CHAN.INCLUSION_CENTER_EXIT_DOWN')
    definition=FactorDefinition('SEQ.CHAN_ORDERED','1.0.0','缠论中枢有序事件序列','sequence',FactorType.BOOLEAN,
        ('open','high','low','close','volume','turnover'),tuple(Timeframe),
        '确认包含中枢的形成、延续、离开事件按可用时间组成序列；失效优先、逐步严格超时、不重叠。明确规则变体，非完整经典缠论。',
        'Ordered finalized-inclusion center events',source_theory=('Chan',),available_at_rule='final required Chan event availability')
    def parameters(self,supplied):
        allowed={'left','right','min_separation','steps','invalidators','max_gap_seconds'}
        if set(supplied)-allowed:raise ValueError('Unknown Chan sequence parameter')
        p=ChanInclusionComponent('center').parameters({k:v for k,v in supplied.items() if k in ('left','right','min_separation')})
        steps=supplied.get('steps',['CHAN.INCLUSION_ACTIVE_CENTER','CHAN.INCLUSION_CENTER_EXIT_UP'])
        invalid=supplied.get('invalidators',['CHAN.INCLUSION_CENTER_EXIT_DOWN']);gap=supplied.get('max_gap_seconds',604800)
        if type(gap) is not int or not 1<=gap<=31536000:raise ValueError('Invalid Chan sequence timeout')
        flat,optional=normalize_steps(steps,self.SOURCES)
        sequence_scopes(steps)
        for values in (invalid,):
            if not isinstance(values,list) or any(not isinstance(v,str) or v not in self.SOURCES for v in values):raise ValueError('Unsupported Chan event selector')
        if len(invalid)!=len(set(invalid)) or set(flat)&set(invalid):raise ValueError('Invalid or conflicting Chan sequence steps')
        return {**p,'steps':deepcopy(steps),'invalidators':list(invalid),'max_gap_seconds':gap}
    def trace(self,bars,parameters):
        p=self.parameters(parameters)
        if bars.select(pl.struct('symbol','available_at').is_duplicated().any()).item():raise ValueError('Chan sequence requires unique symbol/available_at')
        _,_,events=ChanInclusionComponent('center').trace(bars,{k:p[k] for k in ('left','right','min_separation')})
        flat,optional=normalize_steps(p['steps'],self.SOURCES)
        definition=SequenceDefinition(self.definition.factor_id,tuple(EventSelector(v) for v in flat),timedelta(seconds=p['max_gap_seconds']),tuple(EventSelector(v) for v in p['invalidators']),optional_steps=optional,scopes=sequence_scopes(p['steps']))
        transitions=OrderedSequenceEngine(definition).advance(events,bars['available_at'].max()) if bars.height else []
        complete={(v.symbol,v.available_at) for v in transitions if v.status=='completed'}
        values=bars.select('symbol','datetime','available_at').with_columns(pl.Series('value',[float((r['symbol'],r['available_at']) in complete) for r in bars.iter_rows(named=True)],dtype=pl.Float64))
        return values,transitions,events
    def compute(self,bars,parameters):return self.trace(bars,parameters)[0]

def chan_sequence_pack():return FactorPack('ChanSequencePack','1.0.0',(ChanOrderedSequence(),),('ChanInclusionPack',))

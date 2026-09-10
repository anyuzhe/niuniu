"""Classic feature-sequence Chan factors and a separate causal holding policy."""
import polars as pl
from quantlab.adapters.chan_classic import analyze_classic,COMPONENTS,PROFILE
from quantlab.domain import FactorType,Timeframe,SequenceMatch
from quantlab.storage.codec import digest
from quantlab.factors.base import ComputedFactor,FactorDefinition
from quantlab.factors.registry import FactorPack


class ClassicChanFactor(ComputedFactor):
    caches_structures=True
    def __init__(self,component):
        if component not in (*COMPONENTS,'sequence_buy2'):raise ValueError('Unknown classic Chan component')
        self.component=component;self._cache=None
        names={'pivot_high':'顶分型','pivot_low':'底分型','bi_up':'向上笔','bi_down':'向下笔',
            'segment_up':'向上线段','segment_down':'向下线段','center':'中枢','higher_center':'递归中枢',
            'buy1':'一买','sell1':'一卖','buy2':'二买','sell2':'二卖','buy3':'三买','sell3':'三卖','position':'买卖点持仓模型','sequence_buy2':'一买至关联二买序列'}
        self.definition=FactorDefinition('CHAN.CLASSIC_'+component.upper(),'1.0.0','经典缠论 · '+names[component],
            'model' if component=='position' else 'structure',FactorType.SCALAR if component=='position' else FactorType.BOOLEAN,
            ('open','high','low','close','volume','turnover'),tuple(Timeframe),
            '固定 chan.py 严格笔、特征序列线段、中枢与 MACD 面积背驰配置；逐根输入，结构修订按首次可见时间记录。持仓模型为独立交易规则。',
            'chanpy_feature_sequence_strict_v1',source_theory=('Chan',),available_at_rule='current observed bar close; never retroactive pivot time')
    def parameters(self,supplied):
        if supplied:raise ValueError('Classic Chan v1 uses a frozen rule profile; parameters must be {}')
        return {}
    def matrix(self,bars):
        cache=getattr(self,'_persistent_cache',None)
        recent=getattr(cache,'classic_recent',None) if cache is not None else self._cache
        if recent is None or not recent[0].equals(bars):
            if cache is None:values,events=analyze_classic(bars)
            else:
                from datetime import datetime
                from quantlab.domain import Event
                matrices=[];events=[]
                total=bars['symbol'].n_unique()
                for number,(_,group) in enumerate(bars.sort('symbol','datetime').group_by('symbol',maintain_order=True),1):
                    from quantlab.progress import checkpoint
                    checkpoint('经典缠论 · '+group['symbol'][0],number-1,total)
                    # Share all classical components; revisions only recalculate changed stocks.
                    identity={'classic_profile':PROFILE,'version':'1.0.0'}
                    key=cache.key(identity,group)
                    saved=cache.get(key)
                    if saved is None:saved=cache.get_prefix(identity,group)
                    if saved is None:
                        matrix,part=cache.compute_classic(identity,group);cache.put(key,matrix,part);cache.publish_prefix(identity,group,key)
                    else:
                        matrix,items=saved
                        part=[Event(**{**item,'timeframe':Timeframe(item['timeframe']),
                            **{k:datetime.fromisoformat(item[k]) if item.get(k) else None
                                for k in ('occurred_at','available_at','confirmed_at')}}) for item in items]
                    matrices.append(matrix);events.extend(part)
                values=pl.concat(matrices)
                checkpoint("经典缠论结构计算",total,total)
            recent=(bars.clone(),values,events)
            if cache is None:self._cache=recent
            else:cache.classic_recent=recent
        return recent[1:]
    def compute(self,bars,parameters):
        self.parameters(parameters);matrix,_=self.matrix(bars)
        if self.component=='sequence_buy2':
            _,events=self.matrix(bars)
            known={(t.symbol,t.available_at) for t in classic_transitions(events) if t.status=='completed'}
            return matrix.select('symbol','datetime','available_at').with_columns(pl.Series('value',[float((s,t) in known) for s,t in matrix.select('symbol','available_at').iter_rows()]))
        return matrix.select('symbol','datetime','available_at',pl.col(self.component).alias('value'))
    def trace(self,bars,parameters):
        self.parameters(parameters);matrix,events=self.matrix(bars)
        return self.compute(bars,parameters),classic_transitions(events),events


def classic_transitions(events):
    pending={};records=[]
    def record(first,status,at,ids,invalid=None):
        return SequenceMatch('CHAN.CLASSIC_SEQUENCE_BUY2','1.0.0',first.symbol,ids,first.occurred_at,at,status,
            digest({'first_event':first.event_id,'sequence':'classic_related_buy2_v1'}),first.timeframe,invalid)
    for event in sorted(events,key=lambda e:(e.available_at,e.symbol,e.metadata.get('status')!='removed',e.event_id)):
        if event.factor_id not in ('CHAN.CLASSIC_BUY1','CHAN.CLASSIC_BUY2'):continue
        meta=event.metadata;key=(event.symbol,meta['end_index'])
        if event.factor_id=='CHAN.CLASSIC_BUY1':
            if meta['status']=='added' and key not in pending:
                pending[key]=event;records.append(record(event,'active',event.available_at,(event.event_id,)))
            elif meta['status']=='removed' and key in pending:
                first=pending.pop(key);records.append(record(first,'invalidated',event.available_at,(first.event_id,),event.event_id))
        elif meta['status']=='added':
            key=(event.symbol,meta.get('related_buy_sell_1_index'));first=pending.get(key)
            if first is not None and first.available_at<event.available_at:
                records.append(record(first,'completed',event.available_at,(first.event_id,event.event_id)));del pending[key]
    return records


def classic_chan_pack():
    return FactorPack('ClassicChanPack','1.0.0',tuple(ClassicChanFactor(c) for c in (*COMPONENTS,'sequence_buy2')))

"""Confirmed segment containment across actual completed intraday timeframes.

This is a frozen, mechanical MultiScaleNest definition. It does not rename the
single-timeframe recursive segment hierarchy as a higher trading timeframe.
"""
import polars as pl
from quantlab.adapters.chan_classic import PROFILE
from quantlab.data.validation import ordered_bars
from quantlab.domain import Event,FactorType,Timeframe
from quantlab.factors.base import ComputedFactor,FactorDefinition
from quantlab.factors.chan_classic import ClassicChanFactor
from quantlab.factors.registry import FactorPack
from quantlab.multitimeframe.resample import resample_bars
from quantlab.storage.codec import digest


def nested_segments(levels, same_direction=True):
    """Latest confirmed root, then latest fully-contained descendant chain.

    Never fall back to an older root to manufacture a positive nesting result.
    Lower-level candidates are tried in descending endpoint order; a candidate
    must support the entire remaining chain before it can be selected.
    """
    if not levels[-1]:return None
    root=max(levels[-1],key=lambda s:(s['end_at'],s['start_at'],s['object_key']))
    def descend(parent,index):
        if index<0:return [parent]
        candidates=[s for s in levels[index] if parent['start_at']<=s['start_at']<s['end_at']<=parent['end_at']
                    and (not same_direction or s['direction']==parent['direction'])]
        for child in sorted(candidates,key=lambda s:(s['end_at'],s['start_at'],s['object_key']),reverse=True):
            tail=descend(child,index-1)
            if tail:return [parent,*tail]
        return []
    return descend(root,len(levels)-2)


class ClassicChanNestFactor(ComputedFactor):
    def __init__(self,component='direction'):
        if component not in ('direction','up','down'):raise ValueError('Unknown multiscale component')
        self.component=component;self._trace_cache=None
        self.definition=FactorDefinition('CHAN.CLASSIC_MULTISCALE_'+component.upper(),'1.0.0',
            '经典缠论实际周期嵌套 · '+{'direction':'方向','up':'向上','down':'向下'}[component],
            'structure',FactorType.SCALAR if component=='direction' else FactorType.BOOLEAN,
            ('open','high','low','close','volume','turnover'),tuple(t for t in Timeframe if t.minutes<60),
            '由本次低周期完整交易时段 K 线聚合两个更高周期，各自计算经典缠论。选择最高周期最新已确认线段，逐层连接时间范围完全包含的已确认线段；默认同向。缺最高周期线段为预热，缺完整嵌套为 0。只在结构已可见时更新，不回填历史信号。',
            'actual_timeframe_confirmed_segment_containment_v1',source_theory=('Chan',))

    def parameters(self,supplied):
        defaults={'middle_timeframe':'15m','higher_timeframe':'60m','same_direction':True}
        if set(supplied)-set(defaults):raise ValueError('Unknown multiscale parameter')
        p={**defaults,**supplied}
        try:middle=Timeframe(p['middle_timeframe']);high=Timeframe(p['higher_timeframe'])
        except (TypeError,ValueError):raise ValueError('请选择已注册的实际 K 线周期') from None
        if middle.minutes>=high.minutes or (high!=Timeframe.DAILY and high.minutes%middle.minutes):raise ValueError('高周期必须大于且能整除中间周期')
        if type(p['same_direction']) is not bool:raise ValueError('同向要求必须为开关')
        return p

    def trace(self,bars,parameters):
        p=self.parameters(parameters);bars=ordered_bars(bars);low=Timeframe(bars['timeframe'][0])
        middle=Timeframe(p['middle_timeframe']);high=Timeframe(p['higher_timeframe'])
        if low.minutes>=middle.minutes or middle.minutes%low.minutes:raise ValueError('实验周期必须小于且能整除中间周期；日线不能还原分钟线')
        prior=self._trace_cache
        if prior is not None and prior[0]==p and prior[1].equals(bars):return prior[2]
        values=[];events=[]
        for _,group in bars.group_by('symbol',maintain_order=True):
            from quantlab.progress import checkpoint
            checkpoint('缠论实际周期嵌套 · '+group['symbol'][0])
            frames=[group,resample_bars(group,middle,require_all=False),resample_bars(group,high,require_all=False)]
            changes=[]
            for level,frame in enumerate(frames):
                if frame.is_empty():continue
                factor=ClassicChanFactor('position');factor._persistent_cache=getattr(self,'_persistent_cache',None)
                _,source=factor.matrix(frame)
                for e in source:
                    if e.metadata.get('kind') not in ('segment_up','segment_down'):continue
                    obj=e.metadata
                    node={'object_key':obj['object_key'],'timeframe':e.timeframe.value,'start_at':frame['datetime'][obj['start_index']],
                        'end_at':frame['datetime'][obj['end_index']],'available_at':e.available_at,'direction':obj['direction'],
                        'lower':obj['lower'],'upper':obj['upper'],'source_event_id':e.event_id}
                    changes.append((e.available_at,level,e.event_id,obj['status'],node))
            changes.sort(key=lambda x:(x[0],x[1],x[2]));cursor=0;active=[{}, {}, {}];last=None;chain=None
            for i,row in enumerate(group.iter_rows(named=True)):
                if i%100==0:checkpoint()
                changed=False
                while cursor<len(changes) and changes[cursor][0]<=row['available_at']:
                    _,level,_,status,node=changes[cursor];cursor+=1;changed=True
                    if status=='removed':active[level].pop(node['object_key'],None)
                    else:active[level][node['object_key']]=node
                if changed:
                    chain=nested_segments([list(v.values()) for v in active],p['same_direction'])
                    identity=digest(chain) if chain else None
                    if identity!=last:
                        metadata={'status':'nested' if chain else 'unlinked','chain_id':identity,'previous_chain_id':last,
                            'levels':[low.value,middle.value,high.value],'segments':chain or [],'same_direction':p['same_direction'],
                            'profile':PROFILE,'rule':'actual_timeframe_confirmed_segment_containment_v1'}
                        events.append(Event(digest({'factor':self.definition.factor_id,'symbol':row['symbol'],'at':row['available_at'],'metadata':metadata}),
                            self.definition.factor_id,row['symbol'],low,row['datetime'],row['available_at'],
                            direction=chain[0]['direction'] if chain else 0,metadata=metadata));last=identity
                direction=None if chain is None else float(chain[0]['direction']) if chain else 0.
                value=direction if self.component=='direction' or direction is None else float(direction==(1 if self.component=='up' else -1))
                values.append({'symbol':row['symbol'],'datetime':row['datetime'],'available_at':row['available_at'],'value':value})
        result=(pl.DataFrame(values,schema_overrides={'value':pl.Float64}),[],events)
        self._trace_cache=(p,bars.clone(),result);return result

    def compute(self,bars,parameters):return self.trace(bars,parameters)[0]


def classic_multiscale_pack():
    return FactorPack('ClassicChanMultiscalePack','1.0.0',tuple(ClassicChanNestFactor(c) for c in ('direction','up','down')),('ClassicChanPack',))

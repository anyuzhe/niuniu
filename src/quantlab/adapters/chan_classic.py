"""Pinned feature-sequence Chan core, fed one observed bar at a time.

Snapshot revisions are recorded at observation time, never at a historical pivot.
The trading policy is separate from the structural rules: confirmed 1/2/3 buy,
hold until a new confirmed sell or withdrawal of the entry point. No ML.
"""
import polars as pl
from quantlab._vendor.chanpy.ChanConfig import CChanConfig
from quantlab._vendor.chanpy.Common.CEnum import KL_TYPE,FX_TYPE,DATA_FIELD
from quantlab._vendor.chanpy.Common.CTime import CTime
from quantlab._vendor.chanpy.KLine.KLine_List import CKLine_List
from quantlab._vendor.chanpy.KLine.KLine_Unit import CKLine_Unit
from quantlab.data.validation import ordered_bars
from quantlab.domain import Event,Timeframe
from quantlab.storage.codec import digest

PROFILE={
    'trigger_step':True,'bi_algo':'normal','bi_strict':True,'bi_fx_check':'strict',
    'gap_as_kl':False,'bi_end_is_peak':True,'bi_allow_sub_peak':False,
    'seg_algo':'chan','zs_algo':'normal','zs_combine':True,'one_bi_zs':False,
    'divergence_rate':1.0,'min_zs_cnt':2,'macd_algo':'full_area','bs1_peak':True,
    'bs_type':'1,2,3a,3b','bsp2_follow_1':True,'bsp3_follow_1':False,
    'strict_bsp3':True,'macd_algo-seg':'full_area','min_zs_cnt-seg':2,
    'bsp1_only_multibi_zs-seg':True,
}
COMPONENTS=('pivot_high','pivot_low','bi_up','bi_down','segment_up','segment_down',
    'center','higher_center','buy1','sell1','buy2','sell2','buy3','sell3','position')


class ClassicChanState:
    """One-symbol, one-actual-timeframe append state for the frozen core."""
    def __init__(self,symbol,timeframe):
        self.symbol=symbol;self.timeframe=Timeframe(timeframe)
        levels={'1d':KL_TYPE.K_DAY,'1m':KL_TYPE.K_1M,'5m':KL_TYPE.K_5M,
            '15m':KL_TYPE.K_15M,'30m':KL_TYPE.K_30M,'60m':KL_TYPE.K_60M}
        self.engine=CKLine_List(levels[self.timeframe.value],CChanConfig(dict(PROFILE)))
        self.rows=[];self.previous_klu=None;self.previous={};self.entry=None;self.position=0.0
        self.matrix=[];self.events=[]

    @staticmethod
    def line_snapshot(line,kind):
        return {'kind':kind,'start_index':line.get_begin_klu().idx,'end_index':line.get_end_klu().idx,
            'lower':min(line.get_begin_val(),line.get_end_val()),'upper':max(line.get_begin_val(),line.get_end_val()),
            'direction':1 if line.is_up() else -1,'confirmed':line.is_sure}

    def append(self,row):
        r=dict(row)
        if r['symbol']!=self.symbol or r['timeframe']!=self.timeframe.value:raise ValueError('Chan state symbol/timeframe differs')
        if self.rows and (r['datetime']<=self.rows[-1]['datetime'] or r['available_at']<=self.rows[-1]['available_at']):raise ValueError('Chan append requires strictly later bars and information times')
        index=len(self.rows);self.rows.append(r)
        engine=self.engine;previous_klu=self.previous_klu;previous=self.previous;entry=self.entry;position=self.position
        matrix=self.matrix;events=self.events;line_snapshot=self.line_snapshot
        t=r['datetime'];unit=CKLine_Unit({DATA_FIELD.FIELD_TIME:CTime(t.year,t.month,t.day,t.hour,t.minute,t.second,auto=False),
            **{k:r[k] for k in ('open','high','low','close','volume')},'turnover':r['turnover']})
        unit.set_idx(index);unit.kl_type=engine.kl_type
        if previous_klu is not None:unit.set_pre_klu(previous_klu)
        engine.add_single_klu(unit);previous_klu=unit
        current={};pulses={k:0.0 for k in COMPONENTS};points={}
        # Only structural snapshots marked sure by the pinned core are exposed.
        for kl in engine.lst[:-1]:
            if kl.fx==FX_TYPE.UNKNOWN:continue
            kind='pivot_high' if kl.fx==FX_TYPE.TOP else 'pivot_low'
            point=kl.get_peak_klu(kl.fx==FX_TYPE.TOP)
            current[f'fx:{kl.idx}']={'kind':kind,'end_index':point.idx,'price':point.high if kl.fx==FX_TYPE.TOP else point.low,'confirmed':True}
        for prefix,collection in (('bi',engine.bi_list),('segment',engine.seg_list),('higher_segment',engine.segseg_list)):
            for line in collection:
                if line.is_sure:current[f'{prefix}:{line.idx}']=line_snapshot(line,prefix+('_up' if line.is_up() else '_down'))
        for prefix,collection in (('center',engine.zs_list),('higher_center',engine.segzs_list)):
            for z in collection:
                if z.is_sure:
                    current[f'{prefix}:{z.begin.idx}']={'kind':prefix,'start_index':z.begin.idx,'end_index':z.end.idx,
                        'lower':z.low,'upper':z.high,'confirmed':True}
        for prefix,collection in (('',engine.bs_point_lst),('higher_',engine.seg_bs_point_lst)):
            for point in collection.bsp_iter():
                if not point.bi.is_sure:continue
                for ty in point.type:
                    kind=prefix+('buy' if point.is_buy else 'sell')+ty.value[0]
                    key=f'{kind}:{point.klu.idx}:{ty.value}'
                    current[key]={'kind':kind,'end_index':point.klu.idx,'price':point.klu.low if point.is_buy else point.klu.high,
                        'confirmed':True,'subtype':ty.value,'features':dict(point.features.items()),
                        'related_buy_sell_1_index':point.relate_bsp1.klu.idx if point.relate_bsp1 else None}
                    if not prefix:points[key]=current[key]
        additions=[]
        for key in sorted(set(previous)|set(current)):
            old=previous.get(key);new=current.get(key)
            if new==old:continue
            status='removed' if new is None else ('added' if old is None else 'revised')
            obj=new or old;kind=obj['kind'];available=r['available_at'];occurred=self.rows[obj['end_index']]['datetime']
            metadata={'object_key':key,'status':status,**obj}
            identity={'symbol':r['symbol'],'available_at':available,**metadata}
            events.append(Event(digest(identity),'CHAN.CLASSIC_'+kind.upper(),r['symbol'],Timeframe(r['timeframe']),occurred,available,
                direction=obj.get('direction',1 if 'buy' in kind else -1 if 'sell' in kind else 0),metadata=metadata))
            if new is not None and kind in pulses:pulses[kind]=1.0
            if key in points and old is None:additions.append(key)
        buys=[k for k in additions if k.startswith('buy')];sells=[k for k in additions if k.startswith('sell')]
        # Sell wins if both sides become visible on the same close. Withdrawal
        # exits now rather than deleting the historical decision or fill.
        if sells or (entry is not None and entry not in points):position=0.0;entry=None
        elif buys:position=1.0;entry=sorted(buys)[0]
        pulses['position']=position
        matrix.append({'symbol':r['symbol'],'datetime':t,'available_at':r['available_at'],**pulses})
        previous=current
        self.previous_klu=previous_klu;self.previous=previous;self.entry=entry;self.position=position

    def extend(self,bars):
        bars=ordered_bars(bars)
        for index,row in enumerate(bars.iter_rows(named=True)):
            if index%25==0:
                from quantlab.progress import checkpoint
                checkpoint()
            self.append(row)
        return pl.DataFrame(self.matrix),self.events


def analyze_classic(bars,progress=None):
    bars=ordered_bars(bars);matrix=[];events=[]
    for number,(_,group) in enumerate(bars.group_by('symbol',maintain_order=True),1):
        state=ClassicChanState(group['symbol'][0],group['timeframe'][0]);values,part=state.extend(group)
        matrix.append(values);events.extend(part)
        if progress:progress(number,group['symbol'][0],group.height,len(events))
    return pl.concat(matrix),events

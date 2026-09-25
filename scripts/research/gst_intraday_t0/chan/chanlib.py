"""Run the repository's pinned Chan core (quantlab._vendor.chanpy, profile of adapters/chan_classic) one 1-minute
bar at a time and record when each buy/sell point first becomes confirmed (its bi is sure). Research only."""
import sys, os, types, typing
import typing_extensions
typing.Self = typing_extensions.Self            # the VM has Python 3.10; the vendored core imports typing.Self
H=os.environ['HOME']
sys.path.insert(0, f'{H}/mnt/niuniu/src')
for name in ('quantlab.trading','quantlab.adapters'):   # avoid package __init__ side imports
    m=types.ModuleType(name); m.__path__=[f'{H}/mnt/niuniu/src/'+name.replace('.','/')]; sys.modules[name]=m
from quantlab._vendor.chanpy.ChanConfig import CChanConfig
from quantlab._vendor.chanpy.Common.CEnum import KL_TYPE, DATA_FIELD
from quantlab._vendor.chanpy.Common.CTime import CTime
from quantlab._vendor.chanpy.KLine.KLine_List import CKLine_List
from quantlab._vendor.chanpy.KLine.KLine_Unit import CKLine_Unit
PROFILE={
    'trigger_step':True,'bi_algo':'normal','bi_strict':True,'bi_fx_check':'strict',
    'gap_as_kl':False,'bi_end_is_peak':True,'bi_allow_sub_peak':False,
    'seg_algo':'chan','zs_algo':'normal','zs_combine':True,'one_bi_zs':False,
    'divergence_rate':1.0,'min_zs_cnt':2,'macd_algo':'full_area','bs1_peak':True,
    'bs_type':'1,2,3a,3b','bsp2_follow_1':True,'bsp3_follow_1':False,
    'strict_bsp3':True,'macd_algo-seg':'full_area','min_zs_cnt-seg':2,
    'bsp1_only_multibi_zs-seg':True,
}
def run(bars):
    """bars: list of (y,m,d,H,M, open,high,low,close,volume,amount). Returns list of
    (confirm_index, point_index, kind, is_buy, price, level) for bi-level ('') and segment-level ('seg') points."""
    engine=CKLine_List(KL_TYPE.K_1M,CChanConfig(dict(PROFILE)))
    prev=None; seen=set(); out=[]
    for i,(y,mo,d,h,mi,o,hi,lo,c,v,a) in enumerate(bars):
        u=CKLine_Unit({DATA_FIELD.FIELD_TIME:CTime(y,mo,d,h,mi,0,auto=False),'open':o,'high':hi,'low':lo,'close':c,'volume':v,'turnover':a})
        u.set_idx(i); u.kl_type=engine.kl_type
        if prev is not None: u.set_pre_klu(prev)
        engine.add_single_klu(u); prev=u
        for level,coll in (('',engine.bs_point_lst),('seg',engine.seg_bs_point_lst)):
            lst=coll.lst if hasattr(coll,'lst') else list(coll.bsp_iter())
            for p in lst[-6:]:
                if not p.bi.is_sure: continue
                for ty in p.type:
                    key=(level,p.klu.idx,ty.value,p.is_buy)
                    if key in seen: continue
                    seen.add(key)
                    out.append((i,p.klu.idx,ty.value,p.is_buy,p.klu.low if p.is_buy else p.klu.high,level))
    return out

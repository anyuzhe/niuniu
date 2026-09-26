"""Re-price stored research results at 万1 免五 + current stamp duty (round trip 7.2 bp instead of 5+stamp+0.2).
Per-trade adjustment = old fee - 7.2: +8 bp before 2023-08-28, +3 bp after. Research only."""
import pickle, glob, os, numpy as np, sys
sys.path.insert(0,os.path.dirname(__file__)); import agg
H=os.environ['HOME']; NEW=7.2
def adj(dates): return np.where(np.asarray(dates)>='2023-08-28',3.0,8.0)
R={}
for f in glob.glob(f'{H}/research/brk/res_*_*.pkl'):
    yr=int(f[-8:-4])
    for k,v in pickle.load(open(f,'rb')).items():
        a=adj(v['dates']); v=dict(v); ds=v['ds']+v['dc']*a
        # wins/losses can't be re-split exactly from sums; recompute bp and t only
        v['ds']=ds; v['s']=ds.sum(); R.setdefault(k,{})[yr]=v
TR=(2020,2021,2022);TE=(2023,2024);NW=(2025,2026)
def st(k,yrs):
    vs=[R[k][y] for y in yrs if y in R[k] and R[k][y]['n']>0]
    if not vs: return None
    n=sum(v['n'] for v in vs); m=sum(v['s'] for v in vs)/n
    res=np.concatenate([v['ds']-m*v['dc'] for v in vs]); se=np.sqrt((res**2).sum())/n
    return m,m/se,n
fmt=lambda x:'—' if x is None else f"{x[0]:+6.1f}bp t{x[1]:+4.1f} n{x[2]}"
names={'A':'日内平台突破','B':'多日平台突破','C':'放量突破','D':'大盘随动','S':'板块补涨','Z':'任意时点买入对照'}
for F in 'ABCDSZ':
    ks=[k for k in R if k[0]==F and (st(k,TR) or (0,0,0))[2]>=200]
    sc=sorted(ks,key=lambda k:-st(k,TR)[0])
    pos=np.mean([st(k,TR)[0]>0 for k in ks]); pos_all=np.mean([all((st(k,p) or (-1,))[0]>0 for p in (TR,TE,NW)) for k in ks])
    print(f"\n{names[F]}：{len(ks)} 组，训练期为正 {pos*100:.0f}%，三段都为正 {pos_all*100:.1f}%")
    for k in sc[:3]: print('  ',k,'| 20-22',fmt(st(k,TR)),'| 23-24',fmt(st(k,TE)),'| 25-26',fmt(st(k,NW)))

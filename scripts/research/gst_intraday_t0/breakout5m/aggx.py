"""Aggregate swing-exit results (research only)."""
import pickle, glob, os, numpy as np, sys
sys.path.insert(0,os.path.dirname(__file__)); import agg
H=os.environ['HOME']; R={}
for f in glob.glob(f'{H}/research/brk/ex_*_*.pkl'):
    yr=int(f[-8:-4])
    for k,v in pickle.load(open(f,'rb')).items(): R.setdefault(k,{})[yr]=v
agg.R=R
TR=(2020,2021,2022);TE=(2023,2024);NW=(2025,2026)
names=sorted({k[0] for k in R})
def mfe(nm,yrs):
    v=[R[(nm,'mfe')][y] for y in yrs]; n=sum(x['n'] for x in v)
    f=lambda key: sum(x[key] for x in v)/n*1e4
    return f"30分钟内最高 {f('mfe'):+5.0f}bp (同日同时点全体 {f('rmfe'):+5.0f}) 最低 {f('mae'):+5.0f} (全体 {f('rmae'):+5.0f})"
def lab(k):
    _,tp,sl,tr,tb=k
    return f"止盈{'无' if tp is None else f'{tp*100:g}%'} 止损{sl*100:g}% 回撤{'无' if tr is None else f'{tr[0]*100:g}/{tr[1]*100:g}%'} 限时{'收盘' if tb is None else f'{tb*5}分'}"
ncomb=0
for nm in names:
    ks=[k for k in R if k[0]==nm and k[1]!='mfe']; ncomb+=len(ks)
    sc=sorted(ks,key=lambda k:-agg.st(k,TR)['bp'])
    pos=np.mean([agg.st(k,TR)['bp']>0 for k in ks])
    print(f"\n{nm}  [{mfe(nm,TR)}]  训练期为正的比例 {pos:.2f}")
    for k in sc[:3]:
        print('  ',lab(k),'| 20-22',agg.fmt(agg.st(k,TR)),'| 23-24',agg.fmt(agg.st(k,TE)),'| 25-26',agg.fmt(agg.st(k,NW)))
print('combos',ncomb)

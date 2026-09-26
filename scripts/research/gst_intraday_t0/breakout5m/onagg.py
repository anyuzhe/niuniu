"""Aggregate 隔夜T results (research only)."""
import numpy as np, os
H=os.environ['HOME']; Z={}
for y in range(2020,2027):
    z=np.load(f'{H}/research/brk/on_{y}.npz',allow_pickle=True)
    for k in z.files: Z.setdefault(k,[]).append(z[k])
Z={k:np.concatenate(v) for k,v in Z.items()}
for k in [k for k in Z if k.startswith('on_')]:
    Z[k]=np.where(np.abs(Z[k])>2500,np.nan,Z[k])  # drop impossible moves (data glitches / corporate actions)
d=Z['date']; yr=np.array([x[:4] for x in d])
P={'20-22':d<'2023','23-24':(d>='2023')&(d<'2025'),'25-26':d>='2025'}
ud,inv=np.unique(d,return_inverse=True)
def dq(x,q=10):
    out=np.full(len(x),-1); fin=np.isfinite(x)
    order=np.lexsort((x,inv)); iv=inv[order]; start=np.r_[0,np.cumsum(np.bincount(iv,minlength=len(ud)))[:-1]]
    rk=np.arange(len(x))-start[iv]; cnt=np.bincount(inv[fin],minlength=len(ud))
    fo=fin[order]; out[order[fo]]=(rk[fo]*q//np.maximum(cnt[iv[fo]],1)).clip(0,q-1); return out
def st(y,mk):
    mk=mk&np.isfinite(y)
    if mk.sum()<50: return '—'
    v=y[mk]; w=v>0; m=v.mean(); r=np.bincount(inv[mk],v-m); t=m/(np.sqrt((r**2).sum())/len(v))
    return f"{m:+6.1f}bp 胜{w.mean()*100:3.0f}% 赔{v[w].mean()/-v[~w].mean():.2f} t{t:+4.1f} n{mk.sum()}"
def show(lab,y,mk): print(f"  {lab:18s}"+''.join(f" | {p} {st(y,mk&pm)}" for p,pm in P.items()))
all_=np.ones(len(d),bool)
print('全部 500 只，今天收盘买、次日卖出：')
for k in ('次日开盘','次日10:00','次日收盘'): show(k,Z['on_'+k],all_)
y=Z['on_次日开盘']
g=np.where(np.abs(Z['gross'])>2500,np.nan,Z['gross'])
print('  不扣任何费用、不计价差的隔夜涨跌（收盘到次日开盘）：', {p:round(float(np.nanmean(g[pm])),1) for p,pm in P.items()}, '逐年', {Y:round(float(np.nanmean(g[yr==Y])),1) for Y in sorted(set(yr))})
print('  次日开盘卖，逐年：'+' '.join(f"{Y}:{np.nanmean(y[yr==Y]):+.1f}" for Y in sorted(set(yr))))
for f,nm in (('intra','今天开盘到收盘'),('day','今天涨跌'),('last30','尾盘30分钟涨跌'),('loc','收盘在当天区间位置'),('vr','今天量比'),('gap','今天高低开')):
    q=dq(Z[f]); print(f'\n次日开盘卖，按{nm}分十组：')
    for i in (0,1,5,8,9): show(f'第{i}组',y,q==i)
print('\n按大盘今天尾盘30分钟：')
m=Z['mlast30']
for lo,hi,lab in ((-1,-0.005,'大盘尾盘跌>0.5%'),(-0.005,0,'跌0-0.5%'),(0,0.005,'涨0-0.5%'),(0.005,1,'涨>0.5%')): show(lab,y,(m>=lo)&(m<hi))

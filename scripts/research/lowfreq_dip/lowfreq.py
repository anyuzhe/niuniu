"""Low-frequency dip-buying (V1 / R2 rules) with real costs, three periods. Research only.
Signal on close of t (qfq). Buy at open of t+1 (+1 tick), sell at close of t+H (-1 tick), fees 7.2bp round trip.
Universe: not ST, tradable, listed>=80 days, 20d avg amount >= AMT_MIN. Benchmark: same-window equal-weight of the universe (gross)."""
import numpy as np, sys
P=np.load('panel.npz'); dates=P['dates']; codes=P['codes']
O,Hh,L,C,F=[P[k].astype(np.float64) for k in 'ohlcf']; V=P['v'].astype(np.float64); A=P['a'].astype(np.float64); ST=P['st']; TS=P['ts']
nd,nc=C.shape; FEE=7.2e-4; AMT_MIN=float(sys.argv[1]) if len(sys.argv)>1 else 5e7
fin=np.isfinite(C)&np.isfinite(O)&(TS==1)&(V>0)
R=C/F; Ro=O/F  # raw prices for tick
def shift(a,k):
    o=np.full_like(a,np.nan); o[k:]=a[:-k] if k>0 else a; return o
def roll(a,n,f='sum'):
    z=np.where(np.isfinite(a),a,0.0); cnt=np.isfinite(a).astype(float)
    cs=np.vstack([np.zeros((1,nc)),np.cumsum(z,0)]); cc=np.vstack([np.zeros((1,nc)),np.cumsum(cnt,0)])
    s=np.full((nd,nc),np.nan); c=np.full((nd,nc),0.0)
    s[n-1:]=cs[n:]-cs[:-n]; c[n-1:]=cc[n:]-cc[:-n]; s[c<n]=np.nan; return s
ret1=C/shift(C,1)-1
mom20=C/shift(C,20)-1
step=np.abs(C-shift(C,1)); eff20=(C-shift(C,20))/roll(step,20)
s1=roll(ret1,20); s2=roll(ret1**2,20); vol20=np.sqrt(np.maximum(s2-s1*s1/20,0)/19)
rng=Hh-L; cloc=np.where(rng>1e-9,(C-L)/np.where(rng>1e-9,rng,1),0.5)
amt20=roll(A,20)/20; ret5=C/shift(C,5)-1
listed=np.cumsum(np.isfinite(C),0)>=80
uni=fin&(~ST)&listed&(amt20>=AMT_MIN)
lim=np.where(np.char.startswith(codes,'sz.30')|np.char.startswith(codes,'sh.688'),0.2,0.1)[None,:].repeat(nd,0)
early=(dates<'2020-08-24')[:,None]&np.char.startswith(codes,'sz.30')[None,:]; lim=np.where(early,0.1,lim)
limup_open=(O/shift(C,1)-1)>=lim-0.0025
limdn_close=ret1<=-lim+0.0025
base=(mom20<-0.10)&(eff20<0)
rules={'V1基准(20日跌>10%&效率<0)':base,
 'V1候选(+效率>-0.5)':base&(eff20>-0.5),
 'R2收盘位置(<0.3)':base&(cloc<0.3),
 'R2低波动(<3%)':base&(vol20<0.03),
 '参照:20日跌>10%':(mom20<-0.10),
 '参照:5日跌幅最大10%(横截面)':None}
# cross-sectional bottom decile of ret5 within universe
r5=np.where(uni,ret5,np.nan); q10=np.nanpercentile(r5,10,axis=1)[:,None]
rules['参照:5日跌幅最大10%(横截面)']=(r5<=q10)
per={'2020-22':('2020-01-01','2022-12-31'),'2023-24':('2023-01-01','2024-12-31'),'2025-26':('2025-01-01','2026-12-31')}
def run(H):
    # entry at t+1 open, exit at first good day >= t+H close
    T=np.arange(nd)
    ent=np.full(nd,-1); ent[:-1]=T[1:]
    ex=T+H; okx=ex<nd
    e_idx=np.minimum(ex,nd-1)
    buy_ok=np.zeros((nd,nc),bool); buy_ok[:-1]=fin[1:]&~limup_open[1:]
    # exit day resolution (up to 3 delays if suspended / limit-down close)
    ei=np.tile(e_idx[:,None],(1,nc)); jj=np.arange(nc)[None,:]
    for _ in range(3):
        bad=~(fin[np.minimum(ei,nd-1),jj])|limdn_close[np.minimum(ei,nd-1),jj]
        ei=np.where(bad&(ei<nd-1),ei+1,ei)
    exC=C[np.minimum(ei,nd-1),jj]; exR=R[np.minimum(ei,nd-1),jj]
    enO=np.full((nd,nc),np.nan); enO[:-1]=O[1:]; enR=np.full((nd,nc),np.nan); enR[:-1]=Ro[1:]
    valid=uni&buy_ok&okx[:,None]&np.isfinite(exC)&np.isfinite(enO)
    gross=exC/enO-1
    net=(exC*(1-0.01/exR))/(enO*(1+0.01/enR))-1-FEE
    return valid,gross,net
def cl_t(x,grp):
    u,inv=np.unique(grp,return_inverse=True); m=x.mean(); s=np.bincount(inv,x-m); return m/(np.sqrt((s**2).sum())/len(x)+1e-18)
mon=np.array([d[:7] for d in dates])
print(f'AMT_MIN={AMT_MIN:.0e}  universe/day mean {uni.sum(1)[100:].mean():.0f}  date range {dates[0]}..{dates[-1]}')
for H in (3,5,10):
    valid,gross,net=run(H)
    bench_g=np.where(valid,gross,np.nan); bm=np.nanmean(bench_g,1)  # per-signal-date universe avg gross
    print(f'\n===== 持有 {H} 天（次日开盘买、第{H}天收盘卖；扣7.2bp+每边1个价位）=====')
    for name,rm in rules.items():
        m=valid&rm
        line=[]
        for pn,(a,b) in per.items():
            dm=(dates>=a)&(dates<=b)
            mm=m&dm[:,None]
            if mm.sum()<30: line.append(f'{pn}: 样本不足'); continue
            di,ci=np.nonzero(mm); x=net[di,ci]; xe=x-bm[di]; g=gross[di,ci]
            grp=mon[di]; w=x>0; pay=x[w].mean()/-x[~w].mean() if (~w).any() and w.any() else np.nan
            line.append(f'{pn}: {len(x):6d}笔/{len(np.unique(di)):3d}天 净{x.mean()*1e4:+6.0f}bp(t{cl_t(x,grp):+.1f}) 超额{xe.mean()*1e4:+6.0f}(t{cl_t(xe,grp):+.1f}) 胜率{w.mean()*100:.0f}% 赔率{pay:.2f}')
        print(f'{name}\n    '+'\n    '.join(line))
    # also universe average itself, net of same cost, for reference
    line=[]
    for pn,(a,b) in per.items():
        dm=(dates>=a)&(dates<=b); mm=valid&dm[:,None]; di,ci=np.nonzero(mm)
        line.append(f'{pn}: 全市场平均毛{gross[di,ci].mean()*1e4:+.0f}bp 扣成本后{net[di,ci].mean()*1e4:+.0f}bp')
    print('  全市场随机持有 '+' | '.join(line))

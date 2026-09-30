"""Factor screening on dip candidates: daily cross-sectional rank IC vs the 20-day net label, month-clustered t.
Selection uses 2020-22 only; 2023-24 and 2025-26 are out of sample."""
import numpy as np, warnings; warnings.filterwarnings('ignore')
Z=np.load('dipfeat.npz'); dates=Z['dates']; di=Z['date_idx']; y=Z['y']
names=[k for k in Z.files if k not in ('dates','codes','date_idx','code_idx','y','exit_idx')]
cdates=dates[di]; yr=np.array([d[:4] for d in cdates]); mo=np.array([d[:7] for d in cdates])
def pct_rank(f,di):
    f=np.where(np.isfinite(f),f,np.nanmedian(f)); o=np.lexsort((f,di)); ds=di[o]
    st=np.r_[0,np.nonzero(np.diff(ds))[0]+1]; cnt=np.diff(np.r_[st,len(ds)])
    r=np.arange(len(ds))-np.repeat(st,cnt); out=np.empty(len(f)); out[o]=(r+0.5)/np.repeat(cnt,cnt); return out
py=pct_rank(y,di)
nday=np.bincount(di,minlength=di.max()+1)
def daily_ic(px):
    n=np.maximum(nday,1); sx=np.bincount(di,px,minlength=len(n)); sy=np.bincount(di,py,minlength=len(n))
    sxy=np.bincount(di,px*py,minlength=len(n)); sxx=np.bincount(di,px*px,minlength=len(n)); syy=np.bincount(di,py*py,minlength=len(n))
    cov=sxy/n-sx*sy/n**2; vx=sxx/n-(sx/n)**2; vy=syy/n-(sy/n)**2
    ic=cov/np.sqrt(np.maximum(vx*vy,1e-12)); ic[nday<30]=np.nan; return ic
dd_all=dates[np.arange(len(nday))]; dyr=np.array([d[:4] for d in dd_all]); dmo=np.array([d[:7] for d in dd_all])
PER={'2020-22':('2020','2021','2022'),'2023-24':('2023','2024'),'2025-26':('2025','2026')}
def mstat(ic,ys):
    m=np.isin(dyr,ys)&np.isfinite(ic)
    if m.sum()<20: return np.nan,np.nan
    um=np.unique(dmo[m]); mm=np.array([ic[m&(dmo==u)].mean() for u in um]); return ic[m].mean(),mm.mean()/(mm.std(ddof=1)/np.sqrt(len(mm))+1e-12)
def qspread(px,ys):
    m=np.isin(yr,ys); q=np.minimum((px*5).astype(int),4)
    # label market-adjusted by day mean
    dm=np.bincount(di,y,minlength=len(nday))/np.maximum(nday,1); ya=y-dm[di]
    return (ya[m&(q==4)].mean()-ya[m&(q==0)].mean())*1e4

nd_=len(nday)
def daily_spread(px):
    q=np.minimum((px*5).astype(int),4); out=np.full(nd_,np.nan)
    s4=np.bincount(di[q==4],y[q==4],minlength=nd_); n4=np.bincount(di[q==4],minlength=nd_)
    s0=np.bincount(di[q==0],y[q==0],minlength=nd_); n0=np.bincount(di[q==0],minlength=nd_)
    ok=(n4>=5)&(n0>=5); out[ok]=s4[ok]/n4[ok]-s0[ok]/n0[ok]; return out
def sstat(sp,ys):
    m=np.isin(dyr,ys)&np.isfinite(sp)
    if m.sum()<20: return np.nan,np.nan
    um=np.unique(dmo[m]); mm=np.array([sp[m&(dmo==u)].mean() for u in um]); return mm.mean()*1e4,mm.mean()/(mm.std(ddof=1)/np.sqrt(len(mm))+1e-12)
res=[]; PX={}
for nme in names:
    px=pct_rank(Z[nme],di); PX[nme]=px; ic=daily_ic(px); sp=daily_spread(px)
    row=[nme]
    for ys in PER.values(): row+= [mstat(ic,ys)[0], mstat(ic,ys)[1], sstat(sp,ys)[0], sstat(sp,ys)[1]]
    row.append([sstat(sp,(Y,))[0] for Y in ('2020','2021','2022')]); res.append(row)
print(f'候选 {len(y):,} 个股票日/{len(np.unique(di))} 天；标签=次日开盘买、约20个交易日后卖的净收益；分位差=因子最高20%减最低20%的平均净收益(bp)，月度聚类t\n')
print(f'{"因子":14s} | {"2020-22 IC / 分位差bp(t)":>26s} | {"2023-24":>24s} | {"2025-26":>24s}')
res.sort(key=lambda r:-abs(r[4]) if np.isfinite(r[4]) else 0)
for r in res:
    print(f'{r[0]:14s} | {r[1]:+.3f} / {r[3]:+5.0f}({r[4]:+4.1f}) | {r[5]:+.3f} / {r[7]:+5.0f}({r[8]:+4.1f}) | {r[9]:+.3f} / {r[11]:+5.0f}({r[12]:+4.1f})')
sel=[]
for r in res:
    t=r[4]; ic_t=r[2]
    if np.isfinite(t) and abs(t)>=2.0 and np.sign(t)==np.sign(ic_t) and sum(np.sign(v)==np.sign(t) for v in r[13])>=2: sel.append((r[0],np.sign(t)))
print('\n入选（只看2020-22：分位差|t|≥2 且与IC同号、三年里至少两年同号）:',[(n,'+' if s>0 else '-') for n,s in sel])
np.savez('dipsel.npz',names=np.array([n for n,_ in sel]),signs=np.array([s for _,s in sel]))
if sel:
    score=np.mean([PX[n] if s>0 else 1-PX[n] for n,s in sel],axis=0); np.save('dipscore.npy',score)
    ps=pct_rank(score,di); ic=daily_ic(ps); sp=daily_spread(ps)
    print('合成分数（入选因子排名平均）：')
    for k,ys in PER.items():
        m,t=mstat(ic,ys); a,b=sstat(sp,ys); print(f'  {k}: IC {m:+.3f}(t{t:+.1f})  最高20%-最低20% {a:+.0f}bp(t{b:+.1f})')

"""Does the panic-day (market oversold z gate) have a cycle? Research only."""
import sys, numpy as np
exec(open('stockport.py').read().split("print('格式")[0])
rg=np.random.default_rng(11)
print('dates',dates[0],dates[-1],nd)
yr=np.array([int(d[:4]) for d in dates]); mo=np.array([int(d[5:7]) for d in dates])
ok=np.isfinite(zv)
# ---- 1. panic episodes (gate days merged when gap < 20 trading days)
g=np.nonzero((zv<=-1.5)&ok)[0]
eps=[]; 
for t in g:
    if eps and t-eps[-1][-1]<20: eps[-1].append(t)
    else: eps.append([t])
st=np.array([e[0] for e in eps]); print('\n[1] 恐慌日(z<=-1.5)',len(g),'天，合并成',len(eps),'段（间隔<20交易日并为一段）')
for e in eps: print(' ',dates[e[0]],'~',dates[e[-1]],f'{len(e):3d}天  最深z{zv[e].min():+.2f}  E6总数{int(e6[e].sum(1).max())}')
gap=np.diff(st)
print('段间隔(交易日)中位',int(np.median(gap)),'均',int(gap.mean()),'最短',gap.min(),'最长',gap.max(),f'变异系数CV={gap.std()/gap.mean():.2f}')
# Poisson benchmark: random start days among valid days with same count, CV distribution
valid_days=np.nonzero(ok)[0]; cvs=[]
for _ in range(5000):
    s=np.sort(rg.choice(valid_days,len(st),replace=False)); d=np.diff(s); cvs.append(d.std()/d.mean())
cvs=np.array(cvs); print(f'随机起点的CV中位{np.median(cvs):.2f}（5%-95% {np.percentile(cvs,5):.2f}~{np.percentile(cvs,95):.2f}）；周期性应明显低于随机，本数据CV落在随机分布的分位 {(cvs<gap.std()/gap.mean()).mean()*100:.0f}%')
print('各年起始段数：',{int(y):int((yr[st]==y).sum()) for y in range(2005,2027) if (yr[st]==y).sum()})
# ---- 2. month-of-year
print('\n[2] 月份季节性')
cnt=np.array([(mo[st]==m).sum() for m in range(1,13)]); print('各月起始段数 1-12月：',cnt.tolist())
exp=len(st)/12; chi=((cnt-exp)**2/exp).sum()
chis=[]
for _ in range(5000):
    s=rg.choice(valid_days,len(st),replace=False); c=np.bincount(mo[s],minlength=13)[1:]; e_=len(st)*np.bincount(mo[valid_days],minlength=13)[1:]/len(valid_days); chis.append(((c-e_)**2/e_).sum())
e0=len(st)*np.bincount(mo[valid_days],minlength=13)[1:]/len(valid_days); chi=((cnt-e0)**2/e0).sum()
print(f'卡方={chi:.1f}，随机起点下超过它的概率 p={np.mean(np.array(chis)>=chi):.2f}')
mrm=[mr[(mo==m)&np.isfinite(mr)].mean()*245 for m in range(1,13)]
print('等权大盘各月平均日收益(年化%)：',[f'{x*100:+.0f}' for x in mrm])
# ---- 3. 信号日后20日净收益(E6池平均) by month of signal day & episode
pool_net=np.array([np.nanmean(net[t][e6[t]]) if e6[t].any() else np.nan for t in range(nd)])
sig=(zv<=-1.5)&np.isfinite(pool_net)
print('\n[3] 信号日(闸门日且当天有E6)的E6池20日净收益，按信号月份(以段计)')
epi_net=[]; 
for e in eps:
    v=pool_net[[t for t in e if np.isfinite(pool_net[t])]]
    if len(v): epi_net.append((dates[e[0]],mo[e[0]],np.nanmean(v)))
for m in range(1,13):
    x=[v for d,mm,v in epi_net if mm==m]
    print(f'  {m:2d}月 段数{len(x):2d} 平均{np.mean(x)*100:+5.1f}%' if x else f'  {m:2d}月 段数 0')
a=np.array([v for _,_,v in epi_net]); print('  全部段平均 %+.1f%% 胜率 %.0f%%'%(a.mean()*100,(a>0).mean()*100))
q=lambda m:(m-1)//3
for qq,nm in enumerate(['1-3月','4-6月','7-9月','10-12月']):
    x=[v for d,mm,v in epi_net if q(mm)==qq]; print('  ',nm,len(x),'段 平均%+.1f%%'%(np.mean(x)*100))
# ---- 4. Autocorrelation of 20d market returns (non-overlapping blocks) and z
print('\n[4] 自相关')
blk=bench[::20]; r20=blk[1:]/blk[:-1]-1
ac=[np.corrcoef(r20[:-k],r20[k:])[0,1] for k in range(1,25)]
print('20日块收益自相关 lag1..24(月)：',' '.join(f'{x:+.2f}' for x in ac)); print('  |95%置信带| ≈',round(1.96/np.sqrt(len(r20)),2))
zz=np.where(ok,zv,0.0)
acz=[np.corrcoef(zz[:-k],zz[k:])[0,1] for k in (1,5,10,20,40,60,120,250,500,750,1000)]
print('z的自相关 lag(1,5,10,20,40,60,120,250,500,750,1000日)：',' '.join(f'{x:+.2f}' for x in acz))
# ---- 5. periodogram of monthly (20d-block) log market return and of volatility regime
def peaks(x,label,nsur=2000):
    x=x-x.mean(); n=len(x); F=np.abs(np.fft.rfft(x))**2; fr=np.fft.rfftfreq(n,1.0)
    F[0]=0; idx=np.argsort(F)[::-1][:5]
    mx=[]
    for _ in range(nsur):
        # AR(1)-matched surrogate via phase randomization
        ph=np.exp(2j*np.pi*rg.random(len(F))); ph[0]=1
        y=np.fft.irfft(np.fft.rfft(x)*ph,n); Fy=np.abs(np.fft.rfft(y-y.mean()))**2; Fy[0]=0; mx.append(Fy.max())
    # phase-randomised surrogates keep spectrum => not valid for peak test; use AR(1) fit instead
    rho=np.corrcoef(x[:-1],x[1:])[0,1]; sd=x.std(); mx=[]
    for _ in range(nsur):
        e=rg.normal(0,sd*np.sqrt(1-rho**2),n); y=np.zeros(n)
        for i in range(1,n): y[i]=rho*y[i-1]+e[i]
        Fy=np.abs(np.fft.rfft(y-y.mean()))**2; Fy[0]=0
        mx.append(Fy.max()/Fy[1:].mean())
    stat=F.max()/F[1:].mean()
    print(f'  {label}: n={n} 最高峰周期 {1/fr[idx[0]]:.1f} 个单位，其余前4峰周期 '+', '.join(f'{1/fr[i]:.1f}' for i in idx[1:])+f'；峰值/均值={stat:.1f}，AR(1)噪声下同统计的95分位={np.percentile(mx,95):.1f}，p≈{np.mean(np.array(mx)>=stat):.2f}')
print('\n[5] 周期图（谱峰）检验：是否有显著高于“带记忆的随机噪声”的周期')
lr=np.log(1+r20); peaks(lr,'月度(20日块)大盘对数收益(单位=月)')
vol=np.array([np.nanstd(mr[i:i+20]) for i in range(0,nd-20,20)]); peaks(np.log(vol+1e-9),'月度已实现波动率(单位=月)')
zm=np.array([np.nanmean(zv[i:i+20]) if np.isfinite(zv[i:i+20]).any() else 0 for i in range(0,nd-20,20)]); peaks(zm,'月度平均z(单位=月)')
# ---- 6. half-year / annual panic count series & cross-year pattern
print('\n[6] 每年闸门日数')
cy={int(y):int(((yr==y)&(zv<=-1.5)).sum()) for y in range(2005,2027) if ok[yr==y].any()}
print(cy)
v=np.array(list(cy.values()),float); print('年度闸门日数自相关lag1..4：',[round(np.corrcoef(v[:-k],v[k:])[0,1],2) for k in range(1,5)])

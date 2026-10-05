"""Industry-level panic (SW L1 EW index z<=-1.5 while the market is not in panic) + E6 inside the industry; also a faster 10-day market panic. Research only."""
import sys; sys.argv=['x','core']
exec(open('allyears.py').read().split("if GROUP=='core':")[0])
import pandas as pd, numpy as np
D=pd.read_parquet(f"{__import__('os').path.expanduser('~')}/mnt/lake/bronze/provider=swsresearch/industry_classification_history/2026-09-23.parquet")
D=D.sort_values(['code','start_date']).groupby('code').tail(1)
l1=dict(zip(D['code'],D['l1_code'])); sym=np.array([x.split('.')[-1] for x in codes])
ind=np.array([l1.get(s,'') for s in sym]); u=sorted(set(ind)-{''})
print('stocks mapped',(ind!='').sum(),'of',nc,'industries',len(u),flush=True)
ret1=np.full((nd,nc),np.nan,np.float32); ret1[1:]=c[1:]/c[:-1]-1
uni_prev=np.vstack([np.zeros((1,nc),bool),uni[:-1]])
zind=np.full((nd,nc),np.nan,np.float32); cnt={}
for g in u:
    idx=np.nonzero(ind==g)[0]
    R=np.where(uni_prev[:,idx]&np.isfinite(ret1[:,idx]),ret1[:,idx],np.nan)
    n=np.isfinite(R).sum(1); r=np.where(n>=8,np.nanmean(R,1),np.nan)
    s=pd.Series(r); lg=np.log1p(s); c20=np.exp(lg.rolling(20,min_periods=20).sum())-1; sd=s.rolling(60,min_periods=40).std()
    z=(c20/(sd*np.sqrt(20))).values; cnt[g]=(len(idx),int(np.nanmedian(n)))
    zind[:,idx]=z[:,None]
print({g:cnt[g] for g in u},flush=True)
nonp=zv>-1.5; nonp=np.where(np.isfinite(zv),nonp,False)
pan=zv<=-1.5
def mk(th,pool): return pool&(zind<=th)&nonp[:,None]
IP15=mk(-1.5,e6); IP20=mk(-2.0,e6)
ndays=lambda m:int((m.any(1)).sum())
print('行业恐慌(非大盘恐慌日)有E6的天数: z_g<=-1.5:',ndays(IP15),' <=-2:',ndays(IP20),' 平均每天E6只数',round(IP15.sum(1)[IP15.any(1)].mean(),1),flush=True)
# event-level: mean net of E6 in industry panic vs E6 in the same industries on calm days vs all-E6 non-panic
def evl(m,label):
    x=net[m&np.isfinite(net)]; print(f'  {label:44s} 笔{len(x):6d} 均{x.mean()*1e4:+.0f}bp 胜率{(x>0).mean()*100:.0f}%',flush=True)
evl(IP15,'行业恐慌z_g<=-1.5, E6'); evl(IP20,'行业恐慌z_g<=-2.0, E6')
evl(e6&(zind>-0.5)&(zind<=0.5)&nonp[:,None],'同行业平静日(-0.5<z_g<=0.5), E6'); evl(e6&(zind>-1.5)&(zind<=-0.5)&nonp[:,None],'行业偏弱(-1.5<z_g<=-0.5), E6')
evl(e6&pan[:,None],'大盘恐慌日 E6（现策略）')
def run(name,gate,pool,L=1.0,**kw):
    eq,ex_,tr,nl,mr_=sim(gate=gate,pool=pool,L=L,**kw)
    s=stats(eq,ex_,'2008-01-01','2026-12-31'); print(f'{name:46s} 年化{s[0]*100:+5.1f}% 夏普{s[1]:+.2f} 回撤{s[2]*100:4.0f}% 仓位{s[3]*100:3.0f}% 笔{len(tr)} 笔均{tr[:,0].mean()*1e4 if len(tr) else 0:+.0f}bp',flush=True); return eq
allg=np.isfinite(zv)
P=run('现策略 大盘恐慌 E6 2x',pan,e6,L=2.0)
I1=run('行业恐慌(<=-1.5) E6 1x',allg,IP15); I2=run('行业恐慌(<=-1.5) E6 2x',allg,IP15,L=2.0)
I3=run('行业恐慌(<=-2.0) E6 1x',allg,IP20); I3b=run('行业恐慌(<=-2.0) E6 2x',allg,IP20,L=2.0)
poolw=valid&(zind<=-1.5)&nonp[:,None]; run('行业恐慌(<=-1.5) 候选全部,按跌幅排序 1x',allg,poolw)
ctrl=e6&(zind>-0.5)&(zind<=0.5)&nonp[:,None]; run('对照:行业平静日 E6 1x',allg,ctrl)
# faster market panic: 10-day z
b=pd.Series(mr.astype(np.float64)); c10=np.exp(np.log1p(b).rolling(10,min_periods=10).sum())-1; sd60=b.rolling(60,min_periods=40).std(); z10=(c10/(sd60*np.sqrt(10))).values
print('z10<=-1.5 天数',int((z10<=-1.5).sum()),' z20<=-1.5 天数',int(pan.sum()),' 并集',int(((z10<=-1.5)|pan).sum()),flush=True)
F10=(z10<=-1.5)&~pan
evl(e6&F10[:,None],'仅10日恐慌(20日未恐慌) E6')
run('10日恐慌∪20日恐慌 E6 2x',(z10<=-1.5)|pan,e6,L=2.0); run('仅10日恐慌(20日未恐慌) E6 1x',F10,e6)
def dr(eq):
    r=np.full(nd,np.nan); r[1:]=eq[1:]/eq[:-1]-1; return r
yr=np.array([int(d[:4]) for d in dates])
def cs(r,label):
    m=np.isfinite(r); x=r[m]; cum=np.cumprod(1+x); h=[]
    for a,b_ in ((2008,2016),(2017,2026)):
        k=(yr>=a)&(yr<=b_)&m; y=r[k]; c2=np.cumprod(1+y); h.append(f'{(c2[-1]**(245/len(y))-1)*100:+.1f}%/{y.mean()/y.std()*np.sqrt(245):.2f}')
    print(f'{label:46s} 年化{(cum[-1]**(245/len(x))-1)*100:+5.1f}% 夏普{x.mean()/x.std()*np.sqrt(245):.2f} 回撤{(cum/np.maximum.accumulate(cum)-1).min()*100:4.0f}% | 前半{h[0]} 后半{h[1]}',flush=True)
print('合并（两个独立子账户，按固定资金比例，日收益加权）')
rP=dr(P)
for nm,I in (('行业恐慌1x',I1),('行业恐慌2x',I2),('行业<=-2 2x',I3b)):
    rI=dr(I); m=np.isfinite(rP)&np.isfinite(rI); print('  相关',nm,round(np.corrcoef(rP[m],rI[m])[0,1],2))
    for a in (0.75,0.5): cs(np.where(m,a*rP+(1-a)*rI,np.nan),f'  大盘恐慌2x {a:.2f} + {nm} {1-a:.2f}')
np.savez('ind1_eq.npz',P=P,I1=I1,I2=I2,I3b=I3b)

"""Panic regime: dip candidates vs the average stock over the same window, and factor ordering inside the regime."""
import os, sys, numpy as np, warnings; warnings.filterwarnings('ignore')
sys.argv=['x']
exec(open('lowfreq.py').read().split("mon=np.array")[0])
T=np.arange(nd); jj=np.arange(nc)[None,:]
def run2(H):
    e_idx=np.minimum(T+H,nd-1); okx=(T+H)<nd
    buy_ok=np.zeros((nd,nc),bool); buy_ok[:-1]=fin[1:]&~limup_open[1:]
    ei=np.tile(e_idx[:,None],(1,nc))
    for _ in range(3):
        bad=~(fin[np.minimum(ei,nd-1),jj])|limdn_close[np.minimum(ei,nd-1),jj]; ei=np.where(bad&(ei<nd-1),ei+1,ei)
    e2=np.minimum(ei,nd-1); exC=C[e2,jj]; exR=R[e2,jj]
    enO=np.full((nd,nc),np.nan); enO[:-1]=O[1:]; enR=np.full((nd,nc),np.nan); enR[:-1]=Ro[1:]
    valid=uni&buy_ok&okx[:,None]&np.isfinite(exC)&np.isfinite(enO)
    return valid,(exC*(1-0.01/exR))/(enO*(1+0.01/enR))-1-FEE
valid,net=run2(20)
univ_mean=np.nanmean(np.where(valid,net,np.nan),1)                       # random stock, same window, same costs
mret=np.nanmean(np.where(uni,ret1,np.nan),1); mret[~np.isfinite(mret)]=0
idx=np.cumprod(1+mret); mk20=idx/np.r_[np.full(20,np.nan),idx[:-20]]-1
mo=np.array([d[:7] for d in dates]); yr=np.array([d[:4] for d in dates])
train=(dates>='2020-01-01')&(dates<='2022-12-31')
cut=np.nanpercentile(mk20[train&np.isfinite(mk20)],20)
print(f'恐慌日定义：全市场（等权）20日涨跌 ≤ {cut*100:.1f}%（2020–22年的最低20%分位，固定数字用于所有年份）')
reg=(mk20<=cut)
def tstat(x,m):
    um=np.unique(mo[m]); mm=np.array([x[m&(mo==u)].mean() for u in um]); return mm.mean()*1e4, mm.mean()/(mm.std(ddof=1)/np.sqrt(len(mm))+1e-12), len(um)
per={'2020-22':('2020','2021','2022'),'2023-24':('2023','2024'),'2025-26':('2025','2026')}
# episodes: consecutive regime days
def episodes(m):
    d=np.nonzero(m)[0]; return 1+int((np.diff(d)>5).sum()) if len(d) else 0
cand=valid&base&(np.cumsum(np.isfinite(C),0)>=250)&(R>=3.0)
dm_c=np.nanmean(np.where(cand,net,np.nan),1); nc_=cand.sum(1)
print('\n              天数  独立行情段  随机股票20日净(bp) | 抄底候选净(bp)   超额(bp)  t(月聚类) | 平均每天候选数')
for pn,ys in per.items():
    m=reg&np.isin(yr,ys)&np.isfinite(dm_c)&(nc_>=20)
    a,ta,_=tstat(dm_c,m); b,tb,_=tstat(univ_mean,m); e,te,_=tstat(dm_c-univ_mean,m)
    print(f'{pn}:  {m.sum():4d}  {episodes(m):3d}       {b:+6.0f}({tb:+.1f})     | {a:+6.0f}({ta:+.1f})    {e:+5.0f}  ({te:+.1f})   | {nc_[m].mean():.0f}')
m=reg&np.isfinite(dm_c)&(nc_>=20); a,ta,_=tstat(dm_c,m); b,tb,_=tstat(univ_mean,m); e,te,_=tstat(dm_c-univ_mean,m)
print(f'全期:      {m.sum():4d}  {episodes(m):3d}       {b:+6.0f}({tb:+.1f})     | {a:+6.0f}({ta:+.1f})    {e:+5.0f}  ({te:+.1f})')
print('\n非恐慌日：')
for pn,ys in per.items():
    m=(~reg)&np.isfinite(mk20)&np.isin(yr,ys)&np.isfinite(dm_c)&(nc_>=20); a,ta,_=tstat(dm_c,m); b,tb,_=tstat(univ_mean,m); e,te,_=tstat(dm_c-univ_mean,m)
    print(f'{pn}:  {m.sum():4d}      随机股票 {b:+5.0f}({tb:+.1f}) | 抄底候选 {a:+5.0f}({ta:+.1f})  超额 {e:+5.0f}({te:+.1f})')
# episodes list
d=np.nonzero(reg)[0]; starts=[d[0]]+[d[i] for i in range(1,len(d)) if d[i]-d[i-1]>5]
print('\n恐慌段起始日:',' '.join(dates[s] for s in starts))
# factor ordering inside the regime
Z=np.load('dipfeat.npz'); di=Z['date_idx']; y=Z['y']
names=[k for k in Z.files if k not in ('dates','codes','date_idx','code_idx','y','exit_idx')]
inreg=reg[di]
def pct_rank(f,di):
    f=np.where(np.isfinite(f),f,np.nanmedian(f)); o=np.lexsort((f,di)); ds=di[o]
    st=np.r_[0,np.nonzero(np.diff(ds))[0]+1]; cnt=np.diff(np.r_[st,len(ds)])
    r=np.arange(len(ds))-np.repeat(st,cnt); out=np.empty(len(f)); out[o]=(r+0.5)/np.repeat(cnt,cnt); return out
ymk=y-univ_mean[di]      # excess over the average stock
yw=np.clip(ymk,-0.3,0.6)
print(f'\n恐慌日内的因子排序（候选 {inreg.sum():,} 个股票日）：最高20% 减 最低20% 的超额净收益 bp（月聚类t）——按2020-22选，之后样本外')
rows=[]
cy=np.array([dates[i][:4] for i in di]); cmo=np.array([dates[i][:7] for i in di])
for nme in names:
    px=pct_rank(Z[nme],di); q=np.minimum((px*5).astype(int),4); out=[]
    for pn,ys in per.items():
        m=inreg&np.isin(cy,ys); hi=m&(q==4); lo=m&(q==0)
        if hi.sum()<200 or lo.sum()<200: out+= [np.nan,np.nan]; continue
        um=np.unique(cmo[m]); dd=[]
        for u in um:
            mh=hi&(cmo==u); ml=lo&(cmo==u)
            if mh.sum()>=10 and ml.sum()>=10: dd.append(ymk[mh].mean()-ymk[ml].mean())
        dd=np.array(dd); out+=[dd.mean()*1e4, dd.mean()/(dd.std(ddof=1)/np.sqrt(len(dd))+1e-12) if len(dd)>2 else np.nan]
    rows.append((nme,out))
rows.sort(key=lambda r:-abs(r[1][1]) if np.isfinite(r[1][1]) else 0)
print(f'{"因子":14s} | {"2020-22":>16s} | {"2023-24":>16s} | {"2025-26":>16s}')
for nme,o in rows: print(f'{nme:14s} | {o[0]:+6.0f}({o[1]:+4.1f}) | {o[2]:+6.0f}({o[3]:+4.1f}) | {o[4]:+6.0f}({o[5]:+4.1f})')

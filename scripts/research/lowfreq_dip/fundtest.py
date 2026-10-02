"""Fundamental filters on the panic-day dip-buy (z<=-1.5, E6): coverage, factor IC, filter effect, portfolio. Research only."""
import numpy as np, pandas as pd, time, sys; T0=time.time()
exec(open('lev.py').read().split("print('格式：年化")[0])
V=np.load('fund_val.npz'); F=np.load('fund_fin.npz')
dord=(pd.to_datetime(pd.Series(dates)).values.astype('datetime64[D]').astype(int))
raw=(c/f).astype(np.float32)
pe=V['pe']; pb=V['pb']; ps=V['ps']
loss=np.isfinite(pe)&(pe<=0)
roe_p=np.where(pe>0,pb/np.where(pe>0,pe,np.nan),np.nan).astype(np.float32)
mcap=(raw*F['sh_a']/1e8).astype(np.float32)             # 亿元
fc=F['fc_cat']; fcn=F['fc_notice']
fcneg=np.zeros((nd,nc),bool); fcpos=np.zeros((nd,nc),bool)
ii,jj=np.nonzero(np.isfinite(fcn)); age=dord[ii]-fcn[ii,jj]; cat=fc[ii,jj]
okk=(age<=180)&(age>=0)
fcneg[ii[okk&(cat==-1)],jj[okk&(cat==-1)]]=True; fcpos[ii[okk&(cat==1)],jj[okk&(cat==1)]]=True
del ii,jj,age,cat,okk

npy=F['np_yoy']; rvy=F['rev_yoy']; debt=F['debt']; cur=F['cur']; ocf=F['ocf_cum']; pl=F['pledge']
print('built features',round(time.time()-T0),flush=True)
sig=zv<=-1.5; tmax=nd-H-4
Dsel=np.nonzero(sig&(dates>='2008-01-01')&(np.arange(nd)<tmax)&(np.arange(nd)>260))[0]
# episodes
ep=np.zeros(len(Dsel),int); k=0
for i in range(1,len(Dsel)):
    if Dsel[i]-Dsel[i-1]>5: k+=1
    ep[i]=k
nE=k+1; edate=np.array([dates[Dsel[i]] for i in range(len(Dsel))])
ERA2={'2008-11':('2008','2011'),'2012-16':('2012','2016'),'2017-19':('2017','2019'),'2020-26':('2020','2026')}
# ---- coverage among candidates on gate days
def cov(mask_known,pool):
    out=[]
    for nm,(a,b) in ERA2.items():
        n=0;kn=0
        for i,t in enumerate(Dsel):
            if not (a<=dates[t][:4]<=b): continue
            cs=np.nonzero(pool[t])[0]; n+=len(cs); kn+=int(mask_known[t][cs].sum())
        out.append(f'{kn/max(n,1)*100:3.0f}%')
    return ' / '.join(out)
print('\n[0] 覆盖率：闸门日 E6 候选里该字段有值的比例（2008-11 / 2012-16 / 2017-19 / 2020-26）')
for nm,m in (('PE/PB',np.isfinite(pe)),('净利润同比',np.isfinite(npy)),('资产负债率',np.isfinite(debt)),('总股本(市值)',np.isfinite(mcap)),('业绩预告(180天内)',fcneg|fcpos),('质押比例',np.isfinite(pl))):
    print(f'  {nm:14s} E6候选 {cov(m,e6)}  | 全部候选 {cov(m,cand_all)}',flush=True)
# ---- factor IC (all valid candidates on gate days), episode-clustered
def rk(x): 
    o=np.argsort(np.argsort(x)); return o/(len(x)-1) if len(x)>1 else o*0.0
feats={'PE倒数(盈利收益率,仅PE>0)':np.where(pe>0,1/np.where(pe>0,pe,np.nan),np.nan),'PB(低好=负IC)':pb,'PS':ps,'ROE代理=PB/PE':roe_p,'净利润同比%':npy,'营收同比%':rvy,'资产负债率%':debt,'流动比率':cur,'经营现金流>0':(ocf>0).astype(np.float32)*np.where(np.isfinite(ocf),1,np.nan),'总市值(对数)':np.log(np.where(mcap>0,mcap,np.nan)),'质押比例%':pl,'亏损(PE<=0)':loss.astype(np.float32)*np.where(np.isfinite(pe),1,np.nan)}
print('\n[1] 因子 IC（闸门日、全部候选，与20日净收益的Spearman；按段平均 / t / 为正的段占比 / 样本含该字段的日均只数）')
for nm,X in feats.items():
    ic_by=[[] for _ in range(nE)]; cnt=[]
    for i,t in enumerate(Dsel):
        cs=np.nonzero(cand_all[t])[0]; x=X[t][cs]; y=net[t][cs]; m=np.isfinite(x)&np.isfinite(y)
        if m.sum()<30 or np.nanstd(x[m])==0: continue
        ic_by[ep[i]].append(np.corrcoef(rk(x[m]),rk(y[m]))[0,1]); cnt.append(m.sum())
    me=np.array([np.mean(v) for v in ic_by if v]); 
    if len(me)<3: print(f'  {nm:24s} 样本不足'); continue
    print(f'  {nm:24s} IC {me.mean():+.3f}  t={me.mean()/(me.std(ddof=1)/np.sqrt(len(me))):+.1f}  正段{(me>0).mean()*100:3.0f}%  段数{len(me)} 日均{np.mean(cnt):.0f}只',flush=True)
# ---- filter effect on E6 candidates (and all candidates)
def mkmask(cond): return cond
filters={}
filters['亏损(PE<=0)']=loss
filters['净利润同比<0']=np.isfinite(npy)&(npy<0)
filters['净利润同比<-30%']=np.isfinite(npy)&(npy<-30)
filters['营收同比<0']=np.isfinite(rvy)&(rvy<0)
filters['资产负债率>70%']=np.isfinite(debt)&(debt>70)
filters['流动比率<1']=np.isfinite(cur)&(cur<1)
filters['经营现金流<0']=np.isfinite(ocf)&(ocf<0)
filters['业绩预告为负(180天)']=fcneg
filters['质押>30%']=np.isfinite(pl)&(pl>30)
filters['质押>50%']=np.isfinite(pl)&(pl>50)
filters['ROE代理<3%(含亏损)']=(np.isfinite(pe)&(~(roe_p>=0.03)))
filters['PB>5']=np.isfinite(pb)&(pb>5)
filters['PE>80']=np.isfinite(pe)&(pe>80)
# size: bottom 30% / 50% of that day's candidates by market cap
sz30=np.zeros((nd,nc),bool); sz50=np.zeros((nd,nc),bool)
for t in Dsel:
    cs=np.nonzero(cand_all[t]&np.isfinite(mcap[t]))[0]
    if len(cs)>10:
        q30,q50=np.percentile(mcap[t][cs],[30,50]); sz30[t,cs]=mcap[t][cs]<=q30; sz50[t,cs]=mcap[t][cs]<=q50
filters['市值最小30%']=sz30; filters['市值最小50%']=sz50
filters['质量差(亏损|预告负|负债>70%|质押>50%)']=loss|fcneg|(np.isfinite(debt)&(debt>70))|(np.isfinite(pl)&(pl>50))
def eff(bad,pool,label):
    S=np.zeros((nE,4)); allk=[];allb=[]; per={nm:[[],[]] for nm in ERA2}
    for i,t in enumerate(Dsel):
        cs=np.nonzero(pool[t])[0]
        if not len(cs): continue
        b=bad[t][cs]; y=net[t][cs]; e=ep[i]
        S[e,0]+=y[~b].sum(); S[e,1]+=(~b).sum(); S[e,2]+=y[b].sum(); S[e,3]+=b.sum()
        allk.append(y[~b]); allb.append(y[b])
        for nm,(a,bb) in ERA2.items():
            if a<=dates[t][:4]<=bb: per[nm][0].append(y[~b]); per[nm][1].append(y[b])
    k=np.concatenate(allk) if allk else np.array([]); b_=np.concatenate(allb) if allb else np.array([])
    m=(S[:,1]>0)&(S[:,3]>0); d=S[m,0]/S[m,1]-S[m,2]/S[m,3]
    t_=d.mean()/(d.std(ddof=1)/np.sqrt(len(d))) if len(d)>2 else np.nan
    eras=[]
    for nm in ERA2:
        kk=np.concatenate(per[nm][0]) if per[nm][0] else np.array([]); bb=np.concatenate(per[nm][1]) if per[nm][1] else np.array([])
        eras.append(f'{(kk.mean()-bb.mean())*1e4:+4.0f}' if len(kk)>5 and len(bb)>5 else ' 无')
    print(f'  {label:30s} 剔除占{len(b_)/max(len(k)+len(b_),1)*100:3.0f}% | 保留均{k.mean()*1e4:+5.0f}bp 被剔均{b_.mean()*1e4:+5.0f}bp 差{(k.mean()-b_.mean())*1e4:+5.0f} t={t_:+.1f}({m.sum()}段) | 保留胜率{(k>0).mean()*100:.0f}% 被剔{(b_>0).mean()*100:.0f}% | ≤-20%: 保留{(k<=-0.2).mean()*100:.1f}% 被剔{(b_<=-0.2).mean()*100:.1f}% | 分期差 '+' / '.join(eras),flush=True)
print('\n[2] 过滤效果：E6 候选（闸门日），按被剔除组与保留组的20日净收益对比（差 = 保留 − 被剔；t 按段）')
for nm,bad in filters.items(): eff(bad,e6,nm)
print('\n[2b] 同样的过滤，用全部候选（样本更大）')
for nm,bad in filters.items(): eff(bad,cand_all,nm)
np.savez_compressed('fund_masks.npz',**{('f%d'%i):v for i,v in enumerate(filters.values())}); open('fund_masks.keys','w').write('\n'.join(filters.keys()))
print('done part1',round(time.time()-T0))

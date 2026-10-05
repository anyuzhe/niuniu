"""Mirror of E6 in greed: buy stocks above the Bollinger upper band, exit when close falls below the mid line (MA20). Event level. Research only."""
import numpy as np, pandas as pd, json, time, gc; T0=time.time()
P=np.load('panel_ext.npz'); dates=P['dates']; codes=P['codes']; nd=len(dates); nc=len(codes)
B=np.load('s6_base.npz'); valid=B['valid']; zv=B['zv']; fee_=B['fee']
c=P['c']; o=P['o']; f=P['f']; vv=P['v']
ma=np.full((nd,nc),np.nan,np.float32); sd=np.full((nd,nc),np.nan,np.float32); vr=np.full((nd,nc),np.nan,np.float32)
for j in range(0,nc,800):
    C=pd.DataFrame(c[:,j:j+800].astype(np.float64)); ma[:,j:j+800]=C.rolling(20,min_periods=20).mean().values; sd[:,j:j+800]=C.rolling(20,min_periods=20).std().values
    V=pd.DataFrame(vv[:,j:j+800].astype(np.float64)); vr[:,j:j+800]=(V/V.shift(1).rolling(20,min_periods=15).mean()).values
del vv
upper=ma+2*sd
lim=np.full(nc,0.1,np.float32); is30=np.char.startswith(codes,'sz.30'); is688=np.char.startswith(codes,'sh.688')
limm=np.repeat(lim[None,:],nd,0); limm[(dates>='2020-08-24')[:,None]&is30[None,:]]=0.2; limm[:,is688]=0.2
print('prep t=%.0f'%(time.time()-T0),flush=True)
prev=lambda x:np.vstack([np.full((1,nc),np.nan,np.float32),x[:-1]])
above=valid&(c>upper); cross=above&(prev(c)<=prev(upper))
ctrl=valid&(c>ma)&~(c>upper)   # in an uptrend above the mid line but inside the bands
SIG={'突破上轨首日':cross,'收于上轨之上(任一天)':above,'对照:中线之上轨内':ctrl}
zz=np.where(np.isfinite(zv),zv,np.nan)
GR={'z>0.5(偏强+过热)':zz>0.5,'z>1.5(过热)':zz>1.5,'0.5<z≤1.5(偏强)':(zz>0.5)&(zz<=1.5),'-0.5<z≤0.5(中性)':(zz>-0.5)&(zz<=0.5),'z≤-0.5(恐慌+偏弱)':zz<=-0.5,'任何日子':np.isfinite(zz)}
def run_events(M,exitrule,cap,hard=None,fixed=None):
    t_i,j_i=np.nonzero(M); e=t_i+1; ok_=(e<nd-2); t_i,j_i,e=t_i[ok_],j_i[ok_],e[ok_]
    ent=o[e,j_i]; okk=np.isfinite(ent)&(ent>0); t_i,j_i,e,ent=t_i[okk],j_i[okk],e[okk],ent[okk]
    n=len(t_i); sig=np.full(n,-1,np.int64); alive=np.ones(n,bool)
    if fixed: sig[:]=np.minimum(e+fixed-1,nd-2); alive[:]=False
    else:
        for k in range(cap):
            d=e+k; inb=alive&(d<nd-2)
            if not inb.any(): break
            cd=c[np.minimum(d,nd-1),j_i]; m_=ma[np.minimum(d,nd-1),j_i]
            cond=np.isfinite(cd)&np.isfinite(m_)&(cd<m_)
            if hard is not None: cond|=np.isfinite(cd)&(cd<=ent*(1-hard)*(np.nan_to_num(f[np.minimum(d,nd-1),j_i],nan=1)/np.nan_to_num(f[e,j_i],nan=1)))
            if k==cap-1: cond|=True
            hit=inb&cond; sig[hit]=d[hit]; alive&=~hit
            alive&=(d<nd-2)
        sig[alive]=np.minimum(e[alive]+cap-1,nd-2)   # data end
    x=sig+1
    for _ in range(5):                                  # can't sell into limit-down open
        xx=np.minimum(x,nd-1); locked=(o[xx,j_i]/c[xx-1,j_i]-1<=-(limm[xx,j_i]-0.003))|~np.isfinite(o[xx,j_i])
        x=np.where(locked&(x<nd-1),x+1,x)
    x=np.minimum(x,nd-1); px=o[x,j_i]; ok2=np.isfinite(px)&(x>e)
    rawx=px/f[x,j_i]; rawe=ent/f[e,j_i]
    net=(px*(1-0.01/rawx))/(ent*(1+0.01/rawe))-1-fee_[x]
    return t_i[ok2],j_i[ok2],e[ok2],x[ok2],net[ok2]
mon=np.array([d[:7] for d in dates]); _,mi=np.unique(mon,return_inverse=True)
yr=np.array([int(d[:4]) for d in dates])
def summarize(t,e,x,net):
    s=np.bincount(mi[t],weights=net,minlength=mi.max()+1); n=np.bincount(mi[t],minlength=mi.max()+1); mm=(s/np.maximum(n,1))[n>0]
    tt=mm.mean()/(mm.std()/np.sqrt(len(mm))+1e-12) if len(mm)>5 else np.nan
    h1=net[yr[t]<=2016]; h2=net[yr[t]>2016]
    return dict(n=int(len(net)),mean=float(net.mean()),med=float(np.median(net)),win=float((net>0).mean()),hold=float((x-e).mean()),t=float(tt),
                h1=float(h1.mean()) if len(h1) else None,h2=float(h2.mean()) if len(h2) else None,p10=float(np.percentile(net,10)),p90=float(np.percentile(net,90)))
RULES=[('跌破中线卖,最长60天','mid',60,None,None),('跌破中线卖,最长120天','mid',120,None,None),('跌破中线或回落8%卖,最长60天','mid',60,0.08,None),('固定持有20天(对照)','fix',0,None,20)]
OUT=[]
print('信号 | 状态 | 出场 | 笔数 平均净收益 中位 胜率 平均持有天数 月聚类t 前半/后半 10%分位/90%分位')
for sn,M in SIG.items():
    for gn,G in GR.items():
        MG=M&G[:,None]
        if MG.sum()<300: continue
        for rn,kind,cap,hard,fx in RULES:
            t,j,e,x,net=run_events(MG,kind,cap if kind=='mid' else 0,hard,fx if kind=='fix' else None)
            if len(net)<300: continue
            r=summarize(t,e,x,net); r.update(sig=sn,gate=gn,rule=rn); OUT.append(r)
            print(f"{sn[:10]:12s}|{gn[:14]:16s}|{rn[:16]:18s}| {r['n']:6d} {r['mean']*100:+5.2f}% 中{r['med']*100:+5.1f}% 胜{r['win']*100:3.0f}% 持{r['hold']:4.1f}天 t{r['t']:+4.1f} [{(r['h1'] or 0)*100:+.1f}/{(r['h2'] or 0)*100:+.1f}] {r['p10']*100:+.0f}/{r['p90']*100:+.0f}",flush=True)
    print('t=%.0f'%(time.time()-T0),flush=True)
json.dump(OUT,open('bb1.json','w'),ensure_ascii=False)

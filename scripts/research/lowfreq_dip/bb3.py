"""Greed-side / trend-following family: many entries x many exits x z-gates, with matched controls. Event level. Research only."""
import numpy as np, pandas as pd, json, time, gc, sys; T0=time.time()
P=np.load('panel_ext.npz'); dates=P['dates']; codes=P['codes']; nd=len(dates); nc=len(codes)
B=np.load('s6_base.npz'); valid=B['valid']; zv=B['zv']; fee_=B['fee']
mret=np.load('mkreg_ext_liq.npz')['mret'].astype(np.float64); bench=np.cumprod(1+np.nan_to_num(mret))
c=P['c']; o=P['o']; f=P['f']; vv=P['v']; hh=P['h']; ll=P['l']
def blk(fn):
    out=None
    for j in range(0,nc,800):
        r=fn(slice(j,j+800))
        if out is None: out={k:np.full((nd,nc),np.nan,np.float32) if v.dtype!=bool else np.zeros((nd,nc),bool) for k,v in r.items()}
        for k,v in r.items(): out[k][:,j:j+800]=v
    return out
def feat(s):
    C=pd.DataFrame(c[:,s].astype(np.float64)); V=pd.DataFrame(vv[:,s].astype(np.float64))
    ma10=C.rolling(10,min_periods=10).mean(); ma20=C.rolling(20,min_periods=20).mean(); sd20=C.rolling(20,min_periods=20).std(); ma60=C.rolling(60,min_periods=60).mean(); ma30=C.rolling(30,min_periods=30).mean()
    up=ma20+2*sd20; w=4*sd20/ma20; wmin=w.rolling(120,min_periods=100).min(); wmax=w.rolling(120,min_periods=100).max(); wp=(w-wmin)/(wmax-wmin)
    hi60=C.shift(1).rolling(60,min_periods=60).max(); hi120=C.shift(1).rolling(120,min_periods=120).max(); hi250=C.shift(1).rolling(250,min_periods=200).max()
    vr=V/V.shift(1).rolling(20,min_periods=15).mean(); r1=C.pct_change(fill_method=None)
    pos=((C-pd.DataFrame(ll[:,s].astype(np.float64)))/(pd.DataFrame(hh[:,s].astype(np.float64))-pd.DataFrame(ll[:,s].astype(np.float64))).replace(0,np.nan))
    mom=(C.shift(20)/C.shift(120)-1)
    gap=pd.DataFrame(o[:,s].astype(np.float64))/C.shift(1)-1
    cross=(C>up)&(C.shift(1)<=up.shift(1))
    recent_up=(C>up).rolling(10,min_periods=1).max().shift(1).fillna(0).astype(bool)
    return dict(ma20=ma20.values.astype(np.float32),ma60=ma60.values.astype(np.float32),
        up=cross.values, wp=wp.values.astype(np.float32), hi60=(C>hi60).values, hi120=(C>hi120).values, hi250=(C>hi250).values,
        vr=vr.values.astype(np.float32), r1=r1.values.astype(np.float32), pos=pos.values.astype(np.float32), mom=mom.values.astype(np.float32),
        gap=gap.values.astype(np.float32), gold=((ma20>ma60)&(ma20.shift(1)<=ma60.shift(1))).values,
        pull=(recent_up&(ma20>ma60)&(C>ma60)&(C<=ma20*1.01)&(C>=ma20*0.98)&(C>pd.DataFrame(o[:,s].astype(np.float64)))).values,
        abv60=(C>ma60).values, abv20=(C>ma20).values)
F=blk(feat); print('features t=%.0f'%(time.time()-T0),flush=True)
ma20=F['ma20']; ma60=F['ma60']
def cool(m,n=10):
    cs=np.cumsum(m,axis=0,dtype=np.int32); prev=np.zeros_like(cs); prev[1:]=cs[:-1]; prev[n+1:]-=cs[:-n-1][:nd-n-1] if False else 0
    p2=np.zeros((nd,nc),np.int32); p2[n+1:]=cs[:-(n+1)]; pr=np.zeros((nd,nc),np.int32); pr[1:]=cs[:-1]
    return m&((pr-p2)==0)
mt=np.where(valid,F['mom'],np.nan); thr=np.nanpercentile(mt,90,axis=1)[:,None]
S={}
S['上轨突破首日']=valid&F['up']
S['上轨突破+放量(量比≥2)']=valid&F['up']&(F['vr']>=2)
S['上轨突破+强收盘(收在日内高位且涨>3%)']=valid&F['up']&(F['pos']>=0.8)&(F['r1']>0.03)
S['60日新高突破']=cool(valid&F['hi60']&F['abv60'])
S['120日新高突破']=cool(valid&F['hi120'])
S['一年新高突破']=cool(valid&F['hi250'])
S['波动收缩后上轨突破(带宽分位≤15%近5日)']=valid&F['up']&(pd.DataFrame(F['wp']).rolling(5,min_periods=1).min().values<=0.15)
S['强势股回踩中线(上轨后10日内,MA20>MA60)']=cool(valid&F['pull'])
S['相对强度领先(120跳20前10%且在MA20/60上)']=cool(valid&(F['mom']>=thr)&F['abv60']&F['abv20'])
S['放量跳空高开(>3%,量比≥2,收阳)']=valid&(F['gap']>0.03)&(F['vr']>=2)&(F['r1']>0.0)
S['MA20上穿MA60(金叉)']=valid&F['gold']
CT=valid&F['abv60']&F['abv20']&(np.random.default_rng(1).random((nd,nc))<0.06)   # control: generic uptrend stocks (6% subsample)
print({k:int(v.sum()) for k,v in S.items()},'ctrl',int(CT.sum()),flush=True)
del F; gc.collect()
lim=np.full(nc,0.1,np.float32); is30=np.char.startswith(codes,'sz.30'); is688=np.char.startswith(codes,'sh.688')
limm=np.repeat(lim[None,:],nd,0); limm[(dates>='2020-08-24')[:,None]&is30[None,:]]=0.2; limm[:,is688]=0.2
zz=np.where(np.isfinite(zv),zv,np.nan); ma120b=pd.Series(bench).rolling(120,min_periods=120).mean().values
GR={'z>0.5':zz>0.5,'z>1.5':zz>1.5,'牛市(大盘在120日线上)':bench>ma120b,'任何日子':np.isfinite(zz)}
def run_events(M,spec):
    t_i,j_i=np.nonzero(M); e=t_i+1; ok_=(e<nd-3); t_i,j_i,e=t_i[ok_],j_i[ok_],e[ok_]
    ent=o[e,j_i]; okk=np.isfinite(ent)&(ent>0); t_i,j_i,e,ent=t_i[okk],j_i[okk],e[okk],ent[okk]
    n=len(t_i)
    if n==0: return [np.array([],int)]*4+[np.array([])]
    cap=spec.get('cap',60); fixn=spec.get('fix'); sig=np.full(n,-1,np.int64)
    if fixn: sig=np.minimum(e+fixn-1,nd-2)
    else:
        alive=np.ones(n,bool); cnt=np.zeros(n,np.int16); peak=ent.copy()
        for k in range(cap):
            d=np.minimum(e+k,nd-1); inb=alive&(e+k<nd-2)
            if not inb.any(): break
            cd=c[d,j_i]; okc=np.isfinite(cd)
            hit=np.zeros(n,bool)
            if spec.get('ma'):
                mm=(ma20 if spec['ma']==20 else ma60)[d,j_i]; below=okc&np.isfinite(mm)&(cd<mm)
                cnt=np.where(inb&okc,np.where(below,cnt+1,0),cnt); hit|=cnt>=spec.get('consec',1)
            if spec.get('trail'):
                peak=np.where(okc,np.maximum(peak,cd),peak); hit|=okc&(cd<=peak*(1-spec['trail']))
            if spec.get('tp'): hit|=okc&(cd>=ent*(1+spec['tp']))
            if k==cap-1: hit|=True
            h=inb&hit; sig[h]=d[h]; alive&=~h; alive&=(e+k<nd-2)
        sig[alive]=np.minimum(e[alive]+cap-1,nd-2)
    x=sig+1
    for _ in range(5):
        xx=np.minimum(x,nd-1); locked=(o[xx,j_i]/c[xx-1,j_i]-1<=-(limm[xx,j_i]-0.003))|~np.isfinite(o[xx,j_i])
        x=np.where(locked&(x<nd-1),x+1,x)
    x=np.minimum(x,nd-1); px=o[x,j_i]; ok2=np.isfinite(px)&(x>e)
    net=(px*(1-0.01/(px/f[x,j_i])))/(ent*(1+0.01/(ent/f[e,j_i])))-1-fee_[x]
    return t_i[ok2],j_i[ok2],e[ok2],x[ok2],net[ok2]
mon=np.array([d[:7] for d in dates]); _,mi=np.unique(mon,return_inverse=True); NM=mi.max()+1
yr=np.array([int(d[:4]) for d in dates])
def monthly(t,net):
    s=np.bincount(mi[t],weights=net,minlength=NM); n=np.bincount(mi[t],minlength=NM); return s,n
EXITS={'跌破MA20(1日)':dict(ma=20,cap=60),'连续2日跌破MA20':dict(ma=20,consec=2,cap=80),'跌破MA60':dict(ma=60,cap=120),
       '距最高收盘回落12%':dict(trail=0.12,cap=120),'距最高收盘回落20%':dict(trail=0.20,cap=120),'涨25%止盈或跌破MA20':dict(ma=20,tp=0.25,cap=60),
       '固定持有20天':dict(fix=20),'固定持有40天':dict(fix=40)}
#SCAN
if __name__=='__main__' or True:
  OUT=[]; CTRL={}
  which=sys.argv[1] if len(sys.argv)>1 else 'all'
  for gn,G in GR.items():
    for xn,sp in EXITS.items():
        t,j,e,x,net=run_events(CT&G[:,None],sp); s,n=monthly(t,net); CTRL[(gn,xn)]=(net.mean(),s,n)
    print('control',gn,'t=%.0f'%(time.time()-T0),flush=True)
  print('信号 | 状态 | 出场 | 笔数 均值 超额(对照差) 配对t 前半/后半超额 中位 胜率 持有',flush=True)
  for sn,M in S.items():
    for gn,G in GR.items():
        MG=M&G[:,None]
        if MG.sum()<300: continue
        for xn,sp in EXITS.items():
            t,j,e,x,net=run_events(MG,sp)
            if len(net)<300: continue
            s,n=monthly(t,net); cm,cs_,cn=CTRL[(gn,xn)]
            ok=(n>0)&(cn>0); d=(s[ok]/n[ok])-(cs_[ok]/cn[ok])
            tt=d.mean()/(d.std()/np.sqrt(len(d))+1e-12) if len(d)>6 else np.nan
            h1=yr[t]<=2016; ex1=net[h1].mean()-cm if h1.any() else np.nan; ex2=net[~h1].mean()-cm if (~h1).any() else np.nan
            r=dict(sig=sn,gate=gn,exit=xn,n=int(len(net)),mean=float(net.mean()),ctrl=float(cm),ex=float(net.mean()-cm),t=float(tt),ex1=float(ex1),ex2=float(ex2),med=float(np.median(net)),win=float((net>0).mean()),hold=float((x-e).mean()))
            OUT.append(r)
            print(f"{sn[:14]:16s}|{gn[:8]:9s}|{xn[:12]:14s}| {r['n']:7d} {r['mean']*100:+5.2f}% 超额{r['ex']*100:+5.2f}% t{r['t']:+4.1f} [{ex1*100:+.1f}/{ex2*100:+.1f}] 中{r['med']*100:+5.1f}% 胜{r['win']*100:3.0f}% 持{r['hold']:4.1f}",flush=True)
        json.dump(OUT,open('bb3.json','w'),ensure_ascii=False)
    print('signal done',sn,'t=%.0f'%(time.time()-T0),flush=True)
  json.dump(OUT,open('bb3.json','w'),ensure_ascii=False); print('ALL DONE')

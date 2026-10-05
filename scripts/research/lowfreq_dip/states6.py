"""Wide strategy scan by z-state (memory-lean). signals x holding periods x 5 z-states. Research only. writes states6.json + s6_masks.npz"""
import numpy as np, pandas as pd, json, time, gc; T0=time.time()
P=np.load('panel_ext.npz'); dates=P['dates']; codes=P['codes']; nd=len(dates); nc=len(codes)
B=np.load('s6_base.npz'); valid=B['valid']; zv=B['zv']; fee_=B['fee']
ok=np.isfinite(zv); yr=np.array([int(d[:4]) for d in dates]); mon=np.array([d[:7] for d in dates]); _,mi=np.unique(mon,return_inverse=True)
def chunked(fn,*arrs,w=800):
    out=np.full((nd,nc),np.nan,np.float32)
    for j in range(0,nc,w):
        out[:,j:j+w]=fn(*[a[:,j:j+w] for a in arrs]).astype(np.float32)
    return out
c=P['c']; o=P['o']; f=P['f']; h_=P['h']; l_=P['l']; v_=P['v']; a_=P['a']
def feats(cc,vv,aa):
    C=pd.DataFrame(cc.astype(np.float64)); r1=C.pct_change(fill_method=None)
    d=dict(ret1=r1.values, ret5=(C/C.shift(5)-1).values, ret20=(C/C.shift(20)-1).values, mom=(C.shift(20)/C.shift(120)-1).values,
           vol60=r1.rolling(60,min_periods=40).std().values, hi250=(C/C.rolling(250,min_periods=200).max()).values, lo250=(C/C.rolling(250,min_periods=200).min()).values,
           a20=pd.DataFrame(aa.astype(np.float64)).rolling(20,min_periods=15).mean().values)
    V=pd.DataFrame(vv.astype(np.float64)); d['vr']=(V/V.shift(1).rolling(20,min_periods=15).mean()).values
    return d
F={k:np.full((nd,nc),np.nan,np.float32) for k in ('ret1','ret5','ret20','mom','vol60','hi250','lo250','a20','vr')}
for j in range(0,nc,800):
    d=feats(c[:,j:j+800],v_[:,j:j+800],a_[:,j:j+800])
    for k in F: F[k][:,j:j+800]=d[k]
print('features t=%.0f'%(time.time()-T0),flush=True)
lim=np.full(nc,0.1,np.float32); is30=np.char.startswith(codes,'sz.30'); is688=np.char.startswith(codes,'sh.688')
limm=np.repeat(lim[None,:],nd,0); limm[(dates>='2020-08-24')[:,None]&is30[None,:]]=0.2; limm[:,is688]=0.2
def rk(x,q,hi=True):
    t=np.nanpercentile(np.where(valid,x,np.nan),q,axis=1)[:,None]
    return valid&((x>=t) if hi else (x<=t))
S={}
lu=(F['ret1']>=limm-0.003)&(c>=h_*0.998); del limm
S['涨停收盘(封板)']=valid&lu
lu1=np.vstack([np.zeros((1,nc),bool),lu[:-1]]); S['连板(昨今均涨停)']=valid&lu&lu1; del lu,lu1
dn=F['ret1']<0; S['连跌3天']=valid&dn&np.vstack([np.zeros((1,nc),bool),dn[:-1]])&np.vstack([np.zeros((2,nc),bool),dn[:-2]]); del dn
vr=F['vr']; r1=F['ret1']
S['放量上涨(量>3倍均量,涨)']=valid&(vr>=3)&(r1>0); S['放量下跌(量>3倍均量,跌)']=valid&(vr>=3)&(r1<0)
S['缩量(量<0.5倍均量)且5日弱']=valid&(vr<=0.5)&(F['ret5']<0)
S['接近一年新高(≥97%)']=valid&(F['hi250']>=0.97); S['接近一年新低(≤110%)']=valid&(F['lo250']<=1.10)
S['成交额最低20%(小盘代理)']=rk(F['a20'],20,False); S['成交额最高20%']=rk(F['a20'],80,True)
rng=(h_-l_)/np.maximum(c,1e-9); pos=(c-l_)/np.maximum(h_-l_,1e-9)
S['收在日内最高附近且振幅>5%']=valid&(pos>=0.9)&(rng>0.05); S['收在日内最低附近且振幅>5%']=valid&(pos<=0.1)&(rng>0.05); del rng,pos
S['20日最弱10%']=rk(F['ret20'],10,False); S['20日最强10%']=rk(F['ret20'],90,True); S['5日最弱10%']=rk(F['ret5'],10,False); S['5日最强10%']=rk(F['ret5'],90,True)
S['中期动量(120跳20)最强10%']=rk(F['mom'],90,True); S['中期动量最弱10%']=rk(F['mom'],10,False)
S['低波动20%']=rk(F['vol60'],20,False); S['高波动20%']=rk(F['vol60'],80,True)
del F,vr,r1,v_,a_,h_,l_; gc.collect()
fv=np.load('fund_val.npz'); PB=fv['pb']; PE=fv['pe']
S['PB最低10%']=rk(np.where(PB>0,PB,np.nan),10,False); S['PB最高10%']=rk(np.where(PB>0,PB,np.nan),90,True); S['PE最低10%(PE>0)']=rk(np.where(PE>0,PE,np.nan),10,False)
del PB,PE,fv; gc.collect()
print('signals',len(S),'t=%.0f'%(time.time()-T0),flush=True)
np.savez_compressed('s6_masks.npz',**{k:v for k,v in S.items()})
STATES=[('恐慌',lambda z:z<=-1.5),('偏弱',lambda z:(z>-1.5)&(z<=-0.5)),('中性',lambda z:(z>-0.5)&(z<=0.5)),('偏强',lambda z:(z>0.5)&(z<=1.5)),('过热',lambda z:z>1.5)]
zz=np.where(ok,zv,np.nan); SM={n:ok&f_(zz) for n,f_ in STATES}
def fwdnet(h):
    ex=np.full((nd,nc),np.nan,np.float32); ex[:-h]=c[h:]; fx=np.full((nd,nc),np.nan,np.float32); fx[:-h]=f[h:]
    en=np.full((nd,nc),np.nan,np.float32); en[:-1]=o[1:]; fe=np.full((nd,nc),np.nan,np.float32); fe[:-1]=f[1:]
    fe_=np.full(nd,np.nan,np.float32); fe_[:-h]=fee_[h:]
    n=(ex*(1-0.01/(ex/fx)))/(en*(1+0.01/(en/fe)))-1-fe_[:,None]
    return n
def mstat(x,m):
    m=m&np.isfinite(x)
    if m.sum()<30: return (np.nan,np.nan,0)
    s=np.bincount(mi[m],weights=x[m],minlength=mi.max()+1); n=np.bincount(mi[m],minlength=mi.max()+1); mm=(s/np.maximum(n,1))[n>0]
    if len(mm)<8: return (np.nan,np.nan,len(mm))
    return (float(mm.mean()), float(mm.mean()/(mm.std()/np.sqrt(len(mm))+1e-12)), int(m.sum()))
HS=(1,3,5,10,20,40,60); RES=[]
half=yr<=2016
for h in HS:
    nh=fwdnet(h); vh=valid&np.isfinite(nh); allm=np.where(vh,nh,0).sum(1)/np.maximum(vh.sum(1),1)
    for nm,p in S.items():
        m_=p&vh; n=m_.sum(1); pm=np.where(n>=5,np.where(m_,nh,0).sum(1)/np.maximum(n,1),np.nan); ex_=pm-allm
        for sn in SM:
            sm=SM[sn]; a=mstat(pm,sm); e=mstat(ex_,sm); a1=mstat(pm,sm&half); a2=mstat(pm,sm&~half)
            RES.append(dict(sig=nm,h=h,state=sn,abs=a[0],abs_t=a[1],ex=e[0],ex_t=e[1],ndays=a[2],h1=a1[0],h2=a2[0]))
    print('h',h,'done t=%.0f'%(time.time()-T0),flush=True)
    del nh,vh; gc.collect()
json.dump(RES,open('states6.json','w'),ensure_ascii=False,default=lambda x: None if x!=x else float(x))
print('saved',len(RES))

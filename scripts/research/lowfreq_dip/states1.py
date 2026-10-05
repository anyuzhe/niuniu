"""Signal scan by z-state: which stock-selection rule has positive excess net in each market state. Research only."""
import numpy as np, pandas as pd, json
exec(open('stockport.py').read().split("print('格式")[0])
ok=np.isfinite(zv); yrm=np.array([d[:7] for d in dates]); yr=np.array([int(d[:4]) for d in dates])
C=pd.DataFrame(c.astype(np.float64))
r1=C.pct_change(fill_method=None)
ret5=(C/C.shift(5)-1).values; ret60=(C/C.shift(60)-1).values
mom=(C.shift(20)/C.shift(120)-1).values
ma20=C.rolling(20,min_periods=20).mean(); sd20=C.rolling(20,min_periods=20).std(); ma60=C.rolling(60,min_periods=60).mean()
hi60=C.shift(1).rolling(60,min_periods=60).max().values
vol60=r1.rolling(60,min_periods=40).std().values
ma20v=ma20.values; sd20v=sd20.values; ma60v=ma60.values; cv=C.values
del C,r1,ma20,sd20,ma60
r20=np.where(valid,ret20,np.nan)
def thr(x,q,axis=1):
    return np.nanpercentile(np.where(valid,x,np.nan),q,axis=axis)
sig={}
p10,p90=thr(ret20,10),thr(ret20,90)
sig['20日最弱10%(反转)']=valid&(ret20<=p10[:,None])
sig['20日最强10%(动量)']=valid&(ret20>=p90[:,None])
q=thr(ret5,10); sig['5日最弱10%']=valid&(ret5<=q[:,None])
q=thr(mom,90); sig['120日跳过20日动量最强10%']=valid&(mom>=q[:,None])
sig['突破60日新高']=valid&(cv>hi60)
q=thr(vol60,20); sig['低波动20%']=valid&(vol60<=q[:,None])
q=thr(vol60,80); sig['高波动20%']=valid&(vol60>=q[:,None])
sig['E6布林下轨收复(基线池)']=e6
sig['突破布林上轨']=valid&(cv>ma20v+2*sd20v)
sig['上升趋势中回调(价>MA60,MA20>MA60,价<MA20)']=valid&(cv>ma60v)&(ma20v>ma60v)&(cv<ma20v)
sig['全部候选(对照=0)']=valid
fin=np.isfinite(net)
def pool_mean(p):
    m=p&fin
    s=np.where(m,net,0).sum(1); n=m.sum(1)
    return np.where(n>=5,s/np.maximum(n,1),np.nan), n
allm,_=pool_mean(valid)
STATES=[('恐慌 z≤-1.5',lambda z:z<=-1.5),('偏弱 -1.5<z≤-0.5',lambda z:(z>-1.5)&(z<=-0.5)),('中性 -0.5<z≤0.5',lambda z:(z>-0.5)&(z<=0.5)),('偏强 0.5<z≤1.5',lambda z:(z>0.5)&(z<=1.5)),('过热 z>1.5',lambda z:z>1.5)]
zz=np.where(ok,zv,np.nan)
def cl(x,m):
    g={}
    for k,v in zip(yrm[m],x[m]):
        if np.isfinite(v): g.setdefault(k,[]).append(v)
    mm=np.array([np.mean(v) for v in g.values()])
    if len(mm)<4: return (np.nan,np.nan,len(mm))
    return (mm.mean(), mm.mean()/(mm.std()/np.sqrt(len(mm))+1e-12), len(mm))
out={}
half=yr<=2016
print('每格：池内平均净收益-全候选平均净收益（超额，20日，已扣成本）/ 月聚类t / 前半(07-16)后半(17-26)超额')
hdr='信号'.ljust(38)+'|'+'|'.join(s[0][:8].ljust(26) for s in STATES)
print(hdr)
for nm,p in sig.items():
    pm,_=pool_mean(p); ex=pm-allm; cells=[]
    for sn,f in STATES:
        m=ok&f(zz)&np.isfinite(ex)
        a=cl(ex,m); h1=cl(ex,m&half); h2=cl(ex,m&~half)
        cells.append(f'{a[0]*100:+5.1f}% t{a[1]:+4.1f} [{h1[0]*100:+4.1f}/{h2[0]*100:+4.1f}]'.ljust(26))
        out[(nm,sn)]=(a[0],a[1],h1[0],h2[0],a[2])
    print(nm[:36].ljust(38)+'|'+'|'.join(cells),flush=True)
print('\n各状态：全候选绝对净收益(20日)与月数：')
for sn,f in STATES:
    m=ok&f(zz); a=cl(allm,m); print(' ',sn,f'{a[0]*100:+.2f}% t{a[1]:+.1f} 月{a[2]} 天{int(m.sum())}')
print('\n各状态：各信号池绝对净收益')
for nm,p in sig.items():
    pm,_=pool_mean(p); cells=[]
    for sn,f in STATES:
        m=ok&f(zz)&np.isfinite(pm); a=cl(pm,m); cells.append(f'{a[0]*100:+5.1f}% t{a[1]:+4.1f}'.ljust(16))
    print(nm[:36].ljust(38)+'|'+'|'.join(cells))

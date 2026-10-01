"""Long-sample (2008-2026) test: stock-level Bollinger lower-band reclaim (E6) x dynamic market oversold factor. Research only."""
import numpy as np, gc, warnings; warnings.filterwarnings('ignore')
P=np.load('panel_ext.npz'); dates=P['dates']; codes=P['codes']; nd=len(dates); nc=len(codes)
c=P['c']; o=P['o']; f=P['f']; a=P['a']; st=P['st']; ts=P['ts']
fin=np.isfinite(c)&np.isfinite(o)&(ts==1)
listed=np.cumsum(np.isfinite(c),0)>=250
def rollsum(x,n):
    z=np.where(np.isfinite(x),x,0).astype(np.float64); cs=np.vstack([np.zeros((1,nc)),np.cumsum(z,0)]); out=np.full((nd,nc),np.nan,np.float32); out[n-1:]=(cs[n:]-cs[:-n]); return out
amt20=rollsum(a,20)/20
raw=c/f
uni=fin&~st&listed&(amt20>=5e7)&(raw>=3); del amt20,a; gc.collect()
cf=np.where(np.isfinite(c),c,np.nan)
s1=rollsum(cf,20); s2=rollsum(cf.astype(np.float64)**2,20)
ma=s1/20; sd=np.sqrt(np.maximum(s2/20-ma*ma,0)*20/19); del s1,s2
blo=ma-2*sd; del ma,sd
def sh(x,k): out=np.full_like(x,np.nan); out[k:]=x[:-k]; return out
E6=(sh(c,1)<sh(blo,1))&(c>blo)&(c>o)&uni; del blo; gc.collect()
# next-day buy feasibility
lim=np.full(nc,0.1,np.float32); is30=np.char.startswith(codes,'sz.30'); is688=np.char.startswith(codes,'sh.688')
limm=np.repeat(lim[None,:],nd,0); limm[(dates>='2020-08-24')[:,None]&is30[None,:]]=0.2; limm[:,is688]=0.2
gap=np.full((nd,nc),np.nan,np.float32); gap[:-1]=o[1:]/c[:-1]-1
buyok=np.zeros((nd,nc),bool); buyok[:-1]=fin[1:]&~(gap[:-1]>=limm[:-1]-0.0025); del gap,limm; gc.collect()
H=20
# net return with date-dependent costs
ent=np.full((nd,nc),np.nan,np.float32); ent[:-1]=o[1:]; rawE=np.full((nd,nc),np.nan,np.float32); rawE[:-1]=(o[1:]/f[1:])
ex=np.full((nd,nc),np.nan,np.float32); ex[:-H]=c[H:]; rawX=np.full((nd,nc),np.nan,np.float32); rawX[:-H]=(c[H:]/f[H:])
# exit delay up to 3 days if exit close missing
for k in (1,2,3):
    miss=~np.isfinite(ex); 
    if not miss.any(): break
    alt=np.full((nd,nc),np.nan,np.float32); alt[:-(H+k)]=c[H+k:]; altr=np.full((nd,nc),np.nan,np.float32); altr[:-(H+k)]=c[H+k:]/f[H+k:]
    ex=np.where(miss,alt,ex); rawX=np.where(miss,altr,rawX)
yr=np.array([int(d[:4]) for d in dates]); dd=dates
stamp=np.where(dd<'2008-09-19',0.003,np.where(dd<'2023-08-28',0.001,0.0005))   # sell side
comm=np.where(dd<'2015-01-01',0.0006,np.where(dd<'2020-01-01',0.0004,0.00022))  # round trip commission+fees
fee=(stamp+comm).astype(np.float32)[:,None]
net=(ex*(1-0.01/rawX))/(ent*(1+0.01/rawE))-1-fee
valid=uni&buyok&np.isfinite(net)
del ent,ex,rawE,rawX,c,o,f; gc.collect()
M=np.load('mkreg_ext_liq.npz'); assert (M['dates']==dates).all(); mk20=M['mk20']; mr=M['mret']
sd60=np.full(nd,np.nan)
for i in range(59,nd): sd60[i]=mr[i-59:i+1].std(ddof=1)
zv=mk20/(sd60*np.sqrt(20))
good=valid
ref=np.where(good,net,np.nan); refm=np.nanmean(ref,1)
e6v=good&E6; n6=e6v.sum(1); e6m=np.where(n6>0,np.nansum(np.where(e6v,net,0),1)/np.maximum(n6,1),np.nan); e6w=np.where(n6>0,(e6v&(net>0)).sum(1)/np.maximum(n6,1),np.nan)
t_ok=(dates>='2008-01-01')&np.isfinite(zv)&np.isfinite(refm)&(np.arange(nd)<nd-H-4)
ERA={'2008-11':('2008-01-01','2011-12-31'),'2012-16':('2012-01-01','2016-12-31'),'2017-19':('2017-01-01','2019-12-31'),'2020-26':('2020-01-01','2026-12-31'),'全期':('2008-01-01','2026-12-31')}
B={'z<=-2':zv<=-2,'-2<z<=-1.5':(zv>-2)&(zv<=-1.5),'-1.5<z<=-1':(zv>-1.5)&(zv<=-1),'-1<z<=0':(zv>-1)&(zv<=0),'z>0':zv>0,'固定20日<=-9%':mk20<=-0.09,'固定20日>-9%':mk20>-0.09}
print('E6=个股布林下轨收复(昨收<下轨,今收回且阳线)；动态因子 z=等权大盘20日涨跌/(60日日波动×√20)。持有20天，扣成本(印花税/佣金按年代)。')
print('格式：E6绝对净收益bp / 相对当日全部候选(同样买法)bp / 胜率 / E6信号只次(天数)；列='+' | '.join(ERA))
for bn,bm in B.items():
    cells=[]
    for pn,(x,y) in ERA.items():
        m=t_ok&bm&(dates>=x)&(dates<=y)&(n6>=10)
        if m.sum()<3: cells.append('    无    '); continue
        w=n6[m]; ab=(e6m[m]*w).sum()/w.sum(); rl=((e6m[m]-refm[m])*w).sum()/w.sum(); wr=(e6w[m]*w).sum()/w.sum()
        cells.append(f'{ab*1e4:+5.0f}/{rl*1e4:+5.0f}/{wr*100:3.0f}%/{int(w.sum())}({m.sum()})')
    print(f'{bn:14s}| '+' | '.join(cells))
print('\n参照：同样天里“全部候选”的平均20天净收益(bp)')
for bn,bm in B.items():
    cells=[]
    for pn,(x,y) in ERA.items():
        m=t_ok&bm&(dates>=x)&(dates<=y); cells.append('  无  ' if m.sum()<3 else f'{np.nanmean(refm[m])*1e4:+5.0f}({m.sum()})')
    print(f'{bn:14s}| '+' | '.join(cells))
np.savez('stockdyn_daily.npz',dates=dates,zv=zv,e6m=e6m,e6w=e6w,n6=n6,refm=refm)

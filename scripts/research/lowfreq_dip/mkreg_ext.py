import numpy as np, warnings; warnings.filterwarnings('ignore')
P=np.load('panel_ext.npz'); dates=P['dates']; nd=len(dates)
C=P['c']; Ac=P['a']; ST=P['st']; TS=P['ts']; nc=C.shape[1]
fin=np.isfinite(C)&(TS==1)
c1=np.full_like(C,np.nan); c1[1:]=C[:-1]
r=C/c1-1
cnt=np.cumsum(np.isfinite(C),0); listed=cnt>=80
a=np.where(np.isfinite(Ac),Ac,0).astype(np.float64); cs=np.vstack([np.zeros((1,nc)),np.cumsum(a,0)]); amt20=np.full((nd,nc),np.nan,np.float32); amt20[19:]=(cs[20:]-cs[:-20])/20
for name,thr in (('liq',5e7),('all',0.0)):
    uni=fin&~ST&listed&(amt20>=thr)&np.isfinite(r)
    mret=np.nanmean(np.where(uni,r,np.nan),1); n=uni.sum(1); mret[~np.isfinite(mret)]=0
    idx=np.cumprod(1+mret); mk20=np.full(nd,np.nan); mk20[20:]=idx[20:]/idx[:-20]-1
    np.savez(f'mkreg_ext_{name}.npz',dates=dates,mk20=mk20,mret=mret,n=n)
    yrs=np.array([d[:4] for d in dates])
    print(name,'每年平均股票数',{y:int(n[yrs==y].mean()) for y in sorted(set(yrs))[::2]})
    for thr_ in (-0.06,-0.09,-0.12): print(f'  {name} 20日<={thr_*100:.0f}%: 天数',int((mk20<=thr_).sum()))
    if name=='liq': print('liq 每年深度(<=-9%)天数',{y:int(((mk20<=-0.09)&(yrs==y)).sum()) for y in sorted(set(yrs)) if ((mk20<=-0.09)&(yrs==y)).sum()})
c=np.load('mkreg_ext_liq.npz'); a=np.load('mkreg_ext_all.npz'); m=np.isfinite(c['mk20'])&np.isfinite(a['mk20']); print('liq/all mk20 相关',np.corrcoef(c['mk20'][m],a['mk20'][m])[0,1])

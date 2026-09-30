import os, sys, numpy as np, warnings; warnings.filterwarnings('ignore')
sys.argv=['x']
exec(open('lowfreq.py').read().split("mon=np.array")[0])
mret=np.nanmean(np.where(uni,ret1,np.nan),1); mret[~np.isfinite(mret)]=0
idx=np.cumprod(1+mret); mk20=idx/np.r_[np.full(20,np.nan),idx[:-20]]-1
np.savez('mkreg.npz',dates=dates,mk20=mk20,mret=mret); print('ok')

import numpy as np, glob, pyarrow.parquet as pq, pandas as pd, time
T0=time.time(); L=glob_root='/'.join([__import__('os').path.expanduser('~'),'mnt','lake'])
P=np.load('panel_ext.npz'); dates=P['dates'].astype(str); codes=P['codes'].astype(str); nd=len(dates); nc=len(codes)
ci={c:i for i,c in enumerate(codes)}; di={d:i for i,d in enumerate(dates)}
fs=sorted(glob.glob(L+'/bronze/provider=baostock/valuation_daily_v1/**/*.parquet',recursive=True)); print(len(fs),'files',flush=True)
arr={k:np.full((nd,nc),np.nan,np.float32) for k in ('pe','pb','ps','pcf')}; hit=0; miss=0; tot=0; first={}
for n,f in enumerate(fs):
    t=pq.read_table(f,columns=['date','code','peTTM','pbMRQ','psTTM','pcfNcfTTM']).to_pandas()
    if not len(t): continue
    code=t['code'].iloc[0]
    if code not in ci: miss+=1; continue
    hit+=1; j=ci[code]; ix=t['date'].astype(str).map(di); m=ix.notna().values
    ii=ix[m].astype(int).values
    for k,cn in (('pe','peTTM'),('pb','pbMRQ'),('ps','psTTM'),('pcf','pcfNcfTTM')):
        arr[k][ii,j]=pd.to_numeric(t[cn],errors='coerce').values[m]
    if n%800==0: print(n,round(time.time()-T0),flush=True)
print('codes matched',hit,'not in panel',miss)
np.savez('fund_val.npz',**arr)
for k in arr: print(k,'finite share',np.isfinite(arr[k]).mean().round(3))
print('done',round(time.time()-T0))

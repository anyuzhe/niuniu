import numpy as np, os, glob
import pyarrow.parquet as pq
H=os.environ['HOME']; L=f'{H}/mnt/lake'
files=sorted(glob.glob(f'{L}/silver/qfq_kline_daily_v2/*.parquet'))
codes=[os.path.basename(f)[:-8].replace('_','.',1) for f in files]
cal=pq.read_table(f'{L}/silver/qfq_kline_daily_v2/sh_600000.parquet',columns=['date']).column('date').to_numpy().astype('datetime64[D]')
cal=cal[cal>=np.datetime64('2007-01-01')]
nd,nc=len(cal),len(codes); print(nd,nc,cal[0],cal[-1],flush=True)
F={k:np.full((nd,nc),np.nan,np.float32) for k in 'ohlcvaf'}
ST=np.zeros((nd,nc),bool); TS=np.full((nd,nc),-1,np.int8)
for j,f in enumerate(files):
    t=pq.read_table(f,columns=['date','open','high','low','close','volume','amount','factor'])
    d=t.column('date').to_numpy().astype('datetime64[D]'); m=d>=cal[0]
    if not m.any(): continue
    idx=np.searchsorted(cal,d[m]); ok=(idx<nd); ok[ok]&=(cal[idx[ok]]==d[m][ok]); idx=idx[ok]
    for k,cn in zip('ohlcvaf',['open','high','low','close','volume','amount','factor']):
        F[k][idx,j]=t.column(cn).to_numpy(zero_copy_only=False)[m][ok]
    s=pq.read_table(f'{L}/bronze/provider=baostock/daily_status_v2/{os.path.basename(f)}',columns=['date','tradestatus','isST'])
    sd=np.array(s.column('date').to_pylist(),dtype='datetime64[D]'); mm=sd>=cal[0]
    si=np.searchsorted(cal,sd[mm]); ok2=(si<nd); ok2[ok2]&=(cal[si[ok2]]==sd[mm][ok2]); si=si[ok2]
    ST[si,j]=(np.array(s.column('isST').to_pylist())[mm][ok2]=='1'); TS[si,j]=np.where(np.array(s.column('tradestatus').to_pylist())[mm][ok2]=='1',1,0)
    if j%500==0: print(j,flush=True)
np.savez('panel_ext.npz',dates=cal.astype(str),codes=np.array(codes),st=ST,ts=TS,**F)
print('done',flush=True)

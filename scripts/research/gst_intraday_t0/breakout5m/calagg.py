"""Group calendar outcomes by event day (day-averaged across stocks, t across days). Research only."""
import numpy as np, os, datetime as dt
H=os.environ['HOME']; Z={}
for y in range(2020,2027):
    z=np.load(f'{H}/research/brk/cal_{y}.npz',allow_pickle=True)
    for k in z.files: Z.setdefault(k,[]).append(z[k])
Z={k:np.concatenate(v) for k,v in Z.items()}
days=np.unique(Z['date']); D=[dt.date.fromisoformat(d) for d in days]; ix={d:i for i,d in enumerate(days)}
n=len(D); ev={}
gap_next=np.array([(D[i+1]-D[i]).days if i+1<n else 1 for i in range(n)]); gap_prev=np.array([(D[i]-D[i-1]).days if i>0 else 1 for i in range(n)])
ev['节前最后一天']=gap_next>3; ev['节后第一天']=gap_prev>3
ev['月末最后一天']=np.array([i+1<n and D[i+1].month!=D[i].month for i in range(n)])
ev['月初第一天']=np.array([i>0 and D[i-1].month!=D[i].month for i in range(n)])
ev['季末最后一天']=ev['月末最后一天']&np.array([d.month in (3,6,9,12) for d in D])
def third_friday(y,m):
    d=dt.date(y,m,1); fr=[d+dt.timedelta(k) for k in range(31) if (d+dt.timedelta(k)).month==m and (d+dt.timedelta(k)).weekday()==4]; return fr[2]
def second_friday(y,m):
    d=dt.date(y,m,1); fr=[d+dt.timedelta(k) for k in range(31) if (d+dt.timedelta(k)).month==m and (d+dt.timedelta(k)).weekday()==4]; return fr[1]
Dset=np.array(D)
exp=np.zeros(n,bool); reb=np.zeros(n,bool)
for y in range(2020,2027):
    for m in range(1,13):
        tf=third_friday(y,m); k=np.searchsorted(Dset,tf)
        if k<n: exp[k]=True
        if m in (6,12):
            sf=second_friday(y,m); k=np.searchsorted(Dset,sf,side='right')-1
            if 0<=k<n and Dset[k].month==m: reb[k]=True
ev['股指期货交割日']=exp; ev['指数调样前最后一天']=reb
for w,nm in enumerate(['周一','周二','周三','周四','周五']): ev[nm]=np.array([d.weekday()==w for d in D])
ev['全部交易日']=np.ones(n,bool)
di=np.array([ix[d] for d in Z['date']])
per={'20-22':days<'2023','23-24':(days>='2023')&(days<'2025'),'25-26':days>='2025','全部':np.ones(n,bool)}
for key,lab in (('short_open','开盘先卖、收盘买回'),('long_open','开盘先买、收盘卖出'),('short_1005','10:05 先卖、收盘买回')):
    y=Z[key]; y=np.where(np.abs(y)>2500,np.nan,y); ok=np.isfinite(y)  # drop impossible moves (data glitches, corporate actions)
    dm=np.bincount(di[ok],y[ok],minlength=n)/np.maximum(np.bincount(di[ok],minlength=n),1)
    print(f'\n### {lab}（每天先对 500 只取平均，再按天统计；每笔扣费后 bp）')
    for nm,mask in ev.items():
        s=f'  {nm:10s}'
        for pn,pm in per.items():
            v=dm[mask&pm]
            if len(v)<3: s+=f' | {pn} —'; continue
            s+=f' | {pn} {v.mean():+6.1f} t{v.mean()/(v.std(ddof=1)/np.sqrt(len(v))):+4.1f} 天{len(v)} 赚钱天{(v>0).mean()*100:3.0f}%'
        print(s)

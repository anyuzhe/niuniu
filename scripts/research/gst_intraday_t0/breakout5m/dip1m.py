"""1-minute check of 分批抄底 (10:30-11:30 buy window, hold to the close) on tdx_kline_min1, 2026-05-21..09-24, 2026
universe, against the same rule on the 5-minute grid for the same stock-days. Research only."""
import duckdb, os, json, numpy as np, sys
sys.path.insert(0,os.path.dirname(__file__)); import lib5
H=os.environ['HOME']; T=0.01; FEE=7.2
U=json.load(open(f'{H}/research/mkt/universe.json'))['2026']
files=[f"{H}/mnt/lake/bronze/provider=tdx/kline_min1/{c.replace('.','_')}.parquet" for c in U]
c=duckdb.connect()
res1={}; 
for f,cd in zip(files,U):
    if not os.path.exists(f): continue
    x=c.execute("""select date::varchar d, substr(time,9,4) hm, open, high, low, close from read_parquet(?) where date>='2026-05-20' and substr(time,9,4)<>'0930' order by date,time""",[f]).fetchnumpy()
    if len(x['d'])==0: continue
    ud=np.unique(x['d']); closes={}
    for d in ud:
        m=x['d']==d; hm=x['hm'][m]; o=x['open'][m]; h=x['high'][m]; l=x['low'][m]; cl=x['close'][m]
        closes[d]=(hm,o,h,l,cl)
    prev=None
    for d in ud:
        hm,o,h,l,cl=closes[d]
        if prev is None or len(hm)<200: prev=cl[-1] if len(cl) else prev; continue
        pc=prev; prev=cl[-1]
        lim=0.2 if cd.startswith('sz.30') or cd.startswith('sh.688') else 0.1; dn=round(pc*(1-lim)+1e-9,2)
        i0=np.searchsorted(hm,'1031'); i1=np.searchsorted(hm,'1131')  # buy window 10:31..11:30
        if i0==0 or i0>=len(hm): continue
        ref=cl[i0-1]
        for step in (0.015,0.02):
            units=0; cost=0.
            for i in range(i0,i1):
                while units<3:
                    lvl=ref*(1-(units+1)*step)
                    if l[i]<=lvl-T and lvl>dn+0.005: units+=1; cost+=lvl
                    else: break
            if units:
                sp=cl[-1]-T
                if cl[-1]<=dn+0.001: continue
                p=((sp*units-cost)/(cost/units))*1e4-FEE*units
                res1.setdefault(step,{})[(cd,d)]=(p,units)
# 5-minute version for the same stock-days
D=lib5.load(2026); O,Hh,L,C,pc,up,V,code=D['O'],D['H'],D['L'],D['C'],D['pc'],D['up'],D['V'],D['code']
dn5=np.round(pc*(1-np.where(up/pc>1.15,0.2,0.1))+1e-9,2)
key={(a,b):i for i,(a,b) in enumerate(zip(code,D['date']))}
P=np.load(f'{H}/research/brk/offpred.npz',allow_pickle=True); pp={d:p for d,p in zip(P['date'],P['pred'])}
for step in (0.015,0.02):
    r1=res1[step]; both=[]; only1=0
    for (cd,d),(p,u) in r1.items():
        i=key.get((cd,d))
        if i is None or not np.isfinite(pc[i]): continue
        ref=C[i,11]; units=0; cost=0.
        for j in range(12,24):
            while units<3:
                lvl=ref*(1-(units+1)*step)
                if L[i,j]<=lvl-T and lvl>dn5[i]+0.005: units+=1; cost+=lvl
                else: break
        p5=((C[i,-1]-T)*units-cost)/(cost/units)*1e4-FEE*units if units else np.nan
        both.append((d,p,u,p5,units))
    d=np.array([b[0] for b in both]); p1=np.array([b[1] for b in both]); u1=np.array([b[2] for b in both]); p5=np.array([b[3] for b in both]); u5=np.array([b[4] for b in both])
    m=np.isfinite(p5)
    keep=np.array([pp.get(x,np.nan)>=0 for x in d])
    print(f'间隔{step*100:g}%：1分钟线成交 {len(p1)} 次，其中 5 分钟线也成交 {m.sum()} 次；份数相同的比例 {np.mean(u1[m]==u5[m])*100:.0f}%；两者每次收益相关 {np.corrcoef(p1[m],p5[m])[0,1]:.2f}')
    print(f'   每份：1分钟 {p1.sum()/u1.sum():+.1f}bp  5分钟(同样的股票日) {np.nansum(p5)/u5[m].sum():+.1f}bp | 只做“预测下午≥0”的日子：1分钟 {p1[keep].sum()/u1[keep].sum():+.1f}bp（{len(np.unique(d[keep]))}天）  5分钟 {np.nansum(p5[keep&m])/u5[keep&m].sum():+.1f}bp')

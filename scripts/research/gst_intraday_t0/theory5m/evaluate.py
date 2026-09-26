"""Trade every theory signal as 底仓做T on 5-minute bars: first signal of the day (bar close), enter at the next bar's
open (buy +1 tick for 先买后卖, sell -1 tick for 先卖后买), exit at the close (or swing: 1% stop, after +1% a 0.5% giveback).
Costs 万1 免五 + stamp 5 bp + transfer: 7.2 bp round trip. Limit-up buys / limit-down sells skipped; a 先卖 whose close is
sealed at limit-up buys back at the next open. Research only."""
import polars as pl, numpy as np, glob, sys, itertools
T=0.01; FEE=7.2
bars=pl.read_parquet(__import__('os').environ.get('THEORY_BARS','bars.parquet'))
files=glob.glob('sig/*.parquet')
sig=pl.concat([pl.read_parquet(f) for f in files])
done={(int(f.split('/')[-1][:4]),f.split('/')[-1][5:-8]) for f in files}
slots=sorted(bars['hm'].unique().to_list()); si={s:i for i,s in enumerate(slots)}
G={}
for (y,s),g in bars.group_by(['year','symbol']):
    if (y,s) not in done: continue
    g=g.sort('date','hm'); dates=np.array(sorted(set(g['date'].to_list()))); di={d:i for i,d in enumerate(dates)}
    r=np.array([di[d] for d in g['date']]); c=np.array([si[h] for h in g['hm']])
    A={}
    for k in ('open','high','low','close'):
        a=np.full((len(dates),48),np.nan); a[r,c]=g[k].to_numpy(); A[k]=a
    C=A['close']
    for i in range(48):
        m=np.isnan(C[:,i]); C[m,i]=A['open'][m,i] if i==0 else C[m,i-1]
    for k in ('open','high','low'): A[k]=np.where(np.isnan(A[k]),C,A[k])
    pc=np.r_[np.nan,C[:-1,-1]]; nO=np.r_[A['open'][1:,0],np.nan]
    lim=0.2 if (s.startswith('sh.688') or s.startswith('sz.30')) else 0.1
    G[(y,s)]=dict(dates=dates,O=A['open'],H=A['high'],L=A['low'],C=C,pc=pc,nO=nO,up=np.round(pc*(1+lim)+1e-9,2),dn=np.round(pc*(1-lim)+1e-9,2),iny=np.array([d>=f'{y}-01-01' for d in dates]),di=di)
sig=sig.with_columns(pl.col('datetime').dt.strftime('%Y-%m-%d').alias('d'),pl.col('datetime').dt.strftime('%H%M').alias('hm'))
def trade(g,i,col,d,ex):
    e=col+1
    if e>=46 or not g['iny'][i] or np.isnan(g['pc'][i]): return None
    O,H,L,C=g['O'][i],g['H'][i],g['L'][i],g['C'][i]
    if d==1:
        ent=O[e]+T
        if ent>=g['up'][i]-0.005: return None
        px=C[-1]-T
        if ex=='swing':
            peak=ent
            for j in range(e,47):
                lvl=ent*0.99
                if peak>=ent*1.01: lvl=max(lvl,peak*0.995)
                if L[j]<=lvl: px=min(O[j],lvl)-T; break
                peak=max(peak,H[j])
        return (px/ent-1)*1e4-FEE
    else:
        sell=O[e]-T
        if sell<=g['dn'][i]+0.005: return None
        buy=C[-1]+T
        if C[-1]>=g['up'][i]-0.001: buy=g['nO'][i]+T if np.isfinite(g['nO'][i]) else np.nan
        if ex=='swing':
            trough=sell
            for j in range(e,47):
                lvl=sell*1.01
                if trough<=sell*0.99: lvl=min(lvl,trough*1.005)
                if H[j]>=lvl:
                    buy=max(O[j],lvl)+T
                    if C[j]>=g['up'][i]-0.001: buy=g['nO'][i]+T
                    break
                trough=min(trough,L[j])
        return (sell/buy-1)*1e4-FEE
import os
os.makedirs('tr',exist_ok=True)
for (fac,),fgrp in sig.group_by(['factor']):
  rows=[]
  for (y,s),grp in fgrp.group_by(['year','symbol']):
    g=G.get((y,s))
    if g is None: continue
    first={}
    for d,hm in zip(grp['d'].to_list(),grp['hm'].to_list()):
        if hm not in si: continue
        c=si[hm]
        if d in g['di'] and c<=44 and (d not in first or c<first[d]): first[d]=c
    for d,c in first.items():
        i=g['di'][d]
        for dr,ex in itertools.product((1,-1),('close','swing')):
            v=trade(g,i,c,dr,ex)
            if v is not None and np.isfinite(v): rows.append((dr,ex,d,s,float(v)))
  if rows:
    pl.DataFrame(rows,schema=['dir','exit','date','symbol','bp'],orient='row').with_columns(pl.lit(fac).alias('factor')).write_parquet(f'tr/{fac}.parquet')
R=pl.concat([pl.read_parquet(f) for f in __import__('glob').glob('tr/*.parquet')])
R.write_parquet('trades.parquet'); print('trades',R.height,'stock-years',len(G))

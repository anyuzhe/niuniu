"""Timed trades for money-management tests: selected theory signals (implied direction), several trades per stock-day
(re-entry allowed after the previous one exits), exit by swing (1% stop, after +1% a 0.5% giveback) or at the close.
Records entry bar e and exit bar x so same-day outcomes can be sequenced. Costs 7.2 bp + 1 tick each side. Research only."""
import polars as pl, numpy as np, glob, sys
exec(open('evaluate.py').read().split("sig=sig.with_columns")[0])   # reuse bar grids G and constants
sig=sig.with_columns(pl.col('datetime').dt.strftime('%Y-%m-%d').alias('d'),pl.col('datetime').dt.strftime('%H%M').alias('hm'))
SEL={'ICT.MSS_UP':1,'ICT.MSS_DOWN':-1,'SMC.BOS_UP':1,'SMC.BOS_DOWN':-1,'ZONE.FVG_BULL_CREATED':1,'ZONE.FVG_BEAR_CREATED':-1,
     'ICT.DISPLACEMENT_UP':1,'ICT.DISPLACEMENT_DOWN':-1,'WYCKOFF.SOS':1,'WYCKOFF.SOW':-1,'BROOKS.SECOND_UP':1,'BROOKS.SECOND_DOWN':-1}
def one(g,i,e,dr,ex):
    O,H,L,C=g['O'][i],g['H'][i],g['L'][i],g['C'][i]; x=47
    if dr==1:
        ent=O[e]+T
        if ent>=g['up'][i]-0.005: return None
        px=C[-1]-T; peak=ent
        if ex=='swing':
            for j in range(e,47):
                lvl=ent*0.99
                if peak>=ent*1.01: lvl=max(lvl,peak*0.995)
                if L[j]<=lvl: px=min(O[j],lvl)-T; x=j; break
                peak=max(peak,H[j])
        return x,(px/ent-1)*1e4-FEE
    sell=O[e]-T
    if sell<=g['dn'][i]+0.005: return None
    buy=C[-1]+T
    if C[-1]>=g['up'][i]-0.001: buy=g['nO'][i]+T
    trough=sell
    if ex=='swing':
        for j in range(e,47):
            lvl=sell*1.01
            if trough<=sell*0.99: lvl=min(lvl,trough*1.005)
            if H[j]>=lvl:
                buy=max(O[j],lvl)+T; x=j
                if C[j]>=g['up'][i]-0.001: buy=g['nO'][i]+T
                break
            trough=min(trough,L[j])
    return x,(sell/buy-1)*1e4-FEE
rows=[]
for (fac,y,s),grp in sig.filter(pl.col('factor').is_in(list(SEL))).group_by(['factor','year','symbol']):
    g=G.get((y,s)); dr=SEL[fac]
    if g is None: continue
    byday={}
    for d,hm in zip(grp['d'].to_list(),grp['hm'].to_list()):
        if hm in si and d in g['di']: byday.setdefault(d,[]).append(si[hm])
    for d,cols in byday.items():
        i=g['di'][d]
        if not g['iny'][i] or np.isnan(g['pc'][i]): continue
        for ex in ('swing','close'):
            busy=-1
            for c in sorted(set(cols)):
                e=c+1
                if c<=busy or e>=46 or c>44: continue
                r=one(g,i,e,dr,ex)
                if r is None or not np.isfinite(r[1]): continue
                rows.append((fac,ex,d,s,e,r[0],float(r[1]))); busy=r[0] if ex=='swing' else 99
R=pl.DataFrame(rows,schema=['strategy','exit','date','symbol','e','x','bp'],orient='row')
R.write_parquet('mm_theory.parquet'); print(R.group_by('strategy','exit').agg(pl.len(),pl.col('bp').mean()).sort('strategy','exit'))

import polars as pl, numpy as np
R=pl.read_parquet('trades.parquet').with_columns(pl.when(pl.col('date')<'2023').then(pl.lit('20-22')).when(pl.col('date')<'2025').then(pl.lit('23-24')).otherwise(pl.lit('25-26')).alias('p'))
def st(x):
    v=x['bp'].to_numpy(); 
    if len(v)<30: return None
    d=x['date'].to_numpy(); u,iv=np.unique(d,return_inverse=True); m=v.mean(); r=np.bincount(iv,v-m); w=v>0
    return dict(n=len(v),m=m,t=m/(np.sqrt((r**2).sum())/len(v)),win=w.mean(),pay=v[w].mean()/-v[~w].mean() if (~w).any() and w.any() else np.nan)
f=lambda s:'—' if s is None else f"{s['m']:+6.1f}bp 胜{s['win']*100:3.0f}% 赔{s['pay']:.2f} t{s['t']:+4.1f} n{s['n']}"
out=[]
for (fac,dr,ex),g in R.group_by(['factor','dir','exit']):
    ss={p:st(g.filter(pl.col('p')==p)) for p in ('20-22','23-24','25-26')}
    if ss['20-22'] is None or ss['20-22']['n']<100: continue
    out.append((fac,dr,ex,ss))
print('组合数',len(out),'训练期(2020-22)为正',sum(o[3]['20-22']['m']>0 for o in out),'三段都为正',sum(all(o[3][p] is not None and o[3][p]['m']>0 for p in o[3]) for o in out))
out.sort(key=lambda o:-o[3]['20-22']['m'])
for fac,dr,ex,ss in out[:20]:
    print(f"{fac:32s} {'先买' if dr==1 else '先卖'} {ex:5s} | 20-22 {f(ss['20-22'])} | 23-24 {f(ss['23-24'])} | 25-26 {f(ss['25-26'])}")
import collections
fam=collections.defaultdict(list)
for fac,dr,ex,ss in out: fam[fac.split('.')[0]].append(ss['20-22']['m'])
print({k:(len(v),round(float(np.median(v)),1),round(float(max(v)),1)) for k,v in fam.items()})
print()
for pre in ('ICT.','SMC.','ZONE.','BROOKS.','WYCKOFF.','CHAN.'):
    sub=[o for o in out if o[0].startswith(pre)][:3]
    for fac,dr,ex,ss in sub: print(f"{fac:32s} {'先买' if dr==1 else '先卖'} {ex:5s} | 20-22 {f(ss['20-22'])} | 23-24 {f(ss['23-24'])} | 25-26 {f(ss['25-26'])}")
g=R.with_columns((pl.col('bp')+7.2).alias('g')).group_by('dir').agg(pl.col('g').mean(),pl.len()); print(g)
print('factors', R['factor'].n_unique())

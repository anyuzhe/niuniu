"""Aggregate 分批抄底 results (research only)."""
import pickle, numpy as np, os, collections
H=os.environ['HOME']; R={}
for y in range(2020,2027):
    for k,v in pickle.load(open(f'{H}/research/brk/dip_{y}.pkl','rb')).items(): R.setdefault(k,{})[y]=v
P={'20-22':(2020,2021,2022),'23-24':(2023,2024),'25-26':(2025,2026)}
def st(k,ys):
    vs=[R[k][y] for y in ys if R[k][y]['n']>0]
    n=sum(v['n'] for v in vs)
    if n<50: return None
    s=sum(v['s'] for v in vs); u=sum(v['units'] for v in vs); m=s/n
    res=np.concatenate([v['ds']-m*v['dc'] for v in vs]); se=np.sqrt((res**2).sum())/n
    nw=sum(v['nw'] for v in vs); sw=sum(v['sw'] for v in vs); sl=sum(v['sl'] for v in vs)
    full=sum(v['full'] for v in vs); fp=sum(v['fullpnl'] for v in vs)
    return dict(n=n,ep=m,unit=s/u,t=m/se,win=nw/n,pay=(sw/max(nw,1))/(-sl/max(n-nw,1)),tp=sum(v['tp'] for v in vs)/n,
                full=full/n,fullm=fp/max(full,1),q1=np.mean([v['q'][0] for v in vs]))
f=lambda s:'—' if s is None else f"每份{s['unit']:+6.1f} 每天次{s['ep']:+6.1f} 胜{s['win']*100:3.0f}% 赔{s['pay']:.2f} t{s['t']:+4.1f} 反弹卖出{s['tp']*100:3.0f}% 买满{s['full']*100:3.0f}%(每次{s['fullm']:+.0f}) 最差1%{s['q1']:+.0f} n{s['n']}"
lab=lambda k:f"{k[0]} 间隔{k[1]*100:g}% 最多{k[2]}次 反弹{'收盘卖' if k[3] is None else f'{k[3]*100:g}%卖'} {'大盘跌1%不做' if k[4] else ''}"
rows=[(st(k,P['20-22']),k) for k in R]; rows=[r for r in rows if r[0]]
print('组合',len(rows),'2020-22 每份为正',sum(r[0]['unit']>0 for r in rows),'三段每份都为正',sum(all((st(k,p) or {'unit':-1})['unit']>0 for p in P.values()) for _,k in rows))
rows.sort(key=lambda r:-r[0]['unit'])
for s,k in rows[:12]:
    print(lab(k)); [print(f'    {p}: {f(st(k,ys))}') for p,ys in P.items()]
print('\n各时段最好的（按 2020-22 每份）：')
best={}
for s,k in rows:
    if k[0] not in best: best[k[0]]=k
for w,k in best.items(): print(' ',lab(k),'|',' | '.join(f"{p} {st(k,ys)['unit']:+.1f}" for p,ys in P.items()))
print('\n典型设置（间隔1%、最多3次、反弹0.5%卖、不加大盘过滤）各时段：')
for w in best:
    k=(w,0.01,3,0.005,0); print(' ',w,' | '.join(f"{p} {f(st(k,ys))}" for p,ys in P.items()))

import pickle, numpy as np, os
H=os.environ['HOME']; R={}
for y in range(2020,2027):
    for k,v in pickle.load(open(f'{H}/research/brk/dip2_{y}.pkl','rb')).items(): R.setdefault(k,{})[y]=v
P={'20-22':(2020,2021,2022),'23-24':(2023,2024),'25-26':(2025,2026)}
def st(k,ys):
    vs=[R[k][y] for y in ys]; n=sum(v['n'] for v in vs); s=sum(v['s'] for v in vs); u=sum(v['units'] for v in vs); m=s/n
    res=np.concatenate([v['ds']-m*v['dc'] for v in vs]); se=np.sqrt((res**2).sum())/n
    nw=sum(v['nw'] for v in vs); sw=sum(v['sw'] for v in vs); sl=sum(v['sl'] for v in vs)
    return dict(unit=s/u,t=m/se,win=nw/n,pay=(sw/max(nw,1))/(-sl/max(n-nw,1)),big=sum(v['big'] for v in vs)/n,q1=np.mean([v['q'][0] for v in vs]),n=n)
f=lambda s:f"每份{s['unit']:+6.1f} 胜{s['win']*100:3.0f}% 赔{s['pay']:.2f} t{s['t']:+4.1f} 亏3%以上{s['big']*100:4.1f}% 最差1%{s['q1']:+5.0f}"
lab=lambda k:f"{k[0]} 间隔{k[1]*100:g}% 最多{k[2]}次 {'收盘卖' if k[3] is None else f'反弹{k[3]*100:g}%卖'} " + ('无大盘保护' if k[4] is None else f"大盘再跌{k[4]*100:g}%{'停止加仓' if k[5]=='A' else '全部卖出'}")
print('组合',len(R),'三段每份都为正',sum(all(st(k,p)['unit']>0 for p in P.values()) for k in R))
for key in [('10:30-11:30',0.01,3,0.005),('10:30-11:30',0.015,3,None),('10:00-11:30',0.01,3,0.005),('13:30-14:30',0.01,3,0.005)]:
    print()
    for g,mode in ((None,'A'),(0.003,'A'),(0.005,'A'),(0.01,'A'),(0.003,'B'),(0.005,'B'),(0.01,'B')):
        k=key+(g,mode); print(' ',lab(k)); print('     '+' | '.join(f'{p} {f(st(k,ys))}' for p,ys in P.items()))
rows=sorted(R,key=lambda k:-st(k,P['20-22'])['unit'])[:5]
print('\n2020-22 最好的 5 组：')
for k in rows: print(' ',lab(k),'|',' | '.join(f'{p} {f(st(k,ys))}' for p,ys in P.items()))

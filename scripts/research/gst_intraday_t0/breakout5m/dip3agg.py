import pickle, numpy as np, os
H=os.environ['HOME']; R={}
for y in range(2020,2027):
    for k,v in pickle.load(open(f'{H}/research/brk/dip3_{y}.pkl','rb')).items(): R.setdefault(k,{})[y]=v
P={'20-22':(2020,2021,2022),'23-24':(2023,2024),'25-26':(2025,2026)}
def st(k,ys):
    vs=[R[k][y] for y in ys]; n=sum(v['n'] for v in vs)
    if n<30: return None
    s=sum(v['s'] for v in vs); u=sum(v['units'] for v in vs); m=s/n
    res=np.concatenate([v['ds']-m*v['dc'] for v in vs]); se=np.sqrt((res**2).sum())/n
    nw=sum(v['nw'] for v in vs); sw=sum(v['sw'] for v in vs); sl=sum(v['sl'] for v in vs)
    return dict(unit=s/u,t=m/se,win=nw/n,pay=(sw/max(nw,1))/(-sl/max(n-nw,1)),big=sum(v['big'] for v in vs)/n,n=n)
f=lambda s:'—' if s is None else f"每份{s['unit']:+6.1f} 胜{s['win']*100:3.0f}% 赔{s['pay']:.2f} t{s['t']:+4.1f} 亏3%以上{s['big']*100:4.1f}% n{s['n']}"
FN={'无':'不过滤','F1':'大盘比昨收低不买','F2':'大盘近30分钟在跌不买','F3':'两条都满足才买','F4':'大盘比开盘低不买','ORACLE':'事后知道大盘10:30后不大跌(上限)'}
lab=lambda k:f"{k[0]} 间隔{k[1]*100:g}% 最多{k[2]}次 {'收盘卖' if k[3] is None else f'反弹{k[3]*100:g}%卖'}"
real=[k for k in R if k[4]!='ORACLE']
print('组合(不含上限)',len(real),'2020-22 每份为正',sum((st(k,P['20-22']) or {'unit':-1})['unit']>0 for k in real),'三段都为正',sum(all((st(k,p) or {'unit':-1})['unit']>0 for p in P.values()) for k in real))
print('上限组合',len(R)-len(real),'三段都为正',sum(all((st(k,p) or {'unit':-1})['unit']>0 for p in P.values()) for k in R if k[4]=='ORACLE'))
for key in [('10:30-11:30',0.01,3,0.005),('10:30-11:30',0.015,3,None),('10:00-11:30',0.01,3,0.005),('13:30-14:30',0.01,3,0.005),('全天09:40-14:30',0.01,3,0.005)]:
    print('\n'+lab(key))
    for fl in FN: k=key+(fl,); print(f'   {FN[fl]:22s} '+' | '.join(f'{p} {f(st(k,ys))}' for p,ys in P.items()))
rows=sorted(real,key=lambda k:-(st(k,P['20-22']) or {'unit':-99})['unit'])[:6]
print('\n2020-22 最好的 6 组（实际可用的过滤）：')
for k in rows: print(' ',lab(k),FN[k[4]],'|',' | '.join(f'{p} {f(st(k,ys))}' for p,ys in P.items()))

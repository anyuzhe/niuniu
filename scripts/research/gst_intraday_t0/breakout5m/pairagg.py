import pickle, numpy as np, os
H=os.environ['HOME']; A={}
for y in range(2020,2027):
    for k,v in pickle.load(open(f'{H}/research/brk/pairs_{y}.pkl','rb')).items(): A.setdefault(k,[]).extend(v)
P={'20-22':('2000','2023'),'23-24':('2023','2025'),'25-26':('2025','2100')}
print('配对做T：两条腿合计每次（bp，按一条腿的金额；成本已扣两个来回 14.4bp + 4 个价位）')
for k in sorted(A):
    d=np.array([x[0] for x in A[k]]); v=np.array([x[1] for x in A[k]])
    s=f'  相关≥{k[0]} 差距≥{k[1]*100:g}% 出场{"收盘" if k[2]=="close" else "差距减半"}'
    for pn,(lo,hi) in P.items():
        m=(d>=lo)&(d<hi); x=v[m]
        if len(x)<30: s+=f' | {pn} —'; continue
        u,iv=np.unique(d[m],return_inverse=True); mm=x.mean(); r=np.bincount(iv,x-mm); w=x>0
        s+=f' | {pn} {mm:+6.1f} 毛{mm+14.4:+6.1f} 胜{w.mean()*100:3.0f}% 赔{x[w].mean()/-x[~w].mean():.2f} t{mm/(np.sqrt((r**2).sum())/len(x)):+4.1f} n{len(x)}'
    print(s)

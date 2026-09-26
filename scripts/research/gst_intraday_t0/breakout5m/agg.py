"""Aggregate scan results: train 2020-22, test 2023-24, fresh 2025-26 (research only)."""
import pickle, numpy as np, os, sys, glob
H=os.environ['HOME']
R={}
for f in glob.glob(f'{H}/research/brk/res_*_*.pkl'):
    yr=int(f[-8:-4])
    for k,v in pickle.load(open(f,'rb')).items(): R.setdefault(k,{})[yr]=v
def st(k,yrs):
    vs=[R[k][y] for y in yrs if y in R[k] and R[k][y]['n']>0]
    if not vs: return None
    n=sum(v['n'] for v in vs); s=sum(v['s'] for v in vs); m=s/n
    nw=sum(v['nw'] for v in vs); sw=sum(v['sw'] for v in vs); sl=sum(v['sl'] for v in vs)
    res=np.concatenate([v['ds']-m*v['dc'] for v in vs]); se=np.sqrt((res**2).sum())/n
    days=sum(len(v['dates']) for v in vs)
    return dict(n=n,days=days,bp=m,win=nw/n,pay=(sw/max(nw,1))/(-sl/max(n-nw,1)) if n>nw else np.nan,t=m/se if se>0 else np.nan)
def fmt(x): return '—' if x is None else f"{x['bp']:+6.1f}bp n{x['n']:6d} d{x['days']:4d} 胜{x['win']*100:4.1f}% 赔{x['pay']:.2f} t{x['t']:+5.1f}"
if __name__=='__main__':
    TR=(2020,2021,2022);TE=(2023,2024);NW=(2025,2026)
    rows=[]
    for k in R:
        a=st(k,TR)
        if a and a['n']>=200: rows.append((a['bp'],k,a))
    rows.sort(key=lambda x:-x[0])
    fam=sys.argv[1] if len(sys.argv)>1 else None
    print('baselines:')
    for k in sorted(k for k in R if k[0]=='Z' and k[-1]=='close'):
        print(k,'train',fmt(st(k,TR)),'| test',fmt(st(k,TE)),'| new',fmt(st(k,NW)))
    for F in 'ABC':
        sub=[x for x in rows if x[1][0]==F]
        print(f'\n== family {F}: {len(sub)} combos with >=200 train trades; share with train bp>0: {np.mean([x[0]>0 for x in sub]):.2f}')
        for bp,k,a in sub[:8]:
            print(k,'train',fmt(a),'| test',fmt(st(k,TE)),'| new',fmt(st(k,NW)))

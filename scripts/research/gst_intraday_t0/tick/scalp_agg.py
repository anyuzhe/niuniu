import pickle, glob, os, numpy as np
H=os.environ['HOME']; A={}
LOW={'sh.601777','sz.000563','sz.000592','sz.300040'}
for f in glob.glob(f'{H}/research/tick/sc_*.pkl'):
    sym=f[-13:-4]
    for k,v in pickle.load(open(f,'rb')).items():
        if v: A.setdefault(k,[]).append((sym,np.array([x[0] for x in v]),np.array([x[1:] for x in v],float)))
def st(parts):
    if not parts: return None
    d=np.concatenate([p[1] for p in parts]); X=np.vstack([p[2] for p in parts]); net=X[:,2]
    gross=net+10.2; w=net>0; ud,iv=np.unique(d,return_inverse=True); m=net.mean(); r=np.bincount(iv,net-m)
    return dict(n=len(net),net=m,gross=gross.mean(),win=w.mean(),pay=net[w].mean()/-net[~w].mean() if w.any() else np.nan,
                t=m/(np.sqrt((r**2).sum())/len(net)),hold=X[:,3].mean(),tick=((X[:,1]-X[:,0])/0.01).mean())
def f(s): return f"净{s['net']:+6.1f}bp 毛{s['gross']:+6.1f} 平均赚{s['tick']:+.2f}个价位 胜{s['win']*100:4.1f}% 赔{s['pay']:.2f} t{s['t']:+5.1f} 持{s['hold']:4.0f}秒 n{s['n']}"
rows=[]
for k,parts in A.items():
    a=st(parts); lo=st([p for p in parts if p[0] in LOW])
    rows.append((a['net'],k,a,lo))
rows.sort(key=lambda x:-x[0])
print('全部 16 只，净收益最好的 12 组：')
for _,k,a,lo in rows[:12]: print(' ',k,'\n     全部',f(a),'\n     低价4只',f(lo))
print('\n低价4只（2.7–6 元）净收益最好的 6 组：')
for k,a,lo in sorted([(r[1],r[2],r[3]) for r in rows],key=lambda x:-x[2]['net'])[:6]: print(' ',k,'低价',f(lo))
print('\n组合数',len(rows),'为正',sum(r[0]>0 for r in rows),'低价为正',sum(r[3]['net']>0 for r in rows))

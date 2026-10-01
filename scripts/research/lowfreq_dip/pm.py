"""Position sizing test: concentration (N), rank-tilted weights, per-day buy cap. z<=-1.5 x E6, unlevered, 2008-2026. Research only."""
import numpy as np, time; T0=time.time()
exec(open('stockport.py').read().split("print('格式")[0])
def pw(sig,pool,N,rank=None,tilt=None,maxper=None,seed=7,start='2008-01-01'):
    rg=np.random.default_rng(seed); t0=int(np.searchsorted(dates,start)); cash=1.0; act=[]; eq=np.full(nd,np.nan); expo=np.zeros(nd); trades=[]; wts=[]
    for t in range(t0,nd-H-1):
        e=t+1
        for p in [p for p in act if p['x']==t]:
            cash+=p['inv']*(1+p['net']); trades.append((p['net'],p['inv']/p['E0'])); act.remove(p)
        slots=N-len(act)
        if slots>0 and sig[t]:
            cs=np.nonzero(pool[t])[0]
            if len(cs):
                held={p['j'] for p in act}; cs=[j for j in cs if j not in held]
                if rank is None: rg.shuffle(cs)
                else: cs=sorted(cs,key=lambda j:rank[t,j])
                B=min(slots,len(cs),maxper or 999); cs=cs[:B]
                if tilt=='lin': w=np.arange(B,0,-1,dtype=float)
                elif tilt=='geo': w=0.8**np.arange(B)
                elif tilt=='top': w=np.where(np.arange(B)<max(1,B//3),2.0,0.5)
                else: w=np.ones(B)
                w=w/w.mean()
                invested=sum(p['v'] for p in act); E=cash+invested
                for k,j in enumerate(cs):
                    size=min(E/N*w[k],E-invested)
                    if size<=1e-9: break
                    cash-=size; invested+=size; costE=0.01/float(rawE[t,j])+fee1[t+H]/2
                    act.append(dict(j=j,e=e,x=t+H,inv=size,v=size,E0=E,net=float(net[t,j]),o0=float(o[e,j]),costE=costE))
        tot=cash
        for p in act:
            if p['e']<=t: p['v']=p['inv']*(float(c[t,p['j']])/p['o0'] if np.isfinite(c[t,p['j']]) else 1.0)*(1-p['costE'])
            tot+=p['v']
        eq[t]=tot; expo[t]=(tot-cash)/tot
    return eq,expo,np.array(trades)
def row(tag,eq,expo,tr):
    cells=[]
    for pn,(a,b) in ERA.items():
        s=stats(eq,expo,a,b); cells.append('无' if s is None else f'{s[0]*100:+5.1f}/{s[1]:+.2f}/{s[2]*100:3.0f}')
    s=stats(eq,expo,'2008-01-01','2026-12-31'); n=tr[:,0]; wt=tr[:,1]
    print(f'{tag:26s}| '+' | '.join(cells)+f' | 仓{s[3]*100:2.0f}% 笔{len(n)} 单笔最大占比{wt.max()*100:.0f}% 最差单笔拖累{(n*wt).min()*100:.1f}%',flush=True)
print('格式：年化%/夏普/回撤%；列='+' | '.join(ERA))
sig=zv<=-1.5; res={}
print('\n[A] 持仓只数 N（等权，E6 候选）')
for N in (3,5,8,10,15,20,30,50):
    eq,ex,tr=pw(sig,e6,N,rank=ret20); res[('r',N)]=(eq,ex); row(f'N={N} 跌幅排序',eq,ex,tr)
for N in (3,5,10,20,50):
    cg=[]
    for s in range(6):
        eq,ex,tr=pw(sig,e6,N,seed=s); cg.append(stats(eq,ex,'2008-01-01','2026-12-31'))
    print(f'N={N} 随机(6种子) 年化 '+' '.join(f'{x[0]*100:+.1f}' for x in cg)+' 回撤 '+' '.join(f'{x[2]*100:.0f}' for x in cg),flush=True)
print('\n[B] 排序靠前多买（N 固定，同一批里按排名倾斜金额）')
for N in (10,20):
    for tl in (None,'lin','geo','top'):
        eq,ex,tr=pw(sig,e6,N,rank=ret20,tilt=tl); row(f'N={N} 倾斜={tl}',eq,ex,tr)
print('\n[C] 每个信号日最多买 m 只（N 固定）')
for N in (10,20):
    for m in (1,2,3,5):
        eq,ex,tr=pw(sig,e6,N,rank=ret20,maxper=m); row(f'N={N} 日最多{m}只',eq,ex,tr)
print('\n[D] 同样的 N，用 S3 之外的随机对照 + 门更宽 z<=-1.0')
for N in (5,10,20):
    eq,ex,tr=pw(zv<=-1.0,e6,N,rank=ret20); row(f'z<=-1.0 N={N} 排序',eq,ex,tr)
print('done',round(time.time()-T0))

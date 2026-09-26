"""Re-price reversal-side, gap-fade and overnight results at 7.2 bp round trip (research only)."""
import numpy as np, os, pickle
H=os.environ['HOME']
adj=lambda d: np.where(np.asarray(d)>='2023-08-28',3.0,8.0)
P=lambda d:{'20-22':d<'2023','23-24':(d>='2023')&(d<'2025'),'25-26':d>='2025'}
def st(y,d,mk):
    mk=mk&np.isfinite(y)
    if mk.sum()<30: return '—'
    ud,inv=np.unique(d[mk],return_inverse=True); v=y[mk]; m=v.mean(); r=np.bincount(inv,v-m); w=v>0
    return f"{m:+6.1f}bp 胜{w.mean()*100:3.0f}% 赔{v[w].mean()/-v[~w].mean():.2f} t{m/(np.sqrt((r**2).sum())/len(v)):+4.1f} n{mk.sum()}"
def show(lab,y,d,mk): print(f"  {lab:26s}"+''.join(f" | {p} {st(y,d,mk&pm)}" for p,pm in P(d).items()))
Z={}
for yv in range(2020,2027):
    z=np.load(f'{H}/research/brk/rev_{yv}.npz',allow_pickle=True)
    for k in z.files: Z.setdefault(k,[]).append(z[k])
Z={k:np.concatenate(v) for k,v in Z.items()}; d=Z['date']; a=adj(d)
ud,inv=np.unique(d,return_inverse=True)
def dq(x,q=10):
    out=np.full(len(x),-1); fin=np.isfinite(x); order=np.lexsort((x,inv)); iv=inv[order]
    start=np.r_[0,np.cumsum(np.bincount(iv,minlength=len(ud)))[:-1]]; rk=np.arange(len(x))-start[iv]; cnt=np.bincount(inv[fin],minlength=len(ud))
    fo=fin[order]; out[order[fo]]=(rk[fo]*q//np.maximum(cnt[iv[fo]],1)).clip(0,q-1); return out
print('开盘先卖、收盘买回：'); y=Z['rev_open']+a; one=np.ones(len(d),bool)
show('全部',y,d,one); g=Z['gap']
for lo,hi,lab in ((0.02,0.04,'高开2-4%'),(0.04,0.07,'高开4-7%')): show(lab,y,d,(g>=lo)&(g<hi))
q=dq(g); show('高开最多的10%',y,d,q==9)
for tag in ('1000','1030'):
    q=dq(Z[f'rel{tag}'])
    show(f'{tag} 相对大盘最强10%先卖',Z[f'short{tag}']+a,d,q==9); show(f'{tag} 相对大盘最弱10%先买',Z[f'long{tag}']+a,d,q==0)
# gap fade
A={}
for yv in range(2020,2027):
    o=pickle.load(open(f'{H}/research/brk/gf_{yv}.pkl','rb'))
    for k,v in o.items(): A.setdefault(k,[]).append(v)
A={k:np.concatenate(v) for k,v in A.items()}; d2=A['date']; m7=A['gap']>=0.07
print('\n高开≥7% 先卖（收盘封板则次日开盘买回）：')
for k in (('time','收盘'),('stop',0.05),('stop',0.03)):
    y=A[k]+adj(d2); show(str(k),y,d2,m7)
    mk=m7&np.isfinite(y); v=y[mk]; iv=np.unique(d2[mk],return_inverse=True)[1]; m=v.mean(); r=np.bincount(iv,v-m)
    print(f"     合并 {m:+.1f}bp t{m/(np.sqrt((r**2).sum())/len(v)):+.1f}")
# overnight
O={}
for yv in range(2020,2027):
    z=np.load(f'{H}/research/brk/on_{yv}.npz',allow_pickle=True)
    for k in z.files: O.setdefault(k,[]).append(z[k])
O={k:np.concatenate(v) for k,v in O.items()}; d3=O['date']
print('\n隔夜T（今天收盘买、次日卖底仓）：')
for k in ('次日开盘','次日10:00','次日收盘'):
    y=O['on_'+k]; y=np.where(np.abs(y)>2500,np.nan,y)+adj(d3); show(k,y,d3,np.ones(len(d3),bool))

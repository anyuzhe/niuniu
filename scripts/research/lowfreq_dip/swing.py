"""Buy the dip, sell on a take-profit (optionally stop / max hold) -- stocks, real costs. Research only.
Entry: open of t+1 after signal on close t. Earliest exit t+2 (T+1). TP fill = max(open, TP) if high>=TP; stop fill = min(open, stop) if low<=stop
(stop checked first on the same day = pessimistic). Time exit: close of day N. Costs 7.2bp + 1 tick per side. Benchmark: random eligible entries, same rule."""
import numpy as np, sys, warnings; warnings.filterwarnings('ignore')
sys.argv=['x']; exec(open('lowfreq.py').read().split("mon=np.array")[0])
mon=np.array([d[:7] for d in dates]); N=20
rng_=np.random.default_rng(0)
buy_ok=np.zeros((nd,nc),bool); buy_ok[:-1]=fin[1:]&~limup_open[1:]&(np.arange(nd)[:-1,None].repeat(1,1)<nd-N-2 if False else True)
buy_ok[nd-N-3:]=False
valid=uni&buy_ok
def sim(di,ci,tp,sp):
    e=di+1; o=O[e,ci]; n=len(di); done=np.zeros(n,bool); px=np.full(n,np.nan); k_exit=np.zeros(n,int)
    tpP=o*(1+tp); spP=o*(1-sp) if sp else None
    for k in range(1,N+1):
        d=e+k; act=~done
        if not act.any(): break
        lo=L[d,ci]; hi=Hh[d,ci]; op=O[d,ci]; cl=C[d,ci]
        if sp:
            hs=act&(lo<=spP)&np.isfinite(lo); px[hs]=np.minimum(op[hs],spP[hs]); done|=hs; k_exit[hs]=k; act=~done
        ht=act&(hi>=tpP)&np.isfinite(hi); px[ht]=np.maximum(op[ht],tpP[ht]); done|=ht; k_exit[ht]=k
        if k==N:
            rest=~done; px[rest]=cl[rest]; k_exit[rest]=k
    ratio=px/o; rawE=Ro[e,ci]; rawX=rawE*ratio
    net=(px*(1-0.01/rawX))/(o*(1+0.01/rawE))-1-FEE
    return net,k_exit,ratio
def cl_t(x,g):
    u,inv=np.unique(g,return_inverse=True); m=x.mean(); s=np.bincount(inv,x-m); return m/(np.sqrt((s**2).sum())/len(x)+1e-18)
sigs={'V1基准(20日跌>10%)':base,'R2收盘位置(<0.3)':base&(cloc<0.3)}
# random benchmark entries
bd,bc=np.nonzero(valid); pick=rng_.choice(len(bd),400000,replace=False); bd,bc=bd[pick],bc[pick]
finite=np.isfinite(O[bd+1,bc])&np.isfinite(Ro[bd+1,bc]); bd,bc=bd[finite],bc[finite]
print('说明：净=扣7.2bp+每边1价位；超额=对同一批日期随机股票用同一止盈止损规则；最多持有20个交易日\n')
for tp in (0.03,0.05,0.08):
  for sp in (None,0.08):
    tag=f'止盈+{tp*100:.0f}%'+(f' 止损-{sp*100:.0f}%' if sp else ' 无止损')
    bn,bk,_=sim(bd,bc,tp,sp); fb=np.isfinite(bn); bdd=bd[fb]; bn=bn[fb]; bk=bk[fb]
    print(f'=== {tag}（最多20天）  随机股票: 净{bn.mean()*1e4:+.0f}bp 胜率{(bn>0).mean()*100:.0f}% 平均持有{bk.mean():.1f}天')
    for name,rm in sigs.items():
        di,ci=np.nonzero(valid&rm); sel=rng_.choice(len(di),min(len(di),250000),replace=False); di,ci=di[sel],ci[sel]
        ok=np.isfinite(O[di+1,ci])&np.isfinite(Ro[di+1,ci]); di,ci=di[ok],ci[ok]
        net,kx,_=sim(di,ci,tp,sp); f2=np.isfinite(net); net,kx,di=net[f2],kx[f2],di[f2]; out=[]
        for pn,(a,b) in per.items():
            m=(dates[di]>=a)&(dates[di]<=b)
            if m.sum()<200: continue
            x=net[m]; bm_=(dates[bdd]>=a)&(dates[bdd]<=b); xb=bn[bm_].mean(); w=x>0
            pay=x[w].mean()/-x[~w].mean(); out.append(f'{pn}: 净{x.mean()*1e4:+4.0f}bp(t{cl_t(x,mon[di][m]):+.1f}) 超额{(x.mean()-xb)*1e4:+4.0f} 胜率{w.mean()*100:.0f}% 赔率{pay:.2f} 持有{kx[m].mean():.1f}天 到期未止盈{(kx[m]==N).mean()*100:.0f}%')
        print('  '+name+'\n     '+'\n     '.join(out))

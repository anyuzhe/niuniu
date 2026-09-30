"""Buy the dip, sell on a take-profit (optionally stop / max hold) -- stocks, real costs. Research only.
Entry: open of t+1 after signal on close t. Earliest exit t+2 (T+1). TP fill = max(open, TP) if high>=TP; stop fill = min(open, stop) if low<=stop
(stop checked first on the same day = pessimistic). Time exit: close of day N. Costs 7.2bp + 1 tick per side. Benchmark: random eligible entries, same rule."""
import numpy as np, sys, warnings; warnings.filterwarnings('ignore')
sys.argv=['x']; exec(open('lowfreq.py').read().split("mon=np.array")[0])
mon=np.array([d[:7] for d in dates]); N=30
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

PH=np.full((nd,nc),-np.inf)
for k in range(20):
    sh=np.full((nd,nc),np.nan); sh[k:]=Hh[:nd-k]; PH=np.fmax(PH,np.where(np.isfinite(sh),sh,-np.inf))
PH=np.where(np.isfinite(PH),PH,np.nan)
sigs={'V1基准(20日跌>10%)':base,'R2收盘位置(<0.3)':base&(cloc<0.3)}
bd0,bc0=np.nonzero(valid); pick=rng_.choice(len(bd0),300000,replace=False); bd0,bc0=bd0[pick],bc0[pick]
ok0=np.isfinite(O[bd0+1,bc0])&np.isfinite(Ro[bd0+1,bc0]); bd0,bc0=bd0[ok0],bc0[ok0]
print(f'说明：目标价 = 买入价 + f×(前20日最高价 − 买入价)；f=1 表示回到前高。最多持有{N}天；净=扣7.2bp+每边1价位；超额=对同一批日期随机股票、用同样大小的止盈幅度的差\n')
for f in (0.33,0.5,0.67,1.0):
  for sp in (None,0.10):
    tag=f'回补{f*100:.0f}%前高缺口'+(f' 止损-{sp*100:.0f}%' if sp else ' 无止损')
    print('=== '+tag)
    for name,rm in sigs.items():
        di,ci=np.nonzero(valid&rm); sel=rng_.choice(len(di),min(len(di),250000),replace=False); di,ci=di[sel],ci[sel]
        o=O[di+1,ci]; ok=np.isfinite(o)&np.isfinite(Ro[di+1,ci])&np.isfinite(PH[di,ci]); di,ci,o=di[ok],ci[ok],o[ok]
        tp=f*(PH[di,ci]/o-1); keep=tp>0.02; di,ci,tp=di[keep],ci[keep],tp[keep]
        net,kx,_=sim(di,ci,tp,sp); f2=np.isfinite(net); net,kx,di,tp=net[f2],kx[f2],di[f2],tp[f2]
        # benchmark: random entries, target pct resampled from this signal's distribution
        tpb=rng_.choice(tp,len(bd0)); bnet,bk,_=sim(bd0,bc0,tpb,sp); fb=np.isfinite(bnet); bnet,bk,bdd=bnet[fb],bk[fb],bd0[fb]
        out=[]
        for pn,(a,b) in per.items():
            m=(dates[di]>=a)&(dates[di]<=b)
            if m.sum()<200: continue
            x=net[m]; bm_=(dates[bdd]>=a)&(dates[bdd]<=b); xb=bnet[bm_].mean(); w=x>0; pay=x[w].mean()/-x[~w].mean()
            out.append(f'{pn}: 净{x.mean()*1e4:+4.0f}bp(t{cl_t(x,mon[di][m]):+.1f}) 超额{(x.mean()-xb)*1e4:+4.0f} 胜率{w.mean()*100:.0f}% 赔率{pay:.2f} 目标涨幅中位{np.median(tp[m])*100:.0f}% 持有{kx[m].mean():.1f}天 到期未达标{(kx[m]==N).mean()*100:.0f}%')
        print('  '+name+'\n     '+'\n     '.join(out))

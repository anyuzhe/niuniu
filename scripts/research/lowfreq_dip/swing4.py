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
mon_i=np.array([int(m[:4])*12+int(m[5:7]) for m in mon])
def dedup(di,ci,kx):
    o=np.lexsort((di,ci)); di,ci,kx=di[o],ci[o],kx[o]; keep=np.zeros(len(di),bool); free=-1; last=-1
    for i in range(len(di)):
        if ci[i]!=last: last=ci[i]; free=-1
        if di[i]+1>free: keep[i]=True; free=di[i]+1+kx[i]
    return o[keep]

def qbucket(x,k=5):
    q=np.full(x.shape,-1,np.int8)
    for i in range(nd):
        r=x[i]; ok=uni[i]&np.isfinite(r)
        if ok.sum()<50: continue
        rk=np.argsort(np.argsort(r[ok])); q[i,np.nonzero(ok)[0]]=np.minimum((rk*k//ok.sum()),k-1)
    return q
VQ=qbucket(vol20); AQ=qbucket(amt20)
NM=mon_i.max()-mon_i.min()+1
def cell(di,ci): return ((mon_i[di]-mon_i.min())*5+VQ[di,ci])*5+AQ[di,ci]
bd0,bc0=np.nonzero(valid); pick=rng_.choice(len(bd0),900000,replace=False); bd0,bc0=bd0[pick],bc0[pick]
ok0=np.isfinite(O[bd0+1,bc0])&np.isfinite(Ro[bd0+1,bc0])&(VQ[bd0,bc0]>=0)&(AQ[bd0,bc0]>=0); bd0,bc0=bd0[ok0],bc0[ok0]
print('超额 = 减去“同月份、同波动率五分位、同成交额五分位”的随机股票平均（同样大小止盈幅度）；去重叠；最多持有30天\n')
for f,sp in ((0.5,None),(1.0,0.10)):
    print(f'=== 回补{f*100:.0f}%前高缺口'+(f' 止损-{sp*100:.0f}%' if sp else ' 无止损'))
    for name,rm in sigs.items():
        di,ci=np.nonzero(valid&rm&(VQ>=0)&(AQ>=0))
        o=O[di+1,ci]; ok=np.isfinite(o)&np.isfinite(Ro[di+1,ci])&np.isfinite(PH[di,ci]); di,ci,o=di[ok],ci[ok],o[ok]
        tp=f*(PH[di,ci]/o-1); keep=tp>0.02; di,ci,tp=di[keep],ci[keep],tp[keep]
        net,kx,_=sim(di,ci,tp,sp); f2=np.isfinite(net); net,kx,di,ci,tp=net[f2],kx[f2],di[f2],ci[f2],tp[f2]
        idx=dedup(di,ci,kx); di,ci,net,kx,tp=di[idx],ci[idx],net[idx],kx[idx],tp[idx]
        tpb=rng_.choice(tp,len(bd0)); bnet,bk,_=sim(bd0,bc0,tpb,sp); fb=np.isfinite(bnet); bn_,bd_,bc_=bnet[fb],bd0[fb],bc0[fb]
        cid=cell(bd_,bc_); ncell=NM*25; cs=np.bincount(cid,bn_,minlength=ncell); cn=np.bincount(cid,minlength=ncell)
        sc=cell(di,ci); have=cn[sc]>=5; 
        exc=np.where(have,net-cs[sc]/np.maximum(cn[sc],1),np.nan)
        vq_share=np.bincount(VQ[di,ci],minlength=5)/len(di)
        print(f'  {name}：信号所在波动率五分位占比 {np.round(vq_share,2)}，成交额五分位占比 {np.round(np.bincount(AQ[di,ci],minlength=5)/len(di),2)}')
        for pn,(a,b) in per.items():
            m=(dates[di]>=a)&(dates[di]<=b)&have
            print(f'     {pn}: {m.sum():5d}笔 净{net[m].mean()*1e4:+4.0f}bp 超额(控制波动率/成交额){exc[m].mean()*1e4:+4.0f}(t{cl_t(exc[m],mon[di][m]):+.1f})')
        yr_=np.array([d[:4] for d in dates[di]]); print('     分年: '+' '.join(f'{Y}:{np.nanmean(exc[yr_==str(Y)])*1e4:+.0f}' for Y in range(2020,2027) if ((yr_==str(Y))&have).sum()>50))

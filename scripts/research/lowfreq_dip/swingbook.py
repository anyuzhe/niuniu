"""Entry-point x exit-point swing grid on single stocks, real costs, 3 periods. Research only.
Signal at close of t (qfq); buy at open of t+1 (+1 tick). Exits: time / trailing stop / MA break / target-stop / RSI / MACD.
Signal exits fill at next open; stops fill at min(open,stop); limit-down close or suspension => next open. Costs 7.2bp + 1 tick per side.
Benchmark: random eligible entries (same universe) with the SAME exit rule; excess = net - same-month mean of benchmark."""
import numpy as np, sys, warnings, gc; warnings.filterwarnings('ignore')
sys.argv=['x']; exec(open('lowfreq.py').read().split("mon=np.array")[0])
from numpy.lib.stride_tricks import sliding_window_view as swv
for nm in ('step','s1','s2','rng','ret5','F','A','ST','TS','V0'):
    if nm in globals(): del globals()[nm]
gc.collect()
f32=np.float32
mon=np.array([d[:7] for d in dates]); um,monidx=np.unique(mon,return_inverse=True)
def ffill(a):
    idx=np.where(np.isfinite(a),np.arange(nd)[:,None],0); np.maximum.accumulate(idx,axis=0,out=idx)
    o=np.take_along_axis(a,idx,0); first=np.argmax(np.isfinite(a),0)
    o[np.arange(nd)[:,None]<first[None,:]]=np.nan; return o.astype(f32)
c=ffill(C); o_=ffill(O); h=ffill(Hh); l=ffill(L); v=ffill(V)
def sh(a,k):
    out=np.full_like(a,np.nan); out[k:]=a[:-k]; return out
def shb(a,k):
    out=np.zeros_like(a); out[k:]=a[:-k]; return out
def rmean(a,n): return (roll(a.astype(np.float64),n)/n).astype(f32)
def rmax(a,n):
    out=np.full_like(a,np.nan); out[n-1:]=swv(a,n,axis=0).max(-1); return out
def rmin(a,n):
    out=np.full_like(a,np.nan); out[n-1:]=swv(a,n,axis=0).min(-1); return out
def ema(a,alpha):
    out=np.full_like(a,np.nan); out[0]=a[0]
    for t in range(1,nd):
        p=out[t-1]; x=a[t]; out[t]=np.where(np.isfinite(p),np.where(np.isfinite(x),alpha*x+(1-alpha)*p,p),x)
    return out
m5,m10,m20,m60,m120=[rmean(c,n) for n in (5,10,20,60,120)]
sd20=np.sqrt(np.maximum(rmean(c*c,20)-m20*m20,0)); bup=m20+2*sd20; blo=m20-2*sd20
def rsi(n):
    d=c-sh(c,1); g=np.maximum(d,0); ls=np.maximum(-d,0); ag=ema(g,1.0/n); al=ema(ls,1.0/n)
    return (100*ag/np.where(al+ag>0,al+ag,np.nan)).astype(f32)
rsi3=rsi(3); rsi14=rsi(14)
dif=ema(c,2/13)-ema(c,2/27); dea=ema(dif,2/10)
golden=(dif>dea)&(sh(dif,1)<=sh(dea,1)); dead=(dif<dea)&(sh(dif,1)>=sh(dea,1))
hi20=rmax(h,20); lo20=rmin(l,20); hi20p=sh(hi20,1); lo20p=sh(lo20,1); minL3=rmin(l,3)
vma20p=sh(rmean(v,20),1); vma3p=sh(rmean(v,3),1)
c1=sh(c,1); c4=sh(c,4)
lst250=np.cumsum(np.isfinite(C),0)>=250
buy_ok=np.zeros((nd,nc),bool); buy_ok[:-1]=fin[1:]&~limup_open[1:]; buy_ok[nd-36:]=False
valid=uni&buy_ok&lst250&(R>=3)
KMAX=34
ent={}
ent['E0 参照:20日跌>10%&效率<0']=(mom20<-0.10)&(eff20<0)
ent['E1 回踩上升MA20后收复']=(minL3<=m20*1.005)&(c>m20)&(c>o_)&(m20>sh(m20,5))&(c>m60)
ent['E2 突破20日新高+放量1.5x']=(c>hi20p)&(v>1.5*vma20p)
ent['E3 强势股回调后企稳']=(c/sh(c,60)-1>0.2)&(c/hi20-1<=-0.06)&(c/hi20-1>=-0.20)&(c>o_)&(c>c1)
ent['E4 RSI(3)<10且在MA120上']=(rsi3<10)&(c>m120)
ent['E5 MACD零轴上金叉']=golden&(dif>0)
ent['E6 布林下轨收复']=(sh(c,1)<sh(blo,1))&(c>blo)&(c>o_)
ent['E7 缩量回调后放量阳线']=(c1<c4)&(vma3p<0.7*vma20p)&(c>o_)&(v>1.3*vma3p)&(c>m60)
body=np.abs(c-o_); shadow=np.minimum(c,o_)-l; hl=h-l
ent['E8 20日新低锤子线']=(l<=lo20)&(shadow>=2*body)&(shadow>=0.5*hl)&(hl>0)&((c-l)>=0.6*hl)
ent['E9 平台突破(振幅<=12%)']=(hi20p/lo20p-1<=0.12)&(c>hi20p)&(v>1.3*vma20p)
align=(m5>m10)&(m10>m20)&(m20>m60)
ent['E10 均线多头排列新形成']=align&~shb(align,1)&(c>m5)
sigb={'b10':(C<m10),'b20':(C<m20),'rsi70':(rsi14>70),'mdead':dead}
ldo=(O/shift(C,1)-1)<=-lim+0.0025
EX={ 'X1 持有5天':dict(hold=5),'X2 持有10天':dict(hold=10),'X3 持有20天':dict(hold=20),
 'X4 回落6%移动止损':dict(M=30,trail=.06),'X5 回落10%移动止损':dict(M=30,trail=.10),
 'X6 破MA10(硬损8%)':dict(M=30,sig='b10',hard=.08),'X7 破MA20(硬损8%)':dict(M=30,sig='b20',hard=.08),
 'X8 +10%止盈/-5%止损':dict(M=20,tp=.10,hard=.05),'X9 RSI14>70(硬损8%)':dict(M=30,sig='rsi70',hard=.08),
 'X10 MACD死叉(硬损8%)':dict(M=30,sig='mdead',hard=.08)}
def gather(di,ci):
    idx=di[:,None]+1+np.arange(KMAX)[None,:]; cc=ci[:,None]
    d=dict(O=O[idx,cc].astype(f32),H=Hh[idx,cc].astype(f32),L=L[idx,cc].astype(f32),C=C[idx,cc].astype(f32),
           fin=fin[idx,cc],ldc=limdn_close[idx,cc],ldo=ldo[idx,cc])
    for k,m in sigb.items(): d[k]=m[idx,cc]
    d['rawE']=Ro[di+1,ci]; return d
def simx(g,M=None,hold=None,trail=None,hard=None,tp=None,sig=None):
    Ox,Hx,Lx,Cx=g['O'],g['H'],g['L'],g['C']; n=len(Ox); T=hold or M
    done=np.zeros(n,bool); pend=np.zeros(n,bool); px=np.full(n,np.nan,f32); kx=np.zeros(n,np.int8)
    e0=Ox[:,0]; hh=np.fmax(e0,Hx[:,0]); tpP=e0*(1+tp) if tp else None
    for k in range(0,T+4):
        if k>=1:
            can=pend&~done&g['fin'][:,k]&~g['ldo'][:,k]
            px[can]=Ox[can,k]; kx[can]=k; done|=can; pend&=~done
            act=~done&~pend
            if trail or hard:
                lvl=np.full(n,-np.inf,f32)
                if hard: lvl=e0*(1-hard)
                if trail: lvl=np.fmax(lvl,hh*(1-trail))
                hit=act&(Lx[:,k]<=lvl)
                fl=hit&~g['ldc'][:,k]; px[fl]=np.fmin(Ox[:,k],lvl)[fl]; kx[fl]=k; done|=fl
                pend|=hit&g['ldc'][:,k]&~done; act=~done&~pend
            if tp:
                ht=act&(Hx[:,k]>=tpP); px[ht]=np.fmax(Ox[:,k],tpP)[ht]; kx[ht]=k; done|=ht; act=~done&~pend
            if k>=T:
                okc=act&g['fin'][:,k]&~g['ldc'][:,k]&np.isfinite(Cx[:,k])
                px[okc]=Cx[okc,k]; kx[okc]=k; done|=okc; pend|=act&~okc
        if sig and k<T:
            pend|=g[sig][:,k]&~done&~pend
        hh=np.fmax(hh,Hx[:,k])
    rawE=g['rawE']; r=px/e0; rawX=rawE*r
    net=(px*(1-0.01/rawX))/(e0*(1+0.01/rawE))-1-FEE
    return net.astype(np.float64),kx
def cl_t(x,grp):
    u,inv=np.unique(grp,return_inverse=True); m=x.mean(); s=np.bincount(inv,x-m); return m/(np.sqrt((s**2).sum())/len(x)+1e-18)
rng_=np.random.default_rng(1)
if __name__=='__main__':
    NB=300000; NS=150000
    bd,bc=np.nonzero(valid); pick=rng_.choice(len(bd),NB,replace=False); bd,bc=bd[pick],bc[pick]
    g=gather(bd,bc); bnet={}; bkx={}
    for xn,kw in EX.items(): bnet[xn],bkx[xn]=simx(g,**kw)
    del g; gc.collect()
    bm={}
    for xn in EX:
        x=bnet[xn]; ok=np.isfinite(x); s=np.bincount(monidx[bd][ok],x[ok],len(um)); n_=np.bincount(monidx[bd][ok],minlength=len(um)); bm[xn]=np.where(n_>20,s/np.maximum(n_,1),np.nan)
        print(f'随机基准 {xn}: 净{np.nanmean(x)*1e4:+.0f}bp 胜率{(x[ok]>0).mean()*100:.0f}% 持有{bkx[xn][ok].mean():.1f}天 无效{(~ok).mean()*100:.1f}%',flush=True)
    res={}; save={}
    pers=list(per.items())
    for en,mask in ent.items():
        di,ci=np.nonzero(valid&mask); tot=len(di)
        if tot>NS: s=rng_.choice(tot,NS,replace=False); di,ci=di[s],ci[s]
        ok=np.isfinite(O[di+1,ci]); di,ci=di[ok],ci[ok]
        g=gather(di,ci); save[en+'|di']=di; save[en+'|ci']=ci
        print(f'\n##### {en}  信号数{tot} 抽样{len(di)}',flush=True)
        for xn,kw in EX.items():
            net,kx=simx(g,**kw); ex=net-bm[xn][monidx[di]]; okk=np.isfinite(ex)
            save[f'{en}|{xn}|net']=net.astype(f32); save[f'{en}|{xn}|kx']=kx
            line=[]
            for pn,(a,b) in pers:
                m=okk&(dates[di]>=a)&(dates[di]<=b)
                if m.sum()<300: line.append(None); continue
                x=net[m]; e=ex[m]; w=x>0
                pay=x[w].mean()/-x[~w].mean() if w.any() and (~w).any() else np.nan
                line.append((m.sum(),x.mean()*1e4,e.mean()*1e4,cl_t(e,mon[di][m]),w.mean()*100,pay,kx[m].mean()))
            res[(en,xn)]=line
            if all(line):
                print('  '+xn.ljust(18)+' | '.join(f'{pn} n{L_[0]} 净{L_[1]:+4.0f} 超额{L_[2]:+4.0f}(t{L_[3]:+.1f}) 胜{L_[4]:.0f}% 赔{L_[5]:.2f} {L_[6]:.1f}d' for (pn,_),L_ in zip(pers,line)),flush=True)
        del g; gc.collect()
    np.savez_compressed('swingbook_res.npz',**save)
    import pickle; pickle.dump({'res':res,'bm':bm},open('swingbook_res.pkl','wb'))
    print('\n===== 选择规则: 2020-22 超额t>=2 且 超额>0 且 净>0 =====')
    sel=[]
    for (en,xn),line in res.items():
        L0=line[0]
        if L0 and L0[3]>=2 and L0[2]>0 and L0[1]>0: sel.append((en,xn))
    print('组合总数',len(res),'入选',len(sel))
    for en,xn in sel:
        line=res[(en,xn)]
        print(f'{en} × {xn}: '+' | '.join(f'{pn} 净{L_[1]:+4.0f} 超额{L_[2]:+4.0f}(t{L_[3]:+.1f}) 胜{L_[4]:.0f}% 赔{L_[5]:.2f}' if L_ else f'{pn} n不足' for (pn,_),L_ in zip(pers,line)))

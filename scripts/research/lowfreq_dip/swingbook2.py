"""Part A: Bollinger-lower-band-reclaim (E6) variants x longer holds; Part B: de-overlapped, position-capped portfolio with MTM equity. Research only."""
import numpy as np, gc, pickle, warnings; warnings.filterwarnings('ignore')
import swingbook as S
from swingbook import *
S.KMAX=48
mk=np.load('mkreg.npz'); mk20=mk['mk20']; mret=mk['mret']; assert (mk['dates']==dates).all()
bo=buy_ok.copy(); bo[nd-50:]=False; valid2=uni&bo&lst250&(R>=3)
panic=(mk20<=-0.036)[:,None]
E6=(sh(c,1)<sh(blo,1))&(c>blo)&(c>o_)
V={'V0 E6基础(昨收<下轨,今收复且阳线)':E6,
 'V1 +在MA120之上(长期上升)':E6&(c>m120),
 'V2 +在MA120之下':E6&(c<m120),
 'V3 +全市场恐慌(等权20日<=-3.6%)':E6&panic,
 'V4 +非恐慌':E6&~panic,
 'V5 +昨收深破下轨(<下轨x0.99)':E6&(sh(c,1)<sh(blo,1)*0.99),
 'V6 +今日放量(>1.2x 20日均量)':E6&(v>1.2*vma20p),
 'V7 +今日缩量(<0.8x)':E6&(v<0.8*vma20p),
 'V8 +RSI3昨日<10':E6&(sh(rsi3,1)<10),
 'V9 盘中下破下轨后收复(不要求昨收)':(l<blo)&(c>blo)&(c>o_)}
EX2={'H10':dict(hold=10),'H20':dict(hold=20),'H30':dict(hold=30),'H40':dict(hold=40),
     'RSI70出场(M40)':dict(M=40,sig='rsi70',hard=.08),'回落10%移损(M40)':dict(M=40,trail=.10)}
rng_=np.random.default_rng(1)
NB=300000
bd,bc=np.nonzero(valid2); pick=rng_.choice(len(bd),NB,replace=False); bd,bc=bd[pick],bc[pick]
g=gather(bd,bc); bnet={};bkx={};bm={}
for xn,kw in EX2.items():
    bnet[xn],bkx[xn]=simx(g,**kw); x=bnet[xn]; ok=np.isfinite(x)
    s=np.bincount(monidx[bd][ok],x[ok],len(um)); n_=np.bincount(monidx[bd][ok],minlength=len(um)); bm[xn]=np.where(n_>20,s/np.maximum(n_,1),np.nan)
    print(f'随机基准 {xn}: 净{np.nanmean(x)*1e4:+.0f}bp 胜率{(x[ok]>0).mean()*100:.0f}% 持有{bkx[xn][ok].mean():.1f}天',flush=True)
del g; gc.collect()
pers=list(per.items()); store={}
for vn,mask in V.items():
    di,ci=np.nonzero(valid2&mask); ok=np.isfinite(O[di+1,ci]); di,ci=di[ok],ci[ok]
    g=gather(di,ci); print(f'\n##### {vn} 信号数{len(di)}',flush=True)
    for xn,kw in EX2.items():
        net,kx=simx(g,**kw); ex=net-bm[xn][monidx[di]]; okk=np.isfinite(ex); store[(vn,xn)]=(di,ci,net,kx,g['rawE'].copy())
        out=[]
        for pn,(a,b) in pers:
            m=okk&(dates[di]>=a)&(dates[di]<=b)
            if m.sum()<200: out.append(f'{pn} n不足'); continue
            x=net[m]; e=ex[m]; w=x>0; pay=x[w].mean()/-x[~w].mean()
            out.append(f'{pn} n{m.sum()} 净{x.mean()*1e4:+4.0f} 超额{e.mean()*1e4:+4.0f}(t{cl_t(e,mon[di][m]):+.1f}) 胜{w.mean()*100:.0f}% 赔{pay:.2f} {kx[m].mean():.0f}d')
        print('  '+xn.ljust(16)+' | '.join(out),flush=True)
    del g; gc.collect()
# ---------------- Part B portfolio
cf=c  # ffilled float32 qfq close
def portfolio(di,ci,net,kx,rawE,N,rank,start='2020-01-01',label=''):
    ok=np.isfinite(net)&(kx>0); di,ci,net,kx,rawE=di[ok],ci[ok],net[ok],kx[ok],rawE[ok]; rk=rank[ok]
    e=di+1; xi=e+kx; o0=O[e,ci].astype(np.float64); tk=0.01/rawE; costE=tk+FEE/2
    order=np.lexsort((rk,e)); byday={}
    for j in order: byday.setdefault(int(e[j]),[]).append(j)
    t0=int(np.searchsorted(dates,start)); cash=1.0; act=[]; eq=np.full(nd,np.nan); expo=np.zeros(nd); trades=[]
    for t in range(t0,nd):
        for p in [p for p in act if xi[p[0]]==t]:
            j=p[0]; cash+=p[1]*(1+net[j]); trades.append(net[j]); act.remove(p)
        slots=N-len(act)
        if slots>0 and t in byday:
            held={ci[p[0]] for p in act}; E=cash+sum(p[2] for p in act)
            for j in byday[t]:
                if slots==0 or cash<=1e-9: break
                if ci[j] in held: continue
                size=min(E/N,cash); cash-=size; act.append([j,size,size]); held.add(ci[j]); slots-=1
        tot=cash
        for p in act:
            j=p[0]
            if xi[j]==t: p[2]=p[1]*(1+net[j])   # exits at this day's price: value at realised
            else: p[2]=p[1]*(cf[t,ci[j]]/o0[j])*(1-costE[j]) if True else p[2]
            tot+=p[2]
        eq[t]=tot; expo[t]=(tot-cash)/tot
    return eq,expo,np.array(trades)
def metrics(eq,expo,tr,tag):
    r=eq[1:]/eq[:-1]-1; r=np.where(np.isfinite(r),r,0)
    out=[]
    for pn,(a,b) in [('全期',('2020-01-01','2026-12-31'))]+pers:
        m=(dates[1:]>=a)&(dates[1:]<=b)&np.isfinite(eq[1:])&np.isfinite(eq[:-1])
        if m.sum()<50: continue
        rr=r[m]; yrs=m.sum()/244; tot=np.prod(1+rr); cum=np.cumprod(1+rr); dd=(cum/np.maximum.accumulate(cum)-1).min()
        out.append(f'{pn}: 年化{(tot**(1/yrs)-1)*100:+5.1f}% 夏普{rr.mean()/(rr.std()+1e-12)*np.sqrt(244):+.2f} 回撤{dd*100:.0f}% 仓位{expo[1:][m].mean()*100:.0f}%')
    print(f'{tag} | 交易{len(tr)}笔 平均净{tr.mean()*1e4:+.0f}bp 胜率{(tr>0).mean()*100:.0f}%\n    '+'\n    '.join(out),flush=True)
print('\n=========== Part B: 组合回测（扣成本，等权，单票<=1/N，MTM净值） ===========')
r=mret[1:]; 
for pn,(a,b) in [('全期',('2020-01-01','2026-12-31'))]+pers:
    m=(dates[1:]>=a)&(dates[1:]<=b); rr=r[m]; yrs=m.sum()/244; cum=np.cumprod(1+rr)
    print(f'基准 全市场等权(日再平衡,不计成本) {pn}: 年化{(cum[-1]**(1/yrs)-1)*100:+.1f}% 夏普{rr.mean()/rr.std()*np.sqrt(244):+.2f} 回撤{(cum/np.maximum.accumulate(cum)-1).min()*100:.0f}%')
rsi_rank=rsi3
for vn in ['V0 E6基础(昨收<下轨,今收复且阳线)','V1 +在MA120之上(长期上升)','V3 +全市场恐慌(等权20日<=-3.6%)']:
  for xn in ['H10','H20','H40','RSI70出场(M40)']:
    di,ci,net,kx,rawE=store[(vn,xn)]
    for N in (10,20):
        for rk_name in ('随机','最超卖(RSI3最低)'):
            rk=rng_.random(len(di)) if rk_name=='随机' else rsi_rank[di,ci].astype(float)
            eq,expo,tr=portfolio(di,ci,net,kx,rawE,N,rk)
            metrics(eq,expo,tr,f'[{vn[:2]}×{xn} N={N} 排序={rk_name}]')
# random baseline with same exit
for xn in ['H20']:
    for N in (10,20):
        rk=rng_.random(len(bd)); eq,expo,tr=portfolio(bd,bc,bnet[xn],bkx[xn],Ro[bd+1,bc],N,rk); metrics(eq,expo,tr,f'[随机买入基线 ×{xn} N={N}]')
pickle.dump({'store':{k:v for k,v in store.items() if k[0][:2] in ('V0','V1','V3')}},open('swingbook2_store.pkl','wb'))

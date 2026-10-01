"""Leverage (margin financing) test on z<=-1.5 x E6 portfolio, 2008-2026. Research only."""
import numpy as np, sys, time; T0=time.time()
exec(open('stockport.py').read().split("print('格式")[0])
print('loaded',round(time.time()-T0),flush=True)
# financing rate by era (annual), approximate broker margin rates
rate_era=np.where(dates<'2020-01-01',0.085,np.where(dates<'2023-01-01',0.07,0.06))
def portfolio_lev(sig,pool,N,L=1.0,rate=None,rank=None,start='2008-01-01',liq_line=1.3,seed=7):
    rg=np.random.default_rng(seed); rate=rate_era if rate is None else rate
    t0=int(np.searchsorted(dates,start)); cash=1.0; act=[]; eq=np.full(nd,np.nan); expo=np.zeros(nd); trades=[]
    interest=0.0; nliq=0; minratio=9.0; liqdays=[]; nwarn=0; peakdebt=0.0
    for t in range(t0,nd-H-1):
        e=t+1
        for p in [p for p in act if p['x']==t]:
            cash+=p['inv']*(1+p['net']); trades.append(p['net']); act.remove(p)
        slots=N-len(act)
        if slots>0 and sig[t]:
            cs=np.nonzero(pool[t])[0]
            if len(cs):
                held={p['j'] for p in act}; cs=[j for j in cs if j not in held]
                if rank is None: rg.shuffle(cs)
                else: cs=sorted(cs,key=lambda j:rank[t,j])
                invested=sum(p['v'] for p in act); E=cash+invested
                for j in cs[:slots]:
                    size=min(L*E/N, L*E-invested)
                    if size<=1e-9: break
                    cash-=size; invested+=size; costE=0.01/float(rawE[t,j])+fee1[t+H]/2
                    act.append(dict(j=j,e=e,x=t+H,inv=size,v=size,net=float(net[t,j]),o0=float(o[e,j]),costE=costE))
        if cash<0:
            ic=-cash*rate[t]/242.0; cash-=ic; interest+=ic
        tot=cash; vs=0.0
        for p in act:
            if p['e']<=t:
                p['v']=p['inv']*(float(c[t,p['j']])/p['o0'] if np.isfinite(c[t,p['j']]) else 1.0)*(1-p['costE'])
            vs+=p['v']
        tot=cash+vs
        debt=max(-cash,0.0)
        if debt>1e-9:
            peakdebt=max(peakdebt,debt/max(tot,1e-9)); ratio=(vs+max(cash,0))/debt; minratio=min(minratio,ratio)
            if ratio<1.5: nwarn+=1
            if ratio<liq_line:
                cash=cash+vs*(1-0.003); nliq+=1; liqdays.append(dates[t])
                for p in act: trades.append(p['v']/p['inv']-1)
                act=[]; tot=cash; vs=0.0
        eq[t]=tot; expo[t]=vs/max(tot,1e-9)
        if tot<=0.02: eq[t+1:]=eq[t]; break
    return eq,expo,np.array(trades),dict(interest=interest,nliq=nliq,minratio=minratio,liq=liqdays,warn=nwarn,peakdebt=peakdebt)
def pr(tag,eq,expo,tr,info):
    cells=[]
    for pn,(a,b) in ERA.items():
        s=stats(eq,expo,a,b); cells.append('无' if s is None else f'{s[0]*100:+5.1f}%/{s[1]:+.2f}/{s[2]*100:4.0f}%')
    s=stats(eq,expo,'2008-01-01','2026-12-31')
    print(f'{tag:30s}| '+' | '.join(cells)+f' | 仓位{s[3]*100:.0f}% 强平{info["nliq"]}次 最低担保比例{info["minratio"]*100:.0f}% 低于150%共{info["warn"]}天 终值{eq[np.isfinite(eq)][-1]:.2f}',flush=True)
print('格式：年化/夏普/最大回撤；列='+' | '.join(ERA))
sig=zv<=-1.5; R={}
for L in (1.0,1.5,2.0,3.0):
    R[('rank',L)]=portfolio_lev(sig,e6,20,L,rank=ret20); pr(f'E6 跌幅排序 {L:g}x 年代利率',*R[('rank',L)])
for L in (1.0,2.0):
    out=[portfolio_lev(sig,e6,20,L,seed=s) for s in range(4)]
    cg=[stats(o[0],o[1],'2008-01-01','2026-12-31') for o in out]
    print(f'E6 随机(4种子) {L:g}x: 年化 '+' '.join(f'{x[0]*100:+.1f}%' for x in cg)+' 夏普 '+' '.join(f'{x[1]:.2f}' for x in cg)+' 回撤 '+' '.join(f'{x[2]*100:.0f}%' for x in cg)+' 强平 '+' '.join(str(o[3]['nliq']) for o in out),flush=True)
print('\n利率敏感性 (2x, E6 跌幅排序，全年平利率)：')
for rr in (0.0,0.05,0.08,0.10,0.12):
    oo=portfolio_lev(sig,e6,20,2.0,rate=np.full(nd,rr),rank=ret20); pr(f'2x 利率{rr*100:g}%',*oo)
print('\n不同 N（2x，年代利率，排序）：')
for N in (10,30):
    oo=portfolio_lev(sig,e6,N,2.0,rank=ret20); pr(f'N={N} 2x',*oo)
    o1=portfolio_lev(sig,e6,N,1.0,rank=ret20); pr(f'N={N} 1x',*o1)
eq2,ex2,tr2,i2=R[('rank',2.0)]; eq1,ex1,tr1,i1=R[('rank',1.0)]
print('\n强平日(2x)：',i2['liq'][:20])
print('逐年  年份: 1x / 2x / 等权大盘')
for y in range(2008,2027):
    m=(np.char.startswith(dates,str(y)))&np.isfinite(eq1); ii=np.nonzero(m)[0]
    if len(ii)<20: continue
    f=lambda e: e[ii[-1]]/e[ii[0]]-1
    print(f'  {y}: {f(eq1)*100:+6.1f}% / {f(eq2)*100:+6.1f}% / {(bench[ii[-1]]/bench[ii[0]]-1)*100:+6.1f}%')
# worst single-trade and trade stats
for nm,tr in (('1x',tr1),('2x',tr2)):
    print(nm,'笔数',len(tr),'均',f'{tr.mean()*1e4:+.0f}bp 胜率{(tr>0).mean()*100:.0f}% 最差{tr.min()*100:.1f}% 赔率',round(tr[tr>0].mean()/-tr[tr<=0].mean(),2))
# 2x equity: worst 60-day drawdown periods
d2=eq2/np.fmax.accumulate(np.where(np.isfinite(eq2),eq2,0))-1
t=np.nanargmin(d2); print('2x 最大回撤发生在',dates[t],f'{d2[t]*100:.0f}%')
print('done',round(time.time()-T0))

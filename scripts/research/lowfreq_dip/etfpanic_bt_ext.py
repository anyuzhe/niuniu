"""Panic-signal ETF portfolio backtest with position management (research only).
Signal: whole-market (equal-weight stock universe) 20-day return mk20 <= threshold, known at the close; orders at the next open.
Instruments: broad ETFs (fixed list), total-return series (cash distributions and splits adjusted from etf_nav), commission 1bp per side,
1 tick (0.001 yuan) each side at the fill price, cash earns 0."""
import numpy as np, re, os, warnings; warnings.filterwarnings('ignore')
from etfcore_ext import *
import pyarrow.parquet as pq
M=np.load('mkreg_ext_liq.npz'); md=dict(zip(M['dates'],M['mk20']))
mk=np.array([md.get(d,np.nan) for d in dates]); LASTMK=int(np.nonzero(np.isfinite(mk))[0].max())
def events2(sym):
    f=f"{LK}/bronze/provider=eastmoney/etf_nav/{sym.replace('.','_')}.parquet"; ev={}
    if not os.path.exists(f): return ev
    t=pq.read_table(f,columns=['date','distribution']).to_pandas()
    for d,s in zip(t.date.astype(str),t.distribution):
        if not isinstance(s,str) or not s: continue
        m=re.search(r'派现金([\d.]+)元',s)
        if m: ev[d]=('cash',float(m.group(1)))
        m=re.search(r'(?:分拆|折算)([\d.]+)份',s)
        if m: ev[d]=('split',float(m.group(1)))
    return ev
PCADJ=np.full((nd,nc),np.nan); PCADJ[1:]=C[:-1]
for j,s in enumerate(syms):
    ev=events2(s)
    for d,(kind,v) in ev.items():
        k=int(np.searchsorted(dates,d))
        if k<=0 or k>=nd or not np.isfinite(PCADJ[k,j]): continue
        if kind=='split' and k+1<nd and np.isfinite(O[k+1,j]) and abs(O[k+1,j]/PCADJ[k+1,j]*v-1)<abs(O[k,j]/PCADJ[k,j]*v-1): k+=1
        PCADJ[k,j]=PCADJ[k,j]-v if kind=='cash' else PCADJ[k,j]/v
rcc=np.where(np.isfinite(C)&np.isfinite(PCADJ),C/PCADJ-1,0.0); rcc=np.where(np.abs(rcc)>0.25,0.0,rcc)
TRC=np.cumprod(1+rcc,axis=0)
TRO=np.full((nd,nc),np.nan); TRO[1:]=TRC[:-1]*O[1:]/PCADJ[1:]
BASKET=['sh.510300','sh.510500','sh.510050','sz.159915','sh.512100','sh.588000']
bj=[syms.index(s) for s in BASKET]
TICK=0.001; FEE1=1e-4
buyable=np.zeros((nd,nc),bool); buyable[:-1]=uni[:-1]&fin[1:]&~limup_open[1:]&(C[:-1]>=1.0)   # decided at close t, executed at open t+1
def simulate(cfg, basket=None, thr_series=None):
    H=cfg.get('H',20); tiers=cfg['tiers']; maxexp=cfg.get('maxexp',1.0); stop=cfg.get('stop'); cool=cfg.get('cool',10)
    rec=cfg.get('rec'); minhold=cfg.get('minhold',5); maxact=cfg.get('maxact',99); always=cfg.get('always',False)
    idx=[syms.index(s) for s in (basket or BASKET)]
    start=int(np.nonzero(np.isfinite(mk))[0].min())+1
    cash=1.0; tr=[]; eq=np.ones(nd); pend_buy=[]; done_ep=set(); ep_id=0; last_stop=-999; expo=np.zeros(nd); log=[]
    inepisode=False; below_days=0
    for d in range(start,LASTMK+1):
        # 1) open: execute buys decided at close d-1 and exits scheduled at this open
        for t_ in tr:
            if t_['exit_open'] and not t_['closed']:
                for j in list(t_['sh']):
                    if fin[d,j] and TRO[d,j]==TRO[d,j]:
                        px=TRO[d,j]*(1-TICK/O[d,j])*(1-FEE1); cash+=t_['sh'][j]*px; t_['proc']=t_.get('proc',0)+t_['sh'][j]*px; del t_['sh'][j]
                if not t_['sh']: t_['closed']=True
        eq_prev=eq[d-1]
        for (frac,tag) in pend_buy:
            elig=[j for j in idx if buyable[d-1,j]]
            if not elig: continue
            invested=sum(t_['sh'][j]*TRC[d-1,j] for t_ in tr if not t_['closed'] for j in t_['sh'])
            alloc=min(frac*maxexp*eq_prev, max(0.0,maxexp*eq_prev-invested), cash)
            if alloc<=1e-6: continue
            sh={}; 
            for j in elig:
                px=TRO[d,j]*(1+TICK/O[d,j])*(1+FEE1); sh[j]=(alloc/len(elig))/px
            cash-=alloc; tr.append(dict(e=d,x=d+H-1,sh=sh,cost=alloc,closed=False,exit_open=False,tag=tag,ep=ep_id))
        pend_buy=[]
        # 2) close: scheduled exits
        for t_ in tr:
            if t_['closed'] or t_['exit_open']: continue
            due=(d>=t_['x']) or (rec is not None and d-t_['e']>=minhold and mk[d]>=rec and False)
            if due:
                for j in list(t_['sh']):
                    if fin[d,j] and not limdn_close[d,j]:
                        px=TRC[d,j]*(1-TICK/C[d,j])*(1-FEE1); cash+=t_['sh'][j]*px; t_['proc']=t_.get('proc',0)+t_['sh'][j]*px; del t_['sh'][j]
                if not t_['sh']:
                    t_['closed']=True; t_['ret']=None
        # mark to market
        val=cash+sum(t_['sh'][j]*TRC[d,j] for t_ in tr if not t_['closed'] for j in t_['sh'])
        eq[d]=val; expo[d]=1-cash/val if val>0 else 0
        # 3) risk exits decided at close d -> executed next open
        for t_ in tr:
            if t_['closed'] or t_['exit_open']: continue
            mv=sum(t_['sh'][j]*TRC[d,j] for j in t_['sh'])
            if stop is not None and mv/t_['cost']-1<=-stop: t_['exit_open']=True; last_stop=d
            if rec is not None and d-t_['e']>=minhold and mk[d]>=rec: t_['exit_open']=True
        # 4) signal at close d -> buy at open d+1
        if d>=LASTMK: continue
        thr_=thr_series[d] if thr_series is not None else cfg.get('thr',-0.036)
        if always:
            pend_buy.append((1.0/H,'always')); continue
        if d-last_stop<cool and last_stop>0: continue
        if not np.isfinite(mk[d]): continue
        if mk[d]>cfg.get('reset',-0.01): inepisode=False; done_ep=set()
        act=sum(1 for t_ in tr if not t_['closed'])
        for k,(lvl,frac,once) in enumerate(tiers):
            lvl_=lvl if lvl is not None else thr_
            if mk[d]<=lvl_ and act<maxact and (not once or k not in done_ep):
                pend_buy.append((frac,f'L{k}')); act+=1
                if once: done_ep.add(k)
        if pend_buy: inepisode=True; ep_id+=(0 if inepisode else 1)
    # tranche returns
    return eq,expo,tr
PER={'2020-22':('2020-01-01','2022-12-31'),'2023-24':('2023-01-01','2024-12-31'),'2025-26':('2025-01-01','2026-12-31')}
def metrics(eq,expo,d0,d1):
    m=(dates>=d0)&(dates<=d1)&(np.arange(nd)<=LASTMK)&(eq>0)
    i0=max(int(np.nonzero(m)[0][0]),1); i1=np.nonzero(m)[0][-1]
    e=eq[i0-1:i1+1]; r=e[1:]/e[:-1]-1; yrs=(i1-i0+1)/245
    tot=e[-1]/e[0]-1; cagr=(e[-1]/e[0])**(1/yrs)-1; dd=(e/np.maximum.accumulate(e)-1).min()
    vol=r.std()*np.sqrt(245); sh=r.mean()*245/vol if vol>0 else np.nan
    return tot,cagr,vol,sh,dd,expo[i0:i1+1].mean()
def show(tag,eq,expo,tr=None):
    out=[]
    for pn,(a,b) in PER.items():
        tot,cagr,vol,sh,dd,ex=metrics(eq,expo,a,b); out.append(f'{pn}: 收益{tot*100:+6.1f}% 年化{cagr*100:+5.1f}% 波动{vol*100:4.1f}% 夏普{sh:+.2f} 最大回撤{dd*100:5.1f}% 平均仓位{ex*100:3.0f}%')
    tot,cagr,vol,sh,dd,ex=metrics(eq,expo,'2019-06-01','2026-12-31')
    out.append(f'全期: 收益{tot*100:+6.1f}% 年化{cagr*100:+5.1f}% 波动{vol*100:4.1f}% 夏普{sh:+.2f} 最大回撤{dd*100:5.1f}% 平均仓位{ex*100:3.0f}%')
    print(tag+'\n    '+'\n    '.join(out))
if __name__=='__main__':
    # reference: buy and hold the equal-weight basket (rebalanced daily, no cost) and "always invested in tranches"
    rb=np.nanmean(rcc[:,bj],axis=1); bh=np.cumprod(1+np.r_[0,rb[1:]]); bh[:0]=1
    show('【参照】宽基篮子买入持有（每日等权，不计成本）',bh,np.ones(nd))
    eq,ex,tr=simulate(dict(H=20,always=True,tiers=[])); show('【参照】不看信号、每天买1/20持有20天（同样成本，满仓）',eq,ex)
    thr=-0.036
    for H in (20,):
        eq,ex,tr=simulate(dict(H=H,thr=thr,tiers=[(None,1.0,False)],maxact=1)); show(f'A 一次性：恐慌日空仓时全仓买入，持有{H}天',eq,ex,tr)
        for N in (3,5):
            eq,ex,tr=simulate(dict(H=H,thr=thr,tiers=[(None,1.0/N,False)],maxact=N)); show(f'B 分{N}批：每个恐慌日买1/{N}，最多同时{N}批，各持有{H}天',eq,ex,tr)
        eq,ex,tr=simulate(dict(H=H,thr=thr,tiers=[(-0.036,1/3,True),(-0.06,1/3,True),(-0.09,1/3,True)])); show(f'C 按深度加仓：-3.6%/-6%/-9% 各买1/3（每段行情各一次），各持有{H}天',eq,ex,tr)

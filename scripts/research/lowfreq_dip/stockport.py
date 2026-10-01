"""Long-sample portfolio backtest: stock Bollinger-lower-band reclaim (E6) x dynamic market oversold z. Research only."""
import numpy as np, gc, warnings; warnings.filterwarnings('ignore')
src=open('stockdyn.py').read().split("good=valid")[0].replace("del ent,ex,rawE,rawX,c,o,f; gc.collect()","del ent,ex,rawX; gc.collect()")
exec(src)
rng=np.random.default_rng(7)
fee1=fee[:,0].astype(np.float64)
ret20=np.full((nd,nc),np.nan,np.float32); ret20[20:]=c[20:]/c[:-20]-1
cand_all=valid                      # all tradable candidates with a defined 20d net
e6=valid&E6
def portfolio(sigmask_days, pool, N, start='2008-01-01', rank=None, label=''):
    # sigmask_days: bool[nd] of signal days; pool: bool[nd,nc] of eligible (day,stock)
    t0=int(np.searchsorted(dates,start)); cash=1.0; act=[]; eq=np.full(nd,np.nan); expo=np.zeros(nd); trades=[]
    for t in range(t0,nd-H-1):
        e=t+1
        for p in [p for p in act if p['x']==t]:
            cash+=p['inv']*(1+p['net']); trades.append(p['net']); act.remove(p)
        slots=N-len(act)
        if slots>0 and sigmask_days[t]:
            cs=np.nonzero(pool[t])[0]
            if len(cs):
                held={p['j'] for p in act}; cs=[j for j in cs if j not in held]
                if rank is None: rng.shuffle(cs)
                else: cs=sorted(cs,key=lambda j:rank[t,j])
                E=cash+sum(p['v'] for p in act)
                for j in cs[:slots]:
                    size=min(E/N,cash)
                    if size<=1e-9: break
                    cash-=size; costE=0.01/float(rawE[t,j])+fee1[t+H]/2
                    act.append(dict(j=j,e=e,x=t+H,inv=size,v=size,net=float(net[t,j]),o0=float(o[e,j]),costE=costE))
        tot=cash
        for p in act:
            if p['x']==t: pass
            p['v']=p['inv']*(float(c[t,p['j']])/p['o0'] if np.isfinite(c[t,p['j']]) else 1.0)*(1-p['costE']) if p['e']<=t else p['v']
            tot+=p['v']
        eq[t]=tot; expo[t]=(tot-cash)/tot
    return eq,expo,np.array(trades)
ERA={'2008-11':('2008-01-01','2011-12-31'),'2012-16':('2012-01-01','2016-12-31'),'2017-19':('2017-01-01','2019-12-31'),'2020-26':('2020-01-01','2026-12-31'),'全期':('2008-01-01','2026-12-31')}
def stats(eq,expo,a,b):
    m=(dates>=a)&(dates<=b)&np.isfinite(eq); idx=np.nonzero(m)[0]
    if len(idx)<50: return None
    e=eq[idx]; r=e[1:]/e[:-1]-1; yrs=len(r)/245; cagr=(e[-1]/e[0])**(1/yrs)-1; dd=(e/np.maximum.accumulate(e)-1).min(); sh=r.mean()/(r.std()+1e-12)*np.sqrt(245)
    return cagr,sh,dd,expo[idx].mean()
M2=np.load('mkreg_ext_liq.npz'); mr=M2['mret']; bench=np.cumprod(1+mr)
def line(tag,eq,expo,tr):
    cells=[]
    for pn,(a,b) in ERA.items():
        s=stats(eq,expo,a,b); cells.append('无' if s is None else f'{s[0]*100:+5.1f}%/{s[1]:+.2f}/{s[2]*100:4.0f}%/{s[3]*100:2.0f}%')
    print(f'{tag:36s}| '+' | '.join(cells)+f' | 笔数{len(tr)} 均{tr.mean()*1e4:+.0f}bp 胜率{(tr>0).mean()*100:.0f}%',flush=True)
print('格式：年化/夏普/最大回撤/平均仓位；列='+' | '.join(ERA))
# benchmark
cells=[]
for pn,(a,b) in ERA.items():
    m=(dates>=a)&(dates<=b); x=mr[m]; cum=np.cumprod(1+x); yrs=m.sum()/245
    cells.append(f'{(cum[-1]**(1/yrs)-1)*100:+5.1f}%/{x.mean()/x.std()*np.sqrt(245):+.2f}/{(cum/np.maximum.accumulate(cum)-1).min()*100:4.0f}%/100%')
print(f'{"基准 等权大盘(不计成本)":36s}| '+' | '.join(cells))
days_ok=np.isfinite(zv)
PORT={}
for nm,sig,pool in (('z<=-1.5 E6',zv<=-1.5,e6),('z<=-2 E6',zv<=-2,e6),('z<=-1.0 E6',zv<=-1.0,e6),('固定20日<=-9% E6',mk20<=-0.09,e6),
                    ('任何状态 E6',days_ok,e6),('z<=-1.5 随机候选(对照)',zv<=-1.5,cand_all),('z<=-1.0 随机候选(对照)',zv<=-1.0,cand_all)):
    for N in (10,20):
        eq,ex_,tr=portfolio(sig,pool,N); line(f'{nm} N={N}',eq,ex_,tr); PORT[(nm,N)]=(eq,ex_)
eq,ex_,tr=portfolio(zv<=-1.5,e6,20,rank=ret20); line('z<=-1.5 E6 N=20 排序:20日跌幅最大',eq,ex_,tr)
# calendar-year table for z<=-1.5 E6 N=20
eq,ex_=PORT[('z<=-1.5 E6',20)]
print('\n逐年(z<=-1.5 E6 N=20)：年收益 / 基准等权大盘 / 平均仓位')
for y in range(2008,2027):
    m=(np.char.startswith(dates,str(y)))&np.isfinite(eq); ii=np.nonzero(m)[0]
    if len(ii)<20: continue
    r=eq[ii[-1]]/eq[ii[0]]-1; b=bench[ii[-1]]/bench[ii[0]]-1; print(f'  {y}: {r*100:+6.1f}% / {b*100:+6.1f}% / 仓位{ex_[ii].mean()*100:.0f}%')
# current state
print('\n=== 最新状态(面板最后日期 %s)'%dates[-1])
for i in range(nd-8,nd): print(f'  {dates[i]} 大盘20日{mk20[i]*100:+5.1f}% z={zv[i]:+.2f} E6信号只数{int((E6[i]&uni[i]).sum())}')
sg=np.nonzero((zv<=-1.5)&(np.char.startswith(dates,'2026'))&(np.arange(nd)<nd-H-1))[0]
if len(sg):
    print('2026 年 z<=-1.5 的信号日(已满20天)：E6只数 / E6平均20天净 / 全部候选平均')
    segs=[]; 
    for t in sg: print(f'  {dates[t]} z={zv[t]:+.2f} E6 {int(e6[t].sum())}只 平均{np.nanmean(np.where(e6[t],net[t],np.nan))*1e4:+.0f}bp 候选平均{np.nanmean(np.where(cand_all[t],net[t],np.nan))*1e4:+.0f}bp')

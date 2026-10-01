"""How many names can actually be bought when the z gate is open (E6 candidates, fill of N slots). Research only."""
import numpy as np, time
exec(open('stockport.py').read().split("print('格式")[0])
src=open('pm.py').read(); exec("def pw("+src.split("def pw(")[1].split("def row(")[0])
aa=P['a']
sig=zv<=-1.5; t0=int(np.searchsorted(dates,'2008-01-01')); tmax=nd-H-1
gd=[t for t in range(t0,tmax) if sig[t]]
cnt=np.array([int(e6[t].sum()) for t in gd]); gdates=np.array([dates[t] for t in gd])
print('闸门开启天数',len(gd),'  E6 候选数/天: 为0的天数',int((cnt==0).sum()))
for nm,(a,b) in ERA.items():
    m=(gdates>=a)&(gdates<=b)
    if m.sum()==0: print(nm,'无'); continue
    x=cnt[m]; print(f'{nm}: 开闸 {m.sum()} 天  每天E6候选 最小{x.min()} 25%={np.percentile(x,25):.0f} 中位{np.median(x):.0f} 75%={np.percentile(x,75):.0f} 最大{x.max()}  ≥10只占{(x>=10).mean()*100:.0f}% ≥20只占{(x>=20).mean()*100:.0f}% ≥50只占{(x>=50).mean()*100:.0f}%')
# episodes: distinct candidates over the whole episode
ep=[];cur=[gd[0]]
for t in gd[1:]:
    if t-cur[-1]>5: ep.append(cur); cur=[t]
    else: cur.append(t)
ep.append(cur)
print('\n每一段（gap>5日）：起止、开闸天数、段内累计不同的E6候选只数、第一天候选数')
rows=[]
for E in ep:
    u=np.zeros(nc,bool)
    for t in E: u|=e6[t]
    rows.append((dates[E[0]],dates[E[-1]],len(E),int(u.sum()),int(e6[E[0]].sum())))
for r in rows: print(f'  {r[0]}~{r[1]} {r[2]:3d}天 累计{r[3]:4d}只 首日{r[4]:3d}只')
tot=np.array([r[3] for r in rows]); print(f'段数{len(rows)}  累计候选只数 中位{np.median(tot):.0f} 最小{tot.min()} 25%={np.percentile(tot,25):.0f}')
# actual fill under N slots
print('\n实际持仓（1x，跌幅排序）：N | 持仓>0的日子里平均持几只 / 持仓满N的天数占比(持仓>0的日子) / 期间最多持几只 / 开闸日里的平均新买入只数')
for N in (10,20,30,50,100):
    rg=np.random.default_rng(7); cash=1.0; act=[]; held_series=[]; buys_gate=[]
    for t in range(t0,tmax):
        for p in [p for p in act if p['x']==t]: act.remove(p)
        slots=N-len(act); nb=0
        if slots>0 and sig[t]:
            cs=np.nonzero(e6[t])[0]; hs={p['j'] for p in act}; cs=[j for j in cs if j not in hs]
            cs=sorted(cs,key=lambda j:ret20[t,j])[:slots]
            for j in cs: act.append(dict(j=j,x=t+H)); nb+=1
        if sig[t]: buys_gate.append(nb)
        held_series.append(len(act))
    h=np.array(held_series); pos=h[h>0]
    print(f'  N={N:3d} | 平均{pos.mean():5.1f} 只 | 满仓天数占 {(pos>=N).mean()*100:3.0f}% | 最多{h.max():3d} 只 | 开闸日平均新买 {np.mean(buys_gate):.1f} 只')
# capacity: ADV of candidates on gate days
adv=np.concatenate([aa[t][e6[t]] for t in gd]).astype(np.float64)
adv=adv[np.isfinite(adv)]
print('\n候选的 20 日均成交额(万元)：中位 %.0f  25%% %.0f  75%% %.0f'%tuple(np.percentile(adv,[50,25,75])/1e4))
print('若单只占该股日均成交额 ≤1%/2%/5%：中位候选可承接的单只金额(万元)',np.percentile(adv,50)*np.array([.01,.02,.05])/1e4)
for N in (20,30,50):
    for pct in (0.01,0.05):
        # typical total capital with N names each at pct of median-ADV candidate
        print(f'  N={N}, 每只≤{pct*100:g}%日均额: 总资金上限约 {N*np.percentile(adv,50)*pct/1e4:.0f} 万元')

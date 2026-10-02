"""Yearly returns of every dip-buy variant tried (z gate x E6 etc.), one extended engine. Research only.
usage: python3 allyears.py <group>   groups: core exits dyn env fund
Writes allyears_<group>.json (list of {name, group, years, cagr, sharpe, dd, expo, n, win})."""
import sys, json, time, numpy as np; T0=time.time()
GROUP=sys.argv[1]
if GROUP=='fund': exec(open('fundtest2.py').read().split("print('\\n[3]")[0])
else: exec(open('stockport.py').read().split("print('格式")[0])
rate_era=np.where(dates<'2020-01-01',0.085,np.where(dates<'2023-01-01',0.07,0.06))
sig0=zv<=-1.5
ne6=e6.sum(1).astype(float); nu=cand_all.sum(1).astype(float); frac=ne6/np.maximum(nu,1)
ret60=np.full(nd,np.nan); ret60[60:]=bench[60:]/bench[:-60]-1
ret3=np.full(nd,np.nan); ret3[3:]=bench[3:]/bench[:-3]-1
def sim(N=20,hold=20,sl=None,tp=None,trail=None,zx=None,mx=None,Lfun=None,L=1.0,cy=0.0,ddcut=None,start='2008-01-01',liq=1.3,gate=None,rate=rate_era,pool=None,rank='ret20',seed=7,slip=0.0,Sday=None):
    g=sig0 if gate is None else gate; P_=e6 if pool is None else pool
    Lf=Lfun if Lfun else (lambda z:L); Lcap=max(Lf(-9.0),Lf(-1.5),L if not Lfun else 0)
    rg=np.random.default_rng(seed)
    t0=int(np.searchsorted(dates,start)); cash=1.0; act=[]; eq=np.full(nd,np.nan); expo=np.zeros(nd); tr=[]; nliq=0; minr=9.0; peakE=1.0
    for t in range(t0,nd-1):
        keep=[]
        for p in act:
            done=False
            if p['flag'] and np.isfinite(o[t,p['j']]): px=o[t,p['j']]; done=True
            elif t>=p['sig']+hold and np.isfinite(c[t,p['j']]): px=c[t,p['j']]; done=True
            if done:
                raw=px/f[t,p['j']]; m=(px*(1-0.01/raw-slip))/(p['o0']*(1+0.01/p['rawE']+slip))-1-p['fee']
                cash+=p['inv']*(1+m); tr.append((m,t-p['e'],p['inv']/p['E0']))
            else: keep.append(p)
        act=keep
        slots=N-len(act)
        if g[t] and slots>0 and t+1<nd:
            cs=np.nonzero(P_[t])[0]; hs={p['j'] for p in act}; cs=[j for j in cs if j not in hs]
            if cs:
                if isinstance(rank,str) and rank=='ret20': cs=sorted(cs,key=lambda j:ret20[t,j])[:slots]
                elif rank is None: rg.shuffle(cs); cs=cs[:slots]
                else: cs=sorted(cs,key=lambda j:rank[t,j])[:slots]
                invested=sum(p['v'] for p in act); E=cash+invested
                Lt=Lf(zv[t])*(1.0 if Sday is None else Sday[t])
                if ddcut and E<peakE*(1-ddcut[0]): Lt=min(Lt,ddcut[1])
                for j in cs:
                    if Lt<=0: break
                    size=min(Lt*E/N, Lcap*E-invested)
                    if size<=1e-9: break
                    cash-=size; invested+=size
                    rawE_=float(o[t+1,j]/f[t+1,j])
                    act.append(dict(j=j,sig=t,e=t+1,o0=float(o[t+1,j]),rawE=rawE_,fee=float(fee1[t]),inv=size,v=size,E0=E,flag=False,peak=float(o[t+1,j]),costE=0.01/rawE_+float(fee1[t])/2+slip))
        if cash<0: cash-=(-cash)*rate[t]/242.0
        elif cy>0: cash+=cash*cy/242.0
        vs=0.0
        for p in act:
            if p['e']<=t and np.isfinite(c[t,p['j']]):
                cj=float(c[t,p['j']]); p['v']=p['inv']*(cj/p['o0'])*(1-p['costE']); r=cj/p['o0']-1; p['peak']=max(p['peak'],cj)
                if not p['flag']:
                    if sl is not None and r<=-sl: p['flag']=True
                    elif tp is not None and r>=tp: p['flag']=True
                    elif trail is not None and cj<=p['peak']*(1-trail) and p['peak']>p['o0']: p['flag']=True
                    elif zx is not None and zv[t]>=zx and t>p['sig']: p['flag']=True
                    elif mx is not None and bench[t]/bench[p['sig']]-1>=mx: p['flag']=True
            vs+=p['v']
        tot=cash+vs; peakE=max(peakE,tot); debt_=max(-cash,0.0)
        if debt_>1e-9:
            ratio=(vs+max(cash,0))/debt_; minr=min(minr,ratio)
            if ratio<liq:
                cash+=vs*(1-0.003); nliq+=1
                for p in act: tr.append((p['v']/p['inv']-1,t-p['e'],p['inv']/p['E0']))
                act=[]; vs=0.0; tot=cash
        eq[t]=tot; expo[t]=vs/max(tot,1e-9)
        if tot<=0.02: eq[t+1:]=eq[t]; break
    return eq,expo,np.array(tr) if tr else np.zeros((0,3)),nliq,minr
OUT=[]
def rec(group,name,**kw):
    eq,ex_,tr,nl,mr_=sim(**kw)
    years={}
    for y in range(2008,2027):
        ii=np.nonzero(np.char.startswith(dates,str(y))&np.isfinite(eq))[0]
        if len(ii)<20: continue
        prev=ii[0]-1; base=eq[prev] if prev>=0 and np.isfinite(eq[prev]) else eq[ii[0]]
        years[str(y)]=float(eq[ii[-1]]/base-1)
    s=stats(eq,ex_,'2008-01-01','2026-12-31')
    d=dict(group=group,name=name,years=years,cagr=float(s[0]),sharpe=float(s[1]),dd=float(s[2]),expo=float(s[3]),n=int(len(tr)),
           win=float((tr[:,0]>0).mean()) if len(tr) else None,liq=int(nl),minr=None if minr_ok(mr_) else float(mr_))
    OUT.append(d); print(f'{name:36s} 年化{s[0]*100:+5.1f}% 夏普{s[1]:.2f} 回撤{s[2]*100:.0f}% 笔{len(tr)} t={round(time.time()-T0)}',flush=True)
def minr_ok(m): return m==9.0
def done():
    json.dump(OUT,open(f'allyears_{GROUP}.json','w'),ensure_ascii=False)
if GROUP=='core':
    for L in (1.0,1.5,2.0,3.0): rec('杠杆',f'基线 {L:g}x',L=L)
    rec('对照','E6 随机选股 1x',rank=None); rec('对照','E6 随机选股 2x',L=2.0,rank=None)
    rec('对照','全部候选随机 1x（无E6）',pool=cand_all,rank=None); rec('对照','全部候选随机 2x（无E6）',L=2.0,pool=cand_all,rank=None)
    for N in (3,5,8,10,15,30,50): rec('持仓只数',f'N={N} 1x',N=N)
    rec('持仓只数','N=10 2x',N=10,L=2.0); rec('持仓只数','N=30 2x',N=30,L=2.0)
    rec('闸门','z≤-1.0 1x',gate=zv<=-1.0); rec('闸门','z≤-2.0 1x',gate=zv<=-2.0)
    rec('闸门','固定：大盘20日≤-9% 1x',gate=mk20<=-0.09); rec('闸门','无闸门（任何日期）1x',gate=np.isfinite(zv))
    rec('闸门','z≤-1.0 2x',gate=zv<=-1.0,L=2.0); rec('闸门','z≤-2.0 2x',gate=zv<=-2.0,L=2.0)
    rec('成本','每边冲击 10bp 2x',L=2.0,slip=0.001); rec('成本','每边冲击 20bp 2x',L=2.0,slip=0.002); rec('成本','每边冲击 40bp 2x',L=2.0,slip=0.004); rec('成本','每边冲击 20bp 1x',slip=0.002)
    rec('现金收益','闲置资金 1.5% 1x',cy=0.015); rec('现金收益','闲置资金 1.5% 2x',L=2.0,cy=0.015); rec('现金收益','闲置资金 2.0% 2x',L=2.0,cy=0.02)
    rec('融资利率','2x 利率固定 5%',L=2.0,rate=np.full(nd,0.05)); rec('融资利率','2x 利率固定 10%',L=2.0,rate=np.full(nd,0.10))
if GROUP=='exits':
    for h in (5,10,15,25,30,40): rec('持有天数',f'持有{h}天 1x',hold=h); rec('持有天数',f'持有{h}天 2x',hold=h,L=2.0)
    for s in (0.10,0.15,0.20,0.25): rec('止损止盈',f'止损{s*100:g}% 1x',sl=s)
    for s in (0.15,0.20): rec('止损止盈',f'止损{s*100:g}% 2x',sl=s,L=2.0)
    for s in (0.10,0.15,0.20): rec('止损止盈',f'止盈{s*100:g}% 1x',tp=s)
    for s in (0.08,0.12,0.16): rec('止损止盈',f'回撤止盈{s*100:g}% 1x',trail=s)
    for zx in (-0.5,0.0,0.5,1.0): rec('修复出场',f'z回到≥{zx:g}卖出 1x',zx=zx)
    for m in (0.06,0.08,0.10,0.15): rec('修复出场',f'大盘涨{m*100:g}%卖出 1x',mx=m)
if GROUP=='dyn':
    for (la,lb) in ((1,1),(2,2),(1,2),(1,3),(1.5,2),(1.5,2.5),(2,3),(1,1.5)):
        if (la,lb) in ((1,1),(2,2)): continue
        rec('按z深度动态杠杆',f'z∈(-2,-1.5]:{la:g}x z≤-2:{lb:g}x',Lfun=(lambda z,la=la,lb=lb: lb if z<=-2 else la))
    for lb in (1,2,3): rec('按z深度动态杠杆',f'只在z≤-2交易 {lb:g}x',gate=(zv<=-2),Lfun=(lambda z,lb=lb: lb))
    rec('回撤后降杠杆','2x 回撤>20%后新仓降到1x',L=2.0,ddcut=(0.20,1.0)); rec('回撤后降杠杆','2x 回撤>15%后新仓降到1x',L=2.0,ddcut=(0.15,1.0))
if GROUP=='env':
    for L in (2.0,1.0):
        t=f' {L:g}x'
        rec('环境过滤','前60日大盘已跌≥8%才开仓'+t,L=L,gate=sig0&(ret60<=-0.08))
        rec('环境过滤','前60日大盘已跌≥15%才开仓'+t,L=L,gate=sig0&(ret60<=-0.15))
        rec('环境过滤','大盘当日收涨才开仓'+t,L=L,gate=sig0&(mr>0))
        rec('环境过滤','大盘近3日上涨才开仓'+t,L=L,gate=sig0&(ret3>0))
        rec('环境过滤','当日E6≥10只才开仓'+t,L=L,gate=sig0&(ne6>=10))
        rec('环境过滤','当日E6≥20只才开仓'+t,L=L,gate=sig0&(ne6>=20))
        rec('环境过滤','当日E6占候选池≥0.4%才开仓'+t,L=L,gate=sig0&(frac>=0.004))
        rec('环境过滤','E6≥10且大盘当日收涨'+t,L=L,gate=sig0&(ne6>=10)&(mr>0))
    rec('仓位调节','z>-2时仓位减半 2x',L=2.0,Sday=np.where(zv<=-2,1.0,0.5))
    rec('仓位调节','前60日跌得越多仓位越大(0.5~1) 2x',L=2.0,Sday=np.clip(0.5+(-np.nan_to_num(ret60,nan=0))/0.3,0.5,1.0))
    rec('仓位调节','大盘3日未涨则仓位减半 2x',L=2.0,Sday=np.where(ret3>0,1.0,0.5))
    rec('仓位调节','E6<10只则仓位减半 2x',L=2.0,Sday=np.where(ne6>=10,1.0,0.5))
if GROUP=='fund':
    sets=(('基线 跌幅排序',e6,'ret20'),('剔除 资产负债率>70%',e6&~debt70,'ret20'),('剔除 质押>30%',e6&~pl30,'ret20'),('剔除 亏损(PE<=0)',e6&~loss,'ret20'),
          ('剔除 业绩预告为负',e6&~fcneg,'ret20'),('剔除 净利润同比<0',e6&~npneg,'ret20'),('剔除 质量差(亏损|预告负|负债>70|质押>50)',e6&~quality,'ret20'),
          ('只保留 市值较小一半',e6&small,'ret20'),('只保留 市值较大一半',e6&big,'ret20'),('排序=市值最小优先',e6,Rm),('排序=跌幅+小市值',e6,Rc))
    for nm,pool_,rk in sets:
        for L in (1.0,2.0): rec('基本面过滤',f'{nm} {L:g}x',L=L,pool=pool_,rank=rk)
done(); print('done',GROUP,round(time.time()-T0))

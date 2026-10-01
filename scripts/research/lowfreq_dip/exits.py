"""Exit-rule and dynamic-leverage tests on z<=-1.5 x E6 (N=20), 2008-2026. Research only."""
import numpy as np, time; T0=time.time()
exec(open('stockport.py').read().split("print('格式")[0])
rate_era=np.where(dates<'2020-01-01',0.085,np.where(dates<'2023-01-01',0.07,0.06))
sig=zv<=-1.5
def sim(N=20,hold=20,sl=None,tp=None,trail=None,zx=None,mx=None,Lfun=None,L=1.0,cy=0.0,ddcut=None,start='2008-01-01',liq=1.3,gate=None,rate=rate_era):
    g=sig if gate is None else gate
    Lf=Lfun if Lfun else (lambda z:L)
    Lcap=max(Lf(-9.0),Lf(-1.5),L if not Lfun else 0)
    t0=int(np.searchsorted(dates,start)); cash=1.0; act=[]; eq=np.full(nd,np.nan); expo=np.zeros(nd); tr=[]; nliq=0; minr=9.0; peakE=1.0
    for t in range(t0,nd-1):
        keep=[]
        for p in act:
            done=False
            if p['flag'] and np.isfinite(o[t,p['j']]): px=o[t,p['j']]; done=True
            elif t>=p['sig']+hold and np.isfinite(c[t,p['j']]): px=c[t,p['j']]; done=True
            if done:
                raw=px/f[t,p['j']]; m=(px*(1-0.01/raw))/(p['o0']*(1+0.01/p['rawE']))-1-p['fee']
                cash+=p['inv']*(1+m-0.0) ; tr.append((m,t-p['e'],p['inv']/p['E0']))
            else: keep.append(p)
        act=keep
        slots=N-len(act)
        if g[t] and slots>0 and t+1<nd:
            cs=np.nonzero(e6[t])[0]; hs={p['j'] for p in act}; cs=[j for j in cs if j not in hs]
            if cs:
                cs=sorted(cs,key=lambda j:ret20[t,j])[:slots]
                invested=sum(p['v'] for p in act); E=cash+invested
                Lt=Lf(zv[t]);
                if ddcut and E<peakE*(1-ddcut[0]): Lt=min(Lt,ddcut[1])
                for j in cs:
                    if Lt<=0: break
                    size=min(Lt*E/N, Lcap*E-invested)
                    if size<=1e-9: break
                    cash-=size; invested+=size
                    rawE_=float(o[t+1,j]/f[t+1,j])
                    act.append(dict(j=j,sig=t,e=t+1,o0=float(o[t+1,j]),rawE=rawE_,fee=float(fee1[t]),inv=size,v=size,E0=E,flag=False,peak=float(o[t+1,j]),costE=0.01/rawE_+float(fee1[t])/2))
        if cash<0: cash-=(-cash)*rate[t]/242.0
        elif cy>0: cash+=cash*cy/242.0
        vs=0.0
        for p in act:
            if p['e']<=t and np.isfinite(c[t,p['j']]):
                cj=float(c[t,p['j']]); p['v']=p['inv']*(cj/p['o0'])*(1-p['costE']); r=cj/p['o0']-1; p['peak']=max(p['peak'],cj)
                if not p['flag']:
                    if sl is not None and r<=-sl: p['flag']=True
                    elif tp is not None and r>=tp: p['flag']=True
                    elif trail is not None and cj<=p['peak']*(1-trail) and p['peak']>p['o0']*1.0: p['flag']=True
                    elif zx is not None and zv[t]>=zx and t>p['sig']: p['flag']=True
                    elif mx is not None and bench[t]/bench[p['sig']]-1>=mx: p['flag']=True
            vs+=p['v']
        tot=cash+vs; peakE=max(peakE,tot); debt=max(-cash,0.0)
        if debt>1e-9:
            ratio=(vs+max(cash,0))/debt; minr=min(minr,ratio)
            if ratio<liq:
                cash+=vs*(1-0.003); nliq+=1
                for p in act: tr.append((p['v']/p['inv']-1,t-p['e'],p['inv']/p['E0']))
                act=[]; vs=0.0; tot=cash
        eq[t]=tot; expo[t]=vs/max(tot,1e-9)
        if tot<=0.02: break
    return eq,expo,np.array(tr),nliq,minr
def show(tag,res):
    eq,ex_,tr,nl,mr_=res; cells=[]
    for pn,(a,b) in ERA.items():
        s=stats(eq,ex_,a,b); cells.append('无' if s is None else f'{s[0]*100:+5.1f}/{s[1]:+.2f}/{s[2]*100:3.0f}')
    s=stats(eq,ex_,'2008-01-01','2026-12-31'); m=tr[:,0]
    print(f'{tag:34s}| '+' | '.join(cells)+f' | 仓{s[3]*100:2.0f}% 笔{len(m)} 均{m.mean()*1e4:+4.0f}bp 胜{(m>0).mean()*100:.0f}% 持{tr[:,1].mean():4.1f}天 最差{m.min()*100:.0f}%'+(f' 强平{nl}' if nl else ''),flush=True)
print('格式：年化%/夏普/回撤%；列='+' | '.join(ERA))
print('\n[0] 基线核对 1x hold20（应为 +10.2/0.70/-28）'); show('1x hold20',sim())
print('\n[A] 持有天数（1x | 2x）')
for h in (5,10,15,20,25,30,40):
    show(f'1x hold{h}',sim(hold=h)); show(f'2x hold{h}',sim(hold=h,L=2.0))
print('\n[B] 止损/止盈/移动止盈（1x，hold20，触发后次日开盘卖）')
for s in (0.10,0.15,0.20,0.25): show(f'止损{s*100:g}%',sim(sl=s))
for s in (0.10,0.15,0.20): show(f'止盈{s*100:g}%',sim(tp=s))
for s in (0.08,0.12,0.16): show(f'回撤止盈 自高点回落{s*100:g}%',sim(trail=s))
print('\n[C] 大盘修复/反弹出场（1x，hold20）')
for zx in (-0.5,0.0,0.5,1.0): show(f'z回到>={zx:g}就卖',sim(zx=zx))
for m in (0.06,0.08,0.10,0.15): show(f'大盘自信号日涨{m*100:g}%就卖',sim(mx=m))
print('\n[D] 按 z 深度动态杠杆（信号日 z 决定该笔杠杆；年代利率）')
for (la,lb) in ((1,1),(2,2),(1,2),(1,3),(1.5,2),(1.5,2.5),(2,3),(1,1.5)):
    show(f'z∈(-2,-1.5]:{la:g}x  z<=-2:{lb:g}x',sim(Lfun=(lambda z,la=la,lb=lb: lb if z<=-2 else la)))
for lb in (1,2,3): show(f'只在z<=-2交易 {lb:g}x',sim(gate=(zv<=-2),Lfun=(lambda z,lb=lb: lb)))
print('\n[E] 其他：空仓现金收益 / 回撤后降杠杆')
show('2x 现金收益1.5%',sim(L=2.0,cy=0.015)); show('1x 现金收益1.5%',sim(cy=0.015)); show('2x 现金收益2.0%',sim(L=2.0,cy=0.02))
show('2x 回撤>20%后新仓降到1x',sim(L=2.0,ddcut=(0.20,1.0))); show('2x 回撤>15%后新仓降到1x',sim(L=2.0,ddcut=(0.15,1.0)))
print('done',round(time.time()-T0))

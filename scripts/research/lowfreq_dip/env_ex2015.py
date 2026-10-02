import sys, inspect, numpy as np, os, copy
sys.path.insert(0,os.path.expanduser('~/mnt/niuniu/src'))
from quantlab.dipbuy.panel import Panel
from quantlab.dipbuy import engine as E
P=Panel.from_npz('panel_ext.npz'); mk,cd=E.compute_features(P)
dates=P.dates; nd=len(dates); idx=np.cumprod(1+mk.mret)
ret60=np.full(nd,np.nan); ret60[60:]=idx[60:]/idx[:-60]-1
ret3=np.full(nd,np.nan); ret3[3:]=idx[3:]/idx[:-3]-1
ret5=np.full(nd,np.nan); ret5[5:]=idx[5:]/idx[:-5]-1
ne6=(cd.e6&cd.buyok).sum(1)
src=inspect.getsource(E.simulate).replace("size = min(L * equity / N, L * equity - invested)","size = min(L * SCALE[t] * equity / N, L * equity - invested)")
ns=dict(E.__dict__); ns['SCALE']=np.ones(nd); exec(src,ns); sim=ns['simulate']
end=str(dates[nd-23])
def run(L,gate_ok=None,scale=None,label=''):
    z=mk.z.copy()
    if gate_ok is not None: z=np.where(gate_ok,z,9.0)
    m=E.Market(mret=mk.mret,mk20=mk.mk20,z=z,count=mk.count)
    ns['SCALE']=np.ones(nd) if scale is None else scale
    cfg=E.DipConfig(leverage=L,end=end)
    r=sim(P,m,cd,cfg)
    out=[]
    for a,b in (('2008-01-01','2026-12-31'),('2008-01-01','2016-12-31'),('2017-01-01','2026-12-31')):
        s=E.period_stats(dates,r['eq'],r['expo'],a,b); out.append(s)
    return out,len(r['trades']),r['info']['n_liquidations'],r['info']['min_margin_ratio']
def show(label,res):
    out,n,liq,mr=res
    cells=[f"{s['cagr']*100:+5.1f}%/{s['sharpe']:.2f}/{s['max_drawdown']*100:4.0f}%/仓{s['exposure']*100:2.0f}" for s in out]
    print(f'{label:34s}| '+' | '.join(cells)+f' | 笔{n} 强平{liq}',flush=True)

nu=cd.uni.sum(1).astype(float); frac=ne6/np.maximum(nu,1)

nu=cd.uni.sum(1).astype(float); frac=ne6/np.maximum(nu,1)
def rets(L,g):
    ns['SCALE']=np.ones(nd); z=np.where(g,mk.z,9.0) if g is not None else mk.z
    m=E.Market(mret=mk.mret,mk20=mk.mk20,z=z,count=mk.count); r=sim(P,m,cd,E.DipConfig(leverage=L,end=end)); eq=r['eq']
    d=np.full(nd,np.nan); d[1:]=eq[1:]/eq[:-1]-1; return d
def st(d,mask):
    x=d[mask&np.isfinite(d)]; yrs=len(x)/245; c=np.prod(1+x)**(1/yrs)-1; return c, x.mean()/x.std()*np.sqrt(245)
yr=np.array([int(x[:4]) for x in dates]); base=(dates>='2008-01-02')
for L in (2.0,1.0):
    print(f'--- {L:g}x: 去掉2015年后的 年化/夏普 (括号内为含2015)')
    for nm,g in (('基准',None),('E6>=10',ne6>=10),('E6占比>=0.4%',frac>=0.004),('E6占比>=0.6%',frac>=0.006)):
        d=rets(L,g); a=st(d,base&(yr!=2015)); b=st(d,base)
        print(f'{nm:14s} 去2015: {a[0]*100:+5.1f}% / {a[1]:.2f}   (含: {b[0]*100:+5.1f}% / {b[1]:.2f})')
# what happened in 2015 with each
t=np.nonzero((np.char.startswith(dates,'2015'))&(mk.z<=-1.5))[0]
print('2015闸门日',[str(dates[i]) for i in t][:25]); print('2015各闸门日 E6只数',[int(ne6[i]) for i in t][:25])

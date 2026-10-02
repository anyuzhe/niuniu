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
print('格式：年化/夏普/回撤/平均仓位；列=全期 | 2008-16 | 2017-26')
for L in (2.0,):
    show(f'基准 {L:g}x',run(L))
    show('基准 1.5x',run(1.5)); show('基准 1x',run(1.0))
    show('F1 只在前60日大盘已跌≥8%时开仓',run(L,gate_ok=ret60<=-0.08))
    show('F2 只在前60日大盘已跌≥15%时开仓',run(L,gate_ok=ret60<=-0.15))
    show('F3 大盘当日收涨才开仓(止跌)',run(L,gate_ok=mk.mret>0))
    show('F4 大盘近3日涨跌>0才开仓',run(L,gate_ok=ret3>0))
    show('F5 当日E6只数>=10才开仓(多股收复)',run(L,gate_ok=ne6>=10))
    show('F6 当日E6只数>=20才开仓',run(L,gate_ok=ne6>=20))
    sc=np.where(mk.z<=-2.0,1.0,0.5); show('T1 z>-2时仓位减半(其余满)',run(L,scale=sc))
    sc=np.clip(0.5+(-np.nan_to_num(ret60,nan=0))/0.3,0.5,1.0); show('T2 前60日跌得越多仓位越大(0.5~1)',run(L,scale=sc))
    sc=np.where(ret3>0,1.0,0.5); show('T3 大盘3日未涨则仓位减半',run(L,scale=sc))
    sc=np.where(ne6>=10,1.0,0.5); show('T4 E6<10只则仓位减半',run(L,scale=sc))
# how many gate days survive each filter
g=(mk.z<=-1.5)&(np.arange(nd)<nd-23)&(dates>='2008-01-01')
for nm,f in (('base',np.ones(nd,bool)),('F1',ret60<=-0.08),('F3',mk.mret>0),('F4',ret3>0),('F5',ne6>=10)):
    print(nm,'闸门日',int((g&f).sum()),'/',int(g.sum()))

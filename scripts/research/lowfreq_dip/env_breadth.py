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
print('候选池规模(只) 各时期中位:',{y:int(np.median(nu[(np.char.startswith(dates,str(y)))])) for y in (2008,2012,2016,2020,2024)})
print('格式：年化/夏普/回撤/平均仓位；列=全期 | 2008-16 | 2017-26 (2x)')
show('基准 2x',run(2.0))
for k in (3,5,8,10,15,20,30,40):
    show(f'E6只数>={k}',run(2.0,gate_ok=ne6>=k))
for f in (0.002,0.004,0.006,0.01,0.015):
    show(f'E6占候选池>={f*100:.1f}%',run(2.0,gate_ok=frac>=f))
show('E6>=10 且 大盘当日收涨',run(2.0,gate_ok=(ne6>=10)&(mk.mret>0)))
show('E6占比>=0.4% 且 大盘当日收涨',run(2.0,gate_ok=(frac>=0.004)&(mk.mret>0)))
print('\n1x:'); show('基准 1x',run(1.0)); show('E6只数>=10',run(1.0,gate_ok=ne6>=10)); show('E6占比>=0.4%',run(1.0,gate_ok=frac>=0.004)); show('大盘当日收涨',run(1.0,gate_ok=mk.mret>0))
# yearly comparison at 2x
def yearly(res_gate):
    ns['SCALE']=np.ones(nd)
    z=np.where(res_gate,mk.z,9.0) if res_gate is not None else mk.z
    m=E.Market(mret=mk.mret,mk20=mk.mk20,z=z,count=mk.count); r=sim(P,m,cd,E.DipConfig(leverage=2.0,end=end)); eq=r['eq']; out={}
    for y in range(2008,2027):
        ii=np.nonzero((np.char.startswith(dates,str(y)))&np.isfinite(eq))[0]
        if len(ii)>=20: out[y]=eq[ii[-1]]/eq[ii[0]]-1
    return out
b=yearly(None)
for nm,g in (('E6>=10',ne6>=10),('E6占比>=0.4%',frac>=0.004),('大盘当日收涨',mk.mret>0)):
    f=yearly(g); better=sum(1 for y in b if f[y]>b[y]+1e-9); worse=sum(1 for y in b if f[y]<b[y]-1e-9)
    print(nm,'逐年: 更好',better,'更差',worse,'相同',len(b)-better-worse,' 最大改善',max(f[y]-b[y] for y in b), '最大变差',min(f[y]-b[y] for y in b))
    print('   ',' '.join(f'{y}:{(f[y]-b[y])*100:+.0f}' for y in b))

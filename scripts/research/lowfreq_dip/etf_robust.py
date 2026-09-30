"""Robustness of the ETF 'dip then hold ~20 days' finding: non-overlapping positions, price filter, by year/category, leave-one-out, horizon shape."""
import numpy as np, warnings; warnings.filterwarnings('ignore')
from etfcore import *
T=np.arange(nd); jj=np.arange(nc)[None,:]
yr=np.array([d[:4] for d in dates]); catarr=np.array([cat[s] for s in syms])
def build(Hd):
    ei=np.tile(np.minimum(T+Hd,nd-1)[:,None],(1,nc)); okx=(T+Hd<nd)
    for _ in range(3):
        bad=~fin[ei,jj]|limdn_close[ei,jj]; ei=np.where(bad&(ei<nd-1),ei+1,ei)
    exC=C[ei,jj]; enO=np.full((nd,nc),np.nan); enO[:-1]=O[1:]
    buy_ok=np.zeros((nd,nc),bool); buy_ok[:-1]=fin[1:]&~limup_open[1:]
    winbad=(badc[np.minimum(ei,nd-1),jj]-badc[np.maximum(T-1,0)[:,None],jj])>0
    valid=uni&buy_ok&okx[:,None]&np.isfinite(exC)&np.isfinite(enO)&~winbad
    gross=exC/enO-1; enR=enO
    net=(exC-0.001)/(enO+0.001)-1-FEE
    net_half=(exC-0.0005)/(enO+0.0005)-1-FEE   # half-tick per side (mid-ish fills)
    return valid,gross,net,net_half,ei
def nonoverlap(sig,ei):
    """keep a signal only if that ETF has no open position (entry t+1 .. exit ei[t]) from an earlier kept signal"""
    keep=np.zeros_like(sig); free=np.full(nc,-1)
    for t in range(nd):
        row=np.nonzero(sig[t]&(free<=t))[0]
        for j in row: keep[t,j]=True; free[j]=ei[t,j]
    return keep
def stats(x,g,bmx=None):
    w=x>0; pay=x[w].mean()/-x[~w].mean() if w.any() and (~w).any() else np.nan
    t=cl_t(x,g); s=f'{len(x):4d}笔 净{x.mean()*1e4:+5.0f}bp(t{t:+.1f}) 胜率{w.mean()*100:.0f}% 赔率{pay:.2f}'
    if bmx is not None: xe=x-bmx; s+=f' 超额{xe.mean()*1e4:+5.0f}(t{cl_t(xe,g):+.1f})'
    return s
RULES=['V1基准(20日跌>10%)','V1候选(+效率>-0.5)','R2收盘位置(<0.3)','ETF尺度:5日跌≥5%']
for Hd in (20,):
    valid,gross,net,net_half,ei=build(Hd); bm=np.nanmean(np.where(valid,gross,np.nan),1)
    print(f'##### 持有{Hd}天：去重叠（同一只ETF持仓期间不再开新仓）#####')
    for name in RULES:
        rm=rules[name]; sig=valid&rm; keep=nonoverlap(sig,ei)
        print(name)
        for pn,(a,b) in per.items():
            dm=(dates>=a)&(dates<=b); mm=keep&dm[:,None]
            if mm.sum()<20: print('   ',pn,'样本不足',mm.sum()); continue
            d_,c_=np.nonzero(mm); print('   ',pn,stats(net[d_,c_],mon[d_],bm[d_]))
        d_,c_=np.nonzero(keep); print('    合计',stats(net[d_,c_],mon[d_],bm[d_]),f'| 半个价位成本 净{net_half[d_,c_].mean()*1e4:+.0f}bp')
    print('\n#### 价格≥2元的ETF（每边1价位≤5bp）#####')
    px=np.where(np.isfinite(C),C,0)>=2.0
    for name in RULES:
        keep=nonoverlap(valid&rules[name]&px,ei); d_,c_=np.nonzero(keep)
        print(name,'|',stats(net[d_,c_],mon[d_],bm[d_]))
    print('\n#### 分年（去重叠，V1基准 / R2收盘位置）#####')
    for name in (RULES[0],RULES[2]):
        keep=nonoverlap(valid&rules[name],ei); out=[]
        for Y in range(2020,2027):
            m=keep&(yr==str(Y))[:,None]
            if m.sum()<10: out.append(f'{Y}: —'); continue
            d_,c_=np.nonzero(m); out.append(f'{Y}: {len(d_)}笔 净{net[d_,c_].mean()*1e4:+.0f} 超额{(net[d_,c_]-bm[d_]).mean()*1e4:+.0f}')
        print(name,'|',' | '.join(out))
    print('\n#### 按类别（去重叠，V1基准）#####')
    keep=nonoverlap(valid&rules[RULES[0]],ei)
    for cn in ('broad','sector','cross_border','gold'):
        m=keep&(catarr==cn)[None,:]; d_,c_=np.nonzero(m)
        if len(d_)>=20: print(cn,'|',stats(net[d_,c_],mon[d_],bm[d_]))
    print('\n#### 去掉贡献最大的一只/一个月（V1基准，去重叠）#####')
    d_,c_=np.nonzero(keep); x=net[d_,c_]-bm[d_]
    by=np.bincount(c_,x,minlength=nc); worst=np.argsort(-by)[:3]
    for w in worst:
        mk=c_!=w; print(f'去掉 {syms[w]}: 超额{x[mk].mean()*1e4:+.0f}bp (t{cl_t(x[mk],mon[d_][mk]):+.1f}) 笔数{mk.sum()}')
    mo=mon[d_]; um=np.unique(mo); contrib={m:x[mo==m].sum() for m in um}; top=max(contrib,key=contrib.get)
    mk=mo!=top; print(f'去掉最好的月份 {top}: 超额{x[mk].mean()*1e4:+.0f}bp (t{cl_t(x[mk],mo[mk]):+.1f})')
    print('赚钱的月份占比(按月平均超额>0):',np.mean([x[mo==m].mean()>0 for m in um]).round(2),'月数',len(um))
print('\n#### 持有期形状（去重叠 V1基准，超额bp / t）#####')
for Hd in (5,10,15,20,30,40):
    valid,gross,net,net_half,ei=build(Hd); bm=np.nanmean(np.where(valid,gross,np.nan),1)
    keep=nonoverlap(valid&rules[RULES[0]],ei); d_,c_=np.nonzero(keep); x=net[d_,c_]-bm[d_]
    print(f'H={Hd:2d}: {len(d_)}笔 净{net[d_,c_].mean()*1e4:+.0f}bp 超额{x.mean()*1e4:+.0f}bp t{cl_t(x,mon[d_]):+.1f}')

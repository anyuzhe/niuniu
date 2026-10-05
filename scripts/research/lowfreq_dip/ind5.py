"""Leverage grid: original (market-panic E6) vs industry panic variants. Research only."""
import sys
src=open('ind2.py').read().split("allg=np.isfinite(zv)\n# episodes")[0]
exec(src)
allg=np.isfinite(zv); pan=zv<=-1.5
sizes={g:(ind==g).sum() for g in u}; big=np.array(u)[[sizes[g]>=60 for g in u]]; bigm=np.isin(ind,big)[None,:]
U=valid&(zind<=-1.5); UL=U&bigm; A=valid&(zind<=-1.5)&nonp[:,None]
def full(name,gate,pool,L,**kw):
    eq,ex_,tr,nl,mr_=sim(gate=gate,pool=pool,L=L,**kw)
    m=np.isfinite(eq); e=eq[m]; r=e[1:]/e[:-1]-1; yrs=len(r)/245
    cagr=e[-1]**(1/yrs)-1; sh=r.mean()/(r.std()+1e-12)*np.sqrt(245); dd=(e/np.maximum.accumulate(e)-1).min()
    # longest underwater (trading days)
    pk=np.maximum.accumulate(e); uw=0; best=0
    for v,p in zip(e,pk):
        uw=uw+1 if v<p*0.9999 else 0; best=max(best,uw)
    yy={}
    for y in range(2008,2027):
        ii=np.nonzero(np.char.startswith(dates,str(y))&m)[0]
        if len(ii)<20: continue
        prev=ii[0]-1; base=eq[prev] if prev>=0 and np.isfinite(eq[prev]) else eq[ii[0]]
        yy[y]=eq[ii[-1]]/base-1
    worst=min(yy.values()); pos=np.mean([v>0 for v in yy.values()])
    r20=e[20:]/e[:-20]-1
    d=dict(name=name,cagr=cagr,sh=sh,dd=dd,calmar=cagr/abs(dd),expo=ex_[m].mean(),peak=ex_[m].max(),minr=None if mr_==9.0 else mr_,nl=nl,worst_year=worst,pos_years=pos,worst20=r20.min(),uw_years=best/245,final=e[-1]/e[0],n=len(tr),yy=yy)
    print(f"{name:34s} 年化{cagr*100:+5.1f}% 夏普{sh:.2f} 回撤{dd*100:4.0f}% 卡玛{d['calmar']:.2f} 平均仓位{d['expo']*100:3.0f}% 峰值杠杆{d['peak']:.1f}x 最低保证金比{'-' if d['minr'] is None else f'{mr_:.2f}'} 强平{nl} 最差年{worst*100:+.0f}% 盈利年占{pos*100:.0f}% 最差20日{r20.min()*100:.0f}% 最长回撤期{best/245:.1f}年 终值{d['final']:.1f}x",flush=True)
    return d
R=[]
for L in (1.0,1.5,2.0,2.5,3.0):
    R.append(full(f'原策略 大盘恐慌E6 {L:g}x',pan,e6,L))
for L in (1.0,1.5,2.0,2.5,3.0):
    R.append(full(f'行业恐慌(统一闸门) {L:g}x',allg,U,L))
for L in (1.0,1.5,2.0):
    R.append(full(f'行业恐慌(仅大行业) {L:g}x',allg,UL,L))
for L in (1.0,2.0):
    R.append(full(f'行业恐慌(仅大盘没恐慌日) {L:g}x',allg,A,L))
print('--- 统一闸门 + 回撤保护（回撤超过阈值后新仓降到1x）')
R.append(full('统一 2x 回撤>20%后新仓降到1x',allg,U,2.0,ddcut=(0.20,1.0)))
R.append(full('统一 2x 回撤>30%后新仓降到1x',allg,U,2.0,ddcut=(0.30,1.0)))
R.append(full('统一 3x 回撤>20%后新仓降到1x',allg,U,3.0,ddcut=(0.20,1.0)))
R.append(full('大行业 2x 回撤>20%后新仓降到1x',allg,UL,2.0,ddcut=(0.20,1.0)))
print('--- 融资利率敏感(统一 2x)')
for rt in (0.05,0.085,0.10): R.append(full(f'统一 2x 融资利率固定{rt*100:.1f}%',allg,U,2.0,rate=np.full(nd,rt)))
print('--- 逐年(%)')
print('年份'.ljust(26),' '.join(f'{y%100:4d}' for y in range(2008,2027)))
for d in R:
    if d['name'] in ('原策略 大盘恐慌E6 2x','行业恐慌(统一闸门) 1x','行业恐慌(统一闸门) 1.5x','行业恐慌(统一闸门) 2x','行业恐慌(仅大行业) 1.5x','统一 2x 回撤>20%后新仓降到1x'):
        print(f"{d['name']:26s}",' '.join('  - ' if y not in d['yy'] else f"{d['yy'][y]*100:+4.0f}" for y in range(2008,2027)))
import json; json.dump([{k:(v if k!='yy' else {str(a):b for a,b in v.items()}) for k,v in d.items()} for d in R],open('ind5.json','w'),ensure_ascii=False,default=float)

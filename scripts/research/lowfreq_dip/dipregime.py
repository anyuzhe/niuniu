"""When to buy the dip? day-level regime vs the mean 20-day net outcome of that day's candidates, plus winsorised factor spreads."""
import os, sys, numpy as np, warnings; warnings.filterwarnings('ignore')
sys.argv=['x']
exec(open('lowfreq.py').read().split("mon=np.array")[0])
Z=np.load('dipfeat.npz'); di=Z['date_idx']; y=Z['y']
mret=np.nanmean(np.where(uni,ret1,np.nan),1); mret[~np.isfinite(mret)]=0
idx=np.cumprod(1+mret); mk20=idx/np.r_[np.full(20,np.nan),idx[:-20]]-1
ma250=np.convolve(idx,np.ones(250)/250,'full')[:nd]; ma250[:249]=np.nan; above=idx/ma250-1
mk60=idx/np.r_[np.full(60,np.nan),idx[:-60]]-1
share=(base&uni).sum(1)/np.maximum(uni.sum(1),1)          # share of universe that is in the dip set
ndays=len(dates); dm=np.bincount(di,y,minlength=ndays)/np.maximum(np.bincount(di,minlength=ndays),1); has=np.bincount(di,minlength=ndays)>=20
# market-adjusted: subtract the same-window universe mean? use raw net and also net minus universe mean of same window
yr=np.array([d[:4] for d in dates]); mo=np.array([d[:7] for d in dates])
P={'2020-22':('2020','2021','2022'),'2023-24':('2023','2024'),'2025-26':('2025','2026')}
def tstat(x,m):
    um=np.unique(mo[m]); mm=np.array([x[m&(mo==u)].mean() for u in um]); return mm.mean()*1e4, mm.mean()/(mm.std(ddof=1)/np.sqrt(len(mm))+1e-12), len(um)
print('当天候选（20日跌>10%的股票）平均20日净收益，按“当天的市场状态”五分位分组（每档内的月份聚类t）\n')
for nm,var in (('全市场20日涨跌(等权)',mk20),('全市场60日涨跌',mk60),('全市场相对250日均线',above),('跌幅候选占全市场比例',share)):
    print(f'-- {nm}')
    ok=has&np.isfinite(var)
    qs=np.nanpercentile(var[ok],[20,40,60,80]); q=np.digitize(var,qs)
    for k,(pn,ys) in enumerate(P.items()):
        line=[]
        for g in range(5):
            m=ok&(q==g)&np.isin(yr,ys)
            if m.sum()<15: line.append('   —   '); continue
            a,t,n=tstat(dm,m); line.append(f'{a:+5.0f}({t:+.1f})')
        print(f'   {pn}: '+' | '.join(line)+'   (从最低20%到最高20%)')
    # overall five-bucket using full period cutoffs
    line=[]
    for g in range(5):
        m=ok&(q==g); a,t,n=tstat(dm,m); line.append(f'{a:+5.0f}({t:+.1f})')
    print('   全期: '+' | '.join(line))

import numpy as np
exec(open('stockport.py').read().split("print('格式")[0])
rg=np.random.default_rng(5)
ok=np.isfinite(zv); yr=np.array([int(d[:4]) for d in dates]); mo=np.array([int(d[5:7]) for d in dates])
g=np.nonzero((zv<=-1.5)&ok)[0]; eps=[]
for t in g:
    if eps and t-eps[-1][-1]<20: eps[-1].append(t)
    else: eps.append([t])
st=np.array([e[0] for e in eps]); gap=np.diff(st); cv0=gap.std()/gap.mean()
valid=np.nonzero(ok)[0]; cvs=[]
# random starts obeying the same minimum spacing (>=20 days after an episode ends ~ use start gap>=25)
while len(cvs)<4000:
    s=np.sort(rg.choice(valid,len(st),replace=False)); d=np.diff(s)
    if d.min()<25: continue
    cvs.append(d.std()/d.mean())
cvs=np.array(cvs); print(f'同样最小间隔约束下的随机CV中位{np.median(cvs):.2f}（5%~95% {np.percentile(cvs,5):.2f}~{np.percentile(cvs,95):.2f}），本数据CV={cv0:.2f}，分位{(cvs<cv0).mean()*100:.0f}%')
# month effect permutation on episode-level E6 pool net
pool_net=np.array([np.nanmean(net[t][e6[t]]) if e6[t].any() else np.nan for t in range(nd)])
rows=[]
for e in eps:
    v=pool_net[[t for t in e if np.isfinite(pool_net[t])]]
    if len(v): rows.append((dates[e[0]],mo[e[0]],np.nanmean(v)))
yrs=np.array([int(d[:4]) for d,_,_ in rows]); m=np.array([x[1] for x in rows]); v=np.array([x[2] for x in rows])
def q4(mm): return ((mm>=10)).astype(int)
def stat(mm,vv): return vv[mm>=10].mean()-vv[mm<10].mean()
s0=stat(m,v); ps=[stat(rg.permutation(m),v) for _ in range(20000)]
print(f'10-12月起始段 n={int((m>=10).sum())} 平均{v[m>=10].mean()*100:+.1f}% vs 其它 n={int((m<10).sum())} 平均{v[m<10].mean()*100:+.1f}% 差{s0*100:+.1f}点；置换p={np.mean(np.array(ps)>=s0):.3f}')
for d,mm,x in rows:
    if mm>=10: print('   ',d,f'{x*100:+.1f}%')
keep=yrs!=2008; s1=stat(m[keep],v[keep]); ps=[stat(rg.permutation(m[keep]),v[keep]) for _ in range(20000)]
print(f'去掉2008年：差{s1*100:+.1f}点 p={np.mean(np.array(ps)>=s1):.3f}')
# 12 months x best month: p of max monthly mean (multiple comparison)
mm_means=lambda mm,vv:[vv[mm==k].mean() if (mm==k).any() else -9 for k in range(1,13)]
s_max=max(mm_means(m,v)); pm=[max(mm_means(rg.permutation(m),v)) for _ in range(5000)]
print('最好月份平均',round(s_max*100,1),'% ; 若月份标签无意义，12个月里最好那个月至少这么高的概率',round(np.mean(np.array(pm)>=s_max),3))
# year-cycle: 4-year / 'presidential-like' no. Phase of 4-year: episodes by (year mod 4)
cnt=np.bincount([y%4 for y in yrs],minlength=4); print('起始年份 mod 4 分布',cnt.tolist())
# decade-scale regimes: panic days per half-year, and number of E6 per panic
hy=[(y,h,int(((yr==y)&(mo>(6*h))&(mo<=6*(h+1))&(zv<=-1.5)).sum())) for y in range(2007,2027) for h in (0,1)]
print('半年闸门日数：',' '.join(f'{y%100:02d}{"H"+str(h+1)}:{n}' for y,h,n in hy))

import os; os.environ['C70DIR']='c80'; os.environ['SERIES']='c80/series.npz'
import numpy as np, json, lib73 as X, lib70 as L, lib74 as Y
DD=np.asarray(Y.DD60,np.float32); yr=L.yr
out={}
for nm,kw in (('D (20日跌幅排序)',dict(sleeves='ACB')),('D + 回撤二段排序(前40再按60日回撤)',dict(sleeves='ACB',rank_s={s:Y.two_stage(s,40,DD) for s in 'ACB'}))):
    eq,ex,tr,cl=X.fused5(**kw); r=np.full(len(eq),np.nan); r[1:]=eq[1:]/eq[:-1]-1; m=np.isfinite(r)
    st=L.stats(eq,ex,tr); rows={}
    for y in sorted(set(yr[m])):
        k=m&(yr==y); rows[int(y)]=float(np.prod(1+r[k])-1)
    out[nm]=dict(cagr=st['cagr'],sharpe=st['sharpe'],dd=st['dd'],final=st['final'],years=rows, expo={int(y):float(np.mean(ex[m&(yr==y)])) for y in rows})
json.dump(out,open('yr83.json','w'),ensure_ascii=False)
a,b=[out[k] for k in out]
print('年份  D  D+排序  仓位')
for y in a['years']: print(y, f"{a['years'][y]*100:+6.1f}% {b['years'][y]*100:+6.1f}%  {a['expo'][y]*100:3.0f}%")
for k,v in out.items(): print(k,'年化%.1f%% 夏普%.2f 回撤%.0f%% 总倍数%.1f'%(v['cagr']*100,v['sharpe'],v['dd']*100,v['final']))

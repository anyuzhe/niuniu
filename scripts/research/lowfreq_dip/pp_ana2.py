import numpy as np, warnings; warnings.filterwarnings('ignore')
exec(open('pp_ana.py').read().split("res={}")[0])
res=np.load('pp_res.npy',allow_pickle=True).item()
# ---- selection rule on 2020-22 (H=20): |episode t|>=2 and >=75% episodes same sign
sel=[]
for f in fn:
    ic,sp=res[(20,f)]; a=stat(by_ep(ic,pm['2020-22']))
    if abs(a[1])>=2 and max(a[2],1-a[2])>=0.75: sel.append((f,-1 if a[0]<0 else 1,a[1]))
print('2020-22 入选(H=20, |t|>=2 且>=75%段同号):',[(f,s) for f,s,_ in sel],' 共检验',len(fn),'个因子 x 2 个持有期')
def crank(f,i,m):
    x=F[f][i].astype(np.float64); r=np.full(x.shape,np.nan); mm=m&np.isfinite(x); n=mm.sum()
    r[mm]=rank(x[mm])/max(n-1,1); return r
SETS={'S1 20日跌幅最大':[('ret20',-1)],'S2 离MA20最远':[('dist_ma20',-1)],
 'S3 反转族(5日,20日,距60日高,距MA20)':[('ret5',-1),('ret20',-1),('dist_hi60',-1),('dist_ma20',-1)],
 'S4 S3+小成交额+今日缩量':[('ret5',-1),('ret20',-1),('dist_hi60',-1),('dist_ma20',-1),('logamt20',-1),('volratio_today',-1)],
 'S5 S3+高beta':[('ret5',-1),('ret20',-1),('dist_hi60',-1),('dist_ma20',-1),('beta60',1)]}
net20=Z['net20']; net10=Z['net10']
def score(fl,i,m,restrict=None):
    mm=m.copy()
    if restrict=='big': 
        la=F['logamt20'][i]; mm=mm&(la>=np.nanmedian(la[m]))
    s=np.zeros(len(mm)); k=0
    for f,sg in fl:
        r=crank(f,i,mm); s=s+(r if sg>0 else 1-r); k+=1
    s=s/k; s[~mm]=np.nan; return s,mm
def eval_set(fl,topn=None,frac=0.2,restrict=None,net=net20):
    rel=np.full(len(Dsel),np.nan); absr=np.full(len(Dsel),np.nan); allm=np.full(len(Dsel),np.nan)
    for i in range(len(Dsel)):
        m=cand[i]&np.isfinite(net[i])
        if m.sum()<300: continue
        s,mm=score(fl,i,m,restrict); idx=np.nonzero(mm&np.isfinite(s))[0]
        o=idx[np.argsort(-s[idx])]; k=topn if topn else int(len(o)*frac)
        top=o[:k]; absr[i]=net[i][top].mean(); allm[i]=net[i][m].mean(); rel[i]=absr[i]-allm[i]
    return rel,absr,allm
def rep(tag,rel,absr,allm):
    cells=[]
    for p in PER:
        a=stat(by_ep(rel,pm[p])); ab=by_ep(absr,pm[p]).mean(); al=by_ep(allm,pm[p]).mean()
        cells.append(f'相对{a[0]*1e4:+5.0f} t{a[1]:+.1f} 正{a[2]*100:3.0f}%({a[3]}段) 绝对{ab*1e4:+5.0f} 全体{al*1e4:+5.0f}')
    print(f'{tag:34s}| '+' | '.join(cells))
print('\n=== 每个恐慌日(20日<=-6%)按分数买最高的一组，持有20天，扣成本；相对=该组均值-当日全部候选均值（bp），按“段”聚合')
for nm,fl in SETS.items():
    rep(nm+' 前20%',*eval_set(fl,frac=0.2)); rep(nm+' 前30只',*eval_set(fl,topn=30))
print('\n--- 只在成交额较大的一半里选（可操作性检验）')
for nm in ('S1 20日跌幅最大','S3 反转族(5日,20日,距60日高,距MA20)'):
    rep(nm+' 大票前20%',*eval_set(SETS[nm],frac=0.2,restrict='big')); rep(nm+' 大票前30只',*eval_set(SETS[nm],topn=30,restrict='big'))
print('\n--- 持有10天')
rep('S3 前20% 持10天',*eval_set(SETS['S3 反转族(5日,20日,距60日高,距MA20)'],frac=0.2,net=net10))
# decile profile by ret20
print('\n=== ret20 十分位平均净收益（持有20天，bp；1=跌最多）')
for p in PER:
    acc=np.zeros(10); cnt=0
    for i in np.nonzero(pm[p])[0]:
        m=cand[i]&np.isfinite(F['ret20'][i])&np.isfinite(net20[i])
        if m.sum()<300: continue
        o=np.argsort(F['ret20'][i][m]); y=net20[i][m][o]; q=np.array_split(y,10); acc+=np.array([z.mean() for z in q]); cnt+=1
    print(p,' '.join(f'{v*1e4:+5.0f}' for v in acc/cnt))
# deep days only (<=-9%)
deep=mk20<=-0.09
print('\n=== 仅 20日<=-9% 的恐慌日：S3 前20% / 前30只 与 S1')
for nm in ('S1 20日跌幅最大','S3 反转族(5日,20日,距60日高,距MA20)'):
    for lab,kw in (('前20%',dict(frac=0.2)),('前30只',dict(topn=30))):
        rel,absr,allm=eval_set(SETS[nm],**kw)
        for arr in (rel,absr,allm): arr[~deep]=np.nan
        rep(nm+' '+lab,rel,absr,allm)
# ---- one entry per deep episode (ETF-style: first day mk20<=-9%, flat, hold 20)
print('\n=== 单次建仓（20日<=-9%，空仓时第一天买入、持有20天），逐笔：全体候选等权 / S3前30只 / S3前20% / S1前30只')
pos_end=-1; rows=[]
for i in range(len(Dsel)):
    if mk20[i]<=-0.09 and Dsel[i]>pos_end:
        pos_end=Dsel[i]+1+19
        m=cand[i]&np.isfinite(net20[i])
        outs=[]
        for nm,kw in (('S3 反转族(5日,20日,距60日高,距MA20)',dict(topn=30)),('S3 反转族(5日,20日,距60日高,距MA20)',dict(frac=0.2)),('S1 20日跌幅最大',dict(topn=30))):
            s,mm=score(SETS[nm],i,m); idx=np.nonzero(mm&np.isfinite(s))[0]; o=idx[np.argsort(-s[idx])]; k=kw.get('topn') or int(len(o)*kw['frac']); outs.append(net20[i][o[:k]].mean())
        rows.append((dates[i],mk20[i],net20[i][m].mean(),*outs))
for r in rows: print(f'  信号日{r[0]} 大盘20日{r[1]*100:.1f}% | 全体{r[2]*100:+.1f}% | S3前30只{r[3]*100:+.1f}% | S3前20%{r[4]*100:+.1f}% | S1前30只{r[5]*100:+.1f}%')
R_=np.array([r[2:] for r in rows]); print('  平均:',' '.join(f'{v*100:+.1f}%' for v in R_.mean(0)),' 胜率:',' '.join(f'{(R_[:,k]>0).mean()*100:.0f}%' for k in range(R_.shape[1])),' 笔数',len(rows))

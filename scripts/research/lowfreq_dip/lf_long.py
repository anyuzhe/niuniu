"""Long-sample (2008-2026) re-check of panic-day stock selection factors, gate = dynamic z<=-1.5. Research only."""
import numpy as np, gc, warnings, time; warnings.filterwarnings('ignore')
T0=time.time()
exec(open('stockport.py').read().split("print('格式")[0])
h=P['h']; l=P['l']; v=P['v']; aa=P['a']
lim_=np.full(nc,0.1); lim_[is688]=0.2
Dsel=np.nonzero((zv<=-1.5)&(dates>='2008-01-01')&(np.arange(nd)<nd-H-4)&(np.arange(nd)>260))[0]
print('gate days',len(Dsel),' prefix s',round(time.time()-T0),flush=True)
def fac(t):
    F={}
    ct=c[t].astype(np.float64)
    def ck(k): return c[t-k].astype(np.float64)
    for k in (1,3,5,10,20,60): F[f'ret{k}']=ct/ck(k)-1
    F['mom_old(t-25→t-5)']=ck(5)/ck(25)-1
    H20=np.nanmax(h[t-19:t+1].astype(np.float64),0); L20=np.nanmin(l[t-19:t+1].astype(np.float64),0); H60=np.nanmax(h[t-59:t+1].astype(np.float64),0)
    F['dist_hi20']=ct/H20-1; F['dist_lo20']=ct/L20-1; F['dist_hi60']=ct/H60-1
    W20=c[t-19:t+1].astype(np.float64); m20=np.nanmean(W20,0); s20=np.nanstd(W20,0,ddof=1)
    F['dist_ma20']=ct/m20-1; F['dist_ma60']=ct/np.nanmean(c[t-59:t+1].astype(np.float64),0)-1; F['dist_ma120']=ct/np.nanmean(c[t-119:t+1].astype(np.float64),0)-1
    blo=m20-2*s20; bup=m20+2*s20; F['pctB']=(ct-blo)/np.where(bup>blo,bup-blo,np.nan)
    for n in (3,14):
        d=np.diff(c[t-n:t+1].astype(np.float64),axis=0); up=np.nansum(np.where(d>0,d,0),0); dn=np.nansum(np.where(d<0,-d,0),0)
        F[f'rsi{n}']=np.where(up+dn>0,100*up/(up+dn),np.nan)
    r20=c[t-19:t+1].astype(np.float64)/c[t-20:t].astype(np.float64)-1; F['vol20']=np.nanstd(r20,0,ddof=1)
    F['atr14%']=np.nanmean((h[t-13:t+1]-l[t-13:t+1]).astype(np.float64),0)/ct
    F['logamt20']=np.log(np.nanmean(aa[t-19:t+1].astype(np.float64),0)+1); F['logprice']=np.log(ct/f[t].astype(np.float64)*1.0)
    vp=np.nanmean(v[t-20:t].astype(np.float64),0); F['volratio_today']=v[t].astype(np.float64)/np.where(vp>0,vp,np.nan)
    F['volratio5/60']=np.nanmean(v[t-4:t+1].astype(np.float64),0)/np.where(np.nanmean(v[t-59:t+1].astype(np.float64),0)>0,np.nanmean(v[t-59:t+1].astype(np.float64),0),np.nan)
    hl=(h[t]-l[t]).astype(np.float64); hl=np.where(hl>0,hl,np.nan)
    F['cloc']=(ct-l[t])/hl; F['lower_shadow']=(np.minimum(c[t],o[t]).astype(np.float64)-l[t])/hl; F['gap_open']=o[t].astype(np.float64)/ck(1)-1
    F['age']=np.log(np.isfinite(c[:t+1]).sum(0)+1.0)
    r=c[t-59:t+1].astype(np.float64)/c[t-60:t].astype(np.float64)-1; r=np.where(np.isfinite(r),r,0.0); m=mr[t-59:t+1]
    beta=((r*m[:,None]).mean(0)-r.mean(0)*m.mean())/max(m.var(),1e-12); beta=np.clip(beta,-1,4); F['beta60']=beta; F['idiovol60']=np.sqrt(((r-beta*m[:,None])**2).mean(0))
    return F
fnames=None; FA={}; 
cand=np.zeros((len(Dsel),nc),bool); NET=np.full((len(Dsel),nc),np.nan,np.float32)
for i,t in enumerate(Dsel):
    F=fac(t)
    if fnames is None: fnames=list(F.keys()); FA={k:np.full((len(Dsel),nc),np.nan,np.float32) for k in fnames}
    for k in fnames: FA[k][i]=F[k]
    ldown=(c[t]/c[t-1]-1)<=-(limm_[t]-0.0025) if False else (c[t]/c[t-1]-1)<=-(lim_[t]-0.0025)
    cand[i]=valid[t]&~ldown; NET[i]=net[t]
print('factors done s',round(time.time()-T0),'; cand/day',cand.sum(1).mean().round(0),flush=True)
ep=np.zeros(len(Dsel),int)
for i in range(1,len(Dsel)): ep[i]=ep[i-1]+(1 if Dsel[i]-Dsel[i-1]>5 else 0)
dd=dates[Dsel]
PER={'2008-11':('2008-01-01','2011-12-31'),'2012-16':('2012-01-01','2016-12-31'),'2017-19':('2017-01-01','2019-12-31'),'2020-26':('2020-01-01','2026-12-31')}
pm={k:(dd>=a)&(dd<=b) for k,(a,b) in PER.items()}
print('各时期信号日/段:',{k:(int(pm[k].sum()),len(np.unique(ep[pm[k]]))) for k in PER})
def rank(x): return np.argsort(np.argsort(x)).astype(np.float64)
def daily(fv,net):
    ic=np.full(len(Dsel),np.nan); sp=np.full(len(Dsel),np.nan)
    for i in range(len(Dsel)):
        m=cand[i]&np.isfinite(fv[i])&np.isfinite(net[i])
        if m.sum()<300: continue
        fx=fv[i][m]; y=net[i][m]; ic[i]=np.corrcoef(rank(fx),rank(y))[0,1]; q=len(fx)//5; o_=np.argsort(fx); sp[i]=y[o_[-q:]].mean()-y[o_[:q]].mean()
    return ic,sp
def by_ep(x,msk):
    ids=np.unique(ep[msk&np.isfinite(x)]); return np.array([np.nanmean(x[msk&(ep==k)]) for k in ids])
def stat(vv):
    if len(vv)<3: return (np.nan,np.nan,np.nan,len(vv))
    return vv.mean(), vv.mean()/(vv.std(ddof=1)/np.sqrt(len(vv))+1e-12), (vv>0).mean(), len(vv)
res={}
print('\n######## 因子排名IC(Spearman,对未来20天净收益)与五分位差(最高20%-最低20%,bp)，按段聚合；格式 IC / t / 正段比例(段数) / 差')
print(f'{"因子":20s}'+''.join(f'| {p:^34s}' for p in PER))
for fn_ in fnames:
    ic,sp=daily(FA[fn_],NET); res[fn_]=(ic,sp); cells=[]
    for p in PER:
        a_=stat(by_ep(ic,pm[p])); b_=by_ep(sp,pm[p]); cells.append(f'{a_[0]:+.3f} t{a_[1]:+.1f} {a_[2]*100:3.0f}%({a_[3]:2d}) {b_.mean()*1e4:+5.0f}' if a_[3]>=3 else '无')
    print(f'{fn_:20s}| '+' | '.join(cells),flush=True)
sel=[]
for fn_ in fnames:
    ic,sp=res[fn_]; a_=stat(by_ep(ic,pm['2008-11']))
    if abs(a_[1])>=2 and max(a_[2],1-a_[2])>=0.75: sel.append((fn_,-1 if a_[0]<0 else 1))
print('\n2008-11 入选(|t|>=2 且>=75%段同号):',sel,' 共检验',len(fnames),'个因子')
def crank(fn_,i,m):
    x=FA[fn_][i].astype(np.float64); r_=np.full(x.shape,np.nan); mm=m&np.isfinite(x); n=mm.sum(); r_[mm]=rank(x[mm])/max(n-1,1); return r_
SETS={'S1 20日跌幅最大':[('ret20',-1)],'S2 离MA20最远':[('dist_ma20',-1)],
 'S3 反转族(5日,20日,距60日高,距MA20)':[('ret5',-1),('ret20',-1),('dist_hi60',-1),('dist_ma20',-1)],
 'S4 S3+小成交额+今日缩量':[('ret5',-1),('ret20',-1),('dist_hi60',-1),('dist_ma20',-1),('logamt20',-1),('volratio_today',-1)],
 'S5 S3+高beta':[('ret5',-1),('ret20',-1),('dist_hi60',-1),('dist_ma20',-1),('beta60',1)]}
def score(fl,i,m,restrict=None):
    mm=m.copy()
    if restrict=='big': la=FA['logamt20'][i]; mm=mm&(la>=np.nanmedian(la[m]))
    s=np.zeros(len(mm))
    for fn_,sg in fl:
        r_=crank(fn_,i,mm); s=s+(r_ if sg>0 else 1-r_)
    s=s/len(fl); s[~mm]=np.nan; return s,mm
def eval_set(fl,topn=None,frac=0.2,restrict=None):
    rel=np.full(len(Dsel),np.nan); absr=np.full(len(Dsel),np.nan); allm=np.full(len(Dsel),np.nan)
    for i in range(len(Dsel)):
        m=cand[i]&np.isfinite(NET[i])
        if m.sum()<300: continue
        s,mm=score(fl,i,m,restrict); idx=np.nonzero(mm&np.isfinite(s))[0]; o_=idx[np.argsort(-s[idx])]; k=topn if topn else int(len(o_)*frac)
        top=o_[:k]; absr[i]=NET[i][top].mean(); allm[i]=NET[i][m].mean(); rel[i]=absr[i]-allm[i]
    return rel,absr,allm
def rep(tag,rel,absr,allm):
    cells=[]
    for p in PER:
        a_=stat(by_ep(rel,pm[p]))
        cells.append('无' if a_[3]<3 else f'相对{a_[0]*1e4:+5.0f} t{a_[1]:+.1f} 正{a_[2]*100:3.0f}%({a_[3]:2d}) 绝对{by_ep(absr,pm[p]).mean()*1e4:+5.0f} 全体{by_ep(allm,pm[p]).mean()*1e4:+5.0f}')
    print(f'{tag:36s}| '+' | '.join(cells),flush=True)
print('\n=== 每个信号日(z<=-1.5)按分数买最高的一组，持有20天，扣成本；相对=该组均值-当日全部候选均值(bp)，按段聚合')
for nm,fl in SETS.items():
    rep(nm+' 前20%',*eval_set(fl,frac=0.2)); rep(nm+' 前30只',*eval_set(fl,topn=30))
print('\n--- 只在成交额较大的一半里选')
for nm in ('S1 20日跌幅最大','S3 反转族(5日,20日,距60日高,距MA20)'):
    rep(nm+' 大票前20%',*eval_set(SETS[nm],frac=0.2,restrict='big'))
print('\n=== ret20 十分位平均净收益(bp,1=跌最多)')
for p in PER:
    acc=np.zeros(10); cnt=0
    for i in np.nonzero(pm[p])[0]:
        m=cand[i]&np.isfinite(FA['ret20'][i])&np.isfinite(NET[i])
        if m.sum()<300: continue
        o_=np.argsort(FA['ret20'][i][m]); y=NET[i][m][o_]; acc+=np.array([z.mean() for z in np.array_split(y,10)]); cnt+=1
    print(p,' '.join(f'{x*1e4:+5.0f}' for x in acc/cnt))
# ---- portfolios: rank by S3 in the gated days
S3=SETS['S3 反转族(5日,20日,距60日高,距MA20)']
rk=np.full((nd,nc),np.nan,np.float32)
for i,t in enumerate(Dsel):
    m=cand[i]&np.isfinite(NET[i]); s,mm=score(S3,i,m); rk[t]=-s     # smaller = more beaten
# also score on days not in Dsel (nd-H-4..) are irrelevant
print('\n=== 组合(日度盯市,N=20): 闸门 z<=-1.5 ; 格式 年化/夏普/最大回撤/平均仓位')
print('格式：年化/夏普/最大回撤/平均仓位；列='+' | '.join(ERA))
sig=zv<=-1.5
for nm,pool,rank_ in (('E6 随机(基线)',e6,None),('E6 按20日跌幅排序',e6,ret20),('E6 按S3排序',e6,rk),('全部候选 随机',cand_all,None),('全部候选 按S3排序',cand_all,rk),('全部候选 按20日跌幅排序',cand_all,ret20)):
    for N in (20,):
        eq,ex_,tr=portfolio(sig,pool,N,rank=rank_); line(f'{nm} N={N}',eq,ex_,tr)
        if nm in ('全部候选 按S3排序','E6 按S3排序'):
            print('   逐年:',' '.join(f'{y}:{(eq[np.nonzero(np.char.startswith(dates,str(y))&np.isfinite(eq))[0][-1]]/eq[np.nonzero(np.char.startswith(dates,str(y))&np.isfinite(eq))[0][0]]-1)*100:+.0f}' for y in range(2008,2027) if (np.char.startswith(dates,str(y))&np.isfinite(eq)).sum()>20),flush=True)
print('total s',round(time.time()-T0))

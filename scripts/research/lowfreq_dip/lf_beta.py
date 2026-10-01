"""Beta-neutral check of the panic-day reversal selection (2008-2026). Research only."""
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
S3=SETS['S3 反转族(5日,20日,距60日高,距MA20)']
ND=len(Dsel)
mcum=np.array([np.prod(1+mr[t+1:t+H+1])-1 for t in Dsel])
BETA=FA['beta60'].astype(np.float64)
EXC=NET.astype(np.float64)-BETA*mcum[:,None]
def repo(tag,cells): print(f'{tag:42s}| '+' | '.join(cells),flush=True)
def cell(x,msk):
    a_=stat(by_ep(x,msk)); return '无' if a_[3]<3 else f'{a_[0]*1e4:+5.0f} t{a_[1]:+.1f} 正{a_[2]*100:3.0f}%({a_[3]:2d})'
def cellic(x,msk):
    a_=stat(by_ep(x,msk)); return '无' if a_[3]<3 else f'{a_[0]:+.3f} t{a_[1]:+.1f} 正{a_[2]*100:3.0f}%({a_[3]:2d})'
print('\n=== A. S3 前20% 这一组的平均 beta60 对比当日全部候选')
bt=np.full(ND,np.nan); ba=np.full(ND,np.nan)
for i in range(ND):
    m=cand[i]&np.isfinite(NET[i])&np.isfinite(BETA[i])
    if m.sum()<300: continue
    s_,mm=score(S3,i,m); idx=np.nonzero(mm&np.isfinite(s_))[0]; o_=idx[np.argsort(-s_[idx])]; k=int(len(o_)*0.2)
    bt[i]=np.nanmean(BETA[i][o_[:k]]); ba[i]=np.nanmean(BETA[i][m])
for p in PER: print(f'  {p}: 入选组 beta {np.nanmean(bt[pm[p]]):.2f}  全部候选 beta {np.nanmean(ba[pm[p]]):.2f}  信号后20天大盘累计收益均值 {np.nanmean(mcum[pm[p]])*100:+.1f}%')
print('\n=== B. 先按 beta60 分三档，每档里 S3 前20% 相对该档全体 (bp, 按段) ; 每档内 ret20 的 IC')
print(' '*42+'| '+' | '.join(f'{p:^26s}' for p in PER))
for b_lab,(lo_,hi_) in (('低beta三分之一',(0,1/3)),('中beta',(1/3,2/3)),('高beta三分之一',(2/3,1.0001))):
    rel=np.full(ND,np.nan); ic=np.full(ND,np.nan)
    for i in range(ND):
        m=cand[i]&np.isfinite(NET[i])&np.isfinite(BETA[i])
        if m.sum()<300: continue
        rb=crank('beta60',i,m); mb=m&(rb>=lo_)&(rb<hi_)
        if mb.sum()<150: continue
        s_,mm=score(S3,i,mb); idx=np.nonzero(mm&np.isfinite(s_))[0]; o_=idx[np.argsort(-s_[idx])]; k=int(len(o_)*0.2)
        rel[i]=NET[i][o_[:k]].mean()-NET[i][mb].mean()
        x_=FA['ret20'][i][mb].astype(np.float64); y_=NET[i][mb].astype(np.float64); ok=np.isfinite(x_)&np.isfinite(y_)
        ic[i]=np.corrcoef(rank(x_[ok]),rank(y_[ok]))[0,1]
    repo(f'{b_lab} S3前20%相对该档(bp)',[cell(rel,pm[p]) for p in PER]); repo(f'{b_lab} ret20 IC',[cellic(ic,pm[p]) for p in PER])
print('\n=== C. 超额 = 净收益 - beta60 x 同期大盘累计收益；S3前20%相对全体 (bp) 与 IC')
for lab,Y in (('原始净收益',NET.astype(np.float64)),('扣beta后超额',EXC)):
    rel=np.full(ND,np.nan); icr=np.full(ND,np.nan); icb=np.full(ND,np.nan)
    for i in range(ND):
        m=cand[i]&np.isfinite(Y[i])&np.isfinite(BETA[i])
        if m.sum()<300: continue
        s_,mm=score(S3,i,m); idx=np.nonzero(mm&np.isfinite(s_))[0]; o_=idx[np.argsort(-s_[idx])]; k=int(len(o_)*0.2)
        rel[i]=Y[i][o_[:k]].mean()-Y[i][m].mean()
        for fn_,arr in (('ret20',icr),('beta60',icb)):
            x_=FA[fn_][i].astype(np.float64); ok=m&np.isfinite(x_); arr[i]=np.corrcoef(rank(x_[ok]),rank(Y[i][ok]))[0,1]
    repo(f'[{lab}] S3前20%相对全体(bp)',[cell(rel,pm[p]) for p in PER])
    repo(f'[{lab}] ret20 IC',[cellic(icr,pm[p]) for p in PER]); repo(f'[{lab}] beta60 IC',[cellic(icb,pm[p]) for p in PER])
print('\n=== D. 横截面回归 net20 = a + b1*S3排名 + b2*beta排名 (排名 0..1)，系数=最低到最高排名的净收益变化(bp)')
b1s=np.full(ND,np.nan); b2s=np.full(ND,np.nan); b1o=np.full(ND,np.nan); b2o=np.full(ND,np.nan)
for i in range(ND):
    m=cand[i]&np.isfinite(NET[i])&np.isfinite(BETA[i])
    if m.sum()<300: continue
    s_,mm=score(S3,i,m); ok=mm&np.isfinite(s_); rs=rank(s_[ok]); rs=rs/rs.max(); rb=crank('beta60',i,ok)[ok]; y_=NET[i][ok].astype(np.float64)
    X1=np.column_stack([np.ones(ok.sum()),rs,rb]); co=np.linalg.lstsq(X1,y_,rcond=None)[0]; b1s[i]=co[1]; b2s[i]=co[2]
    b1o[i]=np.linalg.lstsq(X1[:,:2],y_,rcond=None)[0][1]; b2o[i]=np.linalg.lstsq(X1[:,[0,2]],y_,rcond=None)[0][1]
repo('S3 单独',[cell(b1o,pm[p]) for p in PER]); repo('beta 单独',[cell(b2o,pm[p]) for p in PER])
repo('S3 (同时控制beta)',[cell(b1s,pm[p]) for p in PER]); repo('beta (同时控制S3)',[cell(b2s,pm[p]) for p in PER])
print('\n=== E. beta中性打分 = S3 分数对 beta 排名回归的残差；买最高的一组 (相对全体 bp, 按段; β=入选组平均beta)')
for lab,kw in (('前20%',dict(frac=0.2)),('前30只',dict(topn=30))):
    for tag,mode in (('S3 原始','raw'),('S3 beta中性','res')):
        rel=np.full(ND,np.nan); bsel=np.full(ND,np.nan)
        for i in range(ND):
            m=cand[i]&np.isfinite(NET[i])&np.isfinite(BETA[i])
            if m.sum()<300: continue
            s_,mm=score(S3,i,m); ok=mm&np.isfinite(s_)
            if mode=='res':
                rb=crank('beta60',i,ok)[ok]; X1=np.column_stack([np.ones(ok.sum()),rb]); co=np.linalg.lstsq(X1,s_[ok],rcond=None)[0]; sc=np.full(len(s_),np.nan); sc[ok]=s_[ok]-X1@co
            else: sc=np.where(ok,s_,np.nan)
            idx=np.nonzero(np.isfinite(sc))[0]; o_=idx[np.argsort(-sc[idx])]; k=kw.get('topn') or int(len(o_)*kw['frac'])
            rel[i]=NET[i][o_[:k]].mean()-NET[i][m].mean(); bsel[i]=BETA[i][o_[:k]].mean()
        repo(f'{tag} {lab}',[cell(rel,pm[p])+f' β{np.nanmean(bsel[pm[p]]):.2f}' for p in PER])
print('\n=== F. 组合: 闸门 z<=-1.5, E6, N=20；列='+' | '.join(ERA))
rk1=np.full((nd,nc),np.nan,np.float32); rk2=np.full((nd,nc),np.nan,np.float32)
for i,t in enumerate(Dsel):
    m=cand[i]&np.isfinite(NET[i])&np.isfinite(BETA[i]); s_,mm=score(S3,i,m); ok=mm&np.isfinite(s_)
    rk1[t]=-np.where(ok,s_,np.nan)
    rb=crank('beta60',i,ok)[ok]; X1=np.column_stack([np.ones(ok.sum()),rb]); co=np.linalg.lstsq(X1,s_[ok],rcond=None)[0]; sc=np.full(len(s_),np.nan); sc[ok]=s_[ok]-X1@co; rk2[t]=-sc
sig=zv<=-1.5
for nm,pool,rank_ in (('E6 按S3排序',e6,rk1),('E6 按S3 beta中性排序',e6,rk2)):
    eq,ex_,tr=portfolio(sig,pool,20,rank=rank_); line(nm+' N=20',eq,ex_,tr)

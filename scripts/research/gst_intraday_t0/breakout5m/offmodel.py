"""10:30 afternoon-risk model on DATA's official whole-market breadth (market_intraday_breadth_5m, READY).
Target: whole-market equal-weight move from 10:30 to the close; 'crash' = <= -1%. Walk-forward by year (fit on earlier
years only) with ridge (move) and L2 logistic (crash). Research only."""
import duckdb, os, numpy as np, datetime as dt
H=os.environ['HOME']; c=duckdb.connect()
B=f'{H}/mnt/lake/silver/market_intraday_breadth/freq=5m/year=*/*.parquet'
r=c.execute(f"""select date::varchar d, replace(time,':','') t, ew_ret_prev_close pc, ew_ret_open op, amt_w_ret_prev_close aw,
   median_ret_prev_close md, up_count*1.0/n_stocks up, down_count*1.0/n_stocks dn, limit_up_count*1.0/n_stocks lu,
   limit_down_count*1.0/n_stocks ld, touched_limit_down_count*1.0/n_stocks tld, touched_limit_up_count*1.0/n_stocks tlu
   from read_parquet('{B}') order by d,t""").fetchnumpy()
days=np.unique(r['d']); T={}
for i,(d,t) in enumerate(zip(r['d'],r['t'])): T[(d,t)]=i
def g(d,t,k):
    i=T.get((d,t)); return np.nan if i is None else float(r[k][i])
rows=[]
for d in days:
    f={'date':d}
    f['m_pc']=g(d,'1030','pc'); f['m_open']=g(d,'1030','op'); f['m_aw']=g(d,'1030','aw'); f['m_md']=g(d,'1030','md')
    f['up']=g(d,'1030','up'); f['dn']=g(d,'1030','dn'); f['lu']=g(d,'1030','lu'); f['ld']=g(d,'1030','ld'); f['tld']=g(d,'1030','tld'); f['tlu']=g(d,'1030','tlu')
    f['m30']=(1+f['m_pc'])/(1+g(d,'1000','pc'))-1; f['m15']=(1+f['m_pc'])/(1+g(d,'1015','pc'))-1
    f['gap']=(1+g(d,'0935','pc'))/(1+g(d,'0935','op'))-1
    f['big_small']=f['m_aw']-f['m_pc']
    f['close']=g(d,'1500','pc'); f['last30']=(1+f['close'])/(1+g(d,'1430','pc'))-1
    f['y']=(1+f['close'])/(1+f['m_pc'])-1
    f['wd']=dt.date.fromisoformat(d).weekday()
    rows.append(f)
for i,f in enumerate(rows):
    prev=rows[max(0,i-20):i]
    f['p_ret']=prev[-1]['close'] if prev else np.nan; f['p_rest']=prev[-1]['y'] if prev else np.nan; f['p_last30']=prev[-1]['last30'] if prev else np.nan
    f['p_5d']=np.nansum([p['close'] for p in prev[-5:]]) if len(prev)>=5 else np.nan
    f['p_vol20']=np.nanstd([p['close'] for p in prev]) if len(prev)>=15 else np.nan
feats=['m_pc','m_open','m_aw','m_md','up','dn','lu','ld','tld','tlu','m30','m15','gap','big_small','p_ret','p_rest','p_last30','p_5d','p_vol20']
d=np.array([f['date'] for f in rows]); y=np.array([f['y'] for f in rows]); X=np.array([[f[k] for k in feats] for f in rows])
yr=np.array([int(x[:4]) for x in d]); crash=y<=-0.01; good=np.all(np.isfinite(X),1)&np.isfinite(y)
def auc(s,lab):
    ok=np.isfinite(s); s=s[ok]; lab=lab[ok]; o=np.argsort(s); rk=np.empty(len(s)); rk[o]=np.arange(1,len(s)+1)
    n1=lab.sum(); n0=len(lab)-n1; return (rk[lab].sum()-n1*(n1+1)/2)/(n1*n0)
print(f'全市场（正式情绪）交易日 {good.sum()}；10:30 后再跌1%以上 {crash[good].mean()*100:.0f}%；各年 '+' '.join(f"{Y}:{crash[good&(yr==Y)].mean()*100:.0f}%" for Y in range(2020,2027)))
print('单因子与下午涨跌的相关（2020–2026 逐年）：')
res=[]
for j,k in enumerate(feats):
    cs=[np.corrcoef(X[good&(yr==Y),j],y[good&(yr==Y)])[0,1] for Y in range(2020,2027)]
    res.append((np.mean(cs),k,cs,auc(X[good,j],crash[good])))
for m,k,cs,a in sorted(res,key=lambda r:-abs(r[0])): print(f'  {k:9s} 平均{m:+.2f} | '+' '.join(f'{x:+.2f}' for x in cs)+f' | AUC {a:.2f} 同号 {sum(np.sign(x)==np.sign(m) for x in cs)}/7')
pred=np.full(len(y),np.nan); prob=np.full(len(y),np.nan)
for Y in range(2021,2027):
    tr=good&(yr<Y); te=good&(yr==Y)
    mu=X[tr].mean(0); sd=X[tr].std(0)+1e-12; A=(X[tr]-mu)/sd
    w=np.linalg.solve(A.T@A+len(A)*np.eye(A.shape[1]),A.T@(y[tr]-y[tr].mean())); pred[te]=((X[te]-mu)/sd)@w+y[tr].mean()
    b=np.zeros(A.shape[1]+1); Ab=np.c_[np.ones(len(A)),A]; t=crash[tr].astype(float)
    for _ in range(25):
        p=1/(1+np.exp(-Ab@b)); gr=Ab.T@(p-t)+np.r_[0,b[1:]]*len(A)*0.05; Hs=(Ab*(p*(1-p))[:,None]).T@Ab+np.diag(np.r_[0,np.ones(len(b)-1)])*len(A)*0.05
        b-=np.linalg.solve(Hs,gr)
    prob[te]=1/(1+np.exp(-np.c_[np.ones(te.sum()),(X[te]-mu)/sd]@b))
print('逐年滚动：')
for Y in range(2021,2027):
    m=(yr==Y)&np.isfinite(pred); top=m&(prob>=np.nanpercentile(prob[m],80))
    print(f'  {Y}: 相关 {np.corrcoef(pred[m],y[m])[0,1]:+.2f} | AUC {auc(prob[m],crash[m]):.2f} | 风险最高20%里真大跌 {crash[top].mean()*100:3.0f}%（全年 {crash[m].mean()*100:.0f}%）')
np.savez(f'{H}/research/brk/offpred.npz',date=d,pred=pred,prob=prob,y=y)

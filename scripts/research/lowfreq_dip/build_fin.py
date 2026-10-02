import numpy as np, glob, pyarrow.parquet as pq, pandas as pd, time, os
T0=time.time(); L=os.path.expanduser('~')+'/mnt/lake/bronze/provider=eastmoney/'
P=np.load('panel_ext.npz'); dates=P['dates'].astype(str); codes=P['codes'].astype(str); nd=len(dates); nc=len(codes)
ci={c:i for i,c in enumerate(codes)}
di=np.array([int(d.replace('-','')) for d in dates]); dprev=np.concatenate([[0],di[:-1]])   # info available through previous trading day
def conv(sec): 
    s=sec.str.slice(0,6); m=sec.str.slice(7,9).str.lower(); return (m+'.'+s)
def load(d,cols,datecol,keycol='SECUCODE'):
    fs=sorted(glob.glob(L+d+'/**/*.parquet',recursive=True)); out=[]
    for f in fs:
        nm=pq.read_schema(f).names
        if keycol not in nm or datecol not in nm: continue
        t=pq.read_table(f,columns=[c for c in dict.fromkeys([keycol,datecol]+cols) if c in nm]).to_pandas()
        for c in cols:
            if c not in t.columns: t[c]=np.nan
        out.append(t)
    x=pd.concat(out,ignore_index=True)
    return x
def pit(x,keycol,datecol,cols,isdate10=True,conv_code=True):
    k=conv(x[keycol]) if conv_code else x[keycol].astype(str)
    j=k.map(ci); m=j.notna()
    x=x[m].copy(); x['j']=j[m].astype(int)
    dd=x[datecol].astype(str).str.slice(0,10).str.replace('-','',regex=False); x['d']=pd.to_numeric(dd,errors='coerce'); x=x[x['d'].notna()]
    u_,inv_=np.unique(x['d'].values.astype(np.int64),return_inverse=True)
    uo_=pd.to_datetime(pd.Series(u_.astype(str)),format='%Y%m%d',errors='coerce').values.astype('datetime64[D]').astype(np.int64).astype(float)
    x['do']=uo_[inv_]
    x=x.sort_values(['j','d'],kind='stable')
    out={c:np.full((nd,nc),np.nan,np.float32) for c in cols}; outd=np.full((nd,nc),np.nan,np.float32)
    jj=x['j'].values; dv=x['d'].values; dov=x['do'].values; starts=np.searchsorted(jj,np.arange(nc)); ends=np.searchsorted(jj,np.arange(nc),side='right')
    vals={c:pd.to_numeric(x[c],errors='coerce').values for c in cols}
    for j in range(nc):
        a,b=starts[j],ends[j]
        if b<=a: continue
        pos=np.searchsorted(dv[a:b],dprev,side='right')-1; ok=pos>=0
        for c in cols: out[c][ok,j]=vals[c][a:b][pos[ok]]
        outd[ok,j]=dov[a:b][pos[ok]]
    return out,outd
R={}
x=load('financial_cpd',['SJLTZ','YSTZ','WEIGHTAVG_ROE','PARENT_NETPROFIT','BASIC_EPS','TOTAL_OPERATE_INCOME'],'NOTICE_DATE'); print('cpd',len(x),round(time.time()-T0),flush=True)
o,od=pit(x,'SECUCODE','NOTICE_DATE',['SJLTZ','YSTZ','WEIGHTAVG_ROE','PARENT_NETPROFIT','BASIC_EPS','TOTAL_OPERATE_INCOME']); 
R.update(np_yoy=o['SJLTZ'],rev_yoy=o['YSTZ'],roe_cum=o['WEIGHTAVG_ROE'],np_cum=o['PARENT_NETPROFIT'],eps=o['BASIC_EPS'],rev_cum=o['TOTAL_OPERATE_INCOME'],cpd_notice=od); del x
x=load('financial_balance',['DEBT_ASSET_RATIO','CURRENT_RATIO','TOTAL_ASSETS','TOTAL_LIABILITIES'],'NOTICE_DATE'); print('bal',len(x),round(time.time()-T0),flush=True)
o,od=pit(x,'SECUCODE','NOTICE_DATE',['DEBT_ASSET_RATIO','CURRENT_RATIO','TOTAL_ASSETS','TOTAL_LIABILITIES']); R.update(debt=o['DEBT_ASSET_RATIO'],cur=o['CURRENT_RATIO'],assets=o['TOTAL_ASSETS'],liab=o['TOTAL_LIABILITIES']); del x
x=load('financial_cashflow',['NETCASH_OPERATE'],'NOTICE_DATE'); print('cf',len(x),round(time.time()-T0),flush=True)
o,od=pit(x,'SECUCODE','NOTICE_DATE',['NETCASH_OPERATE']); R.update(ocf_cum=o['NETCASH_OPERATE']); del x
x=load('share_capital',['TOTAL_A_SHARES','FREE_SHARES','TOTAL_SHARES'],'NOTICE_DATE'); print('shares',len(x),round(time.time()-T0),flush=True)
o,od=pit(x,'SECUCODE','NOTICE_DATE',['TOTAL_A_SHARES','FREE_SHARES','TOTAL_SHARES']); R.update(sh_a=o['TOTAL_A_SHARES'],sh_free=o['FREE_SHARES'],sh_tot=o['TOTAL_SHARES']); del x
x=load('earnings_forecast_history',['forecast_type','change_pct_lower','change_pct_upper','report_date'],'notice_date',keycol='code'); print('fc',len(x),round(time.time()-T0),flush=True)
neg={'首亏','续亏','预减','略减'}; pos={'扭亏','预增','略增','续盈'}
x['fcat']=x['forecast_type'].map(lambda s: -1 if s in neg else (1 if s in pos else 0))
# code -> panel code (no exchange suffix): map by 6-digit
six={c.split('.')[1]:i for i,c in enumerate(codes)}
x['sec']=x['code'].astype(str).map(lambda s: codes[six[s]] if s in six else None); x=x[x['sec'].notna()]
o,od=pit(x,'sec','notice_date',['fcat'],conv_code=False); R.update(fc_cat=o['fcat'],fc_notice=od); del x
x=load('equity_pledge_history',['pledge_ratio_pct'],'date',keycol='code'); print('pledge',len(x),round(time.time()-T0),flush=True)
x['sec']=x['code'].astype(str).map(lambda s: codes[six[s]] if s in six else None); x=x[x['sec'].notna()]
o,od=pit(x,'sec','date',['pledge_ratio_pct'],conv_code=False); R.update(pledge=o['pledge_ratio_pct'],pledge_date=od); del x
for k in ('eps','rev_cum','assets','liab','sh_tot','cpd_notice','pledge_date'): R.pop(k,None)
np.savez_compressed('fund_fin.npz',**R)
for k,v in R.items(): print(k,'finite share',round(float(np.isfinite(v).mean()),3))
print('done',round(time.time()-T0))

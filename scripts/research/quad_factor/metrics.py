"""Metrics for the quad-factor native verification: python metrics.py <cashtag e.g. 1e8> <dir with r0.* files>"""
import pickle, sys, math, numpy as np, polars as pl
tag=sys.argv[1]; D=sys.argv[2] if len(sys.argv)>2 else '/tmp/qr'
r=pickle.load(open(f'{D}/r0.engine{tag}.pkl','rb'))
c=r['curve'].with_columns(pl.col('datetime').dt.date().alias('d')).sort('d')
eq=c['equity'].to_numpy(); d=c['d'].to_list()
ret=np.diff(np.concatenate([[eq[0] if False else float(r['summary']['initial_cash'])],eq]))/np.concatenate([[float(r['summary']['initial_cash'])],eq[:-1]])
def stats(rr):
    rr=np.asarray(rr); 
    if len(rr)<2: return None
    nav=np.cumprod(1+rr); dd=(nav/np.maximum.accumulate(nav)-1).min()
    ann=nav[-1]**(252/len(rr))-1
    return dict(sharpe=rr.mean()/rr.std(ddof=1)*math.sqrt(252), ann=ann, vol=rr.std(ddof=1)*math.sqrt(252), mdd=dd, total=nav[-1]-1, n=len(rr))
out={'all_engine':{k:r['summary'][k] for k in ('sharpe','annualized_return','annualized_volatility','max_drawdown','net_return','fills','commission','sell_tax','slippage_cost')}}
full=stats(ret); out['all_recomputed']=full
pv=c['position_value'].to_numpy()/eq
import datetime as dt
i_full=int(np.argmax(pv>0.9)); 
out['first_invested']=str(d[int(np.argmax(pv>0.05))]); out['first_90pct']=str(d[i_full])
out['steady_state(>=90% invested)']=stats(ret[i_full:])
sl=[i for i,x in enumerate(d) if x>=dt.date(2023,1,1)]
out['2023+']=stats(ret[sl[0]:])
out['2018-2022']=stats(ret[:sl[0]])
yr={}
for y in range(2018,2027):
    idx=[i for i,x in enumerate(d) if x.year==y]
    yr[y]=float(np.prod(1+ret[idx])-1)
out['yearly']=yr
# benchmark: equal-weight daily rebalanced close-to-close of the same 100 symbols
px=pickle.load(open(D+'/r0.meta.pkl','rb'))
bars=pl.read_parquet(D+'/r0.bars.parquet').with_columns(pl.col('datetime').dt.date().alias('d')).sort('symbol','d')
b=bars.with_columns((pl.col('close')/pl.col('close').shift(1).over('symbol')-1).alias('r')).group_by('d').agg(pl.col('r').mean()).sort('d')
br=b['r'].fill_null(0).to_numpy()
out['benchmark_ew100_all']=stats(br)
bi=[i for i,x in enumerate(b['d'].to_list()) if x>=dt.date(2023,1,1)][0]
out['benchmark_2023+']=stats(br[bi:])
byr={}
for y in range(2018,2027):
    idx=[i for i,x in enumerate(b['d'].to_list()) if x.year==y]; byr[y]=float(np.prod(1+br[idx])-1)
out['benchmark_yearly']=byr
# per-cohort-name statistics (gross), signal day s, entry open s+1
coh=px['cohorts']; days=sorted(coh)
o=bars.pivot(on='symbol',index='d',values='open').sort('d'); cl=bars.pivot(on='symbol',index='d',values='close').sort('d')
dl=o['d'].to_list(); pos={x:i for i,x in enumerate(dl)}
O=o.drop('d').to_numpy(); C=cl.drop('d').to_numpy(); cols=o.drop('d').columns; ci={s:i for i,s in enumerate(cols)}
g_close=[];g_open=[]
for s in days:
    sd=s.date(); i=pos[sd]
    if i+41>=len(dl): continue
    for n in coh[s]:
        j=ci[n]; g_close.append(C[i+40,j]/O[i+1,j]-1); g_open.append(O[i+41,j]/O[i+1,j]-1)
gc=np.array(g_close); go=np.array(g_open)
out['cohort_trades']=len(gc)
out['per_trade_gross_bp_exit_close_t+40']=float(gc.mean()*1e4); out['per_trade_gross_bp_exit_open_t+41']=float(go.mean()*1e4)
out['win_rate_close']=float((gc>0).mean())
# realistic round-trip cost estimate for a trade of normal size: slip 2bp + commission 2bp + sell tax(approx from summary) + transfer
s=r['summary']; sellN=s['execution_diagnostics']['sell_notional']
out['cost_bp_of_sell_tax']=s['sell_tax']/sellN*1e4
out['turnover_total_notional/initial']=(s['execution_diagnostics']['buy_notional']+sellN)/float(s['initial_cash'])
import json; print(json.dumps(out,indent=1,default=float,ensure_ascii=False))

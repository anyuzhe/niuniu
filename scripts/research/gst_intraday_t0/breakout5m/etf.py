"""ETF 底仓做T proxy: index 5-minute bars (tdx_index_kline_min5, 2024-09-12..2026-09-24) and, for a longer history,
the whole-market equal-weight breadth (market_intraday_breadth_5m, 2020-2026). Costs: ETF, no stamp duty;
low = 5 bp round trip, normal = 10 bp (2.5 bp commission x2 + about one 0.001 tick). Rules:
  M  morning momentum: at T (10:00/10:30/11:30) return since the previous close <= -x -> sell at T, buy back at close;
     >= +x -> buy at T, sell base at close (正T). Fade F = the opposite trade.
  O  30-minute opening range breakout: first break above -> buy (sell at close); below -> sell (buy back at close).
  N  overnight: buy at close, sell next open. Research only."""
import duckdb, os, numpy as np, itertools
H=os.environ['HOME']; c=duckdb.connect()
IDX={'sh_000300':'沪深300','sh_000905':'中证500','sh_000852':'中证1000','sz_399006':'创业板指','sh_000001':'上证指数'}
def grid_index(f):
    r=c.execute(f"""select date::varchar d, substr(time,9,4) hm, open, close from read_parquet('{H}/mnt/lake/bronze/provider=tdx/index_kline_min5/{f}.parquet') order by date,time""").fetchnumpy()
    ud,inv=np.unique(r['d'],return_inverse=True); slots=sorted(set(r['hm'])); si={s:i for i,s in enumerate(slots)}
    Cc=np.full((len(ud),48),np.nan); Oo=np.full((len(ud),48),np.nan); col=np.array([si[h] for h in r['hm']])
    Cc[inv,col]=r['close']; Oo[inv,col]=r['open']
    good=~np.isnan(Cc).any(1); ud,Cc,Oo=ud[good],Cc[good],Oo[good]
    pc=np.r_[np.nan,Cc[:-1,-1]]
    return ud, Cc/pc[:,None]-1, Oo[:,0]/pc-1, np.r_[Oo[1:,0],np.nan]/Cc[:,-1]-1
def grid_breadth():
    r=c.execute(f"""select date::varchar d, replace(time,':','') hm, ew_ret_prev_close x from read_parquet('{H}/mnt/lake/silver/market_intraday_breadth/freq=5m/year=*/*.parquet') order by d,hm""").fetchnumpy()
    ud,inv=np.unique(r['d'],return_inverse=True); slots=sorted(set(r['hm'])); si={s:i for i,s in enumerate(slots)}
    X=np.full((len(ud),len(slots)),np.nan); X[inv,[si[h] for h in r['hm']]]=r['x']
    return ud,X,slots
def evaluate(ud,R,gapo,label,cost,periods,slots=None):
    # R: return vs previous close at each 5-minute bar close (48 columns, col 47 = close)
    rows=[]
    Tcols={'10:00':5,'10:30':11,'11:30':23}
    rest=lambda j:(1+R[:,-1])/(1+R[:,j])-1
    for (tn,j),x in itertools.product(Tcols.items(),(0.003,0.005,0.008,0.01)):
        rr=rest(j)*1e4
        for side,cond in (('跌→先卖',R[:,j]<=-x),('涨→先买',R[:,j]>=x)):
            pnl=np.where(cond,(-rr if side.startswith('跌') else rr)-cost,np.nan)
            rows.append((f'M {tn} {side} {x*100:g}%',pnl)); rows.append((f'F {tn} {side}反做 {x*100:g}%',np.where(cond,-(pnl+cost)-cost,np.nan)))
    # opening range 30 min (cols 0..5), break after col 5 using bar closes
    hi=np.nanmax(R[:,:6],1); lo=np.nanmin(R[:,:6],1)
    up=R[:,6:45]>hi[:,None]; dn=R[:,6:45]<lo[:,None]
    fu=np.where(up.any(1),np.argmax(up,1)+6,-1); fd=np.where(dn.any(1),np.argmax(dn,1)+6,-1)
    ix=np.arange(len(R))
    pu=np.where(fu>=0,((1+R[:,-1])/(1+R[ix,np.maximum(fu,0)])-1)*1e4-cost,np.nan)
    pd=np.where(fd>=0,-((1+R[:,-1])/(1+R[ix,np.maximum(fd,0)])-1)*1e4-cost,np.nan)
    rows+= [('O 开盘区间向上突破→先买',pu),('O 开盘区间向下突破→先卖',pd)]
    print(f'\n### {label}（来回成本 {cost}bp）')
    for nm,p in rows:
        s=''
        for pn,pm in periods.items():
            v=p[pm&np.isfinite(p)]
            if len(v)<10: s+=f' | {pn} —'; continue
            w=v>0; s+=f' | {pn} {v.mean():+6.1f}bp 胜{w.mean()*100:3.0f}% 赔{v[w].mean()/max(-v[~w].mean(),1e-9):.2f} t{v.mean()/(v.std()/np.sqrt(len(v))):+4.1f} n{len(v)}'
        print(f'  {nm:24s}{s}')
    return rows
if __name__=='__main__':
    import sys
    which=sys.argv[1]
    if which=='idx':
        for f,nm in IDX.items():
            ud,R,gap,on=grid_index(f)
            P={'24-09..25-09':(ud<'2025-10'),'25-10..26-09':(ud>='2025-10')}
            print(f'\n=== {nm} 隔夜（收盘到次日开盘，不扣费）: '+' '.join(f"{k} {np.nanmean(on[m])*1e4:+.1f}bp" for k,m in P.items()))
            evaluate(ud,R,gap,nm,10.0,P)
    else:
        ud,X,slots=grid_breadth()
        P={'20-22':ud<'2023','23-24':(ud>='2023')&(ud<'2025'),'25-26':ud>='2025'}
        assert len(slots)==48, len(slots)
        evaluate(ud,X,None,'全市场等权（近似中证1000/2000类ETF）',10.0,P)

"""Reversal-side ideas for 底仓做T on the yearly top-500 (5-minute bars). Per stock-day records:
 open-sell 反T: sell at the first 5-minute bar open - 1 tick, buy back at the close + 1 tick (net bp),
 with features known at the open; intraday cross-sectional reversal at 10:00 / 10:30 relative to the market.
Writes a compact per-year parquet-like npz for grouping in revagg.py. Research only."""
import sys, os, numpy as np
sys.path.insert(0,os.path.dirname(__file__)); import lib5
yr=int(sys.argv[1]); D=lib5.load(yr); T=lib5.TICK
O,C,pc,m=D['O'],D['C'],D['pc'],D['mret']
cost=5+D['stamp']+0.2
dn=np.round(pc*(1-np.where(D['up']/pc>1.15,0.2,0.1))+1e-9,2)
sell0=O[:,0]-T; buyc=C[:,-1]+T
open_ok=(sell0>dn+0.005)&(D['V'][:,0]>0)&(O[:,0]<D['up']-0.005)   # skip limit-down (cannot sell) / limit-up opens
rev_open=np.where(open_ok,(sell0/buyc-1)*1e4-cost,np.nan)
f=dict(date=D['date'],code=D['code'],rev_open=rev_open,
  gap=O[:,0]/pc-1, r1=pc/D['pc2']-1, r5=pc/D['pc6']-1, vr=D['pdv']/D['dv20'],
  loc=(pc-D['pL1'])/np.maximum(D['pH1']-D['pL1'],1e-6), plu=D['prevLU'].astype(float),
  mgap=m[:,0])
for col,tag in ((5,'1000'),(11,'1030')):
    # entry at next bar open; 正T buy (returns) and 反T sell (returns) to the close
    e=col+1; oe=O[:,e]
    ok=(D['V'][:,e]>0)&(oe<D['up']-0.005)&(oe>dn+0.005)
    f[f'rel{tag}']=(C[:,col]/pc-1)-m[:,col]
    f[f'ret{tag}']=C[:,col]/O[:,0]-1
    f[f'long{tag}']=np.where(ok,((C[:,-1]-T)/(oe+T)-1)*1e4-cost,np.nan)
    f[f'short{tag}']=np.where(ok,((oe-T)/(C[:,-1]+T)-1)*1e4-cost,np.nan)
np.savez(f'{os.environ["HOME"]}/research/brk/rev_{yr}.npz',**f); print(yr,len(D['date']))

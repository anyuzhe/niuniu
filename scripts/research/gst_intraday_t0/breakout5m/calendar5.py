"""Calendar effects for 底仓做T (yearly top-500, 5-minute bars): per stock-day outcomes of
先卖后买 / 先买后卖 from the open (first 5-minute bar open) or from 10:05 to the close, net of 7.2 bp + 1 tick each side.
A sell-first whose close is sealed at limit-up buys back at the next open. Research only."""
import sys, os, numpy as np
sys.path.insert(0,os.path.dirname(__file__)); import lib5
yr=int(sys.argv[1]); D=lib5.load(yr); T=lib5.TICK; FEE=7.2
O,C,pc,up,V=D['O'],D['C'],D['pc'],D['up'],D['V']; code=D['code']
dn=np.round(pc*(1-np.where(up/pc>1.15,0.2,0.1))+1e-9,2)
nO=np.r_[O[1:,0],np.nan]; nO[np.r_[code[1:]!=code[:-1],True]]=np.nan
sealed=C[:,-1]>=up-0.001
out=dict(date=D['date'],code=code,m1000=D['mret'][:,5],mday=D['mret'][:,-1])
for tag,e in (('open',0),('1005',6)):
    o=O[:,e]; ok=V[:,e]>0
    buyback=np.where(sealed,nO+T,C[:,-1]+T)
    out['short_'+tag]=np.where(ok&(o-T>dn+0.005),((o-T)/buyback-1)*1e4-FEE,np.nan)
    out['long_'+tag]=np.where(ok&(o+T<up-0.005),((C[:,-1]-T)/(o+T)-1)*1e4-FEE,np.nan)
np.savez(f'{os.environ["HOME"]}/research/brk/cal_{yr}.npz',**out); print(yr,len(code))

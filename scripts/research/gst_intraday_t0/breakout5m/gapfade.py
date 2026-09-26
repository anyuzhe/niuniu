"""Big gap-up fade for 底仓做T: sell the base at the first 5-minute open - 1 tick when the stock opens >= g above
the previous close (not at limit-up), buy back later. If the buy-back bar is sealed at limit-up (close >= limit price),
the buy-back fails and is done at the next day's open + 1 tick. Variants: buy-back time, limit buy-back at open*(1-x),
stop buy-back at open*(1+s). Research only."""
import sys, os, numpy as np, itertools, pickle
sys.path.insert(0,os.path.dirname(__file__)); import lib5
yr=int(sys.argv[1]); D=lib5.load(yr); T=lib5.TICK
O,Hh,L,C,pc,up=D['O'],D['H'],D['L'],D['C'],D['pc'],D['up']
gap=O[:,0]/pc-1
cand=(gap>=0.04)&(O[:,0]<up-0.005)&(D['V'][:,0]>0)
r=np.flatnonzero(cand); sell=O[r,0]-T; cost=5+D['stamp'][r]+0.2
nO=D['nO'][r]
def settle(buy,sealed):
    b=np.where(sealed,nO+T,buy); return (sell/b-1)*1e4-cost
out={'r':r,'gap':gap[r],'plu':D['prevLU'][r],'date':D['date'][r],'code':D['code'][r],'cy':(up[r]/pc[r]>1.15)}
for col,nm in ((5,'10:00'),(11,'10:30'),(23,'11:30'),(35,'14:00'),(47,'收盘')):
    sealed=C[r,col]>=up[r]-0.001
    out[('time',nm)]=settle(C[r,col]+T,sealed)
    out[('sealedfrac',nm)]=sealed
for x in (0.02,0.03,0.05):
    tg=O[r,0]*(1-x); hit=(L[r,:]<=tg[:,None]-T); anyh=hit.any(1)
    buy=np.where(anyh,tg,C[r,-1]+T); sealed=~anyh&(C[r,-1]>=up[r]-0.001)
    out[('limit',x)]=settle(buy,sealed)
for s in (0.03,0.05):
    st=O[r,0]*(1+s); ok=st<up[r]-0.005
    hit=(Hh[r,:]>=st[:,None]); anyh=hit.any(1)&ok; j=np.argmax(hit,1)
    # stop fill: max(open of that bar, stop)+tick; if that bar sealed at limit, next day
    fill=np.maximum(O[r,j],st)+T; sealedj=C[r,j]>=up[r]-0.001
    buy=np.where(anyh,fill,C[r,-1]+T); sealed=np.where(anyh,sealedj&(fill>=up[r]-0.005),C[r,-1]>=up[r]-0.001)
    out[('stop',s)]=settle(buy,sealed)
pickle.dump(out,open(f'{os.environ["HOME"]}/research/brk/gf_{yr}.pkl','wb')); print(yr,len(r))

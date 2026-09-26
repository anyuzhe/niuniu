"""隔夜T for 底仓: buy an extra lot at today's close (+1 tick; skipped when the close is at limit-up), sell the same
amount of base the next trading day at the open (-1 tick), at 10:00 or at the close. If the next open is at limit-down
the sale moves to the next close. Records features known at today's close. Research only."""
import sys, os, numpy as np
sys.path.insert(0,os.path.dirname(__file__)); import lib5
yr=int(sys.argv[1]); D=lib5.load(yr); T=lib5.TICK
O,C,Hh,L,V,pc,up,code=D['O'],D['C'],D['H'],D['L'],D['V'],D['pc'],D['up'],D['code']
n=len(C)
def lead(x):
    out=np.full(x.shape,np.nan); out[:-1]=x[1:]; bad=np.r_[code[1:]!=code[:-1],True]; out[bad]=np.nan; return out
nO=lead(O[:,0]); n10=lead(C[:,5]); nC=lead(C[:,-1]); nstamp=lead(D['stamp'])
lim=np.where(up/pc>1.15,0.2,0.1); ndn=np.round(C[:,-1]*(1-lim)+1e-9,2)
buy=C[:,-1]+T; ok=(C[:,-1]<up-0.005)&np.isfinite(nO)
cost=5+np.nan_to_num(nstamp,nan=5)+0.2
res={}
for nm,px in (('次日开盘',nO),('次日10:00',n10),('次日收盘',nC)):
    sell=np.where(nO<=ndn+0.005,nC,px)-T
    res[nm]=np.where(ok,(sell/buy-1)*1e4-cost,np.nan)
gross=np.where(ok,(nO/C[:,-1]-1)*1e4,np.nan)
f=dict(gross=gross,mret_on=np.nan*gross,date=D['date'],code=code,intra=C[:,-1]/O[:,0]-1,day=C[:,-1]/pc-1,last30=C[:,-1]/C[:,41]-1,
       loc=(C[:,-1]-Hh.min(1)*0-L.min(1))/np.maximum(Hh.max(1)-L.min(1),1e-6),vr=V.sum(1)/D['dv20'],
       mday=D['mret'][:,-1],mlast30=(1+D['mret'][:,-1])/(1+D['mret'][:,41])-1,gap=O[:,0]/pc-1,
       **{f'on_{k}':v for k,v in res.items()})
np.savez(f'{os.environ["HOME"]}/research/brk/on_{yr}.npz',**f); print(yr,ok.sum())

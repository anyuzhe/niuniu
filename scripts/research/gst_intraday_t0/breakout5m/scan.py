"""Grid scan of intraday breakout families on one year; stores per-day sums per combination (research only).
A 日内平台突破, B 多日平台突破, C 放量突破 (today's high / yesterday's high). Filters: same-slot volume multiple,
market (whole-market equal-weight vs prev close > 0, or its last-30-min change > 0). Exits: close, stop, trailing."""
import sys, pickle, itertools, numpy as np, os
sys.path.insert(0,os.path.dirname(__file__)); import lib5
yr=int(sys.argv[1]); fam=sys.argv[2]
D=lib5.load(yr); C,Hh,L,V,pc=D['C'],D['H'],D['L'],D['V'],D['pc']
n=len(C); m=D['mret']
mk={'none':np.ones((n,48),bool),'up':m>0,'mom':m-np.c_[np.zeros((n,6)),m[:,:-6]]>0}
volr=V/np.where(D['vs20']>0,D['vs20'],np.nan)
volf={v:(np.ones((n,48),bool) if v==0 else volr>=v) for v in (0,1.5,2,3,5)}
out={}
def rec(key,r,bp):
    d=D['date'][r]; u,inv=np.unique(d,return_inverse=True)
    w=bp>0
    out[key]=dict(n=len(bp),s=bp.sum(),nw=int(w.sum()),sw=bp[w].sum(),sl=bp[~w].sum(),dates=u,
                  ds=np.bincount(inv,bp),dc=np.bincount(inv),ss=(bp**2).sum())
def run(key,sig,first,stop,trail):
    for ex in ('close','stop','trail'):
        r,e,bp=lib5.trades(D,sig,first=first,last=44,stop=stop if ex=='stop' else None,trail=trail if ex=='trail' else None)
        rec(key+(ex,),r,bp)
runmaxH=np.maximum.accumulate(Hh,1); prevmaxH=np.c_[np.full((n,1),np.inf),runmaxH[:,:-1]]
prevmaxC=np.c_[np.full((n,1),-np.inf),np.maximum.accumulate(C,1)[:,:-1]]
if fam=='A':
    for k in (6,12,24):
        ph=np.full((n,48),np.nan); pl=np.full((n,48),np.nan)
        for i in range(k,48): ph[:,i]=Hh[:,i-k:i].max(1); pl[:,i]=L[:,i-k:i].min(1)
        width=(ph-pl)/pc[:,None]
        for w in (0.01,0.015,0.02):
            base=(width<=w)&(C>ph)
            for v,mf in itertools.product((0,1.5,2,3),('none','up','mom')):
                run(('A',k,w,v,mf),base&volf[v]&mk[mf],k,pl,0.02)
elif fam=='B':
    for N in (5,10,20):
        lvl=D[f'pH{N}']; width=(lvl-D[f'pL{N}'])/D[f'pL{N}']
        cross=(C>lvl[:,None])&(prevmaxC<=lvl[:,None])
        stop=np.broadcast_to((lvl*0.98)[:,None],(n,48))
        for w in (0.06,0.10,0.15):
            base=cross&(width<=w)[:,None]
            for v,mf in itertools.product((0,1.5,2,3),('none','up','mom')):
                run(('B',N,w,v,mf),base&volf[v]&mk[mf],1,stop,0.03)
elif fam=='C':
    for lv in ('dayhigh','pH1'):
        if lv=='dayhigh': base=C>prevmaxH; stop=prevmaxH*0.98
        else:
            l=D['pH1']; base=(C>l[:,None])&(prevmaxC<=l[:,None]); stop=np.broadcast_to((l*0.98)[:,None],(n,48))
        for v,mf in itertools.product((2,3,5),('none','up','mom')):
            run(('C',lv,0,v,mf),base&volf[v]&mk[mf],6,stop,0.02)
elif fam=='Z':  # baselines: buy at a fixed bar every day
    for i in (0,6,12,18,24,30,36):
        sig=np.zeros((n,48),bool); sig[:,i]=True
        for mf in ('none','up','mom'):
            run(('Z',i,0,0,mf),sig&mk[mf],i,None,0.02)
pickle.dump(out,open(f'{os.environ["HOME"]}/research/brk/res_{fam}_{yr}.pkl','wb'))
print(yr,fam,len(out))

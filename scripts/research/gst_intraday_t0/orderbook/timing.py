"""Timing the market sell with the order book: sell at bid1 at the first snapshot (within W s after the decision)
where the level-1 imbalance is <= thr (sellers heavier), otherwise at bid1 when W runs out."""
from exec import *
for W_,thr in ((30,0.0),(60,0.0),(60,-0.3),(120,-0.3),(180,-0.5)):
    out=[]
    for sym,day,em,eng_px,k in trips:
        if sym not in cache: cache.clear(); cache[sym]=load(sym)
        z=cache[sym]; idx=np.flatnonzero(z['date']==day)
        if not len(idx): continue
        t0=int(em[:2])*3600+int(em[3:])*60-60
        p=np.searchsorted(z['t'][idx],t0)
        if p>=len(idx): continue
        j=idx[p]; b1,bv,av,t=z['bid1_px'],z['bid1_vol'],z['ask1_vol'],z['t']
        m=j
        while m<idx[-1] and t[m]-t[j]<W_ and (bv[m]-av[m])/(bv[m]+av[m])>thr: m+=1
        out.append((b1[m]/eng_px-1)*1e4)
    print(f'wait up to {W_}s for imbalance <= {thr}: mean {np.mean(out):+.1f} bp vs engine, vs immediate market {np.mean(out)-np.mean(mkt):+.1f} bp (n={len(out)})')

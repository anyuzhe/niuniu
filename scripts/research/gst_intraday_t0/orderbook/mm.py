"""Queue-based 底仓做T on 3-second order-book snapshots.
Flat: rest a bid at bid1 (buy-first leg) and/or an ask at ask1 (sell-first leg), joining the back of the queue.
A resting order fills when volume traded at its price after placement exceeds the queue ahead plus its size
(cancellations ahead are ignored: conservative), or immediately when the price trades through it.
Once one leg fills, the other resting order is cancelled and a closing order rests one tick better for us
(buy at fill-1 tick after selling, sell at fill+1 tick after buying). Optional stop: close by crossing the spread
when the mid moves `stop` ticks against. Anything open at 14:56:30 is closed at the last price (proxy for the
closing auction). Fees: commission 2.5 bp each side, transfer 0.1 bp each side, stamp duty 10 bp on the sell leg."""
from feat import *
import sys
FEES=2*2.5+2*0.1+10.0
def run_stock(sym,params,period=None):
    z=load(sym); F,T,mid,seg=features(z)
    d=z['date']; t=z['t']; b1=z['bid1_px']; a1=z['ask1_px']; bv=z['bid1_vol']; av=z['ask1_vol']; last=z['last']
    cum=z['cum_volume']; pc=z['prev_close']
    imb=F['imb1']
    q=params.get('q',2000)   # shares per leg is set per stock below via notional
    stop=params.get('stop',None); side_filter=params.get('filter',None); max_trips=params.get('max_trips',50)
    trips=[]
    n=len(t); i=0
    days=np.flatnonzero(np.r_[True,d[1:]!=d[:-1]]); ends=np.r_[days[1:],n]
    for s,e in zip(days,ends):
        day=d[s]
        if period is not None and not period(day): continue
        p0=pc[s]
        if not np.isfinite(p0): continue
        up=round(p0*1.1,2); dn=round(p0*0.9,2)
        qty=max(100,int(params['notional']/mid[s]/100)*100)
        state=0; bid=None; ask=None; close=None; ntrips=0; entry=None
        for k in range(s+1,e):
            if t[k]>=14*3600+56*60+30: break
            dv=max(0.0,cum[k]-cum[k-1]) if t[k]-t[k-1]<=60 else 0.0
            # --- update resting orders
            def upd(o):
                if o is None: return False
                if o['side']>0:
                    if b1[k] < o['px']-1e-6 or (last[k] < o['px']-1e-6 and dv>0): return True
                    if abs(last[k]-o['px'])<1e-6: o['done']+=dv
                else:
                    if a1[k] > o['px']+1e-6 or (last[k] > o['px']+1e-6 and dv>0): return True
                    if abs(last[k]-o['px'])<1e-6: o['done']+=dv
                return o['done']>=o['queue']+qty
            if state==0:
                fb=upd(bid); fa=upd(ask)
                if fb and fa:   # both legs in the same snapshot: a round trip at the spread
                    trips.append((day,t[k],'both',bid['px'],ask['px'],(ask['px']/bid['px']-1)*1e4-FEES)); ntrips+=1; bid=ask=None
                elif fb:
                    state=1; entry=bid['px']; ask=None; bid=None; t_entry=t[k]
                    px=round(entry+TICK,2); close={'side':-1,'px':px,'queue':(av[k] if abs(a1[k]-px)<1e-6 else 0.0),'done':0.0}
                elif fa:
                    state=-1; entry=ask['px']; bid=None; ask=None; t_entry=t[k]
                    px=round(entry-TICK,2); close={'side':1,'px':px,'queue':(bv[k] if abs(b1[k]-px)<1e-6 else 0.0),'done':0.0}
            else:
                if upd(close):
                    g=(close['px']/entry-1)*1e4 if state>0 else (entry/close['px']-1)*1e4
                    trips.append((day,t[k],'long' if state>0 else 'short',entry,close['px'],g-FEES)); ntrips+=1
                    state=0; close=None
                elif (stop and ((state>0 and mid[k]<=entry-stop*TICK) or (state<0 and mid[k]>=entry+stop*TICK))) or \
                        (params.get('max_hold') and t[k]-t_entry>=params['max_hold']):
                    exitp=b1[k] if state>0 else a1[k]
                    g=(exitp/entry-1)*1e4 if state>0 else (entry/exitp-1)*1e4
                    trips.append((day,t[k],'stop-long' if state>0 else 'stop-short',entry,exitp,g-FEES)); ntrips+=1
                    state=0; close=None
            # --- (re)post when flat
            if state==0 and ntrips<max_trips and t[k]>=9*3600+35*60 and t[k]<14*3600+45*60:
                allow_b = side_filter is None or imb[k]>=side_filter
                allow_s = side_filter is None or imb[k]<=-side_filter
                if params.get('side','both') in ('both','buy') and allow_b and b1[k]>dn+0.005 and b1[k]<up-0.015:
                    if bid is None or abs(bid['px']-b1[k])>1e-6:
                        bid={'side':1,'px':b1[k],'queue':bv[k],'done':0.0}
                elif bid is not None and not allow_b: bid=None
                if params.get('side','both') in ('both','sell') and allow_s and a1[k]<up-0.005 and a1[k]>dn+0.015:
                    if ask is None or abs(ask['px']-a1[k])>1e-6:
                        ask={'side':-1,'px':a1[k],'queue':av[k],'done':0.0}
                elif ask is not None and not allow_s: ask=None
            elif state==0:
                bid=ask=None
        if state!=0:   # close at the last price seen (proxy for the closing auction)
            px=last[min(k,e-1)]
            g=(px/entry-1)*1e4 if state>0 else (entry/px-1)*1e4
            trips.append((day,t[min(k,e-1)],'eod-long' if state>0 else 'eod-short',entry,px,g-FEES))
    return trips
def summary(sym,trips,label=''):
    if not trips: print(sym,label,'no trips'); return
    b=np.array([x[5] for x in trips]); days=len({x[0] for x in trips})
    kinds={}
    for x in trips: kinds[x[2]]=kinds.get(x[2],0)+1
    w=b[b>0]; l=b[b<=0]
    print(f"{sym} {label} trips={len(b)} days={days} per_trip={b.mean():+.1f}bp win={len(w)/len(b):.2f} payoff={(w.mean()/-l.mean()) if len(l) and len(w) else float('nan'):.2f} per_day_sum={b.sum()/days:+.1f}bp kinds={kinds}",flush=True)
if __name__=='__main__':
    syms=sys.argv[1].split(',')
    grid=eval(sys.argv[2]) if len(sys.argv)>2 else [{'notional':50000}]
    for sym in syms:
        for params in grid:
            tr=run_stock(sym,params,period=lambda d:d<='2020-01-31')
            summary(sym,tr,str(params))

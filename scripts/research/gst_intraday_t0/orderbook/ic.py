from feat import *
syms=sorted(os.path.basename(p)[:-4] for p in glob.glob(f'{H}/research/ob/s*.npz'))
acc={}
for sym in syms:
    z=load(sym); F,T,mid,seg=features(z)
    tr=z['date']<='2020-01-31'
    tick_bp=TICK/mid*1e4
    for h,y in T.items():
        for name,x in F.items():
            m=tr&np.isfinite(x)&np.isfinite(y)
            if m.sum()<1000: continue
            c=np.corrcoef(x[m],y[m])[0,1]
            acc.setdefault((h,name),[]).append(c)
    print(sym, 'tick bp', round(np.median(tick_bp),1), 'sd 1m bp', round(np.nanstd(T['1m'][tr]),1), 'sd 5m', round(np.nanstd(T['5m'][tr]),1),flush=True)
print('mean IC across 16 stocks (train 2019-05..2020-01), and how many stocks have the same sign')
for h in HZ:
    print(h,' '.join(f"{n}:{np.mean(v):+.3f}({sum(np.sign(v)==np.sign(np.mean(v)))})" for (hh,n),v in acc.items() if hh==h))

import os, sys, json
import numpy as np
import grp56 as G
out={}
for entry in ('close',):
    tl=[]; eq,ex,ev,ntr=G.fused3(entry=entry, tlog=tl); out[G.SIG]=tl
    print(G.SIG, ntr, len(tl))
    import pickle; pickle.dump(tl, open(f'tl94_{G.SIG}.pkl','wb'))
    np.save(f'eq94_{G.SIG}.npy', eq)

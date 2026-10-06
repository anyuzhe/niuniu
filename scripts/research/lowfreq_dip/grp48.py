"""Small-cap-only restrictions on D pool. Research only."""
import grp11 as g
from grp11 import *
cap = np.load('cap.npy'); nd_, nc_ = cap.shape
print('SW L1 codes:', u, flush=True)
BANK = '480000'
bi = u.index(BANK) if BANK in u else -1
isbank = (l1 == bi)[None, :] & np.ones((nd_, 1), bool)
print('银行只数', int((l1 == bi).sum()), flush=True)
print('cap 分位(亿?)', np.nanpercentile(cap[-1], [50, 90, 99, 100]), flush=True)
capr = np.full((nd_, nc_), np.nan, np.float32)
for s0 in range(0, nd_, 400):
    b = min(nd_, s0 + 400); v = np.where(cand.uni[s0:b] & np.isfinite(cap[s0:b]) & (cap[s0:b] > 0), cap[s0:b], np.nan)
    capr[s0:b] = pd.DataFrame(v).rank(axis=1, pct=True).to_numpy()
O, C = panel.o.astype(np.float64), panel.c.astype(np.float64); H = 20; COST = 0.003
rows = []
for s, (gate, e6, r20) in g.SL.items():
    for t in np.nonzero(gate)[0]:
        if t + 1 + H >= nd_ or dates[t] < '2008-01-01': continue
        pool = np.nonzero(e6[t] & buyok[t])[0]
        if not len(pool): continue
        pick = pool[np.argsort(r20[t, pool], kind='stable')[:20]]
        for j in pick:
            if not (np.isfinite(O[t + 1, j]) and np.isfinite(C[t + H, j])): continue
            rows.append((s, t, j, C[t + H, j] / O[t + 1, j] - 1 - COST, bool(isbank[t, j]), capr[t, j]))
E = pd.DataFrame(rows, columns=['s', 't', 'j', 'net', 'bank', 'capr'])
base_SL = dict(g.SL); W0 = {'A': .08, 'C': .08, 'B': .025}
cr = np.nan_to_num(capr, nan=2.0)
tests = [('基线', None)]
for q in (0.8, 0.6, 0.4, 0.2): tests.append((f'只买流通市值最小的 {int(q*100)}%', cr > q))
tests.append(('只买最小40%且剔除最小5%', (cr > 0.4) | (cr < 0.05)))
tests.append(('只买最小40%且剔除最小10%', (cr > 0.4) | (cr < 0.10)))
tests.append(('只买 5%-60% 分位', (cr > 0.6) | (cr < 0.05)))
tests.append(('只买最小40%且剔除银行', (cr > 0.4) | isbank))
for name, flag in tests:
    g.SL = {s: (v[0], (v[1] & ~flag) if flag is not None else v[1], v[2]) for s, v in base_SL.items()}
    show(f'D {name}', order='ACB', w=W0, G=1.0, caps={}, cash_yield=0.02)

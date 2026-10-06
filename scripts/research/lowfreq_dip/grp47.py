"""Should banks / mega caps be excluded from D? Event composition + fused D with exclusion filters. Research only."""
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
print(f'D 候选事件 {len(E)} 笔', flush=True)
def line(m, label):
    x = E.net[m]
    if len(x) < 20: print(f'  {label}: n={len(x)}'); return
    print(f'  {label:30s} n={len(x):6d} ({len(x)/len(E)*100:4.1f}%) 均值 {x.mean()*100:+6.2f}% 中位 {x.median()*100:+6.2f}% 胜率 {np.mean(x>0)*100:3.0f}%', flush=True)
line(np.ones(len(E), bool), '全部')
line(E.bank.to_numpy(), '银行股'); line(~E.bank.to_numpy(), '非银行')
for s in 'ABC':
    m = (E.s == s).to_numpy(); line(m & E.bank.to_numpy(), f'  {s} 中银行'); line(m, f'  {s} 全部')
for a, b in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, .9), (.9, .95), (.95, 1.01)):
    line(((E.capr >= a) & (E.capr < b)).to_numpy(), f'流通市值分位 {a:.2f}-{min(b,1):.2f}')
print('--- fused D with exclusions', flush=True)
base_SL = dict(g.SL); W0 = {'A': .08, 'C': .08, 'B': .025}
tests = [('基线', None), ('剔除银行', isbank)]
for q in (0.8, 0.9, 0.95): tests.append((f'剔除流通市值前 {int((1-q)*100)}%', np.nan_to_num(capr) > q))
for th in (500,1000): tests.append((f'剔除流通市值>{th}亿', np.nan_to_num(cap)>th))
tests.append(('剔除银行 + 前10%', isbank | (np.nan_to_num(capr) > 0.9)))
tests.append(('只买市值后 80%(剔除前20%)+银行', isbank | (np.nan_to_num(capr) > 0.8)))
for name, flag in tests:
    g.SL = {s: (v[0], (v[1] & ~flag) if flag is not None else v[1], v[2]) for s, v in base_SL.items()}
    show(f'D {name}', order='ACB', w=W0, G=1.0, caps={}, cash_yield=0.02)

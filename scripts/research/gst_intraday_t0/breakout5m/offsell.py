"""先卖后买 with the 10:30 market model, executed stock by stock (research only, manual verification).

Signal: walk-forward prediction of the whole-market equal-weight move from 10:30 to the close
(offpred.npz = DATA's official market_intraday_breadth_5m model from offmodel.py; mfpred.npz = the earlier
sample-universe model from mktfeat.py for comparison) is <= -thr.
On signal days every in-universe stock (top 500 by turnover of that year) is treated as a base position:
  - sell at the 10:35 bar open minus 1 tick (the first trade after the 10:30 decision);
    no sale if that price is at limit-down or the bar has no volume;
  - buy back at the close plus 1 tick; if the close is sealed at limit-up the buy-back moves to the next open
    plus 1 tick (the short stays open overnight).
Fees 7.2 bp round trip (万1免五 both sides, stamp duty 5 bp, transfer 0.1 bp per side).
beta = prior 20-day beta of daily returns to the universe equal-weight (no look-ahead).
Writes offsell.npz (one row per stock-day) and prints the summary."""
import numpy as np, os
H = os.environ['HOME']; B = f'{H}/research/brk'
TICK = 0.01; FEE = 7.2; SELL = 12  # slot 12 = the 10:35 bar


def load(yr):
    z = np.load(f'{B}/g{yr}.npz')
    code = z['code'].astype(str); date = z['date'].astype(str); iny = z['iny']
    O = z['O'].astype(np.float64); C = z['C'].astype(np.float64); V = np.nan_to_num(z['V'].astype(np.float64))
    for i in range(48):
        m = np.isnan(C[:, i]); C[m, i] = O[m, 0] if i == 0 else C[m, i - 1]
    O = np.where(np.isnan(O), C, O)
    n = len(code); same = np.r_[False, code[1:] == code[:-1]]
    dc = C[:, -1]; pc = np.where(same, np.r_[np.nan, dc[:-1]], np.nan)
    nO = np.full(n, np.nan); nO[:-1] = np.where(code[1:] == code[:-1], O[1:, 0], np.nan)
    lim = np.where((np.char.startswith(code, 'sz.30') & (date >= '2020-08-24')) | np.char.startswith(code, 'sh.688'), 0.2, 0.1)
    up = np.round(pc * (1 + lim) + 1e-9, 2); dn = np.round(pc * (1 - lim) + 1e-9, 2)
    # prior 20-day beta of daily returns to the equal-weight mean of rows in the grid
    r = dc / pc - 1; r[~np.isfinite(r) | (np.abs(r) > 0.25)] = np.nan
    ud, inv = np.unique(date, return_inverse=True)
    ok = np.isfinite(r); msum = np.bincount(inv, np.where(ok, r, 0)); mcnt = np.bincount(inv, ok)
    mkt = (msum / np.maximum(mcnt, 1))[inv]
    x = np.where(ok, r * mkt, 0); v = np.where(ok, mkt * mkt, 0)
    cx = np.r_[0, np.cumsum(x)]; cv = np.r_[0, np.cumsum(v)]; beta = np.full(n, np.nan); k = np.arange(20, n)
    beta[k] = (cx[k] - cx[k - 20]) / np.maximum(cv[k] - cv[k - 20], 1e-12)
    beta[np.r_[np.ones(20, bool), code[20:] != code[:-20]]] = np.nan
    keep = iny & np.isfinite(pc) & (pc > 0)
    return dict(code=code[keep], date=date[keep], O=O[keep], C=C[keep], V=V[keep], pc=pc[keep], up=up[keep],
                dn=dn[keep], nO=nO[keep], beta=beta[keep], price=O[keep, SELL])


rows = {k: [] for k in 'date code bp gross skip nextopen beta price'.split()}
for yr in range(2021, 2027):
    D = load(yr)
    o = D['O'][:, SELL]
    skip = ~((o > D['dn'] + 0.005) & (D['V'][:, SELL] > 0))
    sell = o - TICK
    closeLU = D['C'][:, 47] >= D['up'] - 0.005
    buy = np.where(closeLU, D['nO'] + TICK, D['C'][:, 47] + TICK)
    gross = (sell - buy) / sell * 1e4
    bp = gross - FEE
    bad = ~np.isfinite(bp) | (np.abs(gross) > 2500)
    skip = skip | bad
    for k, v in (('date', D['date']), ('code', D['code']), ('bp', bp), ('gross', gross), ('skip', skip),
                 ('nextopen', closeLU & ~skip), ('beta', D['beta']), ('price', D['price'])):
        rows[k].append(v)
    print(yr, 'rows', len(bp), flush=True)
R = {k: np.concatenate(v) for k, v in rows.items()}
np.savez(f'{B}/offsell.npz', **R)
print('saved', len(R['bp']))

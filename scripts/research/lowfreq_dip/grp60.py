"""Research only: within-batch laggard rule on top of D (with-delisted panel, product inputs).
Cohort = positions of the same sleeve bought off the same signal day. At close of day t (age >= KMIN, cohort size >= NMIN):
if >= FRAC of the cohort is up >= U since entry open (and >= 2 names), the cohort's laggards (return < LG) are sold at the NEXT open
(skipped if that open is locked limit-down). mode 'sell': slot stays empty until the position's original exit day; mode 'swap': slot freed at once,
refilled by the normal entry logic (today's sleeve pool, rank order) if the pool has names.
"""
import os, sys, json
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
import numpy as np
from dataclasses import replace
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.fusion import ORDER, order_candidates
from quantlab.dipbuy.engine import _exit_index, _fee_by_day, _limit_rates
from quantlab.dipbuy.panel import Panel

panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
nd, nc = panel.shape
LIM = _limit_rates(panel, slice(0, nc))
VARIANT = os.environ.get('VARIANT', 'D')
cfg = fusion.default_config() if VARIANT == 'D' else fusion.d1_config()
inp = fusion.build_inputs(panel, cfg, cls)

def sim(rule=None):
    """rule: None or dict(U, FRAC, LG, mode, KMIN, NMIN). Returns dict(cagr, sharpe, dd, n_trades, n_cut, fwd(list of (r_at_sale, fwd_ret_to_orig_exit)))."""
    dates, c, o, f = panel.dates, panel.c, panel.o, panel.f
    H, N, G, W = cfg.hold_days, cfg.positions, cfg.gross_cap, cfg.weights
    t0 = int(np.searchsorted(dates, cfg.start)); tend = nd - 1
    fee = _fee_by_day(dates); slip = 0.0
    cash = 1.0; active = []; ghosts = []; eq = np.full(nd, np.nan); ntr = 0; cut = []; ncut = 0
    for t in range(t0, tend + 1):
        for p in [p for p in active if p['x'] == t and p['net'] is not None]:
            cash += p['inv'] * (1 + p['net']); ntr += 1; active.remove(p)
        ghosts = [g for g in ghosts if g['until'] > t]
        if rule and t + 1 <= tend:
            groups = {}
            for p in active:
                if p.get('cut') or p['e'] > t or p['net'] is None: continue
                groups.setdefault((p['s'], p['sig']), []).append(p)
            for key, ps in groups.items():
                if len(ps) < rule['NMIN'] or t - ps[0]['e'] < rule['KMIN']: continue
                rets = []
                for p in ps:
                    ct = c[t, p['j']]; rets.append(ct / p['o0'] - 1 if np.isfinite(ct) else np.nan)
                rets = np.array(rets); win = np.nansum(rets >= rule['U'])
                if win < 2 or win / len(ps) < rule['FRAC']: continue
                for p, r in zip(ps, rets):
                    if not (r < rule['LG']): continue
                    j = p['j']; px = o[t + 1, j]
                    if not np.isfinite(px) or not np.isfinite(c[t, j]): continue
                    if px / c[t, j] - 1 <= -(LIM[t + 1, j] - 0.0025): continue     # locked limit-down at the open: cannot sell
                    fx, k = float(f[t + 1, j]), t + 1
                    while not np.isfinite(fx) and k > 0: k -= 1; fx = float(f[k, j])
                    raw_x = px / fx; raw_e = p['o0'] / float(f[p['e'], j])
                    net = (px * (1 - 0.01 / raw_x)) / (p['o0'] * (1 + 0.01 / raw_e)) - 1 - fee[t + 1]
                    cut.append((float(r), float(p['px_x'] / px - 1) if p['px_x'] else np.nan, p['s'])); ncut += 1
                    p['cut'] = True; p['x'] = t + 1; p['net'] = net
                    if rule['mode'] == 'sell': ghosts.append(dict(s=p['s'], until=p['xo']))
        if t + 1 <= tend:
            held = {p['j'] for p in active}
            for s in ORDER:
                if not inp.gates[s][t]: continue
                n_s = sum(1 for p in active if p['s'] == s and not p.get('cut')) + sum(1 for g in ghosts if g['s'] == s)
                if n_s >= N: continue
                base = np.nonzero(inp.pools[s][t] & inp.buyok[t])[0]
                pool = np.array([j for j in base if j not in held], dtype=int)
                if not len(pool): continue
                pool = order_candidates(panel, inp, cfg, t, base, pool)
                invested = sum(p['v'] for p in active if not p.get('cut')); equity = cash + sum(p['v'] for p in active)
                for j in pool[:N - n_s]:
                    size = min(W[s] * equity, G * equity - invested)
                    if size <= 1e-9: break
                    cash -= size; invested += size
                    e = t + 1; o0 = float(o[e, j]); raw_e = o0 / float(f[e, j]); ex = _exit_index(c, j, t + H, nd)
                    pos = dict(j=int(j), s=s, sig=t, e=e, x=ex[0] if ex else t + H, inv=size, v=size, o0=o0, net=None, px_x=None, last=o0)
                    if ex is not None:
                        xi, px = ex; fx, k = float(f[xi, j]), xi
                        while not np.isfinite(fx) and k > 0: k -= 1; fx = float(f[k, j])
                        raw_x = px / fx
                        pos['net'] = (px * (1 - 0.01 / raw_x)) / (o0 * (1 + 0.01 / raw_e)) - 1 - fee[xi]; pos['px_x'] = px
                        pos['cost_e'] = 0.01 / raw_e + fee[xi] / 2
                    else:
                        pos['cost_e'] = 0.01 / raw_e + fee[min(t + H, nd - 1)] / 2
                    pos['xo'] = pos['x']; active.append(pos); held.add(int(j))
        if cash > 0 and cfg.cash_yield > 0: cash += cash * cfg.cash_yield / 242.0
        vs = 0.0
        for p in active:
            if p['e'] <= t:
                ct = c[t, p['j']]
                if np.isfinite(ct): p['last'] = float(ct)
                p['v'] = p['inv'] * (p['last'] / p['o0']) * (1 - p['cost_e'])
            vs += p['v']
        eq[t] = cash + vs
    ok = np.isfinite(eq); e_ = eq[ok]; n = len(e_); r = e_[1:] / e_[:-1] - 1
    cagr = (e_[-1] / e_[0]) ** (245 / n) - 1; sh = r.mean() / r.std() * np.sqrt(245); dd = (e_ / np.maximum.accumulate(e_) - 1).min()
    yr = np.array([int(d[:4]) for d in dates])[ok][1:]
    byyear = {int(y): float(np.prod(1 + r[yr == y]) - 1) for y in np.unique(yr)}
    return dict(cagr=cagr, sharpe=sh, dd=dd, ntr=ntr, ncut=ncut, cut=cut, byyear=byyear, final=float(e_[-1]))

def label(rule):
    return 'baseline' if not rule else f"U{rule['U']*100:g}% F{rule['FRAC']*100:g}% LG{rule['LG']*100:g}% K{rule['KMIN']} N{rule['NMIN']} {rule['mode']}"

def one(rule):
    r = sim(rule); cuts = np.array([x[1] for x in r['cut']]) if r['cut'] else np.array([])
    out = dict(label=label(rule), rule=rule, cagr=r['cagr'], sharpe=r['sharpe'], dd=r['dd'], ntr=r['ntr'], ncut=r['ncut'], final=r['final'],
               cut_fwd_mean=float(np.nanmean(cuts)) if len(cuts) else None, cut_fwd_med=float(np.nanmedian(cuts)) if len(cuts) else None,
               byyear=r['byyear'])
    print(f"{out['label']:44s} 年化{r['cagr']*100:+6.1f}% 夏普{r['sharpe']:5.2f} 回撤{r['dd']*100:5.0f}% 终值{r['final']:5.1f}x 笔{r['ntr']} 提前卖{r['ncut']}"
          + ('' if not len(cuts) else f" | 被卖掉的票此后到原到期日 均值{np.nanmean(cuts)*100:+.1f}% 中位{np.nanmedian(cuts)*100:+.1f}%"), flush=True)
    return out

if __name__ == '__main__':
    import multiprocessing as mp
    grid = [None]
    for U in (0.05, 0.08, 0.12):
        for FRAC in (0.25, 0.5):
            for mode in ('sell', 'swap'):
                grid.append(dict(U=U, FRAC=FRAC, LG=0.0, KMIN=3, NMIN=4, mode=mode))
    if os.environ.get('GRID') == '2':
        grid = []
        for U, FRAC, LG, K in ((0.05, 0.5, 0.02, 3), (0.08, 0.5, 0.03, 3), (0.05, 0.5, 0.0, 10), (0.08, 0.5, 0.0, 10), (0.08, 0.25, 0.0, 10), (0.12, 0.25, 0.0, 10)):
            for mode in ('sell', 'swap'):
                grid.append(dict(U=U, FRAC=FRAC, LG=LG, KMIN=K, NMIN=4, mode=mode))
    only = os.environ.get('ONLY')
    if only: grid = [g for i, g in enumerate(grid) if str(i) in only.split(',')]
    res = []
    with mp.get_context('fork').Pool(int(os.environ.get('NP', 3))) as pool:
        for out in pool.imap(one, grid): res.append(out)
    json.dump(res, open(os.environ.get('OUT', f'grp60_{VARIANT}.json'), 'w'), ensure_ascii=False, indent=1, default=float)

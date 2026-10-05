"""Group-panic framework on the product engine (quantlab.dipbuy): any grouping of stocks (static labels [nc] or dynamic [nd,nc]).
A group is 'in panic' when its equal-weight 20d return / (60d daily std x sqrt20) <= -1.5; buy the weakest-20d-return tradable stocks
inside panicked groups (global ranking), N=20, hold 20d, next-open buy, 1x. Research only."""
import os, sys, hashlib
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
import numpy as np, pandas as pd
from dataclasses import replace
from quantlab.dipbuy.panel import Panel, build_panel
from quantlab.dipbuy.engine import Candidates, DipConfig, Market, compute_features, simulate, summarize

MIN_MEMBERS = 8
LAKE = os.path.expanduser('~/mnt/lake')
PANEL = os.environ.get('PANEL_NPZ', '')


def load_panel():
    if PANEL and os.path.exists(PANEL):
        return Panel.from_npz(PANEL)
    from pathlib import Path
    L = Path(LAKE)
    return build_panel(L / 'silver/qfq_kline_daily_v2', L / 'bronze/provider=baostock/daily_status_v2')


def group_z(panel, cand, labels, min_members=MIN_MEMBERS):
    """returns z[nd,ng], r20[nd,ng], n[nd,ng]. labels: int [nc] static or [nd,nc] dynamic (known at close of day t); -1 = none."""
    nd, nc = panel.shape
    dyn = labels.ndim == 2
    ng = int(labels.max()) + 1
    uni_prev = np.vstack([np.zeros((1, nc), bool), cand.uni[:-1]])
    z = np.full((nd, ng), np.nan); r20 = np.full((nd, ng), np.nan); cnt = np.zeros((nd, ng), np.int32)
    if dyn:
        lab_prev = np.vstack([np.full((1, nc), -1, labels.dtype), labels[:-1]])
        c = panel.c.astype(np.float32)
        ret1 = np.full((nd, nc), np.nan, np.float32); ret1[1:] = c[1:] / c[:-1] - 1
        ok_all = uni_prev & np.isfinite(ret1)
        ret1 = np.where(ok_all, ret1, 0.0).astype(np.float32)
    for g in range(ng):
        if dyn:
            M = (lab_prev == g) & ok_all
            n = M.sum(1); s = (ret1 * M).sum(1, dtype=np.float64)
        else:
            cols = np.nonzero(labels == g)[0]
            if len(cols) == 0:
                continue
            c = panel.c[:, cols].astype(np.float64)
            r = np.full(c.shape, np.nan); r[1:] = c[1:] / c[:-1] - 1
            ok = uni_prev[:, cols] & np.isfinite(r)
            n = ok.sum(1); s = np.where(ok, r, 0.0).sum(1)
        mean = np.where(n >= min_members, s / np.maximum(n, 1), np.nan)
        ser = pd.Series(mean)
        c20 = np.exp(np.log1p(ser).rolling(20, min_periods=20).sum()) - 1
        sd = ser.rolling(60, min_periods=40).std()
        with np.errstate(invalid='ignore', divide='ignore'):
            z[:, g] = (c20 / (sd * np.sqrt(20))).to_numpy()
        r20[:, g] = c20.to_numpy(); cnt[:, g] = n
    return z, r20, cnt


def inputs(panel, cfg, labels, scope='any', _cache={}):
    """scope 'any': any group triggered; 'idio': only on days when the market itself is not in panic (z_mkt > th)."""
    market, cand = compute_features(panel, cfg.min_amount, cfg.min_price)
    key = hashlib.md5(np.ascontiguousarray(labels).tobytes()).hexdigest()
    if key not in _cache:
        _cache.clear(); _cache[key] = group_z(panel, cand, labels)
    z, r20, cnt = _cache[key]
    trig = np.isfinite(z) & (z <= cfg.z_threshold)
    nd, nc = panel.shape
    if labels.ndim == 1:
        inT = np.zeros((nd, nc), bool); m = np.nonzero(labels >= 0)[0]; inT[:, m] = trig[:, labels[m]]
    else:
        inT = np.zeros((nd, nc), bool)
        for g in range(z.shape[1]):
            inT |= (labels == g) & trig[:, g:g + 1]
    pool = cand.uni & inT & np.isfinite(cand.ret20)
    zmin = np.where(np.isfinite(z), z, np.inf).min(axis=1); zmin = np.where(np.isfinite(zmin), zmin, np.nan)
    mk_panic = np.isfinite(market.z) & (market.z <= cfg.z_threshold)
    if scope == 'idio':
        pool &= ~mk_panic[:, None]
        zmin = np.where(mk_panic, 9.0, zmin)
    fm = Market(mret=market.mret, mk20=market.mk20, z=zmin, count=market.count)
    return fm, Candidates(uni=cand.uni, e6=pool, buyok=cand.buyok, ret20=cand.ret20), (z, cnt)


def halves(panel, eq):
    nd = len(panel.dates); yr = np.array([int(d[:4]) for d in panel.dates])
    r = np.full(nd, np.nan); r[1:] = eq[1:] / eq[:-1] - 1
    out = []
    for a, b in ((2008, 2016), (2017, 2026)):
        k = (yr >= a) & (yr <= b) & np.isfinite(r); y = r[k]
        out.append(f'{(np.prod(1 + y) ** (245 / len(y)) - 1) * 100:+.1f}%/{y.mean() / y.std() * np.sqrt(245):.2f}')
    return out


def run(panel, name, labels, scope='any', cfg=None, quiet=False, **kw):
    cfg = cfg or DipConfig(leverage=1.0)
    fm, fc, (z, cnt) = inputs(panel, replace(cfg, **kw) if kw else cfg, labels, scope)
    c2 = replace(cfg, **kw) if kw else cfg
    raw = simulate(panel, fm, fc, c2)
    s = summarize(panel, fm, raw, c2); st = s['stats'] or {}; tr = s['trades']
    h = halves(panel, raw['eq'])
    valid_g = int((np.isfinite(z).any(0)).sum())
    line = (f"{name:46s} 组{valid_g:3d} 触发{s['gate_days']:5d}天 年化{st.get('cagr', 0) * 100:+5.1f}% 夏普{st.get('sharpe', 0):+.2f} "
            f"回撤{st.get('max_drawdown', 0) * 100:4.0f}% 仓位{st.get('exposure', 0) * 100:3.0f}% 笔{tr['n']:5d} 笔均{(tr['mean'] or 0) * 1e4:+4.0f}bp | 前半{h[0]} 后半{h[1]}")
    if not quiet:
        print(line, flush=True)
    return dict(name=name, scope=scope, groups=valid_g, gate_days=s['gate_days'], cagr=st.get('cagr'), sharpe=st.get('sharpe'),
                mdd=st.get('max_drawdown'), expo=st.get('exposure'), n=tr['n'], mean=tr['mean'], first=h[0], second=h[1])

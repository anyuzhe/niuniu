"""§91: can pre-entry risk filters (price / liquidity / drawdown / valuation-based financial distress) cut the delisted-stock losses on D (with-delisted panel)? fmask = allowed on signal day."""
import sys, json, os, numpy as np
os.environ.setdefault('C70DIR', 'c80'); os.environ.setdefault('SERIES', 'c80/series.npz')
import lib73 as X, lib70 as L, lib74 as Y
F = 'res81_del.json'; res = json.load(open(F)) if os.path.exists(F) else {}
ISDEL = np.load('c80/isdel.npy'); nd = L.nd
def go(label, **kw):
    if label in res: st = res[label]
    else:
        st = X.run(**kw); tr = X.TR
        st['nDel'] = int(sum(1 for t in tr if ISDEL[t[3]])); st['mDel'] = float(np.mean([t[1] for t in tr if ISDEL[t[3]]])) if st['nDel'] else None
        st['lt20'] = float(np.mean([t[1] < -.2 for t in tr])); st['worst'] = float(min(t[1] for t in tr))
        res[label] = st; json.dump(res, open(F, 'w'), ensure_ascii=False)
    print(f"{label:50s} 年化{st['cagr']*100:+5.1f}% 夏普{st['sharpe']:.2f} 回撤{st['dd']*100:4.0f}% 前{(st['h1'] or 0)*100:+5.1f}% 后{(st['h2'] or 0)*100:+5.1f}% 笔{st['ntr']} 退市笔{st['nDel']} 均{st['tret']*1e4:+.0f}bp <-20%:{st['lt20']*100:.1f}% 最差{st['worst']*100:.0f}%", flush=True); return st
def amt20():
    a = np.nan_to_num(np.load('c80/A.npy').astype(np.float64), nan=0.0); cs = np.cumsum(a, 0); o = np.full(a.shape, np.nan, np.float32); o[19:] = ((cs[19:] - np.concatenate([np.zeros((1, a.shape[1])), cs[:-20]])) / 20).astype(np.float32); return o
phase = sys.argv[1]
price = np.asarray(L.C, np.float32) / np.asarray(L.F, np.float32)
if phase in ('f1', 'f2', 'f3'):
    pass
sl_list = ('ACB', 'CB')
if phase == 'f1':   # price / liquidity / drawdown
    AM = amt20()
    for sl in sl_list:
        go(f'[{sl}] 基线', sleeves=sl)
        for p in (2, 3, 5): go(f'[{sl}] 股价>={p}元', sleeves=sl, fmask=price >= p)
        for a in (2e7, 5e7, 1e8): go(f'[{sl}] 20日均成交额>={a/1e4:.0f}万', sleeves=sl, fmask=AM >= a)
        DD = np.asarray(L.L('dd60'), np.float32)
        for d in (-0.5, -0.4): go(f'[{sl}] 60日回撤不超过{abs(d):.0%}', sleeves=sl, fmask=DD >= d)
if phase == 'f2':   # valuation-based financial distress
    PE = np.asarray(L.L('pe'), np.float32); PB = np.asarray(L.L('pb'), np.float32); PS = np.asarray(L.L('ps'), np.float32)
    for sl in sl_list:
        go(f'[{sl}] 基线', sleeves=sl)
        go(f'[{sl}] 市盈率TTM>0（排除亏损/缺失）', sleeves=sl, fmask=PE > 0)
        go(f'[{sl}] 市净率>0（排除净资产为负/缺失）', sleeves=sl, fmask=PB > 0)
        go(f'[{sl}] 市盈率>0 且 市净率>0', sleeves=sl, fmask=(PE > 0) & (PB > 0))
        go(f'[{sl}] 不是(亏损且市净率<1)', sleeves=sl, fmask=~((PE <= 0) & (PB < 1)) | ~np.isfinite(PE))
        go(f'[{sl}] 市净率>=0.8 或缺失 且 非负', sleeves=sl, fmask=(PB >= 0.8) | ~np.isfinite(PB))
        go(f'[{sl}] 市销率>0.3 或缺失', sleeves=sl, fmask=(PS > 0.3) | ~np.isfinite(PS))
if phase == 'f3':   # combinations
    PE = np.asarray(L.L('pe'), np.float32); PB = np.asarray(L.L('pb'), np.float32); AM = amt20(); DD = np.asarray(L.L('dd60'), np.float32)
    for sl in sl_list:
        go(f'[{sl}] 股价>=3 且 市净率>0', sleeves=sl, fmask=(price >= 3) & (PB > 0))
        go(f'[{sl}] 股价>=3 且 市盈率>0 且 市净率>0', sleeves=sl, fmask=(price >= 3) & (PE > 0) & (PB > 0))
        go(f'[{sl}] 股价>=3 且 成交额>=5000万 且 市净率>0', sleeves=sl, fmask=(price >= 3) & (AM >= 5e7) & (PB > 0))
        go(f'[{sl}] 以上 + 60日回撤不超50%', sleeves=sl, fmask=(price >= 3) & (AM >= 5e7) & (PB > 0) & (DD >= -0.5))

"""grp62 step2: execution realism with 5-min bars (2020+). Entry-timing alternatives, order-size vs first 5-min bar, sell-side limit-down."""
import os, sys, json, datetime as dt
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
import numpy as np, pyarrow.parquet as pq
from quantlab.dipbuy.panel import Panel
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
dates = np.array(panel.dates).astype('datetime64[D]'); codes = list(panel.codes); cidx = {c: i for i, c in enumerate(codes)}
LAKE = os.path.expanduser('~/mnt/lake/bronze/provider=baostock')
CAP = 400000.0
trs = json.load(open('grp62_trades.json'))

def lim_of(code, d):
    n = code.split('.')[1]
    if n.startswith('688'): return 0.20
    if n.startswith('300') and d >= '2020-08-24': return 0.20
    return 0.10

def bars(code, ds):
    f = code.replace('.', '_') + '.parquet'
    for sub in ('stock_kline_min5', 'stock_kline_min5_delisted'):
        p = os.path.join(LAKE, sub, f)
        if os.path.exists(p):
            t = pq.read_table(p, columns=['date', 'time', 'open', 'high', 'low', 'close', 'volume', 'amount'],
                              filters=[('date', 'in', [dt.date.fromisoformat(x) for x in ds])]).to_pandas()
            return t
    return None

def per_trade(tr):
    j = cidx[tr['code']]; e = int(np.searchsorted(dates, np.datetime64(tr['entry']))); x = int(np.searchsorted(dates, np.datetime64(tr['exit'])))
    b = bars(tr['code'], [tr['entry'], tr['exit']])
    if b is None or b.empty: return None
    b['d'] = b['date'].astype(str)
    be = b[b.d == tr['entry']].sort_values('time'); bx = b[b.d == tr['exit']].sort_values('time')
    if len(be) < 40 or len(bx) < 40: return None
    t = be['time'].str[8:12].values
    op = be.open.iloc[0]; c0935 = be.close.iloc[0]
    i1000 = np.where(t == '1000')[0]; p1000 = be.close.iloc[i1000[0]] if len(i1000) else np.nan
    v30 = be.volume.iloc[:6].sum(); vw30 = be.amount.iloc[:6].sum() / v30 if v30 > 0 else np.nan
    vwd = be.amount.sum() / be.volume.sum() if be.volume.sum() > 0 else np.nan
    cl = be.close.iloc[-1]; lo = be.low.min(); hi = be.high.max()
    prev_adj = float(panel.c[e - 1, j]); gap = float(panel.o[e, j]) / prev_adj - 1 if np.isfinite(prev_adj) else np.nan
    lim = lim_of(tr['code'], tr['entry'])
    cx = bx.close.iloc[-1]
    # sanity: minute open vs panel daily raw open
    o_raw = float(panel.o[e, j]) / float(panel.f[e, j])
    c_raw_x = float(panel.c[x, j]) / float(panel.f[x, j]) if np.isfinite(panel.c[x, j]) else np.nan
    # exit day limit-down at close
    cprev = float(panel.c[x - 1, j]); chg = float(panel.c[x, j]) / cprev - 1 if np.isfinite(panel.c[x, j]) and np.isfinite(cprev) else np.nan
    ld = bool(np.isfinite(chg) and chg <= -lim_of(tr['code'], tr['exit']) + 0.0025)
    nx = float(panel.o[x + 1, j]) / float(panel.c[x, j]) - 1 if (ld and x + 1 < len(dates) and np.isfinite(panel.o[x + 1, j])) else np.nan
    return dict(w=tr['weight'], ret=tr['ret'], sleeve=tr['sleeve'], year=tr['entry'][:4], gap=gap, lim=lim,
                op=op, c0935=c0935, p1000=p1000, vw30=vw30, vwd=vwd, cl=cl, lo=lo, hi=hi,
                bar1_amt=float(be.amount.iloc[0]), size=tr['weight'] * CAP, o_match=op / o_raw - 1, c_match=cx / c_raw_x - 1 if np.isfinite(c_raw_x) else np.nan,
                ld=ld, nx_open=nx, chg_x=chg)

out = {}
for name in ('D', 'D1'):
    rows = []
    miss = 0
    for tr in trs[name]:
        if tr['entry'] < '2020-01-02' or tr['closed'] != 'exit': continue
        r = per_trade(tr)
        if r is None: miss += 1; continue
        rows.append(r)
    print(name, 'trades with 5-min', len(rows), 'missing', miss, flush=True)
    out[name] = rows
json.dump(out, open('grp62_exec.json', 'w'), default=float)

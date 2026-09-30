"""ETF 先卖后买 on real ETF 5-minute bars (research only, manual verification).

Data (all READY in the DATA catalog, read by their registered paths under LAKE):
  bronze/provider=tdx/etf_universe/latest.parquet      selected ETFs and category
  bronze/provider=tdx/etf_kline_min5/<code>.parquet    5-minute bars, 2024-09-12 onwards
  bronze/provider=eastmoney/etf_nav/<code>.parquet     cash distributions and splits (to adjust the previous close)
  bronze/provider=tdx/live_quotes/date=*.parquet       live bid/ask (from 2026-09-28) to check the one-tick spread
  research/brk/offpred.npz                             walk-forward 10:30 market model (offmodel.py)
Universe: selected ETFs in categories broad / sector / cross_border / gold; two bond funds labelled otherwise
(sh.511220, sz.159398) are dropped. Each ETF is treated as a base position.
Rules
  A  own price at 10:00 is down >= x (0.3 / 0.5 / 1.0%) from the adjusted previous close
     -> sell at the 10:05 bar open minus 1 tick, buy back at the close plus 1 tick
  B  the 10:30 model predicts the whole-market move from 10:30 to the close <= -thr (0.1 / 0.2 / 0.3%)
     -> sell at the 10:35 bar open minus 1 tick, buy back at the close plus 1 tick
  0  no signal: sell at 10:35 every day (baseline)
Costs: commission 万1 each side without the 5-yuan minimum = 2 bp; ETFs pay no stamp duty and no transfer fee;
1 tick = 0.001 yuan each side is inside the prices. No sale at limit-down (10%); a close at limit-up moves the
buy-back to the next open plus 1 tick."""
import numpy as np, os, glob, re
import pyarrow.parquet as pq
H = os.environ['HOME']; LAKE = os.environ.get('LAKE', f'{H}/mnt/lake')
TICK = 0.001; FEE = 2.0
SLOTS = [f'{h:02d}{m:02d}' for h, m in [(9, 35), (9, 40), (9, 45), (9, 50), (9, 55)] + [(h, m) for h in (10,) for m in range(0, 60, 5)] + [(11, m) for m in range(0, 35, 5)]] \
    + [f'{h:02d}{m:02d}' for h, m in [(13, m) for m in range(5, 60, 5)] + [(14, m) for m in range(0, 60, 5)] + [(15, 0)]]
assert len(SLOTS) == 48 and SLOTS[5] == '1000' and SLOTS[6] == '1005' and SLOTS[12] == '1035', SLOTS
U = pq.read_table(f'{LAKE}/bronze/provider=tdx/etf_universe/latest.parquet').to_pandas()
U = U[U.selected & U.category.isin(['broad', 'sector', 'cross_border', 'gold']) & ~U.symbol.isin(['sh.511220', 'sz.159398'])]
FOREIGN = re.compile('HK|港|恒|中概|纳指|标普|中韩|油气')


def group(row):
    if row.category == 'gold': return '黄金'
    if row.category == 'cross_border' or FOREIGN.search(row['name']): return '跨境/港股'
    return 'A股宽基' if row.category == 'broad' else 'A股行业'


GRP = {r.symbol: group(r) for _, r in U.iterrows()}; NAME = dict(zip(U.symbol, U['name']))
P = np.load(f'{H}/research/brk/offpred.npz'); PRED = dict(zip(P['date'].astype(str), P['pred']))


def events(sym):
    f = f"{LAKE}/bronze/provider=eastmoney/etf_nav/{sym.replace('.', '_')}.parquet"
    ev = {}
    if not os.path.exists(f): return ev
    t = pq.read_table(f, columns=['date', 'distribution']).to_pandas()
    for d, s in zip(t.date.astype(str), t.distribution):
        if not isinstance(s, str) or not s: continue
        m = re.search(r'派现金([\d.]+)元', s)
        if m: ev[d] = ('cash', float(m.group(1)))
        m = re.search(r'(?:分拆|折算)([\d.]+)份', s)
        if m: ev[d] = ('split', float(m.group(1)))
    return ev


rows = {k: [] for k in 'sym grp date r10 bpA bpB skipA skipB px'.split()}
evcheck = []
for sym in U.symbol:
    t = pq.read_table(f"{LAKE}/bronze/provider=tdx/etf_kline_min5/{sym.replace('.', '_')}.parquet",
                      columns=['date', 'time', 'open', 'close', 'volume']).to_pandas()
    t['date'] = t.date.astype(str); t['hm'] = t.time.astype(str).str[8:12]
    t = t[t.hm.isin(SLOTS)]  # the standard 48 bars; a stray 13:00 bar in one file is dropped
    days = sorted(t.date.unique()); slots = SLOTS
    di = {d: i for i, d in enumerate(days)}; si = {s: i for i, s in enumerate(slots)}
    O = np.full((len(days), 48), np.nan); C = O.copy(); V = np.zeros_like(O)
    ii = t.date.map(di).values; jj = t.hm.map(si).values
    O[ii, jj] = t.open.values; C[ii, jj] = t.close.values; V[ii, jj] = t.volume.values
    for j in range(48):  # carry the close forward inside a day
        m = np.isnan(C[:, j]); C[m, j] = O[m, 0] if j == 0 else C[m, j - 1]
    O = np.where(np.isnan(O), C, O)
    pc = np.r_[np.nan, C[:-1, 47]]; nO = np.r_[O[1:, 0], np.nan]
    ev = events(sym)
    for k, d in enumerate(days):
        if d in ev and np.isfinite(pc[k]):
            kind, v = ev[d]
            if kind == 'split' and k + 1 < len(days) and abs(O[k + 1, 0] / pc[k + 1] * v - 1) < abs(O[k, 0] / pc[k] * v - 1):
                k += 1  # the NAV row is the conversion date; the traded price splits on the next trading day
            raw = O[k, 0] / pc[k] - 1
            pc[k] = pc[k] - v if kind == 'cash' else pc[k] / v
            evcheck.append((sym, days[k], kind, v, raw * 100, (O[k, 0] / pc[k] - 1) * 100))
    gap = O[:, 0] / pc - 1
    good = np.isfinite(pc) & (np.abs(gap) < 0.11)
    r10 = C[:, 5] / pc - 1
    lu = C[:, 47] >= np.round(pc * 1.1, 3) - TICK / 2
    buy = np.where(lu, nO + TICK, C[:, 47] + TICK)

    def leg(col):
        o = O[:, col]; skip = ~good | (V[:, col] <= 0) | (o <= np.round(pc * 0.9, 3) + TICK / 2)
        s = o - TICK; bp = (s - buy) / s * 1e4 - FEE
        return bp, skip | ~np.isfinite(bp)
    bpA, skA = leg(6); bpB, skB = leg(12)
    for k_, v_ in (('sym', [sym] * len(days)), ('grp', [GRP[sym]] * len(days)), ('date', days), ('r10', r10),
                   ('bpA', bpA), ('bpB', bpB), ('skipA', skA), ('skipB', skB), ('px', O[:, 12])):
        rows[k_].append(np.asarray(v_))
R = {k: np.concatenate(v) for k, v in rows.items()}
d = R['date']; per = np.where(d <= '2025-09-30', 'A', 'B'); pred = np.array([PRED.get(x, np.nan) for x in d])

print('分红/拆分日的开盘缺口（调整前 → 调整后，%）：')
for e in evcheck:
    if e[1] >= '2024-09-12': print(f'  {e[0]} {NAME[e[0]]} {e[1]} {e[2]} {e[3]}: {e[4]:+.2f} → {e[5]:+.2f}')


def st(bp, m):
    v = bp[m]; n = len(v)
    if n < 20: return None
    u, inv = np.unique(d[m], return_inverse=True); mu = v.mean()
    se = np.sqrt((np.bincount(inv, v - mu) ** 2).sum()) / n
    w = v > 0
    return dict(n=n, days=len(u), bp=mu, t=mu / se, win=w.mean() * 100)


def line(lab, bp, m):
    s = st(bp, m)
    if s is None: return f'  {lab}: 太少'
    a = st(bp, m & (per == 'A')); b = st(bp, m & (per == 'B'))
    f = lambda z: f'{z["bp"]:+6.1f}bp（{z["days"]}天）' if z else '   —'
    return f'  {lab}: {s["n"]:5d}笔 {s["days"]:3d}天 每笔 {s["bp"]:+6.1f}bp t{s["t"]:+.1f} 胜率{s["win"]:.0f}% | 2024-09..2025-09 {f(a)} | 2025-10..2026-09 {f(b)}'


G = ['A股宽基', 'A股行业', '跨境/港股', '黄金']
print(f'\nETF {len(U)} 只（宽基 {sum(g=="A股宽基" for g in GRP.values())}，行业 {sum(g=="A股行业" for g in GRP.values())}，跨境/港股 {sum(g=="跨境/港股" for g in GRP.values())}，黄金 {sum(g=="黄金" for g in GRP.values())}），'
      f'{min(d)} 至 {max(d)}；费用 2bp + 每边 1 个价位（0.001 元）')
for g in G:
    gm = R['grp'] == g
    print(f'\n【{g}】')
    print(line('每天 10:35 先卖、收盘买回（对照）', R['bpB'], gm & ~R['skipB']))
    for x in (0.003, 0.005, 0.01):
        print(line(f'A 10:00 比昨收跌≥{x*100:.1f}% 先卖', R['bpA'], gm & ~R['skipA'] & (R['r10'] <= -x)))
    for thr in (0.001, 0.002, 0.003):
        print(line(f'B 10:30 模型预测下午跌≥{thr*100:.1f}% 先卖', R['bpB'], gm & ~R['skipB'] & np.isfinite(pred) & (pred <= -thr)))

print('\n【按价格】一个价位 0.001 元：1 元的 ETF 是 10bp，4 元的是 2.5bp（A股宽基+行业）')
eq = np.isin(R['grp'], ['A股宽基', 'A股行业'])
for lab, pm in (('价格<2元', R['px'] < 2), ('价格≥2元', R['px'] >= 2)):
    print(line(f'{lab} 每天先卖（对照）', R['bpB'], eq & pm & ~R['skipB']))
    print(line(f'{lab} B 预测跌≥0.2%', R['bpB'], eq & pm & ~R['skipB'] & np.isfinite(pred) & (pred <= -0.002)))
    print(line(f'{lab} B 预测跌≥0.3%', R['bpB'], eq & pm & ~R['skipB'] & np.isfinite(pred) & (pred <= -0.003)))

print('\n【主要宽基逐只】A = 10:00 跌≥0.5%；B = 模型预测跌≥0.2%')
for sym in ['sh.510300', 'sh.510050', 'sh.510500', 'sh.512100', 'sz.159915', 'sh.588000', 'sh.563360']:
    sm = R['sym'] == sym
    sa = st(R['bpA'], sm & ~R['skipA'] & (R['r10'] <= -0.005)); sb = st(R['bpB'], sm & ~R['skipB'] & np.isfinite(pred) & (pred <= -0.002))
    f = lambda z: f'{z["n"]:3d}次 {z["bp"]:+6.1f}bp 胜率{z["win"]:.0f}%' if z else '太少'
    print(f'  {sym} {NAME[sym]:8s} A {f(sa)} | B {f(sb)}')

# real spreads from the live recorder
qs = sorted(glob.glob(f'{LAKE}/bronze/provider=tdx/live_quotes/date=*.parquet'))
if qs:
    import pandas as pd
    q = pd.concat([pq.read_table(f, columns=['symbol', 'kind', 'time', 'bid1', 'ask1']).to_pandas() for f in qs])
    q = q[(q.kind == 'etf') & (q.bid1 > 0) & (q.ask1 > 0) & q.symbol.isin(list(GRP))]
    q['sp'] = np.round((q.ask1 - q.bid1) / TICK)
    s = q.groupby('symbol').sp.agg(['median', lambda x: (x <= 1).mean() * 100, 'size'])
    print(f'\n盘中实时买一卖一（{", ".join(os.path.basename(f)[5:15] for f in qs)}），{len(s)} 只：价差中位数 1 个价位的 {int((s["median"] <= 1).sum())} 只；'
          f'价差=1 个价位的分钟占比 中位 {s.iloc[:, 1].median():.0f}%，最差 {s.iloc[:, 1].min():.0f}%')
    for g in G:
        ss = s[[GRP[x] == g for x in s.index]]
        print(f'  {g}: {len(ss)} 只，1 个价位的分钟占比中位 {ss.iloc[:, 1].median():.0f}%，最差 {ss.iloc[:, 1].min():.0f}%（{NAME[ss.iloc[:, 1].idxmin()]}）')

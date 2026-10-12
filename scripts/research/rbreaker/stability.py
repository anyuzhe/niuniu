"""指数 / ETF 日内回测的稳定性：分半年、集中度（前 10 个交易日贡献了多少盈利）。读 run_intraday 写出的 trades_*.csv。"""
import collections
import csv
import glob
import os
import statistics as st
import sys

out = sys.argv[1] if len(sys.argv) > 1 else 'artifacts/research/rbreaker'
for fn in sorted(glob.glob(os.path.join(out, 'trades_*.csv'))):
    base = os.path.basename(fn)
    if '_1_allow_short' in base or '_2_' in base:
        if not base.startswith('trades_etf_'):
            continue
    rows = list(csv.DictReader(open(fn)))
    if not rows:
        continue
    by = collections.defaultdict(list)
    for r in rows:
        d = r['date']
        by[d[:4] + ('H1' if d[5:7] <= '06' else 'H2')].append(float(r['ret']) * 1e4)
    dd = collections.defaultdict(float)
    for r in rows:
        dd[r['date']] += float(r['ret']) * 1e4
    tot = sum(dd.values())
    top = sorted(dd.values(), reverse=True)[:10]
    print(f'{base}  N={len(rows)}  触发日数={len(dd)}  前10天合计占全部盈利 {100 * sum(top) / tot:.0f}%' if tot > 0 else f'{base}  N={len(rows)} 总盈利<=0')
    print('    ' + '  '.join(f'{k}:{st.mean(v):+.0f}bp(n={len(v)})' for k, v in sorted(by.items())))

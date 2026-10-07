"""grp66: D / D1 / D2 的最长回撤时间（水下时间）。python grp66.py D|D1|D2 -> grp66_<V>.json"""
import os, sys, json
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
V = sys.argv[1]
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
cfg = fusion.config_for(V)
inp = fusion.build_inputs(panel, cfg, cls)
raw = fusion.simulate_fused(panel, inp, cfg)
eq = raw['eq']; dates = [str(d) for d in panel.dates]
ok = np.nonzero(np.isfinite(eq))[0]; e = eq[ok]; d = [dates[i] for i in ok]
peak = np.maximum.accumulate(e); dd = e / peak - 1
# 水下区间：从某个高点开始，到第一次创新高（或数据结束）
eps = []; i = 0; n = len(e)
while i < n:
    if dd[i] < 0:
        s = i - 1                                  # 高点那天
        j = i
        while j < n and e[j] < peak[s]: j += 1     # 第一次回到高点
        seg = dd[i:j]; k = i + int(np.argmin(seg))
        eps.append(dict(peak=d[s], trough=d[k], recover=(d[j] if j < n else None), days=(j if j < n else n) - s,
                        cal=int((np.datetime64(d[j] if j < n else d[-1]) - np.datetime64(d[s])).astype(int)),
                        depth=float(dd[k]), to_trough=k - s))
        i = j
    else:
        i += 1
eps.sort(key=lambda r: -r['days'])
out = dict(variant=V, n=n, top_by_days=eps[:6], top_by_depth=sorted(eps, key=lambda r: r['depth'])[:4],
           pct_underwater=float((dd < 0).mean()), pct_below5=float((dd < -0.05).mean()), pct_below10=float((dd < -0.10).mean()),
           now=dict(dd=float(dd[-1]), last=d[-1], peak_date=d[int(np.argmax(e))]))
json.dump(out, open(f'grp66_{V}.json', 'w'), ensure_ascii=False, indent=1)
print(V, 'ok')

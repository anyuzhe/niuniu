"""Step 1 (research only): D and D1 on the with-delisted panel using the PRODUCT engine (quantlab.dipbuy.fusion), 1x, idle yield 0 -> daily returns + exposure."""
import os, sys
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
sw = os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history')
cls = industry.load_classification(sw, panel.codes)
out = {'dates': np.array(panel.dates).astype(str)}
for name, cfg in (('D', fusion.default_config()), ('D1', fusion.d1_config())):
    c0 = replace(cfg, cash_yield=0.0)
    inp = fusion.build_inputs(panel, c0, cls); raw = fusion.simulate_fused(panel, inp, c0)
    eq, ex = raw['eq'], raw['expo']; r = np.full(len(eq), np.nan); r[1:] = eq[1:] / eq[:-1] - 1
    out['r' + name], out['ex' + name] = r, ex
    # check vs product with 2% idle
    c2 = replace(cfg, cash_yield=0.02); raw2 = fusion.simulate_fused(panel, inp, c2); e2 = raw2['eq']; ok = np.isfinite(e2)
    n = ok.sum(); cagr = (e2[ok][-1] / e2[ok][0]) ** (245 / n) - 1
    print(name, 'product 2% idle CAGR', f'{cagr*100:+.1f}%', 'trades', len(raw2['trades']), flush=True)
np.savez('grp57_D.npz', **out); print('saved', flush=True)

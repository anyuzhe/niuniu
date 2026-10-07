"""grp68a: D / D2 的日收益与仓位（产品引擎，含退市股面板，闲置收益记 0），供 grp68b 叠加宽基 ETF。python grp68a.py D|D2"""
import os, sys
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
V = sys.argv[1]
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
cfg = replace(fusion.config_for(V), cash_yield=0.0)
inp = fusion.build_inputs(panel, cfg, cls); raw = fusion.simulate_fused(panel, inp, cfg)
eq, ex = raw['eq'], raw['expo']; r = np.full(len(eq), np.nan); r[1:] = eq[1:] / eq[:-1] - 1
np.savez(f'grp68_{V}.npz', dates=np.array(panel.dates).astype(str), r=r, ex=ex)
c2 = replace(cfg, cash_yield=0.02); e2 = fusion.simulate_fused(panel, inp, c2)['eq']; ok = np.isfinite(e2)
print(V, 'product 2% idle CAGR', round(((e2[ok][-1] / e2[ok][0]) ** (245 / ok.sum()) - 1) * 100, 1))

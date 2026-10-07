"""grp62 step1: export D / D1 trade lists (product engine, with-delisted panel, 2% idle) for 5-min execution tests."""
import os, sys, json
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
sw = os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history')
cls = industry.load_classification(sw, panel.codes)
res = {}
for name, cfg in (('D', fusion.default_config()), ('D1', fusion.d1_config())):
    inp = fusion.build_inputs(panel, cfg, cls); raw = fusion.simulate_fused(panel, inp, cfg)
    tr = raw['trades']
    res[name] = tr
    print(name, len(tr), tr[0], flush=True)
json.dump(res, open('grp62_trades.json', 'w'))
# also save per-day prev-close raw / limit info? not needed here

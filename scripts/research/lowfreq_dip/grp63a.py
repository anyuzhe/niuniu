"""grp63 step1: equal-weight market index from the product engine (with-delisted panel) + position metrics; saved for reuse."""
import os, sys
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
sw = os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history')
cls = industry.load_classification(sw, panel.codes)
cfg = fusion.default_config()
inp = fusion.build_inputs(panel, cfg, cls)
m = inp.market
np.savez('grp63_mkt.npz', dates=np.array(panel.dates).astype(str), mret=m.mret, mk20=m.mk20, z=m.z, count=m.count,
         gA=inp.gates['A'], gC=inp.gates['C'], gB=inp.gates['B'])
print('saved', len(panel.dates), np.nanmin(m.count), np.nanmax(m.count))

"""grp69: B 层（行业恐慌）历史成交按申万一级行业归类，看哪些行业触发后收益差。python grp69.py D|D2 -> grp69_<V>.json"""
import os, sys, json
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
V = sys.argv[1]
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
cfg = fusion.config_for(V); inp = fusion.build_inputs(panel, cfg, cls)
raw = fusion.simulate_fused(panel, inp, cfg)
j_of = {str(c): j for j, c in enumerate(panel.codes)}
rows = []
for t in raw['trades']:
    if t.get('sleeve') != 'B': continue
    rows.append(dict(ind=cls.name_of(j_of[str(t['code'])]), signal=str(t['signal']), ret=float(t['ret']), code=str(t['code'])))
json.dump(dict(variant=V, n=len(rows), trades=rows), open(f'grp69_{V}.json', 'w'), ensure_ascii=False)
print(V, 'B trades', len(rows))

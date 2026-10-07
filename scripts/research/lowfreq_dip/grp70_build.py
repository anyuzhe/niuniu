"""grp70_build: 把原始（未过滤）融合输入存成 pickle，供 grp70 各进程复用，省掉每次 60+ 秒的构建。"""
import os, sys, pickle, time
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
t0 = time.time()
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
inp = fusion._build_inputs(panel, fusion.default_config(), cls)
pickle.dump(inp, open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'wb'), protocol=4)
print('saved', round(time.time() - t0), 's', os.path.getsize(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl')) // 2**20, 'MB')

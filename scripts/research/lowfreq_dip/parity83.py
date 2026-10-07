"""Product quantlab.dipbuy.fusion D and D1 on the with-delisted research panel vs research numbers (res80 / yr83)."""
import sys, time, os, json, numpy as np
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from pathlib import Path
from quantlab.dipbuy.panel import Panel
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.engine import summarize, curve
t0 = time.time(); P = Panel.from_npz('panel_del.npz'); P.meta = {'signature': 'research'}; print('panel', P.shape, round(time.time() - t0), 's', flush=True)
cls = industry.load_classification(Path(os.path.expanduser('~/mnt/lake')) / 'bronze/provider=swsresearch/industry_classification_history', P.codes)
out = {}
for name, cfg in (('D', fusion.default_config()), ('D1', fusion.d1_config())):
    t = time.time(); inp = fusion.build_inputs(P, cfg, cls); print(name, 'inputs', round(time.time() - t), 's', flush=True)
    t = time.time(); raw = fusion.simulate_fused(P, inp, cfg); print(name, 'sim', round(time.time() - t), 's', flush=True)
    s = summarize(P, inp.market, raw, cfg.dip_config())['stats']
    print(name, '年化 %.1f%% 夏普 %.2f 回撤 %.0f%% 笔 %d' % (s['cagr'] * 100, s['sharpe'], s['max_drawdown'] * 100, len(raw['trades'])), flush=True)
    out[name] = raw['eq'][np.isfinite(raw['eq'])]
    np.save(f'parity83_{name}.npy', raw['eq'])

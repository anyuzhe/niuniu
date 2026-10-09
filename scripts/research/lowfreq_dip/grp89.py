"""grp89: 账户回撤熔断（预先登记见档案 §132）。python grp89.py run"""
import os, sys, json, pickle, inspect
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
HERE = os.path.dirname(os.path.abspath(__file__))
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
dates = np.array([str(d) for d in panel.dates]); nd, nc = panel.shape; years = np.array([int(d[:4]) for d in dates]); i18 = int(np.searchsorted(dates, '2018-01-01'))
raw_inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
SCHEMES = {'BASE': None, 'H1': ('halve', -.15, -.08), 'H2': ('halve', -.20, -.10), 'P1': ('pause', -.20, -.10), 'P2': ('pause', -.25, -.15), 'P3': ('days', -.20, 20), 'P4': ('days_reset', -.20, 20)}   # P4 为事后补充（P1~P3 的暂停会永久锁死），不在 §132 登记的 5 个方案里
src = inspect.getsource(fusion.simulate_fused)
def rep(a, b):
    global src; assert src.count(a) == 1, a; src = src.replace(a, b)
rep('def simulate_fused(', 'def simulate_fused_brk(')
rep("    earned = 0.0\n    for t in range(t0, tend + 1):", "    earned = 0.0\n    _peak, _halt, _until, _halt_days, _pend = 1.0, False, -1, 0, False\n    for t in range(t0, tend + 1):")
rep("            held = {p['j'] for p in active}\n", """            held = {p['j'] for p in active}
            _m = 1.0
            if BRK is not None:
                _eq = cash + sum(p['v'] for p in active)
                if BRK[0] == 'days_reset' and _pend and t > _until: _peak = _eq; _pend = False      # 冷静期结束：以当前净值为新的高点
                _peak = max(_peak, _eq); _dd = _eq / _peak - 1
                kind, trig, res = BRK
                if kind in ('days', 'days_reset'):
                    if t > _until and _dd <= trig: _until = t + res; _pend = True
                    _halt = t <= _until
                else:
                    if not _halt and _dd <= trig: _halt = True
                    elif _halt and _dd >= res: _halt = False
                if _halt:
                    _halt_days += 1; _m = 0.5 if kind == 'halve' else 0.0
""")
rep('size = min(W[s] * equity, G * equity - invested)', 'size = min(W[s] * _m * equity, G * equity - invested)')
rep("    return dict(eq=eq,", "    fusion_halt_days[0] = _halt_days\n    return dict(eq=eq,")
fusion.fusion_halt_days = [0]
exec(src, fusion.__dict__)
def mdd_seg(e):
    return float((e / np.maximum.accumulate(e) - 1).min()) if len(e) > 2 else float('nan')
def underwater(e):
    peak = np.maximum.accumulate(e); w = e < peak * (1 - 1e-12); best = cur = 0
    for x in w:
        cur = cur + 1 if x else 0; best = max(best, cur)
    return best
CACHE = os.path.join(HERE, 'grp89_cache.json'); cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
def sim(V, sch):
    key = f'{V}|{sch}'
    if key in cache: return cache[key]
    cfg = fusion.config_for(V); inp = fusion.with_industry_blacklist(fusion.with_near_high_filter(replace(raw_inp), cfg), cfg, cls)
    fusion.BRK = SCHEMES[sch]; raw = fusion.simulate_fused_brk(panel, inp, cfg)
    eq = raw['eq']; ok = np.isfinite(eq); idx = np.nonzero(ok)[0]; e = eq[idx]; r = e[1:] / e[:-1] - 1
    n0 = int((idx < i18).sum()); n1 = int((idx >= i18).sum()); pre = eq[i18 - 1] / e[0]; post = e[-1] / eq[i18 - 1]
    yr = {}
    for y in range(2008, 2027):
        ii = np.nonzero((years == y) & ok)[0]
        if len(ii) > 5:
            b = eq[ii[0] - 1] if ii[0] > 0 and np.isfinite(eq[ii[0] - 1]) else eq[ii[0]]; yr[y] = float(eq[ii[-1]] / b - 1)
    o = dict(cagr=float((e[-1] / e[0]) ** (245 / len(e)) - 1), sharpe=float(r.mean() / r.std() * np.sqrt(245)), mdd=mdd_seg(e), mdd_pre=mdd_seg(e[:n0]), mdd_post=mdd_seg(e[n0:]),
             final=float(e[-1] / e[0]), pre=float(pre ** (245 / n0) - 1), post=float(post ** (245 / n1) - 1), uw=underwater(e), worst_year=min(yr.values()), worst_y=min(yr, key=yr.get),
             halt_days=int(fusion.fusion_halt_days[0]), n_days=len(e), n=len(raw['trades']), years=yr)
    cache[key] = o; json.dump(cache, open(CACHE, 'w'), ensure_ascii=False); return o
if sys.argv[1] == 'run':
    for V in ('D', 'D2'):
        for s in SCHEMES: sim(V, s)
for V in ('D', 'D2'):
    b = cache.get(f'{V}|BASE')
    if not b: continue
    print(f"\n== {V} 基线 年化 {b['cagr']*100:.1f}% 夏普 {b['sharpe']:.2f} 回撤 {b['mdd']*100:.1f}% (前 {b['mdd_pre']*100:.1f} 后 {b['mdd_post']*100:.1f}) 终值 {b['final']:.1f}x 水下最长 {b['uw']} 日 最差年 {b['worst_y']} {b['worst_year']*100:.1f}% 成交 {b['n']}")
    for s in ('H1', 'H2', 'P1', 'P2', 'P3', 'P4'):
        o = cache.get(f'{V}|{s}')
        if o: print(f"  {s} 年化 {o['cagr']*100:5.1f}% ({(o['cagr']-b['cagr'])*100:+.1f}) 夏普 {o['sharpe']:.2f} 回撤 {o['mdd']*100:6.1f}% ({(o['mdd']-b['mdd'])*100:+.1f}) 前 {o['mdd_pre']*100:.1f} 后 {o['mdd_post']*100:.1f} 水下 {o['uw']} 日 最差年 {o['worst_y']} {o['worst_year']*100:.1f}% 熔断 {o['halt_days']} 日({o['halt_days']/o['n_days']*100:.0f}%) 成交 {o['n']}")

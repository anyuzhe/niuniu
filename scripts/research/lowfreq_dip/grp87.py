"""grp87: 广度 / 波动 / 成交额状态变量过滤（预先登记见档案 §128）。
python grp87.py prep | events | run [V ...] | report"""
import os, sys, json, pickle, time
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
from dataclasses import replace
import numpy as np
from quantlab.dipbuy import fusion, industry
from quantlab.dipbuy.panel import Panel
mode = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
dates = np.array([str(d) for d in panel.dates]); nd, nc = panel.shape; years = np.array([int(d[:4]) for d in dates])
i18 = int(np.searchsorted(dates, '2018-01-01'))
raw_inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
FEAT = os.path.join(HERE, 'grp87_feat.npz')
if mode == 'prep':
    uni = raw_inp.cand.uni; c = panel.c; a = np.nan_to_num(panel.a, nan=0.0)
    def breadth(k):
        out = np.full(nd, np.nan)
        for t in range(k, nd):
            r = c[t] / c[t - k] - 1; m = uni[t] & np.isfinite(r)
            if m.sum() >= 100: out[t] = float((r[m] < 0).mean())
        return out
    br20, br5 = breadth(20), breadth(5)
    mret = raw_inp.market.mret; z = raw_inp.market.z
    def roll_std(x, k):
        o = np.full(nd, np.nan)
        for t in range(k - 1, nd): o[t] = np.std(x[t - k + 1:t + 1], ddof=1)
        return o
    s5, s60 = roll_std(mret, 5), roll_std(mret, 60)
    vol = s5 / s60
    amt = np.array([a[t][uni[t]].sum() for t in range(nd)])
    cs = np.cumsum(amt); a5 = np.full(nd, np.nan); a60 = np.full(nd, np.nan)
    a5[5:] = (cs[5:] - cs[:-5]) / 5; a60[60:] = (cs[60:] - cs[:-60]) / 60
    amtr = a5 / a60
    cm = np.cumsum(np.log1p(mret)); r5 = np.full(nd, np.nan); r5[5:] = np.expm1(cm[5:] - cm[:-5])
    spd = r5 / (s60 * np.sqrt(5))
    np.savez(FEAT, br20=br20, br5=br5, vol=vol, amt=amtr, spd=spd, z=z)
    for n, v in dict(br20=br20, br5=br5, vol=vol, amt=amtr, spd=spd).items(): print(n, 'valid', int(np.isfinite(v).sum()), 'mean %.3f' % np.nanmean(v), 'p10/50/90', np.nanpercentile(v, [10, 50, 90]).round(2))
    sys.exit()
F = np.load(FEAT)
RULES = {  # 名称: (变量, 方向, 阈值)
    'BR20>=70': ('br20', 1, .70), 'BR20>=80': ('br20', 1, .80), 'BR20>=90': ('br20', 1, .90),
    'BR5>=70': ('br5', 1, .70), 'BR5>=80': ('br5', 1, .80), 'BR5>=90': ('br5', 1, .90),
    'VOL>=1.0': ('vol', 1, 1.0), 'VOL>=1.25': ('vol', 1, 1.25), 'VOL>=1.5': ('vol', 1, 1.5),
    'AMT>=1.0': ('amt', 1, 1.0), 'AMT>=1.2': ('amt', 1, 1.2), 'AMT>=1.5': ('amt', 1, 1.5),
    'SPD<=-1.0': ('spd', -1, -1.0), 'SPD<=-1.5': ('spd', -1, -1.5), 'SPD<=-2.0': ('spd', -1, -2.0)}
def keep_of(name):
    v, d, th = RULES[name]; x = F[v]
    with np.errstate(invalid='ignore'):
        ok = (x >= th) if d == 1 else (x <= th)
    return np.where(np.isfinite(x), ok, True)          # 历史不足的日子不过滤
def split(eq):
    ok = np.isfinite(eq); idx = np.nonzero(ok)[0]; e = eq[idx]
    n0 = int((idx < i18).sum()); n1 = int((idx >= i18).sum()); pre = eq[i18 - 1] / e[0]; post = e[-1] / eq[i18 - 1]
    r = e[1:] / e[:-1] - 1
    yr = {}
    for y in range(2008, 2027):
        ii = np.nonzero((years == y) & ok)[0]
        if len(ii) > 5:
            b = eq[ii[0] - 1] if ii[0] > 0 and np.isfinite(eq[ii[0] - 1]) else eq[ii[0]]; yr[y] = float(eq[ii[-1]] / b - 1)
    return dict(cagr=float((e[-1] / e[0]) ** (245 / len(e)) - 1), sharpe=float(r.mean() / r.std() * np.sqrt(245)), mdd=float((e / np.maximum.accumulate(e) - 1).min()),
                final=float(e[-1] / e[0]), pre=float(pre ** (245 / n0) - 1), post=float(post ** (245 / n1) - 1), years=yr)
def ex15(eq):   # 去掉 2015 年后的年化：把 2015 年的日收益置 0
    ok = np.isfinite(eq); e = eq[ok]; yy = years[ok]; r = e[1:] / e[:-1] - 1; r = np.where(yy[1:] == 2015, 0.0, r)
    g = np.cumprod(1 + r); return float(g[-1] ** (245 / len(g)) - 1)
CACHE = os.path.join(HERE, 'grp87_cache.json'); cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
def sim(V, rule=None):
    key = f'{V}|{rule}'
    if key in cache: return cache[key]
    cfg = fusion.config_for(V)
    inp = fusion.with_industry_blacklist(fusion.with_near_high_filter(replace(raw_inp), cfg), cfg, cls)
    if rule:
        keep = keep_of(rule); gates = {k: v & keep for k, v in inp.gates.items()}
        inp = replace(inp, gates=gates, any_gate=gates['A'] | gates['C'] | gates['B'])
    raw = fusion.simulate_fused(panel, inp, cfg); o = split(raw['eq']); o['ex15'] = ex15(raw['eq'])
    o['gate_days'] = int(inp.any_gate[np.searchsorted(dates, '2008-01-01'):].sum()); o['n'] = len(raw['trades'])
    if rule is None:
        T = raw['trades']; sig = np.array([np.searchsorted(dates, str(t['signal'])) for t in T]); o['trades'] = [(int(s), float(t['ret'])) for s, t in zip(sig, T)]
    cache[key] = o; json.dump(cache, open(CACHE, 'w'), ensure_ascii=False); return o
if mode == 'events':
    b = sim('D'); sig = np.array([s for s, _ in b['trades']]); ret = np.array([r for _, r in b['trades']])
    mon = np.array([dates[s][:7] for s in sig])
    def mt(x, mo):    # 按月聚类的均值 t
        ms = sorted(set(mo)); m = np.array([x[mo == k].mean() for k in ms]); return len(x), float(x.mean()), float(m.mean() / (m.std(ddof=1) / np.sqrt(len(m)))) if len(m) > 2 else None
    print('D 基线成交', len(ret), '均值 %.2f%%' % (ret.mean() * 100))
    for name, (v, d, th) in RULES.items():
        x = F[v][sig]; ok = np.isfinite(x); keep = ((x >= th) if d == 1 else (x <= th)) & ok
        n1, m1, t1 = mt(ret[keep], mon[keep]) if keep.sum() > 5 else (int(keep.sum()), float('nan'), None); n0, m0, t0 = mt(ret[~keep & ok], mon[~keep & ok]) if (~keep & ok).sum() > 5 else (0, float('nan'), None)
        print(f"{name:10s} 满足 {n1:5d} 笔 均值 {m1*100:+5.2f}% (t {t1 if t1 is None else round(t1,1)}) | 不满足 {n0:5d} 笔 均值 {m0*100:+5.2f}%")
    print('与 z 的相关（所有交易日）：', {v: round(float(np.corrcoef(np.nan_to_num(F[v]), np.nan_to_num(F['z']))[0, 1]), 2) for v in ('br20', 'br5', 'vol', 'amt', 'spd')})
    print('闸门日里：', {v: round(float(np.corrcoef(F[v][ok_], F['z'][ok_])[0, 1]), 2) for v in ('br20', 'br5', 'vol', 'amt', 'spd') for ok_ in [np.isfinite(F[v]) & np.isfinite(F['z']) & (F['z'] <= -1.5)]})
elif mode == 'run':
    t0 = time.time()
    for V in (sys.argv[2:] or ['D', 'D2']):
        sim(V)
        for r in RULES:
            if time.time() - t0 > 100: print('time budget hit; rerun'); sys.exit()
            sim(V, r)
    print('done')
elif mode == 'report':
    for V in ('D', 'D2', 'D3', 'D4'):
        b = cache.get(f'{V}|None')
        if not b: continue
        print(f"\n== {V} 基线 {b['cagr']*100:.1f}% 夏普 {b['sharpe']:.2f} 回撤 {b['mdd']*100:.1f}% 终值 {b['final']:.1f}x  2018前 {b['pre']*100:.1f}% 后 {b['post']*100:.1f}%  去2015 {b['ex15']*100:.1f}%  闸门日 {b['gate_days']} 成交 {b['n']}")
        for r in RULES:
            o = cache.get(f'{V}|{r}')
            if not o: continue
            print(f"  {r:10s} {o['cagr']*100:5.1f}% ({(o['cagr']-b['cagr'])*100:+.1f}) 夏普 {o['sharpe']:.2f} 回撤 {o['mdd']*100:6.1f}% 前 {(o['pre']-b['pre'])*100:+5.1f} 后 {(o['post']-b['post'])*100:+5.1f} 去2015 {(o['ex15']-b['ex15'])*100:+5.1f}  闸门日 {o['gate_days']} ({o['gate_days']/b['gate_days']*100:.0f}%) 成交 {o['n']}")

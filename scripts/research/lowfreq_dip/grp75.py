"""grp75: 行业综合指数 250 日过滤 与 拉黑 7 个差行业 的区别：看各自拦掉了哪些 D 的 B 层成交。"""
import os, sys, json, collections
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
import numpy as np
from quantlab.dipbuy import industry
from quantlab.dipbuy.panel import Panel
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
c = panel.c.astype(np.float64); nd, nc = c.shape; dates = [str(d) for d in panel.dates]; di = {d: i for i, d in enumerate(dates)}
labels = np.asarray(cls.labels); names = cls.names; ng = len(names); nidx = {n: i for i, n in enumerate(names)}
retm = np.full((nd, nc), np.nan); retm[1:] = c[1:] / c[:-1] - 1
idx = np.ones((nd, ng))
for g in range(ng):
    cols = np.nonzero(labels == g)[0]
    if len(cols):
        with np.errstate(all='ignore'): r = np.nanmean(retm[:, cols], axis=1)
        idx[:, g] = np.cumprod(1 + np.nan_to_num(r, nan=0.0))
cs = np.cumsum(idx, axis=0); ma250 = np.full_like(idx, np.nan); ma250[249:] = (cs[249:] - np.vstack([np.zeros((1, ng)), cs[:-250]])) / 250
r250 = np.full_like(idx, np.nan); r250[250:] = idx[250:] / idx[:-250] - 1
BL = {'国防军工', '环保', '煤炭', '基础化工', '家用电器', '美容护理', '房地产'}
rows = json.load(open('grp73_rows.json'))
for V in ('D',):
    T = json.load(open(f'grp69_{V}.json'))['trades']
T = [t for t in T if di[t['signal']] >= 250]
def tag(t):
    g = nidx[t['ind']]; i = di[t['signal']]
    return dict(bl=t['ind'] in BL, ma=bool(idx[i, g] > ma250[i, g]), r250=bool(r250[i, g] >= 0), ret=t['ret'], ind=t['ind'], year=int(t['signal'][:4]))
R = [tag(t) for t in T]; n = len(R)
print('D 的 B 层成交（有 250 日历史）', n, '笔；平均', np.mean([r['ret'] for r in R]) * 100)
for lab, key in (('拉黑7个行业', 'bl'), ('指数在250日线之下', 'ma'), ('行业指数近250日<0', 'r250')):
    rem = [r for r in R if (r[key] if key == 'bl' else not r[key])]; kept = [r for r in R if r not in rem]
    print(f"{lab}: 拦掉 {len(rem)} 笔（{len(rem)/n*100:.0f}%），被拦掉的平均 {np.mean([r['ret'] for r in rem])*100:+.1f}%，留下 {len(kept)} 笔平均 {np.mean([r['ret'] for r in kept])*100:+.1f}%")
def ov(k1, k2):
    a = {id(r) for r in R if (r[k1] if k1 == 'bl' else not r[k1])}; b = {id(r) for r in R if (r[k2] if k2 == 'bl' else not r[k2])}
    return len(a & b), len(a), len(b)
for k in ('ma', 'r250'):
    x, a, b = ov('bl', k); print(f"拉黑7行业 ∩ {k}过滤：共同拦掉 {x} 笔；拉黑拦 {a} 笔里被趋势过滤也拦的占 {x/a*100:.0f}%；趋势过滤拦 {b} 笔里属于7个行业的占 {x/b*100:.0f}%")
print('--- 7 个行业的成交里，趋势过滤放行的比例 / 其余行业被趋势过滤拦掉的比例（r250>=0 规则）')
bl = [r for r in R if r['bl']]; ot = [r for r in R if not r['bl']]
print('7个行业 放行', np.mean([r['r250'] for r in bl]).round(2), '平均收益(放行/被拦)', np.mean([r['ret'] for r in bl if r['r250']])*100, np.mean([r['ret'] for r in bl if not r['r250']])*100)
print('其余行业 放行', np.mean([r['r250'] for r in ot]).round(2), '平均收益(放行/被拦)', np.mean([r['ret'] for r in ot if r['r250']])*100, np.mean([r['ret'] for r in ot if not r['r250']])*100)
print('--- 各行业成交被趋势过滤(r250>=0)拦掉的比例，最高的 12 个')
by = collections.defaultdict(list)
for r in R: by[r['ind']].append(r)
for k, v in sorted(by.items(), key=lambda kv: -np.mean([not r['r250'] for r in kv[1]]))[:12]:
    if len(v) >= 10: print(f"  {k:6s} n={len(v):3d} 拦掉{np.mean([not r['r250'] for r in v])*100:3.0f}% 平均收益 {np.mean([r['ret'] for r in v])*100:+5.1f}% {'(在黑名单)' if k in BL else ''}")
print('--- 7 个行业各自被拦掉的比例')
for k in sorted(BL):
    v = by.get(k, [])
    if v: print(f"  {k:6s} n={len(v):3d} 被趋势过滤拦掉{np.mean([not r['r250'] for r in v])*100:3.0f}% 平均收益 {np.mean([r['ret'] for r in v])*100:+5.1f}%")

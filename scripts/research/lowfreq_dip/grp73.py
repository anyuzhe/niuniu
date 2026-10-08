"""grp73: 验证“差行业为什么差”的几个假说（D 的 B 层成交，grp69_D.json）：
H1 账户亏损来自个股（相对行业的超额）还是行业本身继续跌；
H2 题材退潮：触发前行业指数离 500 日高点多远、此前 250 日涨幅；
H3 个股脆弱：小市值/低流动性、后来退市；
H4 亏损集中在哪些年份/段。"""
import os, sys, json, pickle
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
import numpy as np
from quantlab.dipbuy import industry
from quantlab.dipbuy.panel import Panel
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
c, o, a = panel.c.astype(np.float64), panel.o.astype(np.float64), panel.a.astype(np.float64)
nd, nc = c.shape; dates = [str(d) for d in panel.dates]; di = {d: i for i, d in enumerate(dates)}
labels = np.asarray(cls.labels); names = cls.names; code_j = {str(x): j for j, x in enumerate(panel.codes)}
BAD = ['国防军工', '环保', '煤炭', '基础化工', '家用电器', '美容护理']; RE = ['房地产']
GOOD = ['计算机', '医药生物', '有色金属', '公用事业', '食品饮料', '农林牧渔', '电子', '银行']
def grp_of(n): return '差6' if n in BAD else '房地产' if n in RE else '好8' if n in GOOD else '其余'
# 行业等权指数（日收益 = 成员收益均值）
ret = np.full((nd, nc), np.nan); ret[1:] = c[1:] / c[:-1] - 1
ng = len(names); idx = np.ones((nd, ng)); 
for g in range(ng):
    cols = np.nonzero(labels == g)[0]
    if not len(cols): continue
    with np.errstate(all='ignore'): r = np.nanmean(ret[:, cols], axis=1)
    r = np.nan_to_num(r, nan=0.0); idx[:, g] = np.cumprod(1 + r)
last_valid = np.array([np.nonzero(np.isfinite(c[:, j]))[0].max() if np.isfinite(c[:, j]).any() else -1 for j in range(nc)])
rows = []
for tr in json.load(open('grp69_D.json'))['trades']:
    t = di[tr['signal']]; j = code_j[tr['code']]; g = int(labels[j])
    if t < 510 or t + 61 >= nd: continue
    e = t + 1; x = t + 21
    ent = o[e, j]
    # 行业同窗口（等权指数）收益：从 t+1 开盘近似用 t 收盘，到 t+21 收盘
    ind20 = idx[x, g] / idx[t, g] - 1; ind60 = idx[t + 61, g] / idx[t, g] - 1 if t + 61 < nd else np.nan
    f = dict(ind=names[g], grp=grp_of(names[g]), signal=tr['signal'], year=int(tr['signal'][:4]), ret=tr['ret'], ind20=ind20, ind60=ind60,
             excess=tr['ret'] - ind20,
             dd500=idx[t, g] / idx[t - 499:t + 1, g].max() - 1,         # 离 500 日高点
             run_prev=idx[t - 250, g] / idx[t - 500, g] - 1,            # 触发前第 2 年的涨幅（此前有没有大涨）
             r250=idx[t, g] / idx[t - 250, g] - 1,
             adv=float(np.nanmean(a[t - 19:t + 1, j])), px=float(c[t, j]),
             delist1y=bool(last_valid[j] < min(nd - 1, t + 250) and last_valid[j] < nd - 5))
    rows.append(f)
json.dump(rows, open('grp73_rows.json', 'w'), ensure_ascii=False)
print('rows', len(rows))
import collections
def summ(R, label):
    if not R: return
    g = lambda k: np.array([r[k] for r in R], float)
    print(f"{label:6s} n={len(R):4d} 账户均值{g('ret').mean()*100:+6.1f}% 胜率{(g('ret')>0).mean()*100:4.0f}% | 行业20日{np.nanmean(g('ind20'))*100:+5.1f}% 行业60日{np.nanmean(g('ind60'))*100:+5.1f}% 行业20日<0占{(g('ind20')<0).mean()*100:3.0f}% | 个股超额(中位){np.median(g('excess'))*100:+5.1f}% 均值{g('excess').mean()*100:+5.1f}% | 离500日高点{np.median(g('dd500'))*100:+5.0f}% 前年涨幅{np.median(g('run_prev'))*100:+5.0f}% 行业250日{np.median(g('r250'))*100:+5.0f}% | 日均成交额中位{np.median(g('adv'))/1e8:5.2f}亿 价格{np.median(g('px')):5.1f} 一年内退市{np.mean([r['delist1y'] for r in R])*100:3.0f}%")
print('--- 分组'); 
for gname in ('差6', '房地产', '其余', '好8'): summ([r for r in rows if r['grp'] == gname], gname)
print('--- 分行业（账户均值从低到高）')
byi = collections.defaultdict(list)
for r in rows: byi[r['ind']].append(r)
for k, v in sorted(byi.items(), key=lambda kv: np.mean([r['ret'] for r in kv[1]])):
    if len(v) >= 15: summ(v, k)
print('--- 差6+房地产：亏损按年份')
bad = [r for r in rows if r['grp'] in ('差6', '房地产')]
by = collections.defaultdict(list)
for r in bad: by[r['year']].append(r['ret'])
tot = sum(sum(v) for v in by.values())
for y in sorted(by): print(y, len(by[y]), f"均值{np.mean(by[y])*100:+.1f}% 贡献{sum(by[y])/tot*100:5.1f}%")
print('--- 差6+房地产：亏损笔(<-15%)的特征 vs 其余笔')
L = [r for r in bad if r['ret'] < -0.15]; W = [r for r in bad if r['ret'] >= -0.15]
summ(L, '大亏'); summ(W, '其余')
print('大亏笔占比', len(L) / len(bad), '大亏笔对总亏损贡献', sum(r['ret'] for r in L) / sum(r['ret'] for r in bad if r['ret'] < 0))
print('--- 行业继续跌 vs 个股问题：差6+房地产里，行业20日<0 的笔 vs >=0 的笔')
summ([r for r in bad if r['ind20'] < 0], '行业跌'); summ([r for r in bad if r['ind20'] >= 0], '行业涨')
print('--- 全部B笔按离500日高点分三档')
dd = np.array([r['dd500'] for r in rows]); q = np.quantile(dd, [1/3, 2/3])
for lab, m in (('最深', dd <= q[0]), ('中', (dd > q[0]) & (dd <= q[1])), ('最浅', dd > q[1])): summ([r for r, k in zip(rows, m) if k], lab)
print('--- 全部B笔按行业前年涨幅分三档（题材退潮：此前涨多的）')
rp = np.array([r['run_prev'] for r in rows]); q = np.quantile(rp, [1/3, 2/3])
for lab, m in (('前年跌', rp <= q[0]), ('前年平', (rp > q[0]) & (rp <= q[1])), ('前年涨', rp > q[1])): summ([r for r, k in zip(rows, m) if k], lab)

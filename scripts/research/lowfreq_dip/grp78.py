"""grp78: 同一个行业触发日，账户挑的股票 vs 行业其他股票：拆 E6 候选池效应和排序效应。"""
import os, sys, json, pickle, collections
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
import numpy as np, pandas as pd
from quantlab.dipbuy import industry
from quantlab.dipbuy.panel import Panel
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
nd, nc = panel.shape; dates = [str(d) for d in panel.dates]; di = {d: i for i, d in enumerate(dates)}
labels = np.asarray(cls.labels); names = cls.names; nidx = {n: i for i, n in enumerate(names)}
c = panel.c.astype(np.float64); o = panel.o.astype(np.float64)
cf = pd.DataFrame(c).ffill().to_numpy()           # 退市后用最后收盘价（不丢掉亏损）
pool = inp.pools['B'] & inp.buyok; uni = inp.cand.uni; rank = inp.rank
BAD = ['国防军工','环保','煤炭','基础化工','家用电器','美容护理','房地产']; GOOD = ['计算机','医药生物','有色金属','公用事业','食品饮料','农林牧渔','电子','银行']
R = json.load(open('grp71_indlevel.json')); T = json.load(open('grp69_D.json'))['trades']
traded = collections.defaultdict(list)
for tr in T: traded[(di[tr['signal']], nidx[tr['ind']])].append(tr)
rng = np.random.default_rng(0)
def fwd(t, js):
    ent = o[t + 1, js]; ex = cf[t + 20, js]; ok = np.isfinite(ent) & (ent > 0) & np.isfinite(ex)
    return np.where(ok, ex / ent - 1, np.nan)
out = collections.defaultdict(lambda: collections.defaultdict(list))
for r in R:
    t, g = r['t'], r['g']
    if t < 130 or t + 21 >= nd: continue
    nm = r['ind']; grp = '差7' if nm in BAD else '好8' if nm in GOOD else '其余'
    cols = np.nonzero(labels == g)[0]
    allm = cols[uni[t, cols] & np.isfinite(o[t + 1, cols])]; pl = cols[pool[t, cols]]
    if len(allm) < 5 or len(pl) < 3: continue
    fa = np.nanmean(fwd(t, allm)); fp = np.nanmean(fwd(t, pl))
    ordr = pl[np.argsort(rank[t, pl], kind='stable')]
    k = 10
    ftop = np.nanmean(fwd(t, ordr[:k])); fbot = np.nanmean(fwd(t, ordr[-k:])); frand = np.nanmean(fwd(t, rng.choice(pl, min(k, len(pl)), replace=False)))
    rec = dict(all=fa, pool=fp, top=ftop, bot=fbot, rand=frand)
    if (t, g) in traded: rec['acct'] = np.mean([x['ret'] for x in traded[(t, g)]])
    for kk, vv in rec.items(): out[grp][kk].append(vv)
    if 'acct' in rec:
        for kk, vv in rec.items(): out[grp + '·买了'][kk].append(vv)
    out['全部'] = out['全部']
print('同一触发日里 20 日平均收益（各触发日等权）：行业全部可买成员 / E6 候选池 / 候选池按20日跌幅最大的10只(D的排序) / 候选池随机10只 / 候选池里跌得最少的10只')
for grp in ('差7', '好8', '其余'):
    d = out[grp]; n = len(d['all'])
    print(f"{grp} (触发日 {n}): 全成员 {np.nanmean(d['all'])*100:+.2f}% | E6候选池 {np.nanmean(d['pool'])*100:+.2f}% | 跌最多10只 {np.nanmean(d['top'])*100:+.2f}% | 随机10只 {np.nanmean(d['rand'])*100:+.2f}% | 跌最少10只 {np.nanmean(d['bot'])*100:+.2f}%")
print('\n账户真正买了的那些触发日（同日比较）')
for grp in ('差7', '好8', '其余'):
    d = out[grp + '·买了']; n = len(d['acct'])
    if n: print(f"{grp} (触发日 {n}): 全成员 {np.nanmean(d['all'])*100:+.2f}% | E6候选池 {np.nanmean(d['pool'])*100:+.2f}% | 跌最多10只 {np.nanmean(d['top'])*100:+.2f}% | 随机10只 {np.nanmean(d['rand'])*100:+.2f}% | 跌最少10只 {np.nanmean(d['bot'])*100:+.2f}% | 账户实际 {np.nanmean(d['acct'])*100:+.2f}%")

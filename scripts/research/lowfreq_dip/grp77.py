"""grp77: 为什么账户在差行业买到的那几段偏差？把每个“行业触发日”按账户能不能买分成四类：
 A 没有候选（该行业当天没有满足 E6 且可买的股票）；B 有候选但 B 层名额已满；C 有候选、有名额，但没买成（资金上限 / 已持有）；D 买了。
再比较各类触发日里行业后续 20 日收益（grp71_indlevel 的 fwd，行业全成员）。"""
import os, sys, json, pickle, collections
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
import numpy as np
from quantlab.dipbuy import industry
from quantlab.dipbuy.panel import Panel
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
nd, nc = panel.shape; dates = [str(d) for d in panel.dates]; di = {d: i for i, d in enumerate(dates)}
labels = np.asarray(cls.labels); names = cls.names; nidx = {n: i for i, n in enumerate(names)}
code_j = {str(x): j for j, x in enumerate(panel.codes)}
BAD = ['国防军工','环保','煤炭','基础化工','家用电器','美容护理','房地产']; GOOD = ['计算机','医药生物','有色金属','公用事业','食品饮料','农林牧渔','电子','银行']
T = json.load(open('grp69_D.json'))['trades']
Bt = [(di[t['signal']], t['ind']) for t in T]
nact = np.zeros(nd, int)
for s, _ in Bt: nact[s + 1:min(nd, s + 22)] += 1          # 持有 20 日左右
traded = {(s, nidx[i]) for s, i in Bt}
R = json.load(open('grp71_indlevel.json'))
pool = inp.pools['B'] & inp.buyok
ncand_cache = {}
def ncand(t, g):
    cols = np.nonzero(labels == g)[0]; return int(pool[t, cols].sum())
cat = collections.defaultdict(lambda: collections.defaultdict(list))
for r in R:
    t, g = r['t'], r['g']; nm = r['ind']; grp = '差7' if nm in BAD else '好8' if nm in GOOD else '其余'
    k = ncand(t, g)
    if (t, g) in traded: c = 'D 买了'
    elif k == 0: c = 'A 没有E6候选'
    elif nact[t] >= 20: c = 'B 候选有但B层名额满'
    else: c = 'C 候选有名额有但没买成'
    cat[grp][c].append((r['fwd'], k, r['z']))
print('触发日分类（行业全成员后续20日平均收益）')
for grp in ('差7', '好8', '其余'):
    tot = sum(len(v) for v in cat[grp].values())
    print(f'-- {grp}（触发日 {tot}）')
    for c in sorted(cat[grp]):
        v = cat[grp][c]; print(f"   {c:22s} {len(v):5d} 个 ({len(v)/tot*100:4.1f}%)  行业后续20日 {np.mean([x[0] for x in v])*100:+5.1f}%  平均候选数 {np.mean([x[1] for x in v]):4.1f}  行业z均值 {np.mean([x[2] for x in v]):+.2f}")
print('\n--- “有 E6 候选”的触发日 vs “没有候选”的触发日（不管买没买）')
for grp in ('差7', '好8', '其余'):
    has = [x[0] for c, v in cat[grp].items() if not c.startswith('A') for x in v]; no = [x[0] for x in cat[grp].get('A 没有E6候选', [])]
    print(f"{grp}: 有候选 {len(has)} 个 平均{np.mean(has)*100:+.1f}% | 没有候选 {len(no)} 个 平均{np.mean(no)*100:+.1f}%")
print('\n--- 每个段的第一个触发日与“第一个有E6候选的日子”相隔几天，以及该日行业此前5日涨跌')

import json, numpy as np, collections
R = json.load(open('grp71_indlevel.json'))
BAD = ['国防军工', '环保', '煤炭', '基础化工', '家用电器', '美容护理']; GOOD = ['计算机', '医药生物', '有色金属', '公用事业', '食品饮料', '农林牧渔', '电子', '银行']
def grp(n): return '差6' if n in BAD else '房地产' if n == '房地产' else '好8' if n in GOOD else '其余'
by = collections.defaultdict(list)
for r in R: by[r['ind']].append(r)
out = collections.defaultdict(lambda: collections.defaultdict(list))
for ind, rs in by.items():
    rs.sort(key=lambda r: r['t']); start = None; prev = None
    for r in rs:
        if prev is None or r['t'] - prev > 25: start = r['t']
        k = r['t'] - start; b = '第0-4天' if k <= 4 else '第5-19天' if k <= 19 else '20天后'
        out[grp(ind)][b].append(r['fwd']); prev = r['t']
for g in ('差6', '房地产', '其余', '好8'):
    print(g, ' '.join(f"{b}: n={len(out[g][b])} 行业20日{np.mean(out[g][b])*100:+.1f}%" for b in ('第0-4天', '第5-19天', '20天后') if out[g][b]))

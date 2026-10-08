import os, sys, json, numpy as np, collections
BAD = ["国防军工","环保","煤炭","基础化工","家用电器","美容护理"]
GOOD = ["计算机","医药生物","有色金属","公用事业","食品饮料","农林牧渔","电子","银行"]
def grp(n): return "差6" if n in BAD else "房地产" if n=="房地产" else "好8" if n in GOOD else "其余"
rows = json.load(open('grp73_rows.json')); R = json.load(open('grp71_indlevel.json'))
key = {(r['date'], r['ind']): r for r in R}
# 每个行业的段起点
by = collections.defaultdict(list)
for r in R: by[r['ind']].append(r)
kday = {}
for ind, rs in by.items():
    rs.sort(key=lambda r: r['t']); start = None; prev = None
    for r in rs:
        if prev is None or r['t'] - prev > 25: start = r['t']
        kday[(r['date'], ind)] = r['t'] - start; prev = r['t']
for g in ('差6', '房地产', '其余', '好8'):
    T = [r for r in rows if r['grp'] == g]; hit = [(r, key.get((r['signal'], r['ind']))) for r in T]
    hit = [(r, k) for r, k in hit if k]
    print(g, f"交易{len(T)} 能对上触发日{len(hit)} | 用等权指数算的行业20日 {np.mean([r['ind20'] for r,_ in hit])*100:+.1f}% | 用触发日全成员算的 {np.mean([k['fwd'] for _,k in hit])*100:+.1f}% | 该行业全部触发日均值 {np.mean([k['fwd'] for k in R if grp(k['ind'])==g])*100 if False else 0:.0f}")
    ks = np.array([kday[(r['signal'], r['ind'])] for r, _ in hit]); print('   买入日在段内第几天: 中位', np.median(ks), '第0天占', (ks == 0).mean().round(2), '0-4天占', (ks <= 4).mean().round(2))
    for lab, m in (('第0天', ks == 0), ('1-4天', (ks >= 1) & (ks <= 4)), ('5天后', ks >= 5)):
        if m.sum(): print(f"   {lab}: 交易{m.sum()} 账户均值{np.mean([hit[i][0]['ret'] for i in np.nonzero(m)[0]])*100:+.1f}% 触发日全成员20日{np.mean([hit[i][1]['fwd'] for i in np.nonzero(m)[0]])*100:+.1f}%")

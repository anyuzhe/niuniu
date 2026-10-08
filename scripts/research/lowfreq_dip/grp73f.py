import json, numpy as np, collections
rows = json.load(open('grp73_rows.json'))
BAD = ["国防军工","环保","煤炭","基础化工","家用电器","美容护理"]; GOOD = ["计算机","医药生物","有色金属","公用事业","食品饮料","农林牧渔","电子","银行"]
def grp(n): return "差6" if n in BAD else "房地产" if n=="房地产" else "好8" if n in GOOD else "其余"
by = collections.defaultdict(list)
for r in rows: by[r['ind']].append(r)
eps = []
for ind, rs in by.items():
    rs.sort(key=lambda r: r['signal']); cur = []
    for r in rs:
        if cur and (np.datetime64(r['signal']) - np.datetime64(cur[-1]['signal'])).astype(int) > 25: eps.append((ind, cur)); cur = []
        cur.append(r)
    if cur: eps.append((ind, cur))
for g in ('差6', '房地产', '其余', '好8'):
    E = [(i, e) for i, e in eps if grp(i) == g]; m = np.array([np.mean([r['ret'] for r in e]) for _, e in E]); n = np.array([len(e) for _, e in E])
    print(g, f"有成交的段 {len(E)} 个，每段平均 {n.mean():.1f} 笔；按段平均账户收益 {m.mean()*100:+.1f}%（中位 {np.median(m)*100:+.1f}%），亏损段占 {np.mean(m<0)*100:.0f}%；按笔加权 {np.average(m, weights=n)*100:+.1f}%")
print('差6+房地产 最差的段：')
E = [(i, e) for i, e in eps if grp(i) in ('差6','房地产')]
for i, e in sorted(E, key=lambda ie: np.mean([r['ret'] for r in ie[1]]))[:10]:
    print(f"  {i} {e[0]['signal']} 起 {len(e)} 笔 平均{np.mean([r['ret'] for r in e])*100:+.1f}% 行业20日{np.mean([r['ind20'] for r in e])*100:+.1f}%")

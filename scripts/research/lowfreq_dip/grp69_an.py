import json, sys, numpy as np
from collections import defaultdict
V = sys.argv[1]
T = json.load(open(f'grp69_{V}.json'))['trades']
by = defaultdict(list)
for r in T: by[r['ind']].append(r)
allm = np.mean([r['ret'] for r in T]); print(f'===== {V}  B 层成交 {len(T)} 笔  总体单笔均值 {allm*100:+.2f}%  胜率 {np.mean([r["ret"]>0 for r in T])*100:.0f}%')
def episodes(rs):
    ds = sorted({r['signal'] for r in rs}); eps = []; cur = [ds[0]]
    for d in ds[1:]:
        if (np.datetime64(d) - np.datetime64(cur[-1])).astype(int) > 25: eps.append(cur); cur = [d]
        else: cur.append(d)
    eps.append(cur)
    out = []
    for e in eps:
        s = set(e); out.append((e[0], np.mean([r['ret'] for r in rs if r['signal'] in s])))
    return out
rng = np.random.default_rng(7); rows = []
for ind, rs in by.items():
    ep = episodes(rs); em = np.array([m for _, m in ep])
    if len(em) >= 2:
        bs = [rng.choice(em, len(em)).mean() for _ in range(2000)]; lo, hi = np.percentile(bs, [5, 95])
    else: lo = hi = em.mean()
    rets = np.array([r['ret'] for r in rs])
    early = [m for d, m in ep if d < '2018-01-01']; late = [m for d, m in ep if d >= '2018-01-01']
    rows.append((ind, len(rs), len(ep), rets.mean(), em.mean(), (rets > 0).mean(), lo, hi, np.mean(early) if early else np.nan, len(early), np.mean(late) if late else np.nan, len(late)))
rows.sort(key=lambda x: x[4])
print(f'{"行业":8s} {"成交":>4s} {"段数":>4s} {"单笔均值":>7s} {"按段均值":>7s} {"胜率":>5s} {"按段90%区间":>16s} | {"2018前":>7s}({"段":>2s}) {"2018后":>7s}({"段":>2s})')
f = lambda x: '   —  ' if not np.isfinite(x) else f'{x*100:+6.1f}%'
for r in rows:
    print(f'{r[0]:8s} {r[1]:4d} {r[2]:4d} {f(r[3])} {f(r[4])} {r[5]*100:4.0f}% [{r[6]*100:+6.1f}%,{r[7]*100:+6.1f}%] | {f(r[8])}({r[9]:2d}) {f(r[10])}({r[11]:2d})')
# 样本外：用 2018 前的段均值排最差 5 个行业（至少 3 段），看它们 2018 后的表现 vs 其余行业
pre = {}
for ind, rs in by.items():
    ep = [m for d, m in episodes(rs) if d < '2018-01-01']
    if len(ep) >= 3: pre[ind] = np.mean(ep)
worst = [k for k, _ in sorted(pre.items(), key=lambda kv: kv[1])[:5]]
post = lambda inds, neg=False: [r['ret'] for r in T if r['signal'] >= '2018-01-01' and ((r['ind'] in inds) != neg)]
print('\n样本外：用 2018 年前挑出最差的 5 个行业', worst)
print(f'  它们 2018 后 {len(post(worst))} 笔，单笔均值 {np.mean(post(worst))*100:+.2f}%；其余行业 {len(post(worst, True))} 笔，单笔均值 {np.mean(post(worst, True))*100:+.2f}%')
json.dump(dict(rows=[list(map(lambda x: x if isinstance(x, str) else float(x), r)) for r in rows], worst_pre2018=worst), open(f'grp69_an_{V}.json', 'w'), ensure_ascii=False)

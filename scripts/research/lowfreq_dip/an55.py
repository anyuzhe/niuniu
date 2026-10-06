import json, numpy as np, sys
R = json.load(open(sys.argv[1]))
def name(a):
    p = [f'{t}平{v}' for t, v in zip('ACB', a[:3]) if v]; return ' '.join(p) if p else '基线'
for c in (0.0, 0.003):
    rs = [r for r in R if r['a'][3] == c]; b = next(r for r in rs if r['a'][:3] == ['', '', ''])
    print(f'\n=== 额外卖出成本 {c*1e4:.0f}bp  基线 年化{b["s"][0]*100:.1f}% 夏普{b["s"][1]:.2f} 回撤{b["s"][2]*100:.0f}% | {len(rs)} 种')
    print(f'{"规则":18s} 年化   夏普  回撤  前半   后半  平均仓位 平仓笔  分年胜/负')
    yb = np.array(b['eqy']); yb = yb[1:] / yb[:-1] - 1
    by = sorted(rs, key=lambda r: -r['s'][1])
    for r in by[:10] + by[-3:]:
        ey = np.array(r['eqy']); y = ey[1:] / ey[:-1] - 1; d = y - yb
        print(f'{name(r["a"]):18s} {r["s"][0]*100:5.1f}% {r["s"][1]:.2f} {r["s"][2]*100:4.0f}% {r["s"][3]*100:5.1f}% {r["s"][4]*100:5.1f}%  {r["s"][5]*100:4.0f}%  {r["n"]:6d}  {int((d>.0005).sum())}/{int((d<-.0005).sum())}')
    sh = np.array([r['s'][1] for r in rs])
    print(f'夏普中位 {np.median(sh):.2f}; 优于基线 {np.mean(sh > b["s"][1]+.005)*100:.0f}%')
    for t, i in (('A', 0), ('C', 1), ('B', 2)):
        print(f'  {t} 层平仓集合 平均夏普:', {(v or "无"): round(float(np.mean([r["s"][1] for r in rs if r["a"][i] == v])), 3) for v in sorted({r["a"][i] for r in rs})})

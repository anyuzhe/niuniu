import json, sys, numpy as np
V = sys.argv[1]
d = json.load(open(f'grp64_{V}.json')); cells = d['cells']; b = d['base']
print(f'===== {V} 基线 {b["cagr"]*100:.1f}% / 夏普 {b["sh"]:.2f} / 回撤 {b["dd"]*100:.0f}%   共 {len(cells)} 个组合')
def table(fam, key, scale, fmt, title):
    cs = [c for c in cells if c['fam'] == fam]; Ws = sorted({c['W'] for c in cs}); Xs = sorted({c['X'] for c in cs})
    print(f'\n[{fam}] {title}   行=窗口(日)  列=阈值')
    print('W\\X   ' + ' '.join(f'{x:>7.2f}' for x in Xs))
    for W in Ws:
        row = []
        for X in Xs:
            c = next((c for c in cs if c['W'] == W and c['X'] == X), None)
            row.append(fmt.format(c[key] * scale) if c else '     —')
        print(f'{W:>5} ' + ' '.join(f'{r:>7}' for r in row))
for fam in ('near_high', 'above_ma', 'pctile'):
    table(fam, 'gain', 100, '{:+.1f}', '年化变化（点）')
table('near_high', 'nmask', 1, '{:.0f}', '少用的闸门日')
table('near_high', 'z', 1, '{:+.1f}', '相对随机关同数量闸门日的 z')
table('near_high', 'drop2', 100, '{:+.0f}', '去掉最好的两年后累计对数收益变化（点）')
g = [c for c in cells]
print('\n全部组合：年化变化>0 的 %d/%d；z>2 的 %d；z<-2 的 %d' % (sum(c['gain'] > 0 for c in g), len(g), sum(c['z'] > 2 for c in g), sum(c['z'] < -2 for c in g)))
rob = [c for c in g if c['gain'] > 0 and c['drop2'] > 0 and c['early'] >= 0 and c['late'] > 0]
print('稳健判据（年化变好 + 去掉最好两年仍为正 + 2008–2019 不亏 + 2020 后为正）：%d 个' % len(rob))
for c in sorted(rob, key=lambda c: -c['drop2'])[:12]:
    print(f"  {c['fam']:9s} W={c['W']:>4} X={c['X']:<5} 年化{c['cagr']*100:+.1f}% (变化{c['gain']*100:+.1f}) 夏普{c['sh']:.2f} 回撤{c['dd']*100:.0f}% 少用{c['nmask']}天 z={c['z']:+.1f} 去2年后{c['drop2']*100:+.0f} 早{c['early']*100:+.0f} 晚{c['late']*100:+.0f} 赢{c['wins']}输{c['losses']}")
print('\n年化变化最大的 8 个：')
for c in sorted(g, key=lambda c: -c['gain'])[:8]:
    print(f"  {c['fam']:9s} W={c['W']:>4} X={c['X']:<5} 年化{c['cagr']*100:+.1f}% (变化{c['gain']*100:+.1f}) 少用{c['nmask']}天 z={c['z']:+.1f} 去2年后{c['drop2']*100:+.0f} 早{c['early']*100:+.0f} 晚{c['late']*100:+.0f} 赢{c['wins']}输{c['losses']}")

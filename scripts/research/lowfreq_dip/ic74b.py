import numpy as np, lib74 as Y
R = np.load('rows74.npy'); cols = ['t','j','A','B','C'] + Y.FN + ['y']; D = {c: R[:, i] for i, c in enumerate(cols)}
t = D['t'].astype(int); y = D['y']
def rank_ic(x, y, t, mask):
    ics = []
    for d in np.unique(t[mask]):
        m = mask & (t == d); xs, ys = x[m], y[m]; ok = np.isfinite(xs) & np.isfinite(ys)
        if ok.sum() < 15: continue
        a = np.argsort(np.argsort(xs[ok])); b = np.argsort(np.argsort(ys[ok])); ics.append(np.corrcoef(a, b)[0, 1])
    ics = np.array(ics); return ics.mean(), ics.mean() / (ics.std() / np.sqrt(len(ics)) + 1e-12), len(ics)
for nm, mask in (('C 层候选', D['C'] == 1), ('只在 B 层（不在 C）', (D['B'] == 1) & (D['C'] == 0)), ('全部', np.ones(len(t), bool))):
    print(f'=== {nm}: 行数 {int(mask.sum())}，平均净收益 {np.nanmean(y[mask])*1e4:+.0f}bp')
    for f in Y.FN:
        ic, tv, n = rank_ic(D[f], y, t, mask)
        # quintile spread within day: top vs bottom quintile of feature
        print(f'  {f:9s} 日内秩相关 {ic:+.3f}  (t≈{tv:+.1f}, {n} 天)')

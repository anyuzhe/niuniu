"""Practical overlay: defensive sleeve (gold + 10y bond 1/2) takes only D's idle capital, but is re-sized only when the target moves more than a band. Research only."""
exec(open('grp40.py').read().split("for uname")[0])
g, b = ret('sh.518880'), ret('sh.511260')
gb = 0.5 * np.nan_to_num(g) + 0.5 * np.nan_to_num(b); gb[~(np.isfinite(g) & np.isfinite(b))] = np.nan
v = np.isfinite(rD) & np.isfinite(ex) & np.isfinite(gb)
print(f'窗口 {dates[np.nonzero(v)[0][0]]} ~ {dates[np.nonzero(v)[0][-1]]}', flush=True)
stat(rD + idle * CY, v, 'D 单独（闲置 2%）')
def run(k, band, cap=1.0, buffer=0.0):
    a = np.zeros(nd); cur = 0.0; trades = 0
    for t in range(nd):
        tgt = min(cap, max(0.0, k * (idle[t] - buffer)))
        # D needs cash first: if the current sleeve exceeds what is idle, cut immediately to idle (priority to D)
        if cur > idle[t] - buffer: cur = tgt; trades += 1
        elif abs(tgt - cur) > band: cur = tgt; trades += 1
        a[t] = cur
    da = np.abs(np.diff(np.r_[0, a]))
    tot = rD + a * np.nan_to_num(gb) - COST * da + (idle - a) * CY
    return tot, trades, a
for k, band, buffer in ((1.0, 0.0, 0.0), (1.0, 0.1, 0.0), (1.0, 0.2, 0.0), (1.0, 0.1, 0.1), (1.0, 0.2, 0.2), (0.5, 0.1, 0.0), (0.5, 0.2, 0.0), (0.7, 0.1, 0.1)):
    tot, n, a = run(k, band, buffer=buffer)
    yrs = (np.count_nonzero(v)) / 245
    stat(tot, v, f'占闲置 {k*100:.0f}%，偏离超 {band*100:.0f}% 才调，留 {buffer*100:.0f}% 缓冲（年调仓 {n/yrs:.0f} 次，平均占 {a[v].mean()*100:.0f}%）')

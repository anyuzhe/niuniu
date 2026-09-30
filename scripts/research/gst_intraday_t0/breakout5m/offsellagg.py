"""Summary of offsell.npz: stock-by-stock 先卖后买 on days the 10:30 model predicts an afternoon drop (research only)."""
import numpy as np, os
H = os.environ['HOME']; B = f'{H}/research/brk'
R = np.load(f'{B}/offsell.npz'); d = R['date']; bp = R['bp']; skip = R['skip']; nxt = R['nextopen']; beta = R['beta']; price = R['price']
yr = np.array([x[:4] for x in d]); YRS = ['2021', '2022', '2023', '2024', '2025', '2026']
M = {}
for name, f in (('正式情绪模型', 'offpred.npz'), ('样本模型', 'mfpred.npz')):
    P = np.load(f'{B}/{f}', allow_pickle=True); mp = dict(zip(P['date'].astype(str), P['pred'])); my = dict(zip(P['date'].astype(str), P['y']))
    M[name] = (np.array([mp.get(x, np.nan) for x in d]), my)


def st(m):
    v = bp[m]; n = len(v)
    if n < 30: return None
    u, inv = np.unique(d[m], return_inverse=True); mu = v.mean()
    se = np.sqrt((np.bincount(inv, v - mu) ** 2).sum()) / n
    w = v > 0; pay = v[w].mean() / -v[~w].mean()
    daym = np.bincount(inv, v) / np.bincount(inv)
    return dict(n=n, days=len(u), bp=mu, t=mu / se, win=w.mean() * 100, pay=pay, dpos=(daym > 0).mean() * 100)


base = st(~skip)
print(f'不看信号、每天都先卖后买：{base["n"]:,} 笔，每笔 {base["bp"]:+.1f} bp（胜率 {base["win"]:.0f}%）')
for name, (pred, my) in M.items():
    print(f'\n【{name}】10:30 预测下午大盘跌幅 ≥ 门槛的日子，样本内全部股票逐只先卖、收盘买回（万1免五 7.2bp + 每边 1 个价位）')
    for thr in (0.001, 0.002, 0.003, 0.005):
        sig = np.isfinite(pred) & (pred <= -thr)
        m = sig & ~skip; s = st(m)
        if s is None: continue
        yrs = [st(m & (yr == Y)) for Y in YRS]
        pos = sum(1 for z in yrs if z and z['bp'] > 0)
        sd = np.unique(d[m]); approx = np.mean([-my[x] * 1e4 - 13.2 for x in sd])
        print(f'  预测跌≥{thr*100:.1f}%: {s["days"]}天 {s["n"]:,}笔 每笔 {s["bp"]:+.1f}bp t{s["t"]:+.1f} 胜率{s["win"]:.0f}% 赔率{s["pay"]:.2f} '
              f'赚钱天{s["dpos"]:.0f}% | 年份为正 {pos}/6 | 跌停卖不出 {skip[sig].mean()*100:.1f}% 封涨停改次日开盘买回 {nxt[m].mean()*100:.2f}% | 按天近似 {approx:+.1f}bp')
        print('     ' + ' | '.join(f'{Y} {z["days"]:3d}天 {z["bp"]:+6.1f}' if z else f'{Y}   —' for Y, z in zip(YRS, yrs)))
pred = M['正式情绪模型'][0]; sig = np.isfinite(pred) & (pred <= -0.002) & ~skip
print('\n【正式情绪模型、预测跌≥0.2% 的日子】按股票分组')
for lab, g in (('beta<0.8', beta < 0.8), ('beta 0.8–1.2', (beta >= 0.8) & (beta < 1.2)), ('beta≥1.2', beta >= 1.2),
               ('股价<5元', price < 5), ('股价5–15元', (price >= 5) & (price < 15)), ('股价≥15元', price >= 15)):
    s = st(sig & g); yrs = [st(sig & g & (yr == Y)) for Y in YRS]
    if s: print(f'  {lab:12s} {s["n"]:6,}笔 每笔 {s["bp"]:+6.1f}bp t{s["t"]:+.1f} 胜率{s["win"]:.0f}% | 年份为正 {sum(1 for z in yrs if z and z["bp"]>0)}/6 | '
                + ' '.join(f'{z["bp"]:+.0f}' if z else '—' for z in yrs))

"""Strategies stackable on D's idle cash: monthly factor baskets (low-vol, momentum, small cap, value, EW beta, trend) -> daily stream, correlation with D, overlay on idle capital. Research only."""
import grp11 as g
from grp11 import *
W = {'A': .08, 'C': .08, 'B': .025}
eq, ex, *_ = fused(order='ACB', w=W, G=1.0, caps={}, cash_yield=0.0)
rD = dr(eq); print('D done', flush=True)
c = panel.c.astype(np.float64); ret1 = np.full((nd, nc), np.nan); ret1[1:] = c[1:] / c[:-1] - 1
uni = cand.uni
cap = np.load('cap.npy'); pb = np.load('fund_val.npz')['pb']; pe = np.load('fund_val.npz')['pe']
ser = pd.DataFrame(ret1)
vol60 = ser.rolling(60, min_periods=40).std().to_numpy()
mom = np.full((nd, nc), np.nan); mom[250:] = c[230:-20] / c[:-250] - 1 if False else np.nan
mom = np.full((nd, nc), np.nan); mom[250:] = c[250 - 20:nd - 20] / c[:nd - 250] - 1
r20 = np.full((nd, nc), np.nan); r20[20:] = c[20:] / c[:-20] - 1
dts = pd.to_datetime(panel.dates); ym = dts.year * 100 + dts.month
reb = [t for t in range(nd - 1) if ym[t] != ym[t + 1]]
N = 50; COST = 0.002
def basket(score, asc, n=N):
    """monthly top-n by score (asc=True: smallest first), equal weight; returns daily stream with turnover cost."""
    out = np.full(nd, np.nan); prev = np.zeros(nc); cur = prev; last = None
    pos = {}
    for i, t in enumerate(reb):
        s = score[t].copy(); ok = uni[t] & np.isfinite(s)
        if ok.sum() < n: continue
        idx = np.nonzero(ok)[0]; o = np.argsort(s[idx] if asc else -s[idx], kind='stable')[:n] if n else np.arange(len(idx))
        w = np.zeros(nc); w[idx[o]] = 1.0 / len(o); pos[t] = w
    ts = sorted(pos)
    cur = np.zeros(nc); k = 0
    for t in range(nd):
        while k < len(ts) and ts[k] + 2 <= t:   # signal at close ts[k], enter close ts[k]+1, first return day ts[k]+2
            new = pos[ts[k]]; tov = np.abs(new - cur).sum(); cur = new; k += 1; cost = COST * tov / 2 * 2 / 2
            pend = cost
            break_ = True
        else:
            pend = 0.0
        if cur.sum() == 0: continue
        r = np.nansum(np.where(np.isfinite(ret1[t]), ret1[t], 0.0) * cur)
        out[t] = r - pend
    return out
def trend_ew():
    ew = np.array([np.nanmean(ret1[t][uni[t - 1]]) if t > 0 and uni[t - 1].sum() > 50 else np.nan for t in range(nd)])
    idx = np.cumprod(1 + np.nan_to_num(ew)); ma = pd.Series(idx).rolling(200, min_periods=200).mean().to_numpy()
    on = np.r_[False, (idx[:-1] > ma[:-1])]  # known at prior close
    return np.where(on, ew, np.nan_to_num(0.0)), ew
EWr = trend_ew()[1]
streams = {
    '全市场等权（贝塔）': EWr,
    '低波动 50 只': basket(vol60, True),
    '动量 12-1 50 只': basket(mom, False),
    '小市值 50 只': basket(cap, True),
    '低 PB 50 只': basket(np.where(pb > 0, pb, np.nan), True),
    '低 PE 50 只': basket(np.where(pe > 0, pe, np.nan), True),
    '近 1 月最弱 50 只（对照，和 D 同类）': basket(r20, True),
}
ew = EWr; idxv = np.cumprod(1 + np.nan_to_num(ew)); ma = pd.Series(idxv).rolling(200, min_periods=200).mean().to_numpy(); on = np.r_[False, idxv[:-1] > ma[:-1]]
streams['等权指数 200 日线趋势（线下空仓）'] = np.where(on, ew, 0.0)
np.savez('grp30_streams.npz', rD=rD, ex=ex, **{f's{i}': v for i, v in enumerate(streams.values())})
valid = np.isfinite(rD) & np.all([np.isfinite(v) for v in streams.values()], 0) & np.isfinite(ex)
print('window', panel.dates[np.nonzero(valid)[0][0]], 'to', panel.dates[np.nonzero(valid)[0][-1]], 'days', valid.sum(), flush=True)
def stat(r, label):
    x = r[valid]; cum = np.cumprod(1 + x); n = len(x); cagr = cum[-1] ** (245 / n) - 1; sh = x.mean() / x.std() * np.sqrt(245); dd = (cum / np.maximum.accumulate(cum) - 1).min()
    print(f'{label:44s} 年化{cagr*100:+6.1f}% 夏普{sh:5.2f} 回撤{dd*100:5.0f}% 卡玛{cagr/abs(dd):4.2f}', flush=True)
CY = 0.02 / 245
D2 = rD + (1 - np.r_[0, ex[:-1]]) * CY
stat(D2, 'D 单独（闲置 2%）')
for name, s in streams.items():
    rr = np.where(valid, s, np.nan); cor = np.corrcoef(rD[valid], s[valid])[0, 1]
    stat(s, f'[单独] {name}（与 D 相关 {cor:+.2f}）')
print('--- 叠加：S 占用 D 闲置资金（k = 占闲置比例），余下闲置 2%，S 仓位变动扣 20bp 单边')
for name, s in streams.items():
    for k in (0.5, 1.0):
        a = k * (1 - np.r_[0, ex[:-1]]); da = np.abs(np.diff(np.r_[0, a]))
        tot = rD + a * np.nan_to_num(s) - COST * da + (1 - np.r_[0, ex[:-1]] - a) * CY
        stat(tot, f'D + {name} k={k:g}')

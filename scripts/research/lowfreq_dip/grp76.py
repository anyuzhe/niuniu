"""grp76: 这些行业的价格行为本身是“跌了会弹回”（均值回归）还是“跌了会接着跌”（趋势）？
用行业综合指数（成分股等权，含退市股）直接测，不依赖账户成交。"""
import os, sys, json, pickle, collections
sys.path.insert(0, os.path.expanduser('~/mnt/niuniu/src'))
import numpy as np
from quantlab.dipbuy import industry
from quantlab.dipbuy.panel import Panel
panel = Panel.from_npz(os.path.expanduser('~/research/lowfreq/panel_del.npz'))
cls = industry.load_classification(os.path.expanduser('~/mnt/lake/bronze/provider=swsresearch/industry_classification_history'), panel.codes)
inp = pickle.load(open(os.path.expanduser('~/research/lowfreq/grp70_inp.pkl'), 'rb'))
c = panel.c.astype(np.float64); nd, nc = c.shape; dates = [str(d) for d in panel.dates]
labels = np.asarray(cls.labels); names = cls.names; ng = len(names); st = inp.ind_state
retm = np.full((nd, nc), np.nan); retm[1:] = c[1:] / c[:-1] - 1
idx = np.ones((nd, ng)); members = np.zeros(ng, int); avgcorr = np.full(ng, np.nan)
for g in range(ng):
    cols = np.nonzero(labels == g)[0]; members[g] = len(cols)
    if len(cols):
        with np.errstate(all='ignore'): r = np.nanmean(retm[:, cols], axis=1)
        idx[:, g] = np.cumprod(1 + np.nan_to_num(r, nan=0.0))
BAD = ['国防军工', '环保', '煤炭', '基础化工', '家用电器', '美容护理', '房地产']
GOOD = ['计算机', '医药生物', '有色金属', '公用事业', '食品饮料', '农林牧渔', '电子', '银行']
lidx = np.log(idx); H = 20
past = np.full((nd, ng), np.nan); fwd = np.full((nd, ng), np.nan)
past[H:] = lidx[H:] - lidx[:-H]; fwd[:-H] = lidx[H:] - lidx[:-H]; fwd = np.roll(fwd, 0, axis=0)
# fwd[t] = log(idx[t+H]/idx[t])；past[t] = log(idx[t]/idx[t-H])
rows = []
rng = np.random.default_rng(0)
for g in range(ng):
    m = np.isfinite(past[:, g]) & np.isfinite(fwd[:, g]) & (np.arange(nd) >= 130)
    if m.sum() < 500: continue
    x, y = past[m, g], fwd[m, g]
    ok = np.isfinite(x) & np.isfinite(y); x, y = x[ok], y[ok]
    if members[g] < 5 or x.std() < 1e-9: continue
    slope = (np.cov(x, y, bias=True)[0, 1] / x.var()); corr = np.corrcoef(x, y)[0, 1]
    # 分块自助法求斜率区间（块长 40）
    n = len(x); bs = []
    for _ in range(150):
        starts = rng.integers(0, n - 40, size=n // 40 + 1); ii = np.concatenate([np.arange(s, s + 40) for s in starts])[:n]
        bs.append((np.cov(x[ii], y[ii], bias=True)[0, 1] / x[ii].var()))
    lo, hi = np.percentile(bs, [5, 95])
    # 触发日（行业 z <= -1.5）的前向收益 vs 全样本无条件均值
    trig = np.isfinite(st.z[:, g]) & (st.z[:, g] <= -1.5) & m & np.isfinite(fwd[:, g])
    unc = np.expm1(y).mean(); tr = np.expm1(fwd[trig, g]).mean() if trig.sum() else np.nan
    ts = np.nonzero(trig)[0]; eps = []; cur = []
    for t in ts:
        if cur and t - cur[-1] > 25: eps.append(cur); cur = []
        cur.append(t)
    if cur: eps.append(cur)
    epm = np.mean([np.expm1(fwd[e, g]).mean() for e in eps]) if eps else np.nan
    eplen = np.mean([len(e) for e in eps]) if eps else np.nan
    ret = np.diff(lidx[:, g]); vol = np.nanstd(ret[130:]) * np.sqrt(245)
    rows.append(dict(ind=names[g], n=int(members[g]), slope=float(slope), lo=float(lo), hi=float(hi), corr=float(corr), unc=float(unc), trig=float(tr),
                     excess=float(tr - unc) if trig.sum() else None, ep_excess=float(epm - unc) if eps else None, neps=len(eps), ntrig=int(trig.sum()), eplen=float(eplen) if eps else None, vol=float(vol)))
json.dump(rows, open('grp76.json', 'w'), ensure_ascii=False)
print(f"{'行业':8s}{'成分股':>5s}{'20日自回归斜率[90%区间]':>26s}{'无条件20日':>9s}{'触发后20日':>9s}{'超额':>7s}{'按段超额':>8s}{'段数':>5s}{'段长':>6s}{'年化波动':>7s}")
for r in sorted(rows, key=lambda r: r['slope']):
    tag = '差' if r['ind'] in BAD else '好' if r['ind'] in GOOD else ' '
    print(f"{tag}{r['ind']:7s}{r['n']:5d}   {r['slope']:+.3f} [{r['lo']:+.3f},{r['hi']:+.3f}]  {r['unc']*100:+7.2f}% {r['trig']*100:+7.2f}% {((r['excess'] or 0))*100:+6.2f}% {((r['ep_excess'] or 0))*100:+7.2f}% {r['neps']:5d} {r['eplen'] or 0:6.1f} {r['vol']*100:6.1f}%")
def grpstat(S, key):
    v = [r[key] for r in rows if r['ind'] in S and r[key] is not None]; return np.mean(v) if v else np.nan
print('\n分组平均：')
for lab, S in (('差7', set(BAD)), ('好8', set(GOOD)), ('其余', {r['ind'] for r in rows} - set(BAD) - set(GOOD))):
    print(f"{lab}: 斜率 {grpstat(S,'slope'):+.3f} 触发超额 {grpstat(S,'excess')*100:+.2f}% 按段超额 {grpstat(S,'ep_excess')*100:+.2f}% 段长 {grpstat(S,'eplen'):.1f} 年化波动 {grpstat(S,'vol')*100:.1f}% 成分股数 {grpstat(S,'n'):.0f}")
# 与账户成绩的关系
acc = collections.defaultdict(list)
for r in json.load(open('grp73_rows.json')): acc[r['ind']].append(r['ret'])
from scipy.stats import spearmanr
X = [(r['slope'], r['excess'], r['ep_excess'], np.mean(acc[r['ind']])) for r in rows if len(acc.get(r['ind'], [])) >= 20 and r['excess'] is not None]
print('\n跨行业（账户成交>=20笔的', len(X), '个行业）Spearman：')
for i, lab in enumerate(('20日自回归斜率', '触发超额', '按段超额')):
    rho, p = spearmanr([x[i] for x in X], [x[3] for x in X]); print(f"  {lab} vs 账户平均收益: rho={rho:+.2f} p={p:.3f}")

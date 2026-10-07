"""§92: delisting-rule style financial filters (annual report: loss & revenue < 1e8, two consecutive losses, negative equity), point-in-time by notice date, on the with-delisted D panel. Research only."""
import sys, json, os, numpy as np, pandas as pd
os.environ.setdefault('C70DIR', 'c80'); os.environ.setdefault('SERIES', 'c80/series.npz')
import lib73 as X, lib70 as L
F = 'res82_del.json'; res = json.load(open(F)) if os.path.exists(F) else {}
ISDEL = np.load('c80/isdel.npy'); nd = L.nd; dates = L.dates.astype(str); codes = np.load('c80/codes.npy').astype(str); ci = {c: i for i, c in enumerate(codes)}; nc = len(codes)
def build():
    T = pd.read_csv('fin_tab.csv'); T = T[T.code.isin(ci)]; T['pref'] = (T.src == 'em').astype(int); T = T.sort_values(['code', 'year', 'pref']).drop_duplicates(['code', 'year'], keep='last')
    T['j'] = T.code.map(ci); T['a'] = np.searchsorted(dates, T.notice.values.astype(str), side='right')   # first trading day strictly after notice
    P = {(r.j, r.year): r.np for r in T.itertuples()}
    REV = np.full((nd, nc), np.nan, np.float32); NP = REV.copy(); NPP = REV.copy(); EQ = REV.copy(); YR = np.full((nd, nc), np.nan, np.float32)
    for r in T.sort_values('a').itertuples():
        if r.a >= nd: continue
        REV[r.a:, r.j] = r.rev; NP[r.a:, r.j] = r.np; NPP[r.a:, r.j] = P.get((r.j, r.year - 1), np.nan); EQ[r.a:, r.j] = r.equity; YR[r.a:, r.j] = r.year
    return REV, NP, NPP, EQ, YR
def go(label, **kw):
    if label in res: st = res[label]
    else:
        st = X.run(**kw); tr = X.TR
        st['nDel'] = int(sum(1 for t in tr if ISDEL[t[3]])); st['mDel'] = float(np.mean([t[1] for t in tr if ISDEL[t[3]]])) if st['nDel'] else None
        st['lt20'] = float(np.mean([t[1] < -.2 for t in tr])); st['worst'] = float(min(t[1] for t in tr))
        res[label] = st; json.dump(res, open(F, 'w'), ensure_ascii=False)
    print(f"{label:54s} 年化{st['cagr']*100:+5.1f}% 夏普{st['sharpe']:.2f} 回撤{st['dd']*100:4.0f}% 前{(st['h1'] or 0)*100:+5.1f}% 后{(st['h2'] or 0)*100:+5.1f}% 笔{st['ntr']} 退市笔{st['nDel']} 均{st['tret']*1e4:+.0f}bp <-20%:{st['lt20']*100:.1f}%", flush=True); return st
phase = sys.argv[1]; REV, NP, NPP, EQ, YR = build()
fin = np.isfinite
rules = {
  '亏损且营收<1亿': (NP < 0) & (REV < 1e8),
  '亏损且营收<3亿': (NP < 0) & (REV < 3e8),
  '连续两年亏损': (NP < 0) & (NPP < 0),
  '净资产为负': EQ < 0,
  '上年亏损': NP < 0,
}
rules['以上三条任一(1亿/两年亏/净资产)'] = rules['亏损且营收<1亿'] | rules['连续两年亏损'] | rules['净资产为负']
if phase == 'd':   # coverage + diagnostics on baseline fills
    X.run(sleeves='ACB'); tr = X.TR; d = L.dates
    known = lambda t: bool(fin(NP[t[4] - 1, t[3]]))
    for nm, z in (('退市股', [t for t in tr if ISDEL[t[3]]]), ('在市股', [t for t in tr if not ISDEL[t[3]]])):
        kn = np.mean([known(t) for t in z]) * 100
        line = ' '.join(f'{k}:{np.mean([bool(m[t[4]-1, t[3]]) for t in z])*100:.0f}%' for k, m in rules.items())
        print(f'{nm} n={len(z)} 有年报数据 {kn:.0f}% | {line}')
    print('2021起退市股 n=%d' % sum(1 for t in tr if ISDEL[t[3]] and d[t[4]] >= '2021-01-01'), ' '.join(f'{k}:{np.mean([bool(m[t[4]-1, t[3]]) for t in tr if ISDEL[t[3]] and d[t[4]]>="2021-01-01"])*100:.0f}%' for k, m in rules.items()))
    for k, m in rules.items():
        z = [t for t in tr if m[t[4] - 1, t[3]]]; w = [t for t in tr if not m[t[4] - 1, t[3]]]
        print(f'{k}: 命中 {len(z)} 笔 均 {np.mean([t[1] for t in z])*1e4:+.0f}bp (其中退市股 {sum(1 for t in z if ISDEL[t[3]])}) | 未命中 {len(w)} 笔 均 {np.mean([t[1] for t in w])*1e4:+.0f}bp')
if phase == 'f':
    for sl in ('ACB', 'CB'):
        go(f'[{sl}] 基线', sleeves=sl)
        for k, m in rules.items(): go(f'[{sl}] 排除 {k}', sleeves=sl, fmask=~m)
if phase == 'g':   # strict: also drop names whose latest annual report is unknown/stale (> 1 yr)
    for sl in ('ACB', 'CB'):
        go(f'[{sl}] 只买有年报数据且不满足上述任一风险', sleeves=sl, fmask=fin(NP) & ~rules['以上三条任一(1亿/两年亏/净资产)'])

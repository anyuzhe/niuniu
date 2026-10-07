"""§90: survivorship check - rerun key D conclusions with delisted stocks merged into the panel (NODEL=1: gates/pools without them)."""
import sys, json, os, numpy as np
os.environ.setdefault('C70DIR', 'c80'); os.environ.setdefault('SERIES', 'c80/series.npz')
import lib73 as X, lib70 as L, lib74 as Y
TAG = 'nodel' if os.environ.get('NODEL') == '1' else 'del'
F = f'res80_{TAG}.json'; res = json.load(open(F)) if os.path.exists(F) else {}
ISDEL = np.load('c80/isdel.npy')
def go(label, **kw):
    if label in res: st = res[label]
    else:
        st = X.run(**kw); tr = X.TR
        st['nDel'] = int(sum(1 for t in tr if ISDEL[t[3]])); st['mDel'] = float(np.mean([t[1] for t in tr if ISDEL[t[3]]])) if st['nDel'] else None
        st['worst'] = float(min(t[1] for t in tr)); st['med'] = float(np.median([t[1] for t in tr]))
        res[label] = st; json.dump(res, open(F, 'w'), ensure_ascii=False)
    print(f"{TAG:5s} {label:46s} 年化{st['cagr']*100:+5.1f}% 夏普{st['sharpe']:.2f} 回撤{st['dd']*100:4.0f}% 仓位{st['expo']*100:3.0f}% 前{(st['h1'] or 0)*100:+5.1f}% 后{(st['h2'] or 0)*100:+5.1f}% 笔{st['ntr']} 退市笔{st['nDel']} 退市均{(st['mDel'] or 0)*1e4:+.0f}bp 均{st['tret']*1e4:+.0f}bp 中位{st['med']*1e4:+.0f}bp", flush=True); return st
phase = sys.argv[1]
R20 = Y.R20; SIG = np.asarray(L.SIG, np.float32); DD = np.asarray(Y.DD60, np.float32)
iv = lambda s, t, j: float(np.clip(0.03 / SIG[t, j], 0.5, 2.0)) if np.isfinite(SIG[t, j]) and SIG[t, j] > 0 else 1.0
if phase == 'p1':
    for sl in ('ACB', 'CB', 'A', 'C', 'B'): go(f'[{sl}] 基线', sleeves=sl)
if phase == 'p2':
    for sl in ('CB', 'ACB'):
        go(f'[{sl}] 回撤二段 K=40', sleeves=sl, rank_s={s: Y.two_stage(s, 40, DD) for s in 'ACB'})
        go(f'[{sl}] 波动率倒数加权', sleeves=sl, wfun=iv)
        go(f'[{sl}] 回撤K40+波动率倒数', sleeves=sl, rank_s={s: Y.two_stage(s, 40, DD) for s in 'ACB'}, wfun=iv)
if phase == 'p3':
    for sl in ('CB', 'ACB'):
        for r in ('r5', 'dma20', 'zown'): go(f'[{sl}] 排序={r}', sleeves=sl, rank=r)
        go(f'[{sl}] 排序=随机(seed0)', sleeves=sl, rank='rand', seed=0)
        go(f'[{sl}] 排序=随机(seed1)', sleeves=sl, rank='rand', seed=1)
        for k in (3, 5): go(f'[{sl}] 跳过跌最多前{k}只', sleeves=sl, skip=k)
if phase == 'p4':
    for sl in ('ACB',):
        go(f'[{sl}] 层序 CBA', sleeves=sl, order=lambda t, act: sorted(act, key='CBA'.index))
        go(f'[{sl}] 层序 BCA', sleeves=sl, order=lambda t, act: sorted(act, key='BCA'.index))
        go(f'[{sl}] 2011起 基线', sleeves=sl, start='2011-01-01')
        go(f'[{sl}] 2015起 基线', sleeves=sl, start='2015-01-01')
if phase == 'p5':   # delisted columns present in the panel (gates/pools/universe computed with them) but never bought
    nm = np.broadcast_to(~ISDEL[None, :], (L.nd, len(ISDEL)))
    for sl in ('ACB', 'CB'): go(f'[{sl}] 含退市数据但不买退市股', sleeves=sl, fmask=nm)

import sys, time, json, os, numpy as np
import lib73 as X, lib70 as L
F = 'res73.json'; res = json.load(open(F)) if os.path.exists(F) else {}
def go(label, **kw):
    if label in res: st = res[label]
    else:
        st = X.run(**kw); res[label] = st; json.dump(res, open(F, 'w'), ensure_ascii=False)
    print(f"{label:46s} 年化{st['cagr']*100:+5.1f}% 夏普{st['sharpe']:.2f} 回撤{st['dd']*100:4.0f}% 仓位{st['expo']*100:3.0f}% 前{(st['h1'] or 0)*100:+5.1f}% 后{(st['h2'] or 0)*100:+5.1f}% 笔{st['ntr']} A/C/B笔均 {st['mA']*1e4 if st.get('mA') else 0:+.0f}/{st['mC']*1e4 if st.get('mC') else 0:+.0f}/{st['mB']*1e4 if st.get('mB') else 0:+.0f}bp 笔数 {st['nA']}/{st['nC']}/{st['nB']}", flush=True); return st
phase = sys.argv[1]
if phase == 'diag':
    d = dict(des={s: 0.0 for s in 'ACB'}, got={s: 0.0 for s in 'ACB'}, n={s: 0 for s in 'ACB'})
    eq, ex, tr, cl = X.fused5(diag=d)
    for s in 'ACB': print(s, '段首日', int(np.sum(X.EPS[s][int(np.searchsorted(X.dates,'2008-01-01')):])), '次尝试；想买(权益倍数合计)', round(d['des'][s],2), '实际买到', round(d['got'][s],2), '满足率', round(d['got'][s]/max(d['des'][s],1e-9),2))
    # exposure distribution on gate days
    t0 = int(np.searchsorted(X.dates, '2008-01-01'))
    for s in 'ACB':
        g = np.asarray(X.GATE[s])[t0:]; e = ex[t0:]
        print(s, '触发日平均仓位', round(float(np.nanmean(e[g])),2), '仓位≥95% 的触发日占比', round(float(np.mean(e[g] >= .95)),2), '非触发日平均仓位', round(float(np.nanmean(e[~g])),2))
if phase == 'p1':
    go('基线 ACB')
    for o in ('ABC', 'CAB', 'CBA', 'BAC', 'BCA'): go(f'优先级 {o}', sleeves=o)
    for k in (1.5, 2.0, 3.0):
        for o in ('ACB', 'CBA', 'BCA'): go(f'权重×{k} 优先级 {o}', sleeves=o, W={s: v * k for s, v in L.W0.items()})
if phase == 'p2':
    go('统一排序(全局20日跌幅) 标签ACB', unified=True)
    go('统一排序 标签CAB', unified=True, sleeves='CAB'); go('统一排序 标签BCA', unified=True, sleeves='BCA')
    go('动态优先级: 最深的 z 先', order=lambda t, act: sorted(act, key=lambda s: X.zmin[s][t]))
    go('动态优先级: 最浅的 z 先', order=lambda t, act: sorted(act, key=lambda s: -X.zmin[s][t]))
    go('共振加权: 权重相加', confl='sum'); go('共振加权: 取最大', confl='max')
    for c in (0.5, 1.0, 2.0): go(f'共振加权: 每多一个层×(1+{c})', confl='mult', cpar=c)
json.dump(res, open(F, 'w'), ensure_ascii=False)
if phase == 'p3':
    go('只有 C+B（去掉 A）', sleeves='CB'); go('只有 C', sleeves='C'); go('只有 B', sleeves='B'); go('只有 A', sleeves='A'); go('只有 A+C', sleeves='AC'); go('只有 A+B', sleeves='AB')
    for u in ('zown', 'dd60', 'r5', 'dma20', 'comb', 'siglo', 'sighi', 'volhi', 'vollo'): go(f'统一排序用 {u}', unified=True, urank=u)
    go('统一排序 + 去掉 A', unified=True, sleeves='CB')
    for g in (0.6, 0.8): go(f'预留: B 只能用到总仓位 {g:.0%}', gfun=lambda t, s, g=g: g if s == 'B' else 1.0)
    for g in (0.7, 0.85): go(f'预留: B/C 只能用到总仓位 {g:.0%}（给 A）', gfun=lambda t, s, g=g: g if s in 'BC' else 1.0)
    go('互斥: A 日只买 A, C 日只买 C, 其余 B', excl=lambda t, act: act[:1])
    go('A 日不买 B', excl=lambda t, act: [s for s in act if not (s == 'B' and 'A' in act)])
    go('A 日、C 日都不买 B（B 只在只有行业恐慌时买）', excl=lambda t, act: [s for s in act if not (s == 'B' and ('A' in act or 'C' in act))])
    go('A 日不买 C', excl=lambda t, act: [s for s in act if not (s == 'C' and 'A' in act)])
    go('C 日不买 B', excl=lambda t, act: [s for s in act if not (s == 'B' and 'C' in act)])
if phase == 'p4':
    for m in (0.5, 0.75, 1.5, 2.0): go(f'A 日 C/B 权重×{m}', wfun=lambda s, t, j, m=m: m if (s in 'CB' and L.GATE['A'][t]) else 1.0)
    for m in (0.5, 2.0): go(f'C 日 B 权重×{m}', wfun=lambda s, t, j, m=m: m if (s == 'B' and L.GATE['C'][t]) else 1.0)
    for k in (0.25, 0.5, 1.0, -0.25, -0.5):
        def wf(s, t, j, k=k):
            z = X.zstock(s, t, j)
            return float(np.clip(1 + k * (-z - 1.5), 0.4, 2.5)) if np.isfinite(z) else 1.0
        go(f'按本股所在组 z 深度加权 k={k:+}', wfun=wf)
    for k in (0.25, 0.5, -0.25):
        def wm(s, t, j, k=k):
            z = X.zmin[s][t]; return float(np.clip(1 + k * (-z - 1.5), 0.4, 2.5)) if np.isfinite(z) and z < 99 else 1.0
        go(f'按该层最深 z 加权 k={k:+}', wfun=wm)
def daily(eq):
    r = np.full(nd, np.nan); r[1:] = eq[1:] / eq[:-1] - 1; return r
nd = X.nd
if phase == 'p5':
    e0 = X.fused5()[0]; e1 = X.fused5(sleeves='CB')[0]; e2 = X.fused5(unified=True)[0]
    r0, r1, r2 = daily(e0), daily(e1), daily(e2); ok = np.isfinite(r0) & np.isfinite(r1)
    ys = sorted(set(X.yr[ok]))
    print('逐年(年内复利): 年 | 基线 ACB | C+B(去A) | 差 | 统一排序 | 差')
    w = l = 0
    for y in ys:
        k = ok & (X.yr == y); a = np.prod(1 + r0[k]) - 1; b = np.prod(1 + r1[k]) - 1; c = np.prod(1 + r2[k]) - 1
        print(f'{y} | {a*100:+6.1f}% | {b*100:+6.1f}% | {(b-a)*100:+5.1f} | {c*100:+6.1f}% | {(c-a)*100:+5.1f}'); w += b > a + 1e-9; l += b < a - 1e-9
    print('去A 优于基线的年数', w, '劣于', l, '共', len(ys))
    rng = np.random.default_rng(0); idx = np.nonzero(ok)[0]; d = (r1 - r0)[idx]; n = len(d); B = 20; outs = []
    for _ in range(2000):
        starts = rng.integers(0, n - B, size=n // B + 1); x = np.concatenate([d[s:s + B] for s in starts])[:n]; outs.append(x.mean() * 245)
    print('去A 对基线的日收益差（年化加总，20日块 bootstrap）均值 %.2f%%  95%%区间 [%.2f%%, %.2f%%]  P(<=0)=%.3f' % (np.mean(outs) * 100, np.percentile(outs, 2.5) * 100, np.percentile(outs, 97.5) * 100, np.mean(np.array(outs) <= 0)))
    d = (r2 - r0)[idx]; outs = []
    for _ in range(2000):
        starts = rng.integers(0, n - B, size=n // B + 1); x = np.concatenate([d[s:s + B] for s in starts])[:n]; outs.append(x.mean() * 245)
    print('统一排序 对基线 均值 %.2f%%  95%%区间 [%.2f%%, %.2f%%]  P(<=0)=%.3f' % (np.mean(outs) * 100, np.percentile(outs, 2.5) * 100, np.percentile(outs, 97.5) * 100, np.mean(np.array(outs) <= 0)))
if phase == 'p6':
    for wc in (.05, .08, .12, .16):
        for wb in (.015, .025, .04, .06): go(f'CB 权重 C={wc:.0%} B={wb:.1%}', sleeves='CB', W={'A': .08, 'C': wc, 'B': wb})
    for n in (10, 15, 30): go(f'CB 每层名额 {n}', sleeves='CB', N=n)
if phase == 'p7':
    for sl, nm in (('ACB', 'D(ACB)'), ('CB', 'C+B')):
        go(f'{nm} 基线', sleeves=sl)
        for k, gap in ((2, 1), (3, 1), (5, 1), (2, 2), (3, 2), (5, 2), (3, 3), (4, 5)):
            for ex in ('common', 'own'): go(f'{nm} 同一批分{k}次买 间隔{gap}天 {"共同到期" if ex=="common" else "各自20天"}', sleeves=sl, tr=dict(k=k, gap=gap, exit=ex))
    for fr in ((1/3, 2/3), (2/3, 1/3), (.5, .25, .25), (.25, .25, .5)):
        go(f'D 分批比例 {tuple(round(x,2) for x in fr)} 间隔1天 各自20天', tr=dict(k=len(fr), gap=1, exit='own', fr=fr))
    for s in 'ACB': go(f'D 只对 {s} 分3次买 间隔1天 各自20天', tr=dict(k=3, gap=1, exit='own', sleeves=s))
    go('D 只对 A、C 分3次', tr=dict(k=3, gap=1, exit='own', sleeves='AC')); go('D 只对 C、B 分3次', tr=dict(k=3, gap=1, exit='own', sleeves='CB'))
if phase == 'p8':
    for sl, nm in (('ACB', 'D'),):
        go('限价对照: 全部在开盘价限价(x=0) 全部', lim=dict(x=0.0, frac=1.0, fb='skip'))
        for x in (0.01, 0.02, 0.03, 0.05):
            for fr in (0.5, 1.0):
                for fb in ('skip', 'close'):
                    if fr == 1.0 and fb == 'close' and x != 0.03: continue
                    go(f'{nm} 限价单 开盘价下 {x:.0%} 占 {fr:.0%} 未成交{"放弃" if fb=="skip" else "收盘买"}', lim=dict(x=x, frac=fr, fb=fb))
if phase == 'p9':
    for x in (0.03, 0.05, 0.08):
        for fr in (0.3, 0.5): go(f'加仓: 跌破买价 -{x:.0%} 时补 {fr:.0%}（10天内）', pyr=dict(mode='px', x=x, frac=fr))
    for dl in (0.5, 1.0):
        for fr in (0.3, 0.5): go(f'加仓: 该组恐慌分比买入时更深 {dl} 时补 {fr:.0%}（10天内）', pyr=dict(mode='z', delta=dl, frac=fr))
if phase == 'p10':
    go('(验证) D 基线再算', )
    for s in 'ACB':
        for h in (10, 15, 25, 30):
            Hd = {'A': 20, 'C': 20, 'B': 20}; Hd[s] = h; go(f'只把 {s} 层持有期改成 {h} 天', H=Hd)
    go('A=10 C=20 B=20 且去 A 无意义→ C+B: B=15', sleeves='CB', H={'A': 20, 'C': 20, 'B': 15})
    go('C+B: B=25', sleeves='CB', H={'A': 20, 'C': 20, 'B': 25}); go('C+B: C=25', sleeves='CB', H={'A': 20, 'C': 25, 'B': 20}); go('C+B: C=15', sleeves='CB', H={'A': 20, 'C': 15, 'B': 20})
    for s in 'ACB':
        for rn in ('dd60', 'comb', 'zown', 'dma20'): go(f'只把 {s} 层排序改成 {rn}', rank_s={s: rn})

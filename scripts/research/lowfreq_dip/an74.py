import sys, json, os, numpy as np
import lib73 as X, lib70 as L, lib74 as Y
F = 'res74.json'; res = json.load(open(F)) if os.path.exists(F) else {}
def go(label, **kw):
    if label in res: st = res[label]
    else:
        st = X.run(**kw); res[label] = st; json.dump(res, open(F, 'w'), ensure_ascii=False)
    print(f"{label:52s} 年化{st['cagr']*100:+5.1f}% 夏普{st['sharpe']:.2f} 回撤{st['dd']*100:4.0f}% 仓位{st['expo']*100:3.0f}% 前{(st['h1'] or 0)*100:+5.1f}% 后{(st['h2'] or 0)*100:+5.1f}% 笔{st['ntr']} C/B笔均 {st['mC']*1e4 if st.get('mC') else 0:+.0f}/{st['mB']*1e4 if st.get('mB') else 0:+.0f}bp", flush=True); return st
phase = sys.argv[1]
R20 = Y.R20; SIG = np.asarray(L.SIG, np.float32); RET1 = np.asarray(L.L('ret1'), np.float32); VR = np.asarray(L.L('volratio'), np.float32); DD60 = np.asarray(L.L('dd60'), np.float32)

SIGREF = float(np.nanmedian(SIG[X.GATE['C']][:, :][np.isfinite(SIG[X.GATE['C']])])) if False else None
if phase == 'q1':
    for sl in ('CB', 'ACB'):
        go(f'[{sl}] 基线', sleeves=sl)
        go(f'[{sl}] 排序=个股跌幅-本组跌幅', sleeves=sl, rank_s={s: Y.rel20(s) for s in 'ACB'})
        go(f'[{sl}] 排序=先按本组恐慌分最深、组内按20日跌幅', sleeves=sl, rank_s={s: Y.zgrp_key(s) for s in 'ACB'})
        for k in (3, 5, 10): go(f'[{sl}] 跳过跌得最多的前 {k} 只', sleeves=sl, skip=k)
        for x in (-0.5, -0.4, -0.3, -0.25): go(f'[{sl}] 排除20日跌幅超过 {abs(x):.0%} 的', sleeves=sl, fmask=(R20 >= x))
        for x in (-0.03, -0.05, -0.07): go(f'[{sl}] 只买信号日跌幅不超过 {abs(x):.0%} 的（不在继续杀跌）', sleeves=sl, fmask=(RET1 >= x))
        for x in (0.0, 0.02): go(f'[{sl}] 只买信号日收涨超过 {x:.0%} 的', sleeves=sl, fmask=(RET1 >= x))
        for x in (2.0, 3.0, 5.0): go(f'[{sl}] 排除量比超过 {x} 的（放量杀跌）', sleeves=sl, fmask=(VR <= x))
        for x in (1.0, 1.5): go(f'[{sl}] 只买量比不低于 {x} 的', sleeves=sl, fmask=(VR >= x))
if phase == 'q2':
    DD60a = np.asarray(Y.DD60, np.float32); DMAa = np.asarray(Y.DMA, np.float32)
    for sl in ('CB', 'ACB'):
        go(f'[{sl}] 基线', sleeves=sl)
        for K in (30, 40, 60, 100):
            go(f'[{sl}] 先取20日跌幅前{K}，再按60日回撤最深优先', sleeves=sl, rank_s={s: Y.two_stage(s, K, DD60a) for s in 'ACB'})
        for K in (40, 60):
            go(f'[{sl}] 先取前{K}，再按距MA20最远优先', sleeves=sl, rank_s={s: Y.two_stage(s, K, DMAa) for s in 'ACB'})
            go(f'[{sl}] 先取前{K}，再按 5日跌幅最深', sleeves=sl, rank_s={s: Y.two_stage(s, K, np.asarray(Y.R5, np.float32)) for s in 'ACB'})
            go(f'[{sl}] 先取前{K}，再按 60日回撤+20日跌幅 综合', sleeves=sl, rank_s={s: Y.two_stage(s, K, DD60a + R20) for s in 'ACB'})
if phase == 'q3':
    R = np.load('rows74.npy')
    for lam in (30.0, 300.0):
        SC = Y.learned(R, lam=lam)
        for sl in ('CB', 'ACB'):
            go(f'[{sl}] 2011起 基线', sleeves=sl, start='2011-01-01')
            go(f'[{sl}] 2011起 学习打分(岭回归, 逐年滚动, λ={lam:g})', sleeves=sl, start='2011-01-01', rank=SC)
if phase == 'q4':
    SIGa = SIG; DD = np.asarray(Y.DD60, np.float32)
    for sl in ('CB',):
        for ref in (0.03,):
            go(f'[{sl}] 波动率倒数加权(参考 {ref})', sleeves=sl, wfun=lambda s, t, j, ref=ref: float(np.clip(ref / SIGa[t, j], 0.5, 2.0)) if np.isfinite(SIGa[t, j]) and SIGa[t, j] > 0 else 1.0)
            go(f'[{sl}] 波动率正比加权(参考 {ref})', sleeves=sl, wfun=lambda s, t, j, ref=ref: float(np.clip(SIGa[t, j] / ref, 0.5, 2.0)) if np.isfinite(SIGa[t, j]) else 1.0)
        for k in (1.0, -1.0): go(f'[{sl}] 按60日回撤深度加权 k={k:+}', sleeves=sl, wfun=lambda s, t, j, k=k: float(np.clip(1 + k * (-DD[t, j] - 0.35) / 0.2, 0.5, 2.0)) if np.isfinite(DD[t, j]) else 1.0)
        go(f'[{sl}] 排名靠前权重大(1.5→0.5)', sleeves=sl, wfun=lambda s, t, j: 1.5 - X.CUR_POS.get(s, 0) / 19.0)
        go(f'[{sl}] 排名靠前权重小(0.5→1.5)', sleeves=sl, wfun=lambda s, t, j: 0.5 + X.CUR_POS.get(s, 0) / 19.0)
        for k in (2, 3, 5):
            go(f'[{sl}] C 层每个行业最多 {k} 只', sleeves=sl, gcap={'C': (X.l1, k)})
            go(f'[{sl}] B 层每个行业最多 {k} 只', sleeves=sl, gcap={'B': (X.l1, k)})
        go(f'[{sl}] B、C 每个行业最多 3 只', sleeves=sl, gcap={'C': (X.l1, 3), 'B': (X.l1, 3)})
        def dyn(K):
            def f(t, act):
                h = {s: [x[1] for x in X.TR[-400:] if x[0] == s][-K:] for s in act}
                if any(len(v) < 10 for v in h.values()): return act
                return sorted(act, key=lambda s: -np.mean(h[s]))
            return f
        for K in (30, 60): go(f'[ACB] 动态优先级: 近{K}笔平均收益高的层先拿钱', sleeves='ACB', order=dyn(K))
if phase == 'q5':
    rng = np.random.default_rng(1); outs = []
    for sd in range(25):
        rr = np.random.default_rng(sd)
        def rnd(t, act, rr=rr):
            act = list(act); rr.shuffle(act); return act
        st = X.run(sleeves='ACB', order=rnd); outs.append(st['cagr'])
    outs = np.array(outs); print('随机层顺序(每天随机) 25 次: 年化均值 %.1f%% 最小 %.1f%% 最大 %.1f%%' % (outs.mean()*100, outs.min()*100, outs.max()*100))
    go('(参考) 基线 ACB'); go('(参考) CB'); 
    o2 = []
    for sd in range(8):
        st = X.run(sleeves='CB', rank='rand', seed=100 + sd); o2.append((st['cagr'], st['sharpe']))
    o2 = np.array(o2); print('CB 随机排序 8 次: 年化均值 %.1f%% 范围 [%.1f%%, %.1f%%] 夏普均值 %.2f' % (o2[:,0].mean()*100, o2[:,0].min()*100, o2[:,0].max()*100, o2[:,1].mean()))
if phase == 'q6':
    DDa = np.asarray(Y.DD60, np.float32); iv = lambda s, t, j: float(np.clip(0.03 / SIG[t, j], 0.5, 2.0)) if np.isfinite(SIG[t, j]) and SIG[t, j] > 0 else 1.0
    rs40 = {s: Y.two_stage(s, 40, DDa) for s in 'ACB'}; rc60 = {s: Y.two_stage(s, 60, DDa + R20) for s in 'ACB'}
    for sl in ('CB', 'ACB'):
        go(f'[{sl}] 回撤前40 + 波动率倒数加权', sleeves=sl, rank_s=rs40, wfun=iv)
        go(f'[{sl}] 回撤+跌幅综合前60 + 波动率倒数加权', sleeves=sl, rank_s=rc60, wfun=iv)
        go(f'[{sl}] 只用波动率倒数加权（20日跌幅排序）', sleeves=sl, wfun=iv)
    for lo, hi in ((0.3, 3.0), (0.5, 1.5), (0.7, 1.4)):
        go(f'[CB] 波动率倒数加权 截断[{lo},{hi}]', sleeves='CB', wfun=lambda s, t, j, lo=lo, hi=hi: float(np.clip(0.03 / SIG[t, j], lo, hi)) if np.isfinite(SIG[t, j]) and SIG[t, j] > 0 else 1.0)
    for ref in (0.02, 0.04): go(f'[CB] 波动率倒数加权 参考 {ref}', sleeves='CB', wfun=lambda s, t, j, ref=ref: float(np.clip(ref / SIG[t, j], 0.5, 2.0)) if np.isfinite(SIG[t, j]) and SIG[t, j] > 0 else 1.0)

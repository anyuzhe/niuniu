"""Job runner with a time budget; results are cached in res70.json so repeated calls resume. Usage: python run70.py PHASE BUDGET_SECONDS"""
import sys, os, json, time, multiprocessing as mp
import numpy as np
import lib70 as L
phase, budget = sys.argv[1], float(sys.argv[2]); T0 = time.time()
def jobs(phase):
    J = {}
    if phase == 'base':
        J['基线(固定持有20天)'] = {}
    if phase == 'exit1':
        for R in (.06, .08, .10, .15, .20): J[f'止盈 {R*100:.0f}% (最长20天)'] = dict(rules=[['target', R]])
        for k in (0, .02, .05): J[f'回到 MA20{"+%d%%" % round(k*100) if k else ""} 即退(持有≥2天)'] = dict(rules=[['ma20', k, 2]])
        for f in (.5, .75, 1.0): J[f'收复 20 日跌幅的 {f*100:.0f}% 即退'] = dict(rules=[['recover', f]])
    if phase == 'exit2':
        for m in (.5, .75, 1.0, 1.5): J[f'波动率目标 {m}×σ√20'] = dict(rules=[['volt', m]])
        for th in (-.5, 0, .5, 1.0): J[f'大盘恐慌分回升到 ≥{th} 即退(持有≥3天)'] = dict(rules=[['mz', th, 3]])
        J['跟踪止盈 峰值≥8% 回撤4%'] = dict(rules=[['trail', .08, .04]]); J['跟踪止盈 峰值≥10% 回撤5%'] = dict(rules=[['trail', .10, .05]])
        for S in (.10, .15, .20): J[f'止损 {S*100:.0f}%'] = dict(rules=[['stop', S]])
    if phase == 'hold':
        for H in (10, 15, 25, 30, 40): J[f'固定持有 {H} 天'] = dict(H=H)
    if phase == 'rank1':
        for r in ('r5', 'zown', 'dd60', 'dma20', 'volhi', 'vollo', 'ret1', 'sighi', 'siglo'): J[f'排序:{r}'] = dict(rank=r)
        for sd in (1, 2, 3): J[f'排序:随机(对照){sd}'] = dict(rank='rand', seed=sd)
    if phase == 'combo':
        T = lambda x: ['target', x]
        J['止盈20% 或 止损20%'] = dict(rules=[T(.20), ['stop', .20]])
        J['止盈25%'] = dict(rules=[T(.25)]); J['止盈30%'] = dict(rules=[T(.30)])
        J['波动率1.5× 或 止损15%'] = dict(rules=[['volt', 1.5], ['stop', .15]])
        J['收复100% 或 止盈20%'] = dict(rules=[['recover', 1.0], T(.20)])
        J['恐慌分≥1.0 或 止盈20%'] = dict(rules=[['mz', 1.0, 3], T(.20)])
        J['止盈20% 或 跟踪(峰值15%回撤7%)'] = dict(rules=[T(.20), ['trail', .15, .07]])
        J['止盈20% 或 收复100% 或 止损20%'] = dict(rules=[T(.20), ['recover', 1.0], ['stop', .20]])
        J['同时满足: 盈利≥8% 且 恐慌分≥0'] = dict(rules=[['all', T(.08), ['mz', 0, 3]]])
        J['同时满足: 盈利≥10% 且 恐慌分≥0.5'] = dict(rules=[['all', T(.10), ['mz', .5, 3]]])
        J['同时满足: 盈利≥8% 且 回到MA20'] = dict(rules=[['all', T(.08), ['ma20', 0, 2]]])
        J['同时满足: 盈利≥10% 且 收复50%'] = dict(rules=[['all', T(.10), ['recover', .5]]])
        J['同时满足: 收复100% 且 恐慌分≥0'] = dict(rules=[['all', ['recover', 1.0], ['mz', 0, 3]]])
        J['同时满足: 回到MA20+5% 且 恐慌分≥0.5'] = dict(rules=[['all', ['ma20', .05, 2], ['mz', .5, 3]]])
    if phase == 'nw':
        for N, k in ((10, 1.5), (10, 2.0), (5, 3.0), (5, 4.0)): J[f'名额 {N} 每只权重×{k}'] = dict(N=N, W={'A': .08 * k, 'C': .08 * k, 'B': .025 * k})
    if phase == 'pred':
        J['基线(2012起)'] = dict(start='2012-01-01')
        for k in (.5, .75, 1.0, 1.5): J[f'预测反弹高度×{k} 为目标(2012起)'] = dict(start='2012-01-01', rules=[['predt', k, .03]])
        for k in (.5, .75, 1.0): J[f'固定止盈(同期对照)波动率×{k}(2012起)'] = dict(start='2012-01-01', rules=[['volt', k]])
    if phase == 'nw':
        for N, k in ((10, 1.5), (10, 2.0), (5, 3.0), (5, 4.0)): J[f'名额 {N} 每只权重×{k}'] = dict(N=N, W={'A': .08 * k, 'C': .08 * k, 'B': .025 * k})
    if phase == 'rank2':
        for k in (10, 30, 40, 60): J[f'排序:{k}日跌幅'] = dict(rank=f'r{k}')
        J['排序:20日跌幅+距MA20 综合'] = dict(rank='comb')
        for sd in (11, 12): J[f'排序:随机(对照){sd}'] = dict(rank='rand', seed=sd)
    if phase == 'N':
        for N in (5, 10, 15, 30, 40): J[f'每层名额 {N}'] = dict(N=N)
    return J
def one(a):
    lab, kw = a; kw = dict(kw)
    if 'rules' in kw: kw['rules'] = [tuple(r) for r in kw['rules']]
    tr = []; eq, ex, trades = L.fused4(log=tr, **kw); return lab, L.stats(eq, ex, trades)
if __name__ == '__main__':
    if phase == 'pred':
        L.set_pred(np.load('X71.npy'), -2)
    fn = 'res70.json'; res = json.load(open(fn)) if os.path.exists(fn) else {}
    todo = [(k, v) for k, v in jobs(phase).items() if k not in res]; print('todo', len(todo), flush=True)
    pool = mp.get_context('fork').Pool(2); it = pool.imap_unordered(one, todo)
    try:
        for _ in todo:
            left = budget - (time.time() - T0)
            if left <= 0: break
            try: lab, s = it.next(timeout=left)
            except mp.TimeoutError: break
            res[lab] = s; json.dump(res, open(fn, 'w'), ensure_ascii=False)
            print(f'{lab:36s} 年化{s["cagr"]*100:+5.1f}% 夏普{s["sharpe"]:.2f} 回撤{s["dd"]*100:4.0f}% 仓位{s["expo"]*100:3.0f}% 前{(s["h1"] or 0)*100:+5.1f}% 后{(s["h2"] or 0)*100:+5.1f}% 笔{s.get("ntr")} 均持有{s.get("hold",0):.1f}天 单笔{s.get("tret",0)*1e4:+.0f}bp', flush=True)
    finally: pool.terminate()

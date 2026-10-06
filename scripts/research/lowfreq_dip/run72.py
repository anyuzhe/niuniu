"""Does the best holding period move with the panic window? Usage: python run72.py "10,20,40" "5,10,15,20,25,30,40,60" BUDGET [TH]. Resumable via res72.json. Research only."""
import sys, os, json, time, multiprocessing as mp
import numpy as np
import lib70 as L, lib72 as M
Ws = [int(x) for x in sys.argv[1].split(',')]; Hs = [int(x) for x in sys.argv[2].split(',')]; budget = float(sys.argv[3]); th = float(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] != 'x' else None; RK20 = os.environ.get('RK20') == '1'; MATCH = os.environ.get('MATCH') == '1'
SUF = ('' if th is None else f'_th{th}') + ('_rk20' if RK20 else '') + ('_match' if MATCH else '')
T0 = time.time(); F = 'res72.json'; res = json.load(open(F)) if os.path.exists(F) else {}
RK = {}
def one(a):
    W, H = a; eq, ex, tr = L.fused4(rank=RK['r'], H=H); st = L.stats(eq, ex, tr); return f'W{W}_H{H}' + SUF, st
for W in Ws:
    todo = [(W, H) for H in Hs if f'W{W}_H{H}' + SUF not in res]
    if not todo: continue
    thW = th
    if MATCH:
        thW = M.match_th(W, 413)
        print(f'W={W} matched threshold {thW:.2f}', flush=True)
    b = M.install(W, thW); RK['r'] = M.rW(20) if RK20 else b['rank']
    print(f'W={W} gate days A/C/B: {int(b["gate"]["A"].sum())}/{int(b["gate"]["C"].sum())}/{int(b["gate"]["B"].sum())}', flush=True)
    with mp.get_context('fork').Pool(2) as pool:
        for k, st in pool.imap_unordered(one, todo):
            res[k] = st; json.dump(res, open(F, 'w'), ensure_ascii=False)
            print(f"{k:14s} 年化{st['cagr']*100:+5.1f}% 夏普{st['sharpe']:.2f} 回撤{st['dd']*100:4.0f}% 仓位{st['expo']*100:3.0f}% 前{(st['h1'] or 0)*100:+.1f}% 后{(st['h2'] or 0)*100:+.1f}% 笔{st['ntr']} 持有{st['hold']:.1f}  [{time.time()-T0:.0f}s]", flush=True)
            if time.time() - T0 > budget: pool.terminate(); print('budget hit; rerun to resume'); sys.exit(0)
print('done', flush=True)

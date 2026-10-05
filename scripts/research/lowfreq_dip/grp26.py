"""D (A8%/C8%/B2.5% shared 1x, idle cash 2%) with 09:35 buy / 09:30 sell timing, 2020+ (min5 coverage). Research only."""
import grp11 as g
from grp11 import *
Z_ = np.load('fb.npz'); fo, fcl = Z_['fo'], Z_['fc']
ratio = np.where(np.isfinite(fo) & np.isfinite(fcl) & (fo > 0), fcl / fo, np.nan)
O0, C0 = g.O_.copy(), g.C_.copy()
g.SL['A'] = (gateA, cand.e6, cand.ret20); g.SL['B'] = (gateB, fcB.e6, fcB.ret20); g.SL['C'] = (gateC, fcC.e6, fcC.ret20)
S0 = 3163                                         # first day with min5 data (2020-01)
def stat(r, label, ex):
    x = r[S0:]; m = np.isfinite(x); x = x[m]; cum = np.cumprod(1 + x); n = len(x)
    cagr = cum[-1] ** (245 / n) - 1; sh = x.mean() / x.std() * np.sqrt(245); dd = (cum / np.maximum.accumulate(cum) - 1).min()
    yrs_ = np.array([int(d[:4]) for d in panel.dates])[S0:][m]; ys = {y: np.prod(1 + x[yrs_ == y]) - 1 for y in sorted(set(yrs_))}
    print(f'{label:40s} 年化{cagr*100:+6.1f}% 夏普{sh:.2f} 回撤{dd*100:4.0f}% 仓位{np.nanmean(ex[S0:])*100:3.0f}% | ' + ' '.join(f'{y%100}:{v*100:+.0f}' for y, v in ys.items()), flush=True)
def run(label, buy935, exit_open, H):
    g.O_ = np.where(np.isfinite(ratio), O0 * ratio, O0).astype(np.float32) if buy935 else O0
    g.C_ = O0 if exit_open else C0
    eq, ex, ntr, pnl, wsum, minr = g.fused(order='ACB', w={'A': .08, 'C': .08, 'B': .025}, G=1.0, cash_yield=0.02, H=H)
    stat(dr(eq), label, ex)
    print(f'{"":40s} ' + ' '.join(f'{s}:{ntr[s]}笔均{pnl[s]/max(ntr[s],1)*1e4:+.0f}bp' for s in ntr), flush=True)
print('=== D，2020 起（年化 / 夏普 / 回撤 / 仓位 | 逐年收益%）', flush=True)
run('1 基线：9:30 开盘买，第20日收盘卖', False, False, 20)
run('2 9:30 开盘买，第21日 9:30 卖', False, True, 21)
run('3 9:35 买，第20日收盘卖', True, False, 20)
run('4 9:35 买，第21日 9:30 卖（你的规则）', True, True, 21)
run('5 9:35 买，第20日 9:30 卖', True, True, 20)

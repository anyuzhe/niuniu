"""Intraday execution timing for strategies A/B/C: buy at 09:35 (close of first 5-min bar), sell at 09:30 (open). 2020+ only (min5 coverage). Research only."""
import copy
from grp11 import *
Z_ = np.load('fb.npz'); fo, fcl = Z_['fo'], Z_['fc']
ratio = np.where(np.isfinite(fo) & np.isfinite(fcl) & (fo > 0), fcl / fo, np.nan)
o0, c0 = panel.o, panel.c
# check consistency of first-bar open vs daily open (scale-free): ratio of fo to daily open should be ~ constant per stock/day only up to adjustment; report drift stats instead
ok = np.isfinite(ratio) & cand.uni
d = (ratio - 1)[ok & (np.arange(nd)[:, None] >= 3163)]
print(f'9:30->9:35 平均漂移 {np.nanmean(d)*1e4:+.1f}bp  中位 {np.nanmedian(d)*1e4:+.1f}bp  |漂移|>2% 占比 {(np.abs(d)>0.02).mean()*100:.1f}%', flush=True)
def mk_panel(entry935, exit_open):
    p = copy.copy(panel)
    o_new = np.where(np.isfinite(ratio), o0 * ratio, o0) if entry935 else o0
    c_new = o0 if exit_open else c0
    for k, v in (('o', o_new.astype(np.float32)), ('c', c_new.astype(np.float32))):
        try: setattr(p, k, v)
        except Exception: object.__setattr__(p, k, v)
    return p
def run(label, fm, fc, entry935, exit_open, hold):
    p = mk_panel(entry935, exit_open)
    cfg = DipConfig(leverage=1.0, hold_days=hold, start='2020-01-01')
    r = simulate(p, fm, fc, cfg); sm = summarize(p, fm, r, cfg); s2 = sm['stats'] or {}; tr = r['trades']
    print(f"{label:34s} 笔{len(tr):5d} 笔均{np.mean([t['ret'] for t in tr])*1e4:+5.0f}bp | 年化{s2.get('cagr',0)*100:+6.1f}% 夏普{s2.get('sharpe',0):+.2f} 回撤{s2.get('max_drawdown',0)*100:4.0f}% 仓位{s2.get('exposure',0)*100:3.0f}%", flush=True)
import sys
which = sys.argv[1]
S = {'A': (market, cand), 'B': (fmB, fcB), 'C': (fmC, fcC)}[which]
print(f'=== 策略 {which}，2020 起，1x，持有 20 日，扣成本', flush=True)
run('1 基线: 9:30开盘买, 收盘卖(t+20)', *S, False, False, 20)
run('2 9:35买, 收盘卖(t+20)', *S, True, False, 20)
run('3 9:30开盘买, 开盘卖(t+21)', *S, False, True, 21)
run('4 9:35买, 9:30开盘卖(t+21)', *S, True, True, 21)
run('5 9:35买, 9:30开盘卖(t+20)', *S, True, True, 20)

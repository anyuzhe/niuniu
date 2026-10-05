"""Shared-capital account: heavy per-position weight for the high-quality sleeves (A, C), light weight for B to fill idle capital. Research only."""
from grp11 import *
print('=== 1x 共用资金，优先级 A>C>B，闲置资金 2%；权重 = 每只占权益比例（A / C / B）', flush=True)
for wA, wC, wB, caps in ((.05, .05, .05, {'B': .5, 'C': .5}), (.08, .08, .025, {}), (.10, .10, .025, {}), (.08, .08, .04, {}), (.10, .08, .02, {}), (.10, .10, .01, {}), (.08, .08, .0, {}), (.10, .10, .0, {}), (.12, .12, .02, {})):
    order = 'ACB' if wB > 0 else 'AC'
    w = {'A': wA, 'C': wC, 'B': max(wB, 1e-9)}
    show(f'A{wA*100:g}% C{wC*100:g}% B{wB*100:g}%' + (' 且B/C≤50%' if caps else ''), order=order, w=w, G=1.0, caps=caps, cash_yield=0.02)

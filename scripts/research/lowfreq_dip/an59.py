import numpy as np, multiprocessing as mp
import grp56 as m
J = [(lab, ev, ma) for lab, ev in (('A:B C:B B:AC', {'A': 'B', 'C': 'B', 'B': 'AC'}), ('B:AC', {'B': 'AC'})) for ma in (0, 1, 3, 5)]
def one(a):
    lab, ev, ma = a; eq, ex, n, ntr = m.fused3(evict=ev, minage=ma); s = m.stats(eq, ex); return lab, ma, s, n
if __name__ == '__main__':
    with mp.get_context('fork').Pool(2) as p:
        for lab, ma, s, n in p.imap(one, J):
            print(f'{lab:14s} 最短持有 {ma} 天才允许被平: 年化{s["cagr"]*100:+5.1f}% 夏普{s["sharpe"]:.2f} 回撤{s["dd"]*100:4.0f}% 提前平仓{n}', flush=True)

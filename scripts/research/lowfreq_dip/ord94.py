import os, json, sys
import grp56 as G
import multiprocessing as mp
combos = {'A平C+B, C平B': dict(A='BC', C='B'), 'A平C': dict(A='C'), 'C平B': dict(C='B')}
def one(lab):
    ev = combos[lab]; eq, ex, n, ntr = G.fused3(evict=ev, minage=int(os.environ.get('MINAGE', 1)))
    r = G.stats(eq, ex); r.update(ev=n, ntr=ntr); return lab, r
if __name__ == '__main__':
    only = os.environ['COMBOS'].split('|')
    with mp.get_context('fork').Pool(2) as p:
        for lab, r in p.imap_unordered(one, only):
            print(os.environ['EVORD'], lab, f'{r["cagr"]*100:+.1f}% sh{r["sharpe"]:.2f} dd{r["dd"]*100:.0f}% 提前平{r["ev"]}', flush=True)
            json.dump({lab: r}, open(f'ord94_{os.environ["EVORD"]}_{lab.replace(" ","").replace(",","_")}.json', 'w'), ensure_ascii=False)

import numpy as np
exec(open('fundtest.py').read().split("# ---- coverage")[0])
def mc_rank(base_pool):
    # per-day combined rank: ret20 rank + market-cap rank (small first), only on signal days
    R=np.full((nd,nc),9e9,np.float32); Rm=np.full((nd,nc),9e9,np.float32)
    for t in np.nonzero(sig&(np.arange(nd)>260))[0]:
        cs=np.nonzero(base_pool[t])[0]
        if not len(cs): continue
        a=ret20[t,cs]; m=np.where(np.isfinite(mcap[t,cs]),mcap[t,cs],np.inf)
        ra=np.argsort(np.argsort(a)); rm=np.argsort(np.argsort(m))
        R[t,cs]=ra+rm; Rm[t,cs]=rm
    return R,Rm
debt70=np.isfinite(debt)&(debt>70); pl30=np.isfinite(pl)&(pl>30); pl50=np.isfinite(pl)&(pl>50); npneg=np.isfinite(npy)&(npy<0)
quality=loss|fcneg|debt70|pl50
big=np.zeros((nd,nc),bool); small=np.zeros((nd,nc),bool)
for t in np.nonzero(sig&(np.arange(nd)>260))[0]:
    cs=np.nonzero(e6[t]&np.isfinite(mcap[t]))[0]
    if len(cs)>3:
        q=np.median(mcap[t][np.nonzero(cand_all[t]&np.isfinite(mcap[t]))[0]]); small[t,cs]=mcap[t][cs]<=q; big[t,cs]=mcap[t][cs]>q
Rc,Rm=mc_rank(e6)
print('\n[3] 组合层面（门 z<=-1.5，N=20，次日开盘买持有20天；列=各时期年化/夏普/回撤；括号外 1x，下一行 2x 年代利率）')
print('格式：年化/夏普/回撤；列='+' | '.join(ERA))
def run(tag,pool,rank=ret20):
    for L in (1.0,2.0):
        r=portfolio_lev(sig,pool,20,L,rank=rank); pr(f'{tag} {L:g}x',*r)
run('基线 跌幅排序',e6)
run('剔除 资产负债率>70%',e6&~debt70)
run('剔除 质押>30%',e6&~pl30)
run('剔除 亏损(PE<=0)',e6&~loss)
run('剔除 业绩预告为负',e6&~fcneg)
run('剔除 净利润同比<0',e6&~npneg)
run('剔除 质量差(亏损|预告负|负债>70|质押>50)',e6&~quality)
run('剔除 负债>70%且质押>30%',e6&~(debt70|pl30))
run('只保留 市值较小一半',e6&small)
run('只保留 市值较大一半',e6&big)
run('排序=市值最小优先',e6,rank=Rm)
run('排序=跌幅+小市值(两名次相加)',e6,rank=Rc)
run('基线随机选(对照)',e6,rank=None)
print('done',round(time.time()-T0))

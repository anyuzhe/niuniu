import numpy as np
exec(open('fundtest.py').read().split("# ---- coverage")[0])
npneg=np.isfinite(npy)&(npy<0)
cands={'基线':e6,'剔除亏损':e6&~loss,'剔除业绩预告为负':e6&~fcneg,'剔除净利润同比<0':e6&~npneg,'剔除三者任一':e6&~(loss|fcneg|npneg),'剔除三者任一(净利润同比<-30%)':e6&~(loss|fcneg|(np.isfinite(npy)&(npy<-30)))}
print('随机选股(8种子) 1x 全期年化/夏普 均值 [最小,最大]；对比排序选股')
for nm,pool in cands.items():
    out=[]
    for s in range(8):
        eq,ex_,tr,_=portfolio_lev(sig,pool,20,1.0,rank=None,seed=s); st=stats(eq,ex_,'2008-01-01','2026-12-31'); out.append((st[0],st[1],st[2]))
    a=np.array(out); r=portfolio_lev(sig,pool,20,1.0,rank=ret20); sr=stats(r[0],r[1],'2008-01-01','2026-12-31')
    print(f'  {nm:24s} 随机 年化{a[:,0].mean()*100:+.1f}% [{a[:,0].min()*100:+.1f},{a[:,0].max()*100:+.1f}] 夏普{a[:,1].mean():.2f} 回撤{a[:,2].mean()*100:.0f}% | 排序 年化{sr[0]*100:+.1f}% 夏普{sr[1]:.2f} 回撤{sr[2]*100:.0f}%',flush=True)
# episode-level: does the filtered portfolio beat baseline in each calendar year?  (ranked, 1x)
base=portfolio_lev(sig,e6,20,1.0,rank=ret20)[0]; fl=portfolio_lev(sig,e6&~(loss|fcneg|npneg),20,1.0,rank=ret20)[0]
print('\n逐年(1x 排序)：基线 / 剔除三者任一 / 差')
w=0;n=0
for y in range(2008,2027):
    ii=np.nonzero(np.char.startswith(dates,str(y))&np.isfinite(base))[0]
    if len(ii)<20: continue
    a=base[ii[-1]]/base[ii[0]]-1; b=fl[ii[-1]]/fl[ii[0]]-1
    if abs(a)>1e-9 or abs(b)>1e-9: n+=1; w+=b>a+1e-9
    print(f'  {y}: {a*100:+6.1f}% / {b*100:+6.1f}% / {(b-a)*100:+5.1f}')
print('有交易的年份里，过滤后更好的年数',w,'/',n)
print('done',round(time.time()-T0))

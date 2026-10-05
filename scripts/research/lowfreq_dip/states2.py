"""Sleeves for the non-panic z-states + combination with the panic sleeve. Research only."""
import sys; sys.argv=['x','core']
src=open('allyears.py').read().split("if GROUP=='core':")[0]
exec(src)
import numpy as np
p10=np.nanpercentile(np.where(valid,ret20,np.nan),10,axis=1)
loser=valid&(ret20<=p10[:,None])
S={'偏弱':(zv>-1.5)&(zv<=-0.5),'中性':(zv>-0.5)&(zv<=0.5),'偏强':(zv>0.5)&(zv<=1.5),'过热':(zv>1.5)}
def run(name,gate,pool,L=1.0,rank='ret20',N=20,**kw):
    eq,ex_,tr,nl,mr_=sim(N=N,gate=gate,pool=pool,L=L,rank=rank,**kw)
    s=stats(eq,ex_,'2008-01-01','2026-12-31')
    print(f'{name:42s} 年化{s[0]*100:+5.1f}% 夏普{s[1]:+.2f} 回撤{s[2]*100:4.0f}% 平均仓位{s[3]*100:3.0f}% 笔{len(tr)} 笔均{tr[:,0].mean()*1e4 if len(tr) else 0:+.0f}bp',flush=True)
    return eq
def dr(eq):
    r=np.full(nd,np.nan); r[1:]=eq[1:]/eq[:-1]-1; return r
def cstats(r,label):
    m=np.isfinite(r); x=r[m]; cum=np.cumprod(1+x); yrs=len(x)/245
    print(f'{label:42s} 年化{(cum[-1]**(1/yrs)-1)*100:+5.1f}% 夏普{x.mean()/x.std()*np.sqrt(245):+.2f} 回撤{(cum/np.maximum.accumulate(cum)-1).min()*100:4.0f}%',flush=True)
    return cum
P=run('恐慌 E6 2x（现策略）',zv<=-1.5,e6,L=2.0)
print('--- 各状态用“20日最弱10%”池（排序按20日跌幅）1x')
EQ={}
for k,g in S.items(): EQ[k]=run(f'{k} 最弱10% 1x',g,loser)
print('--- 对照：同样的状态，随机候选 / E6池')
for k in ('偏弱','中性'):
    run(f'{k} 全部候选随机 1x',S[k],cand_all,rank=None); run(f'{k} E6池 1x',S[k],e6)
print('--- 偏弱 变体')
run('偏弱 最弱10% 1.5x',S['偏弱'],loser,L=1.5)
run('偏弱 最弱10% 1x N=10',S['偏弱'],loser,N=10)
run('偏弱 最弱10% 1x 持有10天',S['偏弱'],loser,hold=10)
g2=(zv>-1.5)&(zv<=-1.0); run('仅 -1.5<z≤-1.0 最弱10% 1x',g2,loser)
g3=(zv>-1.0)&(zv<=-0.5); run('仅 -1.0<z≤-0.5 最弱10% 1x',g3,loser)
g4=(zv>-0.5)&(zv<=0.0); run('仅 -0.5<z≤0 最弱10% 1x',g4,loser)
print('--- 与恐慌子策略合并（日收益相加，两个子策略各用一份本金，总杠杆最高 2x+W）')
rP=dr(P); rW=dr(EQ['偏弱'])
m=np.isfinite(rP)&np.isfinite(rW)
print('相关(日收益)', round(np.corrcoef(rP[m],rW[m])[0,1],2), '  仅偏弱子策略与大盘日收益相关', round(np.corrcoef(rW[m&np.isfinite(mr)],mr[m&np.isfinite(mr)])[0,1],2))
for k in (0,0.5,1.0):
    cstats(np.where(m,rP+k*rW,np.nan),f'恐慌2x + {k:g}×偏弱最弱10%')
# yearly of W alone and combined
yr=np.array([int(d[:4]) for d in dates])
def ytab(r,label):
    s=[]
    for y in range(2008,2027):
        mm=(yr==y)&np.isfinite(r)
        s.append('  - ' if mm.sum()<20 else f'{(np.prod(1+r[mm])-1)*100:+4.0f}')
    print(f'{label:20s}',' '.join(s))
print('年份'.ljust(20),' '.join(f'{y%100:4d}' for y in range(2008,2027)))
ytab(rP,'恐慌2x'); ytab(rW,'偏弱最弱10% 1x'); ytab(np.where(m,rP+rW,np.nan),'合并 2x+1x')

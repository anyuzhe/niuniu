import sys; sys.argv=['x','core']
exec(open('states2.py').read().split("p10=np.nanpercentile")[0])
import numpy as np
M=np.load('s6_masks.npz'); low=M['成交额最低20%(小盘代理)']; weak=M['20日最弱10%']
yr=np.array([int(d[:4]) for d in dates])
def dr(eq):
    r=np.full(nd,np.nan); r[1:]=eq[1:]/eq[:-1]-1; return r
def run(name,gate,pool,L=1.0,rank='ret20',N=20,hold=20):
    eq,ex_,tr,nl,mr_=sim(N=N,hold=hold,gate=gate,pool=pool,L=L,rank=rank)
    s=stats(eq,ex_,'2008-01-01','2026-12-31'); rr=dr(eq); h=[]
    for a,b in ((2008,2016),(2017,2026)):
        mm=(yr>=a)&(yr<=b)&np.isfinite(rr); x=rr[mm]; cum=np.cumprod(1+x); h.append(f'{(cum[-1]**(245/len(x))-1)*100:+.1f}%/{x.mean()/x.std()*np.sqrt(245):.2f}')
    print(f'{name:46s} 年化{s[0]*100:+5.1f}% 夏普{s[1]:+.2f} 回撤{s[2]*100:4.0f}% 仓位{s[3]*100:3.0f}% 笔{len(tr)} | 前半{h[0]} 后半{h[1]}',flush=True)
    return eq
up=zv>-0.5; wk=(zv>-1.5)&(zv<=-0.5); allg=np.isfinite(zv)
print('--- 非恐慌三档以上(z>-0.5)，持有60天，N=30，1x')
A=run('小盘代理(成交额最低20%) 随机30只',up,low,rank=None,N=30,hold=60)
run('小盘代理 按20日最弱优先30只',up,low,rank='ret20',N=30,hold=60)
run('对照：全部候选 随机30只',up,valid,rank=None,N=30,hold=60)
print('--- 偏弱，持有60天 / 20天')
run('偏弱 小盘代理 随机30只 60天',wk,low,rank=None,N=30,hold=60)
run('偏弱 对照 全部候选随机30只 60天',wk,valid,rank=None,N=30,hold=60)
print('--- 任何日子(always-on)')
run('任何状态 小盘代理 随机30只 60天',allg,low,rank=None,N=30,hold=60)
run('任何状态 对照 全部候选随机30只 60天',allg,valid,rank=None,N=30,hold=60)
print('--- 与恐慌2x合并')
P=run('恐慌 E6 2x（现策略）',zv<=-1.5,e6,L=2.0)
rP=dr(P); rA=dr(A); m=np.isfinite(rP)&np.isfinite(rA)
def cs(r,label):
    mm=np.isfinite(r); x=r[mm]; cum=np.cumprod(1+x); h=[]
    for a,b in ((2008,2016),(2017,2026)):
        k=(yr>=a)&(yr<=b)&mm; y=r[k]; c2=np.cumprod(1+y); h.append(f'{(c2[-1]**(245/len(y))-1)*100:+.1f}%/{y.mean()/y.std()*np.sqrt(245):.2f}')
    print(f'{label:46s} 年化{(cum[-1]**(245/len(x))-1)*100:+5.1f}% 夏普{x.mean()/x.std()*np.sqrt(245):.2f} 回撤{(cum/np.maximum.accumulate(cum)-1).min()*100:4.0f}% | 前半{h[0]} 后半{h[1]}')
print('相关',round(np.corrcoef(rP[m],rA[m])[0,1],2))
for a in (1.0,0.75,0.5): cs(np.where(m,a*rP+(1-a)*rA,np.nan),f'恐慌2x {a:.2f} + 小盘(z>-0.5)1x {1-a:.2f}')
print('年份'.ljust(22),' '.join(f'{y%100:4d}' for y in range(2008,2027)))
def ytab(r,label):
    s=[]
    for y in range(2008,2027):
        mm=(yr==y)&np.isfinite(r); s.append('  - ' if mm.sum()<20 else f'{(np.prod(1+r[mm])-1)*100:+4.0f}')
    print(f'{label:22s}',' '.join(s))
ytab(rP,'恐慌2x'); ytab(rA,'小盘(z>-0.5)'); ytab(np.where(m,0.75*rP+0.25*rA,np.nan),'75/25')

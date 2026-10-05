import sys
src=open('ind1.py').read().split("P=run('现策略")[0]
exec(src)
yr=np.array([int(d[:4]) for d in dates])
def dr(eq):
    r=np.full(nd,np.nan); r[1:]=eq[1:]/eq[:-1]-1; return r
def halves(eq):
    rr=dr(eq); h=[]
    for a,b_ in ((2008,2016),(2017,2026)):
        k=(yr>=a)&(yr<=b_)&np.isfinite(rr); y=rr[k]; c2=np.cumprod(1+y); h.append(f'{(c2[-1]**(245/len(y))-1)*100:+.1f}%/{y.mean()/y.std()*np.sqrt(245):.2f}')
    return h
def run(name,gate,pool,L=1.0,**kw):
    eq,ex_,tr,nl,mr_=sim(gate=gate,pool=pool,L=L,**kw)
    s=stats(eq,ex_,'2008-01-01','2026-12-31'); h=halves(eq); mn='' if mr_==9.0 else f' 最低保证金比{mr_:.2f}'
    print(f'{name:50s} 年化{s[0]*100:+5.1f}% 夏普{s[1]:+.2f} 回撤{s[2]*100:4.0f}% 仓位{s[3]*100:3.0f}% 笔{len(tr)} 笔均{tr[:,0].mean()*1e4 if len(tr) else 0:+.0f}bp 强平{nl}{mn} | 前半{h[0]} 后半{h[1]}',flush=True); return eq
allg=np.isfinite(zv)
# episodes
pg=(zind<=-1.5)&nonp[:,None]
ep=0; indep={}
for g in u:
    idx=np.nonzero(ind==g)[0][0]; dd=np.nonzero(pg[:,idx])[0]
    e_=0; last=-99
    for t in dd:
        if t-last>=20: e_+=1
        last=t
    indep[g]=e_; ep+=e_
print('行业恐慌段数(各行业间隔>=20天算新一段, 大盘非恐慌日):',ep,' 31个行业,平均每行业',round(ep/31,1),'段',flush=True)
base=valid&(zind<=-1.5)&nonp[:,None]
print('--- 基准：行业恐慌(z_g<=-1.5, 大盘z>-1.5)，候选=行业内全部可交易股，按20日跌幅排序，N=20')
B1=run('基准 1x',allg,base); B2=run('基准 2x',allg,base,L=2.0)
print('--- 稳健性')
run('随机选(不按跌幅排序) 1x',allg,base,rank=None)
run('对照:行业平静日(-0.5<z_g<=0.5)同样选法 1x',allg,valid&(zind>-0.5)&(zind<=0.5)&nonp[:,None])
run('对照:行业偏弱(-1.5<z_g<=-0.5)同样选法 1x',allg,valid&(zind>-1.5)&(zind<=-0.5)&nonp[:,None])
for th in (-1.0,-2.0): run(f'阈值 z_g<={th} 1x',allg,valid&(zind<=th)&nonp[:,None])
for N in (10,30,50): run(f'N={N} 1x',allg,base,N=N)
for hd in (10,40): run(f'持有{hd}天 1x',allg,base,hold=hd)
run('不限大盘状态(含大盘恐慌日) 1x',allg,valid&(zind<=-1.5))
rel=valid&(zind<=-1.5)&nonp[:,None]
# relative: industry 20d return minus market 20d return <= -5% -> need industry ret; approximate via z difference: zind - zv <= -1.0
run('行业显著弱于大盘(z_g-z<=-1.0) 且z_g<=-1.5 1x',allg,valid&(zind<=-1.5)&((zind-np.where(np.isfinite(zv),zv,0)[:,None])<=-1.0)&nonp[:,None])
print('--- 与大盘恐慌子策略 P(2x) 合并')
P=np.load('ind1_eq.npz')['P']; rP=dr(P)
def cs(r,label):
    m=np.isfinite(r); x=r[m]; cum=np.cumprod(1+x); h=[]
    for a,b_ in ((2008,2016),(2017,2026)):
        k=(yr>=a)&(yr<=b_)&m; y=r[k]; c2=np.cumprod(1+y); h.append(f'{(c2[-1]**(245/len(y))-1)*100:+.1f}%/{y.mean()/y.std()*np.sqrt(245):.2f}')
    print(f'{label:50s} 年化{(cum[-1]**(245/len(x))-1)*100:+5.1f}% 夏普{x.mean()/x.std()*np.sqrt(245):.2f} 回撤{(cum/np.maximum.accumulate(cum)-1).min()*100:4.0f}% | 前半{h[0]} 后半{h[1]}',flush=True); return cum
for nm,I in (('1x',B1),('2x',B2)):
    rI=dr(I); m=np.isfinite(rP)&np.isfinite(rI); print('  相关',nm,round(np.corrcoef(rP[m],rI[m])[0,1],2))
    for a in (0.75,0.6,0.5): cs(np.where(m,a*rP+(1-a)*rI,np.nan),f'  大盘恐慌2x {a:.2f} + 行业恐慌{nm} {1-a:.2f}')
# utilization of combined 0.5/0.5: average gross exposure
rI=dr(B1); m=np.isfinite(rP)&np.isfinite(rI)
def ytab(r,label):
    s=[]
    for y in range(2008,2027):
        mm=(yr==y)&np.isfinite(r); s.append('  - ' if mm.sum()<20 else f'{(np.prod(1+r[mm])-1)*100:+4.0f}')
    print(f'{label:22s}',' '.join(s))
print('年份'.ljust(22),' '.join(f'{y%100:4d}' for y in range(2008,2027)))
ytab(rP,'大盘恐慌2x'); ytab(rI,'行业恐慌1x'); ytab(np.where(m,0.6*rP+0.4*rI,np.nan),'合并 0.6/0.4')
np.savez('ind2_eq.npz',B1=B1,B2=B2)

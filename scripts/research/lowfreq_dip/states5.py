import sys; sys.argv=['x','core']
exec(open('states2.py').read().split("P=run(")[0])
yr=np.array([int(d[:4]) for d in dates])
pan=zv<=-1.5; g2=(zv>-1.5)&(zv<=-1.0); gate=pan|g2
def run2(name,gate,pool,Lfun=None,L=1.0,N=20):
    eq,ex_,tr,nl,mr_=sim(N=N,gate=gate,pool=pool,L=L,Lfun=Lfun)
    s=stats(eq,ex_,'2008-01-01','2026-12-31')
    rr=dr(eq); h=[]
    for a,b in ((2008,2016),(2017,2026)):
        mm=(yr>=a)&(yr<=b)&np.isfinite(rr); x=rr[mm]; cum=np.cumprod(1+x); h.append(f'{(cum[-1]**(245/len(x))-1)*100:+.1f}%/{x.mean()/x.std()*np.sqrt(245):.2f}')
    mn='' if mr_==9.0 else f' 最低保证金比{mr_:.2f}'
    print(f'{name:44s} 年化{s[0]*100:+5.1f}% 夏普{s[1]:.2f} 回撤{s[2]*100:4.0f}% 仓位均{s[3]*100:3.0f}%/峰{ex_.max():.1f}x 笔{len(tr)} 强平{nl}{mn} | 前半{h[0]} 后半{h[1]}',flush=True)
    return eq
mixpool=np.where(pan[:,None],e6,loser); mixpool_e6=e6
print('A. 单一账户、共用 20 个仓位（z≤-1.0 开仓；恐慌用 E6，第二档用指定池）')
P=run2('0 仅恐慌档 2x（现策略）',pan,e6,L=2.0)
E1=run2('1 两档都2x，第二档=最弱10%',gate,mixpool,Lfun=lambda z:2.0)
E2=run2('2 恐慌2x/第二档1x，第二档=最弱10%',gate,mixpool,Lfun=lambda z:2.0 if z<=-1.5 else 1.0)
E3=run2('3 恐慌2x/第二档1x，第二档=E6',gate,mixpool_e6,Lfun=lambda z:2.0 if z<=-1.5 else 1.0)
E4=run2('4 同2，N=30',gate,mixpool,Lfun=lambda z:2.0 if z<=-1.5 else 1.0,N=30)
print('B. 两个独立子账户按固定资金比例每日再平衡（总杠杆上限=2x，不再叠加）')
W2=run2('第二档单独 2x（最弱10%）',g2,loser,L=2.0)
rP=dr(P); rW=dr(W2); m=np.isfinite(rP)&np.isfinite(rW)
def cs(r,label):
    mm=np.isfinite(r); x=r[mm]; cum=np.cumprod(1+x); h=[]
    for a,b in ((2008,2016),(2017,2026)):
        k=(yr>=a)&(yr<=b)&mm; y=r[k]; c2=np.cumprod(1+y); h.append(f'{(c2[-1]**(245/len(y))-1)*100:+.1f}%/{y.mean()/y.std()*np.sqrt(245):.2f}')
    print(f'{label:44s} 年化{(cum[-1]**(245/len(x))-1)*100:+5.1f}% 夏普{x.mean()/x.std()*np.sqrt(245):.2f} 回撤{(cum/np.maximum.accumulate(cum)-1).min()*100:4.0f}% | 前半{h[0]} 后半{h[1]}'); return cum
for a in (0.75,0.6,0.5): cs(np.where(m,a*rP+(1-a)*rW,np.nan),f'恐慌2x {a:.2f} + 第二档2x {1-a:.2f}')
print('C. 逐年（%）')
print('年份'.ljust(26),' '.join(f'{y%100:4d}' for y in range(2008,2027)))
def ytab(r,label):
    s=[]
    for y in range(2008,2027):
        mm=(yr==y)&np.isfinite(r)
        s.append('  - ' if mm.sum()<20 else f'{(np.prod(1+r[mm])-1)*100:+4.0f}')
    print(f'{label:26s}',' '.join(s))
ytab(rP,'0 仅恐慌档 2x'); ytab(dr(E1),'1 共用仓位 2x/2x'); ytab(dr(E2),'2 共用仓位 2x/1x'); ytab(np.where(m,0.75*rP+0.25*rW,np.nan),'B 0.75/0.25 子账户')
# how often is the second gear's capital blocking panic entries?
act=pan&np.isfinite(zv)
print('恐慌日数',int(pan.sum()),' 第二档日数',int(g2.sum()),' 第二档日里20个交易日内随后进入恐慌的比例 %.0f%%'%(100*np.mean([pan[t+1:t+21].any() for t in np.nonzero(g2)[0] if t+21<nd])))

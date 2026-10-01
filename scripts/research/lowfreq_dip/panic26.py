import numpy as np, warnings; warnings.filterwarnings('ignore')
import swingbook as S
from swingbook import *
mk=np.load('mkreg.npz'); mk20=mk['mk20']; mret=mk['mret']; idx=np.cumprod(1+mret)
r=ret1.astype(np.float64); mm=np.repeat(mret[:,None],nc,1)
rz=np.where(np.isfinite(r),r,0.0)
n=60; Er=roll(rz,n)/n; Em=roll(mm,n)/n; Erm=roll(rz*mm,n)/n; Emm=roll(mm*mm,n)/n
beta=(Erm-Er*Em)/np.maximum(Emm-Em*Em,1e-12); beta=np.clip(beta,-1,4)
E6=(sh(c,1)<sh(blo,1))&(c>blo)&(c>o_)
ok0=uni&lst250&(R>=3)&E6
panic=(mk20<=-0.036)
H=20; rows=[]
for t in np.nonzero(panic)[0]:
    e=t+1
    if e>=nd-1: continue
    cs=np.nonzero(ok0[t]&fin[e]&~limup_open[e])[0]
    if len(cs)==0: continue
    x=min(e+H,nd-1); done=(e+H<=nd-1)
    # exit at last available valid close
    Cx=C[x,cs]; Cx=np.where(np.isfinite(Cx),Cx,c[x,cs])
    o=O[e,cs]; rawE=Ro[e,cs]; rawX=rawE*Cx/o
    gross=Cx/o-1; net=Cx*(1-0.01/rawX)/(o*(1+0.01/rawE))-1-FEE
    m=idx[x]/idx[e-1]-1; b=beta[t,cs]
    rows.append((t,len(cs),done,np.nanmean(gross),np.nanmean(net),np.nanmean(net>0),m,np.nanmean(b),np.nanmean(gross-b*m),np.nanmean((b-1)*m),np.nanmean(Cx/o-1 - (C[t,cs]/C[t-20,cs]-1)*0),np.nanmean(C[t,cs]/C[max(t-20,0),cs]-1)))
rows=np.array([[*x] for x in rows],dtype=float)
D=dates[rows[:,0].astype(int)]
def seg(mask):
    # gap-based episodes among selected rows
    ii=np.nonzero(mask)[0]; out=[[ii[0]]]
    for i in ii[1:]:
        (out[-1].append(i) if rows[i,0]-rows[out[-1][-1],0]<=5 else out.append([i]))
    return out
def show(title,mask):
    print('\n==',title)
    allw=[]
    for s in seg(mask):
        a=rows[s]; w=a[:,1]
        wm=lambda col: (a[:,col]*w).sum()/w.sum()
        comp=a[:,2].all()
        print(f'{D[s[0]]}~{D[s[-1]]} 信号日{len(s)}个 E6信号{int(w.sum())}只次{"" if comp else "(含未满20天)"} | 股票平均毛{wm(3)*1e4:+.0f} 净{wm(4)*1e4:+.0f}bp 胜率{wm(5)*100:.0f}% | 同窗口大盘等权{a[:,6].mean()*1e4:+.0f}bp | 平均beta{wm(7):.2f} 前20日已跌{wm(11)*100:.1f}% | 毛收益拆分: 大盘{a[:,6].mean()*1e4:+.0f} + beta放大{wm(9)*1e4:+.0f} + 选股残差{wm(8)*1e4:+.0f}')
y26=np.char.startswith(D,'2026'); show('2026 年恐慌日',y26)
for pn,(a,b) in per.items():
    mk_=(D>=a)&(D<=b)&(rows[:,2]==1)
    w=rows[mk_,1]; wm=lambda col:(rows[mk_,col]*w).sum()/w.sum()
    print(f'\n{pn} 全部恐慌日(已满20天) 信号日{mk_.sum()}个 E6 {int(w.sum())}: 股票毛{wm(3)*1e4:+.0f} 净{wm(4)*1e4:+.0f} 胜率{wm(5)*100:.0f}% | 大盘{rows[mk_,6].mean()*1e4:+.0f} | beta{wm(7):.2f} | 拆分: 大盘{rows[mk_,6].mean()*1e4:+.0f} + beta放大{wm(9)*1e4:+.0f} + 残差{wm(8)*1e4:+.0f}')
# market forward after panic vs non-panic days, all history
fw=np.full(nd,np.nan); 
for t in range(1,nd-21): fw[t]=idx[t+20]/idx[t]-1
yy=(dates>='2020-01-01')&np.isfinite(fw)
print('\n大盘等权 次日起20天涨幅: 恐慌日均值 %+.1f%% (n=%d) 非恐慌日 %+.1f%%; 恐慌日里为正的比例 %.0f%%'%(fw[yy&panic].mean()*100,(yy&panic).sum(),fw[yy&~panic].mean()*100,(fw[yy&panic]>0).mean()*100))
# panic by depth buckets
for lo,hi in [(-0.06,-0.036),(-0.09,-0.06),(-0.5,-0.09)]:
    mm_=yy&(mk20>lo)&(mk20<=hi); print(f'  20日跌幅 ({lo*100:.0f}%,{hi*100:.1f}%]: n={mm_.sum()} 之后20天均值{fw[mm_].mean()*100:+.1f}% 正比例{(fw[mm_]>0).mean()*100:.0f}%')

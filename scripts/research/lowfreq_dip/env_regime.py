import sys, numpy as np, os
sys.path.insert(0,os.path.expanduser('~/mnt/niuniu/src'))
from quantlab.dipbuy.panel import Panel
from quantlab.dipbuy import engine as E
P=Panel.from_npz('panel_ext.npz'); mk,cd=E.compute_features(P)
dates=P.dates; nd=len(dates); idx=np.cumprod(1+mk.mret)
ma250=np.full(nd,np.nan); 
cs=np.cumsum(idx); ma250[249:]=(cs[249:]-np.concatenate([[0],cs[:-250]]))/250
trend=idx/ma250-1
ret60=np.full(nd,np.nan); ret60[60:]=idx[60:]/idx[:-60]-1
cfg=E.DipConfig(leverage=1.0,end=str(dates[nd-23]))
r=E.simulate(P,mk,cd,cfg)
tr=r['trades']; di={d:i for i,d in enumerate(dates)}
rows=[]
for t in tr:
    s=di[t['signal']]; e=di[t['entry']]; x=di[t['exit']]
    rows.append((s,mk.z[s],trend[s],ret60[s],idx[x]/idx[e]-1,t['ret'],int(t['signal'][:4])))
A=np.array(rows,float); print('trades',len(A))
def grp(name,key,bins,labels):
    print(f'\n== {name}  (按信号日分组；每笔净收益均值 / 同期等权大盘涨跌 / 超额 / 胜率 / 笔数 / 信号日数)')
    for lo,hi,lab in zip(bins[:-1],bins[1:],labels):
        m=(key>=lo)&(key<hi)
        if m.sum()<5: continue
        n=A[m,5]; b=A[m,4]
        print(f'{lab:14s} {n.mean()*100:+6.1f}% / {b.mean()*100:+6.1f}% / {(n-b).mean()*100:+6.1f}pt / 胜率{(n>0).mean()*100:3.0f}% / {m.sum():4d}笔 / {len(set(A[m,0])):3d}天')
grp('闸门深度 z',A[:,1],[-99,-3,-2.5,-2,-1.5],['z<-3','-3~-2.5','-2.5~-2','-2~-1.5'])
grp('大盘相对250日均线(信号日)',A[:,2],[-9,-0.15,-0.08,-0.03,0.03,9],['<-15%','-15~-8%','-8~-3%','-3~+3%','>+3%'])
grp('信号前60日大盘涨跌',A[:,3],[-9,-0.25,-0.15,-0.08,0,9],['<-25%','-25~-15%','-15~-8%','-8~0%','>0%'])
grp('之后持有期大盘涨跌(事后)',A[:,4],[-9,-0.10,-0.03,0.03,0.10,9],['<-10%','-10~-3%','-3~+3%','+3~+10%','>+10%'])
print('\n逐年: 笔数 每笔均值 同期大盘 超额')
for y in range(2008,2027):
    m=A[:,6]==y
    if m.sum(): print(y,int(m.sum()),f'{A[m,5].mean()*100:+.1f}% {A[m,4].mean()*100:+.1f}% {(A[m,5]-A[m,4]).mean()*100:+.1f}pt')
# overall market after big drops: relation
print('\n每笔净收益与持有期大盘涨跌的相关',np.corrcoef(A[:,5],A[:,4])[0,1],' 回归斜率(beta)',np.polyfit(A[:,4],A[:,5],1))

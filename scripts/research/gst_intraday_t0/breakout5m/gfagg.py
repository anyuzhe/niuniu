import pickle, numpy as np, os
H=os.environ['HOME']; A={}
for y in range(2020,2027):
    o=pickle.load(open(f'{H}/research/brk/gf_{y}.pkl','rb'))
    for k,v in o.items(): A.setdefault(k,[]).append(v)
A={k:np.concatenate(v) for k,v in A.items()}
d=A['date']; yr=np.array([x[:4] for x in d]); g=A['gap']
P={'20-22':d<'2023','23-24':(d>='2023')&(d<'2025'),'25-26':d>='2025'}
ud,inv=np.unique(d,return_inverse=True)
def st(y,mk):
    mk=mk&np.isfinite(y); y2=y[mk]; w=y2>0; m=y2.mean(); r=np.bincount(inv[mk],y2-m)
    return f"{m:+6.1f}bp 胜{w.mean()*100:3.0f}% 赔{y2[w].mean()/-y2[~w].mean():.2f} t{m/(np.sqrt((r**2).sum())/len(y2)):+4.1f} n{mk.sum()} 天{len(np.unique(inv[mk]))}"
def show(lab,y,mk):
    print(f"  {lab:24s}"+''.join(f" | {p} {st(y,mk&pm)}" for p,pm in P.items()))
y=A[('time','收盘')]
print('收盘买回（封板则次日开盘买回），按高开幅度：')
for lo,hi in ((0.04,0.05),(0.05,0.06),(0.06,0.07),(0.07,0.08),(0.08,0.2)):
    show(f'高开{lo*100:g}-{hi*100:g}%',y,(g>=lo)&(g<hi))
m7=g>=0.07
print('\n高开≥7%，各买回方式：')
for k in [k for k in A if isinstance(k,tuple) and k[0] in ('time','limit','stop')]:
    show(str(k),A[k],m7)
print('\n高开≥7% 收盘买回，分组：')
show('昨日涨停',y,m7&(A['plu']>0)); show('昨日未涨停',y,m7&(A['plu']==0))
show('创业板/科创板(20%)',y,m7&A['cy']); show('主板(10%)',y,m7&~A['cy'])
print('  收盘封板比例',{p:round(A[('sealedfrac','收盘')][m7&pm].mean(),3) for p,pm in P.items()})
print('\n高开≥7% 收盘买回，逐年：')
for Y in sorted(set(yr)):
    mk=m7&(yr==Y); yy=y[mk]; print(f'  {Y} 每笔{yy.mean():+6.1f}bp 胜{(yy>0).mean()*100:3.0f}% n{mk.sum()} 最差{yy.min():.0f} 最好{yy.max():.0f}')
print('\n高开≥7%，全部 2020-2026 合并与逐年（去掉次日价格缺失的）:')
for k in (('time','收盘'),('stop',0.05),('stop',0.03),('limit',0.05)):
    y=A[k]; mk=m7&np.isfinite(y)
    yy=y[mk]; ii=inv[mk]; mm=yy.mean(); rr=np.bincount(ii,yy-mm); t=mm/(np.sqrt((rr**2).sum())/len(yy))
    per=' '.join(f"{Y}:{y[mk&(yr==Y)].mean():+.0f}" for Y in sorted(set(yr)))
    q=np.percentile(yy,[5,50,95])
    print(f'  {str(k):16s} 合并{mm:+6.1f}bp t{t:+4.1f} 胜{(yy>0).mean()*100:3.0f}% n{mk.sum()} 5%/中位/95%分位 {q[0]:.0f}/{q[1]:.0f}/{q[2]:.0f} | {per}')

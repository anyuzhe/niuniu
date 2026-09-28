"""When do the big losses of 分批抄底 happen? (research only)"""
import numpy as np, os
H=os.environ['HOME']; Z={}
for y in range(2020,2027):
    z=np.load(f'{H}/research/brk/dd_{y}.npz',allow_pickle=True)
    for k in z.files: Z.setdefault(k,[]).append(z[k])
Z={k:np.concatenate(v) for k,v in Z.items()}
p=Z['pnl']; d=Z['date']; big=p<=-300; n=len(p)
print(f'共 {n} 次；平均 {p.mean():+.1f}bp；胜率 {(p>0).mean()*100:.0f}%；亏 3% 以上 {big.sum()} 次（{big.mean()*100:.1f}%），这些次的亏损合计是全部盈亏合计的 {p[big].sum()/p.sum():.1f} 倍；去掉它们后平均 {p[~big].mean():+.1f}bp')
tot_loss=p[p<0].sum(); o=np.sort(p)
for q in (0.01,0.05,0.10): k=int(n*q); print(f'  最差 {q*100:.0f}% 的交易占全部亏损的 {o[:k].sum()/tot_loss*100:.0f}%')
print('\n1) 按买了几份：')
for u in (1,2,3):
    mk=Z['units']==u; print(f'  {u} 份: 次数占比 {mk.mean()*100:4.1f}% 平均 {p[mk].mean():+7.1f}bp 胜率 {(p[mk]>0).mean()*100:3.0f}% 亏3%以上占 {big[mk].mean()*100:4.1f}%  占全部大亏 {big[mk].sum()/big.sum()*100:3.0f}%')
print('\n2) 当天大盘（样本等权）从 10:30 到收盘：')
ma=Z['m_after']
for lo,hi,lab in ((-1,-0.01,'又跌 1% 以上'),(-0.01,-0.005,'又跌 0.5–1%'),(-0.005,0,'小跌 0–0.5%'),(0,0.005,'小涨'),(0.005,1,'涨 0.5% 以上')):
    mk=(ma>=lo)&(ma<hi); print(f'  {lab:12s} 天数占比 {len(np.unique(d[mk]))/len(np.unique(d))*100:4.1f}% 交易占比 {mk.mean()*100:4.1f}% 平均 {p[mk].mean():+7.1f}bp 亏3%以上占 {big[mk].mean()*100:4.1f}% 占全部大亏 {big[mk].sum()/big.sum()*100:3.0f}%')
print('\n3) 大亏最集中的日子（前 15 天）：')
ud,iv=np.unique(d,return_inverse=True); cnt=np.bincount(iv,big); tot=np.bincount(iv,p); ntr=np.bincount(iv); mafter=np.bincount(iv,ma)/ntr; mclose=np.bincount(iv,Z['m_close'])/ntr
top=np.argsort(-cnt)[:15]; share=cnt[top].sum()/big.sum()
for i in top: print(f'  {ud[i]} 大亏 {int(cnt[i]):4d} 次/当天做 {ntr[i]:4d} 次，当天合计 {tot[i]/100:+8.0f}%，大盘10:30后 {mafter[i]*100:+.1f}% 全天 {mclose[i]*100:+.1f}%')
print(f'  这 15 天占全部大亏 {share*100:.0f}%；大亏分布在 {int((cnt>0).sum())} 个交易日里，占全部交易日 {(cnt>0).mean()*100:.0f}%；前 5% 的交易日占全部大亏 {np.sort(cnt)[::-1][:int(len(cnt)*0.05)].sum()/big.sum()*100:.0f}%')
print('\n4) 大亏那些次，股票本身：')
print(f'  10:30 到收盘平均 {Z["after"][big].mean()*100:+.1f}%（其他 {Z["after"][~big].mean()*100:+.1f}%）；之后最低平均 {Z["low_after"][big].mean()*100:+.1f}%；收盘跌停 {Z["limdn"][big].mean()*100:.1f}%（其他 {Z["limdn"][~big].mean()*100:.2f}%）')
print(f'  三份买满的时刻：平均第 {Z["lastf"][big].mean():.1f} 根（10:30 为第 12 根）；其他 {Z["lastf"][~big].mean():.1f}')
print('\n5) 进场前就能知道的情况（按 2020–22 定分组，看各段亏3%以上的比例与平均收益）：')
per={'20-22':d<'2023','23-24':(d>='2023')&(d<'2025'),'25-26':d>='2025'}
def grp(name,x,edges,labels):
    print(f'  {name}')
    for (lo,hi),lab in zip(zip(edges[:-1],edges[1:]),labels):
        mk=(x>=lo)&(x<hi)
        print(f'    {lab:14s}'+''.join(f" | {pn} 占{(mk&pm).sum()/pm.sum()*100:4.1f}% 平均{p[mk&pm].mean():+7.1f} 大亏{big[mk&pm].mean()*100:4.1f}%" for pn,pm in per.items()))
grp('10:30 前大盘涨跌',Z['m_pre'],[-1,-0.01,-0.005,0,0.005,1],['跌>1%','跌0.5–1%','跌0–0.5%','涨0–0.5%','涨>0.5%'])
grp('10:30 前个股涨跌',Z['pre'],[-1,-0.03,-0.01,0,0.01,0.03,1],['跌>3%','跌1–3%','跌0–1%','涨0–1%','涨1–3%','涨>3%'])
grp('今天开盘高低开',Z['gap'],[-1,-0.02,0,0.02,1],['低开>2%','低开0–2%','高开0–2%','高开>2%'])
grp('昨天涨跌',Z['r1'],[-1,-0.05,-0.02,0,0.02,0.05,1],['跌>5%','跌2–5%','跌0–2%','涨0–2%','涨2–5%','涨>5%'])
grp('近5日涨跌',Z['r5'],[-1,-0.1,-0.03,0,0.03,0.1,1],['跌>10%','跌3–10%','跌0–3%','涨0–3%','涨3–10%','涨>10%'])
grp('10:30 前振幅',Z['pre_rng'],[0,0.02,0.04,0.06,1],['<2%','2–4%','4–6%','>6%'])
grp('10:30 前量比',Z['vr'],[0,0.7,1,1.5,2.5,100],['<0.7','0.7–1','1–1.5','1.5–2.5','>2.5'])
grp('板块',Z['cy'].astype(float),[-0.5,0.5,1.5],['主板(10%)','创业/科创(20%)'])

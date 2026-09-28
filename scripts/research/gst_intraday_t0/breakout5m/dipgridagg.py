"""Robustness of risk-filtered 分批抄底 (research only)."""
import pickle, numpy as np, os, itertools, sys
H=os.environ['HOME']; R={}
for y in range(2020,2027):
    for k,v in pickle.load(open(f'{H}/research/brk/grid_{y}.pkl','rb')).items(): R.setdefault(k,{})[y]=v
WF=np.load(f'{H}/research/brk/mfpred.npz',allow_pickle=True); LO=np.load(f'{H}/research/brk/mfpred_loyo.npz',allow_pickle=True)
pw={d:p for d,p in zip(WF['date'],WF['prob'])}; pl={d:p for d,p in zip(LO['date'],LO['prob'])}
def agg(k,years,th,src):
    S=C=U=B=0.; res=[]; days=0; skipped=0; alld=0; dayvals=[]
    for y in years:
        v=R[k][y]; pr=np.array([(src.get(d,np.nan)) for d in v['dates']])
        has=v['c']>0; alld+=has.sum()
        keep=has&np.isfinite(pr)&((pr<th) if th else True); skipped+=(has&np.isfinite(pr)&~keep).sum()
        S+=v['s'][keep].sum(); C+=v['c'][keep].sum(); U+=v['u'][keep].sum(); B+=v['big'][keep].sum(); days+=keep.sum()
        res.append((v['s'][keep],v['c'][keep],v['u'][keep]))
    if C<30: return None
    m=S/C; r=np.concatenate([s-m*c for s,c,_ in res]); t=m/(np.sqrt((r**2).sum())/C)
    du=np.concatenate([s/np.maximum(u,1) for s,_,u in res])
    return dict(unit=S/U,ep=m,t=t,big=B/C,days=days,skip=skipped/max(alld,1),worst=du.min(),n=C)
P3={'21-22':(2021,2022),'23-24':(2023,2024),'25-26':(2025,2026)}
YRS=range(2021,2027)
combos=[k for k in R if k[0]!='BASE']
lab=lambda k:f"{k[0]} 间隔{k[1]*100:g}% 最多{k[2]}次 {'收盘卖' if k[3] is None else f'反弹{k[3]*100:g}%卖'}"
print('一、按“模型大跌概率 ≥ 门槛就不做”（逐年滚动预测，2021–2026），192 组参数的整体情况：')
for th in (None,0.10,0.15,0.20,0.25):
    s3=[all((agg(k,ys,th,pw) or {'unit':-1})['unit']>0 for ys in P3.values()) for k in combos]
    s6=[all((agg(k,[y],th,pw) or {'unit':-1})['unit']>0 for y in YRS) for k in combos]
    med={pn:np.median([(agg(k,ys,th,pw) or {'unit':np.nan})['unit'] for k in combos]) for pn,ys in P3.items()}
    sk=agg(combos[0],YRS,th,pw)['skip']
    b={pn:agg(('BASE',),ys,th,pw)['ep'] for pn,ys in P3.items()}
    print(f"  {'不过滤' if th is None else f'概率≥{th:.2f}不做'}（跳过{sk*100:4.1f}%的日子）: 三段都为正 {sum(s3):3d}/192，六年都为正 {sum(s6):3d}/192；每份中位数 "+' '.join(f'{pn} {v:+.1f}' for pn,v in med.items())+' | 对照(10:35买拿到收盘，同样的日子) '+' '.join(f'{pn} {v:+.1f}' for pn,v in b.items()))
print('\n二、重点组合逐年（每份 bp；括号是亏3%以上的比例）：')
focus=[('10:30-11:30',0.015,3,None),('10:30-11:30',0.015,4,None),('10:30-11:30',0.0125,3,None),('10:30-11:30',0.02,3,None),('10:30-13:30',0.015,3,None),('10:30-14:30',0.015,3,None),('13:00-14:30',0.015,3,None),('10:30-11:30',0.015,3,0.02),('10:30-11:30',0.015,3,0.01),('10:30-11:30',0.015,1,None)]
for k in focus:
    for th in (None,0.15,0.20):
        s=f"  {lab(k):32s} {'不过滤   ' if th is None else f'概率≥{th:.2f}'} |"
        for y in YRS:
            a=agg(k,[y],th,pw); s+=f" {y}:{a['unit']:+6.1f}({a['big']*100:3.0f}%)"
        a=agg(k,YRS,th,pw); s+=f" || 合计{a['unit']:+6.1f} t{a['t']:+4.1f} 最差一天{a['worst']:+.0f}"
        print(s)
    print()
print('三、2020 年（只能用“去掉当年、用其余年份拟合”的预测，偏乐观，只作参考）：')
for k in focus[:4]:
    s=f'  {lab(k):32s}'
    for th in (None,0.15,0.20):
        a=agg(k,[2020],th,pl); s+=f" | {'不过滤' if th is None else f'≥{th:.2f}'} {a['unit']:+6.1f}"
    print(s)
print('\n四、同一套滚动预测，所有年份一起看：哪些参数在“概率≥0.20 不做”下六年都为正：')
ok=[k for k in combos if all((agg(k,[y],0.20,pw) or {'unit':-1})['unit']>0 for y in YRS)]
for k in ok: a=agg(k,YRS,0.20,pw); print(f"  {lab(k):32s} 合计每份{a['unit']:+6.1f} t{a['t']:+4.1f} 天数{a['days']} 亏3%以上{a['big']*100:.1f}%")

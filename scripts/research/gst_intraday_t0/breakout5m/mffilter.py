"""Skip 分批抄底 on days the walk-forward model rates risky (research only; 2021-2026, the model needs earlier years)."""
import numpy as np, os
H=os.environ['HOME']; P=np.load(f'{H}/research/brk/mfpred.npz',allow_pickle=True)
prob={d:p for d,p in zip(P['date'],P['prob'])}; pred={d:p for d,p in zip(P['date'],P['pred'])}
# thresholds per year from the model's own previous-year distribution would be ideal; use within-year rank of the prediction
# only through a fixed cut learned on 2021-2022 predictions (no look-ahead for later years)
d_all=P['date']; pr=P['prob']; ok=np.isfinite(pr)
cut={q:np.nanpercentile(pr[ok&(d_all<'2023')],100-q) for q in (10,20,30,50)}
for tag,lab in (('','典型设置：间隔1%、最多3次、反弹0.5%卖'),('close15','间隔1.5%、最多3次、拿到收盘')):
    Z={}
    for y in range(2021,2027):
        z=np.load(f'{H}/research/brk/dd{tag}_{y}.npz',allow_pickle=True)
        for k in z.files: Z.setdefault(k,[]).append(z[k])
    Z={k:np.concatenate(v) for k,v in Z.items()}
    d=Z['date']; p=Z['pnl']; u=Z['units']; rk=np.array([prob.get(x,np.nan) for x in d])
    per={'21-22':(d<'2023'),'23-24':(d>='2023')&(d<'2025'),'25-26':d>='2025'}
    print(f'\n### {lab}（每份收益 bp；2021–22 的切点用 2021–22 的预测定，之后年份沿用）')
    for q in (0,10,20,30,50):
        keep=np.isfinite(rk)&((rk<cut[q]) if q else True)
        s=f'  跳过风险最高的{q:2d}%日子' if q else '  不过滤             '
        for pn,pm in per.items():
            mk=pm&keep; v=p[mk]; un=u[mk]; big=(v<=-300).mean()
            ud,iv=np.unique(d[mk],return_inverse=True); m=v.mean(); r=np.bincount(iv,v-m); t=m/(np.sqrt((r**2).sum())/len(v))
            s+=f' | {pn} 每份{v.sum()/un.sum():+6.1f} t{t:+4.1f} 亏3%以上{big*100:4.1f}% 做的天数{len(ud)}'
        print(s)

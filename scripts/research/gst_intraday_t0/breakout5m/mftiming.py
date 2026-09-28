"""Use the 10:30 market model for 先卖后买 (research only): on days the walk-forward prediction of the market's move
from 10:30 to the close is <= -thr, sell first in all sample stocks and buy back at the close. Day-level approximation:
per trade = -(equal-weight move 10:30->close) - 7.2 bp fees - about 6 bp for two ticks."""
import numpy as np, os
H=os.environ['HOME']; P=np.load(f'{H}/research/brk/mfpred.npz',allow_pickle=True); d=P['date']; pred=P['pred']; y=P['y']; ok=np.isfinite(pred)
yr=np.array([x[:4] for x in d])
print('用同一个模型做“先卖后买”：10:30 预测下午大盘跌幅 ≥ 门槛的日子，全部 500 只先卖、收盘买回（每笔近似 = 大盘10:30后跌幅 − 7.2bp 费用 − 约 6bp 两个价位）')
for thr in (0.001,0.002,0.003,0.005):
    s='  预测跌≥%.1f%%'%(thr*100)
    for Y in ('2021','2022','2023','2024','2025','2026'):
        m=ok&(yr==Y)&(pred<=-thr); v=-y[m]*1e4-13.2
        s+=f' | {Y} {len(v):3d}天 {v.mean() if len(v) else np.nan:+6.1f}bp'
    m=ok&(pred<=-thr); v=-y[m]*1e4-13.2; s+=f' || 合计 {len(v)}天 {v.mean():+.1f}bp 赚钱天{(v>0).mean()*100:.0f}% t{v.mean()/(v.std()/np.sqrt(len(v))):+.1f}'
    print(s)

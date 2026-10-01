import numpy as np, warnings; warnings.filterwarnings('ignore')
from etfpanic_bt import *
for th,H in ((-0.09,20),(-0.12,40)):
    eq,ex,tr=simulate(dict(H=H,thr=th,tiers=[(None,1.0,False)],maxact=1))
    print(f'阈值{th*100:.0f}% 持有{H}天 一次性：全部交易 (买入日 信号日大盘20日 净收益)')
    for t in tr:
        r=t.get('proc',0)/t['cost']-1 if t.get('closed') else np.nan
        mtm=sum(t['sh'][j]*TRC[LASTMK,j] for j in t['sh'])/t['cost']-1 if not t.get('closed') else np.nan
        print(f"  {dates[t['e']]} mk20={mk[t['e']-1]*100:.1f}% {'净%+.1f%%'%(r*100) if t.get('closed') else '未平仓 浮盈%+.1f%%'%(mtm*100)}")

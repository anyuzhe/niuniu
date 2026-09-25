from evalchan import *
import collections
print('points',len(pts), collections.Counter((p['type'],p['buy'],p['level']) for p in pts).most_common())
px8=lambda p,k,i,side: tick_bp[k]<=12.5
for ty in ('1','2','3a','3b'):
    for buy in (True,False):
        f=lambda p,k,i,side,ty=ty,buy=buy: p['type']==ty and p['buy']==buy and p['level']=='' and tick_bp[k]<=12.5
        for ex in ('close','opp','stop'):
            report(f'{ty}{"买" if buy else "卖"} exit={ex}',evaluate(f,ex))

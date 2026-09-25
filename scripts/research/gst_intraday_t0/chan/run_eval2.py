from evalchan import *
for thr in (0.003,0.01):
    for ty in ('2','3a','3b','any23'):
        for buy in (True,False):
            def f(p,k,i,side,ty=ty,buy=buy,thr=thr):
                okty = (p['type'] in ('2','3a','3b')) if ty=='any23' else p['type']==ty
                return okty and p['buy']==buy and p['level']=='' and tick_bp[k]<=12.5 and side*mkt_at(i)[k]>thr
            report(f'{ty}{"买" if buy else "卖"} 大盘同向>{thr:.1%} close',evaluate(f,'close'))
# segment-level points (bigger structure)
for buy in (True,False):
    f=lambda p,k,i,side,buy=buy: p['buy']==buy and p['level']=='seg' and tick_bp[k]<=12.5
    report(f'线段级 {"买" if buy else "卖"} close',evaluate(f,'close'))

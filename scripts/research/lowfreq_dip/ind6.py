import sys
src=open('ind2.py').read().split("allg=np.isfinite(zv)\n# episodes")[0]
exec(src)
NAME={'110000':'农林牧渔','220000':'基础化工','230000':'钢铁','240000':'有色金属','270000':'电子','280000':'汽车','330000':'家用电器','340000':'食品饮料','350000':'纺织服饰','360000':'轻工制造','370000':'医药生物','410000':'公用事业','420000':'交通运输','430000':'房地产','450000':'商贸零售','460000':'社会服务','480000':'银行','490000':'非银金融','510000':'综合','610000':'建筑材料','620000':'建筑装饰','630000':'电力设备','640000':'机械设备','650000':'国防军工','710000':'计算机','720000':'传媒','730000':'通信','740000':'煤炭','750000':'石油石化','760000':'环保','770000':'美容护理'}
zi={g:zind[:,np.nonzero(ind==g)[0][0]] for g in u}
def show(t):
    pan=[(NAME.get(g,g),zi[g][t]) for g in u if np.isfinite(zi[g][t]) and zi[g][t]<=-1.5]
    print(f'{dates[t][:10]} 大盘z={zv[t]:+.2f}  触发行业: '+(', '.join(f'{n}(z{z:+.1f})' for n,z in sorted(pan,key=lambda x:x[1])) or '无'))
    # candidates: valid stocks in triggered industries, ranked by ret20 ascending
    if not pan: return
    gs=[g for g in u if np.isfinite(zi[g][t]) and zi[g][t]<=-1.5]
    m=valid[t]&np.isin(ind,gs); idx=np.nonzero(m)[0]; idx=idx[np.argsort(ret20[t,idx])][:20]
    from collections import Counter
    print('   候选池',int(m.sum()),'只；按20日跌幅最大取前20只的行业分布:',dict(Counter(NAME.get(ind[j],ind[j]) for j in idx)),' 这20只20日平均跌幅 %.1f%%'%(np.nanmean(ret20[t,idx])*100))
    fw=np.nanmean(net[t,idx]); print('   这20只买入后20日平均净收益(含成本) %+.1f%%'%(fw*100) if np.isfinite(fw) else '   (未满20日)')
print('--- 最近几个交易日（数据到 2026-09-23）')
for t in range(nd-4,nd): show(t)
print('--- 历史例子：大盘没恐慌、只有个别行业恐慌')
ex=[]
for t in range(nd-1500,nd-30):
    gs=[g for g in u if np.isfinite(zi[g][t]) and zi[g][t]<=-1.5]
    if gs and zv[t]>-0.5 and len(gs)<=2 and (not ex or t-ex[-1]>200): ex.append(t)
for t in ex[:5]: show(t)

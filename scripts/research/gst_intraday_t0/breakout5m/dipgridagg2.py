exec(open('dipgridagg.py').read().split("print('一、")[0])
focus=[('10:30-11:30',0.015,3,None),('10:30-11:30',0.015,4,None),('10:30-11:30',0.0125,3,None),('10:30-11:30',0.02,3,None),('10:30-13:30',0.015,3,None),('10:30-14:30',0.015,3,None),('13:00-14:30',0.015,3,None)]
print('跳过“大跌概率 ≥0.10”的日子（约跳过一半多交易日）：')
for k in focus[:7]:
    s=f"  {lab(k):32s} |"
    for y in YRS:
        a=agg(k,[y],0.10,pw); s+=f" {y}:{a['unit']:+6.1f}"
    a=agg(k,YRS,0.10,pw); s+=f" || 合计{a['unit']:+6.1f} t{a['t']:+4.1f} 天数{a['days']} 亏3%以上{a['big']*100:.1f}% 最差一天{a['worst']:+.0f}"
    print(s)
b=' '.join(f"{y}:{agg(('BASE',),[y],0.10,pw)['ep']:+.1f}" for y in YRS); print('  对照：同样的日子 10:35 全部买入拿到收盘 |',b)
print('\n三段都为正的组合（概率≥0.10 不做）：')
ok=[k for k in combos if all((agg(k,ys,0.10,pw) or {'unit':-1})['unit']>0 for ys in P3.values())]
for k in sorted(ok,key=lambda k:-agg(k,YRS,0.10,pw)['unit']):
    a=agg(k,YRS,0.10,pw); yrs=' '.join(f"{agg(k,[y],0.10,pw)['unit']:+.0f}" for y in YRS)
    print(f"  {lab(k):32s} 合计每份{a['unit']:+6.1f} t{a['t']:+4.1f} | 逐年 {yrs}")

exec(open('dipgridagg.py').read().split("print('一、")[0])
ks=[('10:30-11:30',0.015,3,None),('10:30-11:30',0.02,3,None),('10:30-11:30',0.0125,3,None),('10:30-11:30',0.015,1,None)]
print('门槛敏感性（大跌概率 ≥ 门槛就不做；逐年滚动预测；每份 bp，t）：')
for k in ks:
    s=f'  {lab(k):28s}'
    for th in (0.06,0.08,0.10,0.12,0.14,0.16):
        a=agg(k,YRS,th,pw); s+=f" | ≥{th:.2f} 跳过{a['skip']*100:3.0f}% {a['unit']:+5.1f} t{a['t']:+3.1f}"
    print(s)
b='  对照（10:35 全买拿到收盘）   '+''.join(f" | ≥{th:.2f} {agg(('BASE',),YRS,th,pw)['ep']:+5.1f}" for th in (0.06,0.08,0.10,0.12,0.14,0.16)); print(b)
print('\n2020 年（去掉当年、用其余年份拟合的预测，偏乐观）：')
for k in ks:
    print(f'  {lab(k):28s}'+''.join(f" | ≥{th:.2f} {agg(k,[2020],th,pl)['unit']:+6.1f}" for th in (0.08,0.10,0.12)))
print('\n按年的跳过比例（≥0.10）：'+' '.join(f"{y}:{agg(ks[0],[y],0.10,pw)['skip']*100:.0f}%" for y in YRS))

"""Risk-filtered 分批抄底 with the official-breadth 10:30 model (research only)."""
exec(open('dipgridagg.py').read().split("print('一、")[0].replace("mfpred.npz","offpred.npz"))
OP=np.load(f'{H}/research/brk/offpred.npz',allow_pickle=True); pp={d:p for d,p in zip(OP['date'],OP['pred'])}
def agg2(k,years,rule):
    """rule: ('prob',th) skip prob>=th ; ('pred',x) keep only pred>=x"""
    kind,th=rule; src=pw if kind=='prob' else pp
    if kind=='prob': return agg(k,years,th,pw)
    # keep days with predicted afternoon move >= th  <=> skip when -pred > -th ; reuse agg by passing a transformed map
    tmp={d:(0.0 if v>=th else 1.0) for d,v in pp.items() if np.isfinite(v)}
    return agg(k,years,0.5,tmp)
rules=[('prob',None)]+[('prob',t) for t in (0.04,0.06,0.08,0.10,0.12,0.15)]+[('pred',x) for x in (-0.003,-0.002,-0.001,0.0,0.001)]
rl=lambda r:('不过滤' if r[1] is None else (f'大跌概率≥{r[1]:.2f}不做' if r[0]=='prob' else f'预测下午≥{r[1]*100:+.1f}%才做'))
print('正式情绪模型；192 组参数：')
for r in rules:
    s3=sum(all((agg2(k,ys,r) or {'unit':-1})['unit']>0 for ys in P3.values()) for k in combos)
    s6=sum(all((agg2(k,[y],r) or {'unit':-1})['unit']>0 for y in YRS) for k in combos)
    a=agg2(combos[0],YRS,r); b=agg2(('BASE',),YRS,r)
    print(f"  {rl(r):18s} 跳过{a['skip']*100:4.1f}%日子 | 三段都为正 {s3:3d} 六年都为正 {s6:3d} | 对照(10:35全买) {b['ep']:+.1f}")
ks=[('10:30-11:30',0.015,3,None),('10:30-11:30',0.02,3,None),('10:30-11:30',0.0125,3,None),('10:30-11:30',0.015,1,None),('10:30-13:30',0.015,3,None)]
print('\n重点组合（每份 bp）：')
for k in ks:
    for r in [('prob',None),('prob',0.08),('prob',0.10),('pred',-0.001),('pred',0.0)]:
        a=agg2(k,YRS,r); yrs=' '.join(f"{(agg2(k,[y],r) or {'unit':np.nan})['unit']:+.0f}" for y in YRS)
        print(f"  {lab(k):28s} {rl(r):18s} 合计{a['unit']:+6.1f} t{a['t']:+4.1f} 跳过{a['skip']*100:3.0f}% | 逐年 {yrs}")
    print()

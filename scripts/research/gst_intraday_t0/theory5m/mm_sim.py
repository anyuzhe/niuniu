"""Money-management rules on timed trade streams (research only).
A trade's outcome is known only after its exit (same-day exit bar, or the close); sizing uses known outcomes only."""
import polars as pl, numpy as np, collections
th=pl.read_parquet('mm_theory.parquet').with_columns((pl.col('strategy')+'|'+pl.col('exit')).alias('strategy'),
    pl.col('e').cast(pl.Int64).alias('tin'),pl.col('x').cast(pl.Int64).alias('tout'))
def mins(s): h,m=s.split(':'); return int(h)*60+int(m)
pr=pl.read_csv(__import__('os').environ.get('MM_PRODUCT_CSV','mm_product.csv')).with_columns(
    pl.col('entry').map_elements(mins,return_dtype=pl.Int64).alias('tin'),pl.col('exit').map_elements(mins,return_dtype=pl.Int64).alias('tout'))
pr=pr.with_columns(pl.when(pl.col('tout')>=899).then(10**6).otherwise(pl.col('tout')).alias('tout'))
th=th.with_columns(pl.when(pl.col('tout')>=47).then(10**6).otherwise(pl.col('tout')).alias('tout'))
cols=['strategy','date','symbol','tin','tout','bp']
ALL=pl.concat([th.select(cols),pr.select(cols)])
RULES=['固定仓位','输了加倍(最多8倍)','输了×1.5(最多4倍)','同一天内输了加倍','赢了加倍(最多4倍)','赢了减半','单日亏100bp或连输2笔停','单日赚100bp停','近50笔为正才做','按同时持仓数分摊','同时最多3笔']
def simulate(df):
    df=df.sort('date','tin','symbol'); D=df['date'].to_list(); TI=df['tin'].to_numpy(); TO=df['tout'].to_numpy(); B=df['bp'].to_numpy()
    out={}
    for rule in RULES:
        size=np.zeros(len(B)); known=[]  # known outcomes sequence
        L=W=0; day=None; dayp=0.; dayl=0; pending=[]; stopped=False; Ld=0
        for k in range(len(B)):
            if D[k]!=day:
                for j in pending: known.append(B[j]); L,W=(0,W+1) if B[j]>0 else (L+1,0)
                pending=[]; day=D[k]; dayp=0.; dayl=0; stopped=False; Ld=0
            # outcomes closed before this entry become known
            still=[]
            for j in pending:
                if TO[j]<TI[k]:
                    known.append(B[j]); L,W=(0,W+1) if B[j]>0 else (L+1,0)
                    dayp+=size[j]*B[j]; dayl+=B[j]<=0; Ld=0 if B[j]>0 else Ld+1
                else: still.append(j)
            pending=still; openn=len(pending)
            if rule=='固定仓位': s=1
            elif rule=='输了加倍(最多8倍)': s=min(2**L,8)
            elif rule=='输了×1.5(最多4倍)': s=min(1.5**L,4)
            elif rule=='同一天内输了加倍': s=min(2**Ld,8)
            elif rule=='赢了加倍(最多4倍)': s=min(2**W,4)
            elif rule=='赢了减半': s=0.5 if W>0 else 1
            elif rule=='单日亏100bp或连输2笔停':
                if dayp<=-100 or dayl>=2: stopped=True
                s=0 if stopped else 1
            elif rule=='单日赚100bp停':
                if dayp>=100: stopped=True
                s=0 if stopped else 1
            elif rule=='近50笔为正才做': s=1 if len(known)<50 or np.mean(known[-50:])>0 else 0
            elif rule=='按同时持仓数分摊': s=1/(1+openn)
            elif rule=='同时最多3笔': s=1 if openn<3 else 0
            size[k]=s; pending.append(k)
        pnl=size*B; tot=pnl.sum(); cap=size.sum()
        dd=pl.DataFrame({'d':D,'p':pnl,'s':size}).group_by('d').agg(pl.col('p').sum(),pl.col('s').sum()).sort('d')
        cum=np.cumsum(dd['p'].to_numpy()); mdd=(np.maximum.accumulate(np.r_[0,cum])[1:]-cum).max()
        per={}
        for nm,lo,hi in (('20-22','2000','2023'),('23-24','2023','2025'),('25-26','2025','2100')):
            m=np.array([lo<=x<hi for x in D]); per[nm]=pnl[m].sum()/max(size[m].sum(),1e-9)
        per_imp={}
        out[rule]=dict(n=int((size>0).sum()),unit=tot/max(cap,1e-9),tot=tot,mdd=mdd,worst=dd['p'].min(),maxs=size.max(),
                       peakcap=dd['s'].max(),roc=tot/max(dd['s'].max(),1e-9),per=per)
    return out
# serial dependence
def dep(df):
    df=df.sort('date','tin','symbol'); B=df['bp'].to_numpy(); D=df['date'].to_list(); TI=df['tin'].to_numpy(); TO=df['tout'].to_numpy()
    last=np.full(len(B),np.nan); lastk=None; pending=[]; day=None; lastt=-1
    for k in range(len(B)):
        if D[k]!=day:
            if pending:
                j=max(pending,key=lambda j:(TO[j],j)); lastk=B[j]
            pending=[]; day=D[k]
        done=[j for j in pending if TO[j]<TI[k]]
        if done: j=max(done,key=lambda j:(TO[j],j)); lastk=B[j]
        pending=[j for j in pending if TO[j]>=TI[k]]
        last[k]=np.nan if lastk is None else lastk; pending.append(k)
    m=np.isfinite(last); w=B>0; pw=last>0
    return (w[m&pw].mean(), w[m&~pw].mean(), np.corrcoef(last[m],B[m])[0,1])
res={}; deps={}
for (st,),g in ALL.group_by(['strategy']):
    res[st]=simulate(g); deps[st]=dep(g)
import pickle; pickle.dump((res,deps),open('mm_res.pkl','wb'))
print('进场时已知的上一笔结果 → 这一笔：上一笔赢后赢的比例 / 上一笔输后赢的比例 / 相关系数')
for st,(a,b,c) in sorted(deps.items()): print(f'  {st:32s} {a*100:5.1f}% / {b*100:5.1f}% / {c:+.3f}')
print('\n每投入 1 份资金的平均收益（bp），各策略：')
hdr='  '+' '*32+''.join(f'{r[:8]:>10s}' for r in RULES); print(hdr)
for st in sorted(res): print(f'  {st:32s}'+''.join(f"{res[st][r]['unit']:+10.1f}" for r in RULES))
print('\n规则汇总（相对固定仓位）：每份资金收益变化的中位数、改善的策略数、最大回撤/最差一天的倍数（中位数）')
for r in RULES[1:]:
    du=[res[s][r]['unit']-res[s]['固定仓位']['unit'] for s in res]
    md=[res[s][r]['mdd']/max(res[s]['固定仓位']['mdd'],1e-9) for s in res]; wd=[res[s][r]['worst']/min(res[s]['固定仓位']['worst'],-1e-9) for s in res]
    rc=[res[s][r]['roc']/res[s]['固定仓位']['roc'] if res[s]['固定仓位']['roc']>0 else np.nan for s in res]
    print(f'  {r:22s} 变化中位 {np.median(du):+6.1f}bp  改善 {sum(x>0 for x in du)}/{len(du)}  回撤×{np.median(md):.2f}  最差一天×{np.median(wd):.2f}  最大单笔倍数 {max(res[s][r]["maxs"] for s in res):.1f}  赚钱策略的"总收益/所需最大资金"×{np.nanmedian(rc):.2f}')
print('\n页面上赚钱的几种策略：')
for st in ('morning_score','close_score','weak_close','intraday_score','gap_rebound'):
    for r in RULES:
        x=res[st][r]; print(f"  {st:15s} {r:22s} 笔数{x['n']:5d} 每份{x['unit']:+6.1f}bp 总{x['tot']/100:+8.1f}% 最大回撤{x['mdd']/100:6.1f}% 最差一天{x['worst']/100:+6.1f}% 最大单笔{x['maxs']:.1f}倍 所需最大资金{x['peakcap']:.0f}份 总收益/所需资金{x['roc']:.1f}bp | "+' '.join(f"{k} {v:+.1f}" for k,v in x['per'].items()))
    print()

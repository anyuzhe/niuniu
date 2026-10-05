import sys
src=open('ind2.py').read().split("allg=np.isfinite(zv)\n# episodes")[0]
exec(src)
allg=np.isfinite(zv)
base=valid&(zind<=-1.5)&nonp[:,None]; uni_all=valid&(zind<=-1.5)
def ex_stats(eq,label):
    rr=dr(eq); out=[]
    for ex in ((),(2008,),(2015,),(2008,2015)):
        k=np.isfinite(rr)&~np.isin(yr,ex); y=rr[k]; cum=np.cumprod(1+y)
        out.append(f'去{"/".join(map(str,ex)) if ex else "无"}: {(cum[-1]**(245/len(y))-1)*100:+.1f}%/{y.mean()/y.std()*np.sqrt(245):.2f}')
    print(f'   {label}: '+' | '.join(out),flush=True)
print('=== A. 行业恐慌(大盘非恐慌日) 候选全部按跌幅排序 N=20')
B1=run('1x',allg,base); ex_stats(B1,'去年份复核')
run('1x 每边冲击20bp',allg,base,slip=0.002)
run('1x 每边冲击10bp',allg,base,slip=0.001)
sizes=np.array([ (ind==g).sum() for g in u]); big=set(np.array(u)[sizes>=60]); bigm=np.isin(ind,list(big))[None,:]
run('1x 只用成分股≥60只的行业',allg,base&bigm)
run('1x 只用成分股<60只的行业',allg,base&~bigm)
print('=== B. 统一闸门：任何大盘状态，行业 z_g<=-1.5，候选全部按跌幅排序')
U1=run('1x',allg,uni_all); ex_stats(U1,'去年份复核')
U15=run('1.5x',allg,uni_all,L=1.5)
run('1x 每边冲击20bp',allg,uni_all,slip=0.002)
run('1x 持有30天',allg,uni_all,hold=30)
U2=run('2x',allg,uni_all,L=2.0)
print('=== C. 对照：现策略 P（大盘恐慌 E6）')
P1=run('P 1x',zv<=-1.5,e6); P2=run('P 2x',zv<=-1.5,e6,L=2.0); ex_stats(P2,'P 2x 去年份复核')
rU=dr(U1); rP=dr(P2)
m=np.isfinite(rU)&np.isfinite(rP); print('  U1 与 P2x 相关',round(np.corrcoef(rU[m],rP[m])[0,1],2))
def ytab(r,label):
    s=[]
    for y in range(2008,2027):
        mm=(yr==y)&np.isfinite(r); s.append('  - ' if mm.sum()<20 else f'{(np.prod(1+r[mm])-1)*100:+4.0f}')
    print(f'{label:22s}',' '.join(s))
print('年份'.ljust(22),' '.join(f'{y%100:4d}' for y in range(2008,2027)))
ytab(rP,'P 2x'); ytab(dr(B1),'A 行业恐慌 1x'); ytab(rU,'B 统一闸门 1x'); ytab(dr(U15),'B 统一闸门 1.5x')
# pure market-panic days vs industry-only days contribution for U1
pan=zv<=-1.5
print('U1 的交易按入场日是否大盘恐慌分：笔数/占比见下（用事件近似）')
x=net[uni_all&np.isfinite(net)]; xp=net[uni_all&pan[:,None]&np.isfinite(net)]; xn=net[uni_all&~pan[:,None]&np.isfinite(net)]
print(f'  事件均值 全部{x.mean()*1e4:+.0f}bp(n={len(x)}) 大盘恐慌日{xp.mean()*1e4:+.0f}bp(n={len(xp)}) 非恐慌日{xn.mean()*1e4:+.0f}bp(n={len(xn)})')

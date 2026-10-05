import numpy as np
exec(open('bb1.py').read().split("OUT=[]")[0])
rng=np.random.default_rng(3)
over=np.where(np.isfinite(upper),(c-upper)/np.where(upper>0,upper,np.nan),np.nan)
def port(M,kind,cap,hard,fx,N=20,rank='over',start='2008-01-01',label=''):
    t,j,e,x,net=run_events(M,kind,cap,hard,fx)
    key=over[t,j] if rank=='over' else rng.random(len(t))
    order=np.lexsort((key,t)); t,j,e,x,net,key=t[order],j[order],e[order],x[order],net[order],key[order]
    starts=np.searchsorted(t,np.arange(nd+1))
    t0=int(np.searchsorted(dates,start)); cash=1.0; act=[]; eq=np.full(nd,np.nan); expo=np.zeros(nd); ntr=0; tr=[]
    for d in range(t0,nd-1):
        for p in [p for p in act if p['x']<=d]:
            cash+=p['inv']*(1+p['net']); tr.append(p['net']); act.remove(p)
        slots=N-len(act)
        if slots>0 and starts[d+1]>starts[d]:
            E=cash+sum(p['v'] for p in act); held={p['j'] for p in act}
            for k in range(starts[d],starts[d+1]):
                if slots==0: break
                if j[k] in held: continue
                size=min(E/N,cash)
                if size<=1e-9: break
                cash-=size; ent=float(o[e[k],j[k]]); act.append(dict(j=int(j[k]),e=int(e[k]),x=int(x[k]),inv=size,v=size,net=float(net[k]),o0=ent,costE=0.01/(ent/float(f[e[k],j[k]]))+float(fee_[x[k]])/2)); slots-=1; held.add(int(j[k]))
        tot=cash
        for p in act:
            if p['e']<=d:
                cd=float(c[d,p['j']]); p['v']=p['inv']*(cd/p['o0'] if np.isfinite(cd) else 1.0)*(1-p['costE'])
            tot+=p['v']
        eq[d]=tot; expo[d]=(tot-cash)/tot
    m=np.isfinite(eq); ee=eq[m]; r=ee[1:]/ee[:-1]-1; yrs=len(r)/245
    cagr=(ee[-1]**(1/yrs)-1); sh=r.mean()/(r.std()+1e-12)*np.sqrt(245); dd=(ee/np.maximum.accumulate(ee)-1).min()
    tr=np.array(tr); yy=[]
    for y in range(2008,2027):
        ii=np.nonzero((yr==y)&m)[0]
        yy.append('  - ' if len(ii)<20 else f'{(eq[ii[-1]]/(eq[ii[0]-1] if ii[0]>0 and np.isfinite(eq[ii[0]-1]) else eq[ii[0]])-1)*100:+4.0f}')
    print(f'{label:46s} 年化{cagr*100:+5.1f}% 夏普{sh:+.2f} 回撤{dd*100:4.0f}% 仓位{expo[m].mean()*100:3.0f}% 笔{len(tr)} 胜率{(tr>0).mean()*100:.0f}% 笔均{tr.mean()*100:+.2f}%',flush=True)
    print('   逐年',' '.join(yy),flush=True)
    return eq
print('年份'.ljust(8),' '.join(f'{y%100:4d}' for y in range(2008,2027)))
G15=(zz>1.5)[:,None]; G05=(zz>0.5)[:,None]
for gl,G in (('z>1.5',G15),('z>0.5',G05)):
    port(cross&G,'mid',60,None,None,label=f'突破首日 {gl} 跌破中线卖 排序=超出上轨最少')
    port(cross&G,'mid',60,None,None,rank='rand',label=f'突破首日 {gl} 跌破中线卖 随机')
    port(cross&G,'mid',60,0.08,None,label=f'突破首日 {gl} 中线或回落8%卖 超出最少')
    port(cross&G,'fix',0,None,20,label=f'突破首日 {gl} 固定持有20天(对照)')
    port(ctrl&G,'mid',60,None,None,rank='rand',label=f'对照:中线之上轨内 {gl} 跌破中线卖 随机')

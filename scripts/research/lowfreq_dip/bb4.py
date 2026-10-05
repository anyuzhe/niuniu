import sys; sys.argv=['x']
src=open('bb3b.py').read().split("print('extra set'")[0]
exec(src)
yr=np.array([int(d[:4]) for d in dates])
STG={'恐慌 z≤-1.5':zz<=-1.5,'偏弱 -1.5~-0.5':(zz>-1.5)&(zz<=-0.5),'中性 -0.5~0.5':(zz>-0.5)&(zz<=0.5),'偏强 0.5~1.5':(zz>0.5)&(zz<=1.5),'过热 z>1.5':zz>1.5}
ENT={'深回踩(距20日高-10%~-20%,MA60上)':T['深回踩(距20日高-10%~-20%,MA60上)'],'强势股急跌(5日跌>8%)':T['强势股急跌(5日跌>8%,MA60上,MA20>MA60)']}
print('事件级：趋势股急跌/深回踩，固定持有20天，按 z 状态（均值 / 对照=同状态普通强势股 / 超额 / 配对t / 前后半超额 / 中位 / 胜率）')
for sn,M in ENT.items():
  for gn,G in STG.items():
    t,j,e,x,net=run_events(M&G[:,None],dict(fix=20)); tc,jc,ec,xc,nc_=run_events(CT&G[:,None],dict(fix=20))
    s,n=monthly(t,net); cs_,cn=monthly(tc,nc_)[0],monthly(tc,nc_)[1]; ok=(n>0)&(cn>0); d=s[ok]/n[ok]-cs_[ok]/cn[ok]
    tt=d.mean()/(d.std()/np.sqrt(len(d))+1e-12); h1=yr[t]<=2016; cm=nc_.mean()
    print(f"{sn[:14]:16s}|{gn:16s}| n{len(net):6d} 均{net.mean()*100:+5.2f}% 对照{cm*100:+5.2f}% 超额{(net.mean()-cm)*100:+5.2f}% t{tt:+4.1f} [{(net[h1].mean()-cm)*100:+.1f}/{(net[~h1].mean()-cm)*100:+.1f}] 中{np.median(net)*100:+.1f}% 胜{(net>0).mean()*100:.0f}%",flush=True)
# portfolio sleeves
dd20=F2['dd20']; r5=F2['r5']; rng=np.random.default_rng(3)
def port(M,key,N=20,start='2008-01-01',label='',spec=dict(fix=20)):
    t,j,e,x,net=run_events(M,spec); k_=key[t,j] if key is not None else rng.random(len(t))
    order=np.lexsort((k_,t)); t,j,e,x,net=t[order],j[order],e[order],x[order],net[order]
    starts=np.searchsorted(t,np.arange(nd+1)); t0=int(np.searchsorted(dates,start)); cash=1.0; act=[]; eq=np.full(nd,np.nan); expo=np.zeros(nd); tr=[]
    for d in range(t0,nd-1):
        for p in [p for p in act if p['x']<=d]:
            cash+=p['inv']*(1+p['net']); tr.append(p['net']); act.remove(p)
        slots=N-len(act)
        if slots>0 and starts[d+1]>starts[d]:
            E=cash+sum(p['v'] for p in act); held={p['j'] for p in act}
            for k in range(starts[d],starts[d+1]):
                if slots==0: break
                if int(j[k]) in held: continue
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
    cagr=ee[-1]**(1/yrs)-1; sh=r.mean()/(r.std()+1e-12)*np.sqrt(245); dd=(ee/np.maximum.accumulate(ee)-1).min()
    h=[]
    rr=np.full(nd,np.nan); idx=np.nonzero(m)[0]; rr[idx[1:]]=ee[1:]/ee[:-1]-1
    for a_,b_ in ((2008,2016),(2017,2026)):
        mm=(yr>=a_)&(yr<=b_)&np.isfinite(rr); xx=rr[mm]; cum=np.cumprod(1+xx); h.append(f'{(cum[-1]**(245/len(xx))-1)*100:+.1f}%/{xx.mean()/xx.std()*np.sqrt(245):.2f}')
    print(f'{label:52s} 年化{cagr*100:+5.1f}% 夏普{sh:+.2f} 回撤{dd*100:4.0f}% 仓位{expo[m].mean()*100:3.0f}% 笔{len(tr)} 笔均{np.mean(tr)*100:+.2f}% | 前半{h[0]} 后半{h[1]}',flush=True)
    return rr
print('\n组合(N=20,1x,持有20天)')
Ma=ENT['深回踩(距20日高-10%~-20%,MA60上)']; Mb=ENT['强势股急跌(5日跌>8%)']
for gn,G in (('z>-0.5 三档',zz>-0.5),('中性',STG['中性 -0.5~0.5']),('偏强+过热',zz>0.5),('偏弱',STG['偏弱 -1.5~-0.5']),('任何日子',np.isfinite(zz))):
    port(Ma&G[:,None],dd20,label=f'深回踩 {gn} 排序=回撤最深')
    port(Mb&G[:,None],r5,label=f'强势股急跌 {gn} 排序=5日跌最多')
port(Ma&(zz>-0.5)[:,None],None,label='深回踩 z>-0.5 随机')
port((CT&(zz>-0.5)[:,None]),None,label='对照:普通强势股 z>-0.5 随机')

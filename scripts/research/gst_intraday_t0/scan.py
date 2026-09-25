from lib import *
import itertools
times=['09:35','09:45','10:00','10:30','11:00','13:30','14:00','14:30']
def feats(t):
    i=T(t); p=C[:,i]
    op=first_open
    f={}
    f['gap']=(op/pc-1)
    f['ret_open']=(p/op-1)
    f['ret_pc']=(p/pc-1)
    f['vwap_dev']=(p/VW[:,i]-1)
    tot=cumB[:,i]+cumS[:,i]
    f['imb']=np.where(tot>0,(cumB[:,i]-cumS[:,i])/np.maximum(tot,1),np.nan)
    j=max(0,i-30); f['ret_30']=(p/C[:,j]-1)
    tot30=(cumB[:,i]-cumB[:,j])+(cumS[:,i]-cumS[:,j])
    f['imb_30']=np.where(tot30>0,((cumB[:,i]-cumB[:,j])-(cumS[:,i]-cumS[:,j]))/np.maximum(tot30,1),np.nan)
    f['relvol']=cumV[:,i]/volu20
    f['range_pos']=np.where(HI[:,i]>LO[:,i],(p-LO[:,i])/(HI[:,i]-LO[:,i]),np.nan)
    f['prev_ret']=prev_ret
    for k in ('gap','ret_open','ret_pc','vwap_dev','ret_30'): f[k+'_z']=f[k]/vol20
    return f
rows=[]
cost=cost_bp()
exits={'14:50':T('14:50')}
for t in times:
    i=T(t); F=feats(t)
    for e_name,e in exits.items():
        if e<=i: continue
        r=fwd(i,e)
        for name,x in F.items():
            ok=train&np.isfinite(x)&np.isfinite(r)
            qs=np.nanquantile(x[ok],[0.05,0.2,0.8,0.95])
            for label,m in (('<p5',x<=qs[0]),('<p20',x<=qs[1]),('>p80',x>=qs[2]),('>p95',x>=qs[3])):
                mean,tt,n=clustered(r,ok&m)
                c=np.nanmean(cost[ok&m])
                rows.append((t,name,label,n,mean,tt,c,abs(mean)-c))
rows.sort(key=lambda r:-r[7])
print('tests:',len(rows))
print('time  feature  bucket  n  mean_fwd_bp  t  cost  net(|mean|-cost)')
for r in rows[:40]: print(r[0],r[1],r[2],r[3],f'{r[4]:+.1f}',f'{r[5]:+.1f}',f'{r[6]:.1f}',f'{r[7]:+.1f}')
import pickle; pickle.dump(rows,open('scan1.pkl','wb'))

import numpy as np
exec(open('stockport.py').read().split("print('格式")[0])
print(nd,nc,c.dtype,c.shape,'nanfrac c',np.isnan(c).mean(),'valid frac',valid.mean())
print('net',net.shape,net.dtype,'nanfrac',np.isnan(net).mean())
ok=np.isfinite(zv); z=zv[ok]
print('z quantiles',np.round(np.percentile(z,[1,5,10,25,50,75,90,95,99]),2))
edges=[-9,-2,-1.5,-1,-0.5,0,0.5,1,1.5,2,9]
yrm=np.array([d[:7] for d in dates])
fw=np.full(nd,np.nan); fw[:-21]=bench[21:]/bench[1:-20]-1
allnet=np.array([np.nanmean(net[t][valid[t]]) if valid[t].any() else np.nan for t in range(nd)])
e6net=np.array([np.nanmean(net[t][e6[t]]) if e6[t].any() else np.nan for t in range(nd)])
def cl(x,m):
    g={}
    for k,v in zip(yrm[m],x[m]):
        if np.isfinite(v): g.setdefault(k,[]).append(v)
    mm=np.array([np.mean(v) for v in g.values()]); 
    return (mm.mean(), mm.mean()/(mm.std()/np.sqrt(len(mm))+1e-12), len(mm)) if len(mm)>2 else (np.nan,np.nan,len(mm))
print('档位           天数  月数 | 大盘后20日均值 t | 全候选池net t | E6池net')
for a,b in zip(edges[:-1],edges[1:]):
    m=ok&(zv>a)&(zv<=b)
    f=cl(fw,m); n_=cl(allnet,m); e=cl(e6net,m)
    print(f'({a:+.1f},{b:+.1f}] {m.sum():5d} {f[2]:4d} | {f[0]*100:+5.1f}% {f[1]:+4.1f} | {n_[0]*100:+5.1f}% {n_[1]:+4.1f} | {e[0]*100:+5.1f}% (有E6天数{int(np.isfinite(e6net[m]).sum())})')

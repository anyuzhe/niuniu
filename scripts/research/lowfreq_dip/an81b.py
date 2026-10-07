"""§91: entry-time features of delisted-stock fills vs listed-stock fills (ACB, with-delisted panel)."""
import os; os.environ['C70DIR']='c80'; os.environ['SERIES']='c80/series.npz'
import numpy as np, lib73 as X, lib70 as L
X.run(sleeves='ACB'); tr=X.TR; ISD=np.load('c80/isdel.npy'); d=L.dates
PE=np.asarray(L.L('pe'),np.float32); PB=np.asarray(L.L('pb'),np.float32); DD=np.asarray(L.L('dd60'),np.float32); SG=np.asarray(L.SIG,np.float32); R20=np.asarray(L.R20,np.float32)
price=np.asarray(L.C,np.float32)/np.asarray(L.F,np.float32)
def feats(z):
    s=[(PE[t[4]-1,t[3]],PB[t[4]-1,t[3]],price[t[4]-1,t[3]],DD[t[4]-1,t[3]],SG[t[4]-1,t[3]],R20[t[4]-1,t[3]],t[1]) for t in z]; return np.array(s,float)
for nm,z in (('退市股',[t for t in tr if ISD[t[3]]]),('在市股',[t for t in tr if not ISD[t[3]]]),('退市股 2021起',[t for t in tr if ISD[t[3]] and d[t[4]]>='2021-01-01'])):
    a=feats(z); fin=np.isfinite
    print(f'{nm} n={len(z)} 市盈率<=0或缺失 {np.mean(~(a[:,0]>0))*100:.0f}% | 市净率中位 {np.nanmedian(a[:,1]):.2f} 市净率<1 {np.mean(a[:,1]<1)*100:.0f}% | 股价中位 {np.nanmedian(a[:,2]):.1f} 股价<5 {np.mean(a[:,2]<5)*100:.0f}% | 60日回撤中位 {np.nanmedian(a[:,3])*100:.0f}% | 20日跌幅中位 {np.nanmedian(a[:,5])*100:.0f}% | 日波动中位 {np.nanmedian(a[:,4])*100:.1f}% | 净收益均 {np.mean(a[:,6])*1e4:+.0f}bp')
a=feats([t for t in tr if ISD[t[3]]]); w=a[:,6]<-0.1; print('退市股里亏超10%%的 %d 笔: 市盈率<=0或缺失 %.0f%% 市净率<1 %.0f%% 股价<5 %.0f%%'%(w.sum(),np.mean(~(a[w,0]>0))*100,np.mean(a[w,1]<1)*100,np.mean(a[w,2]<5)*100))

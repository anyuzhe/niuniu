"""§90: trade-level breakdown of delisted-stock fills in the with-delisted D baseline (ACB)."""
import os; os.environ['C70DIR']='c80'; os.environ['SERIES']='c80/series.npz'
import numpy as np, lib73 as X, lib70 as L
X.run(sleeves='ACB'); tr = X.TR; ISD=np.load('c80/isdel.npy'); d=L.dates
Dl=[t for t in tr if ISD[t[3]]]; Ls=[t for t in tr if not ISD[t[3]]]
f=lambda z:(len(z), np.mean([t[1] for t in z])*1e4, np.median([t[1] for t in z])*1e4, np.mean([t[1]<-.2 for t in z])*100, np.mean([t[1]<-.4 for t in z])*100, min(t[1] for t in z)*100)
print('退市股', 'n=%d 均%+.0fbp 中位%+.0fbp <-20%%:%.1f%% <-40%%:%.1f%% 最差%.0f%%'%f(Dl)); print('在市股', 'n=%d 均%+.0fbp 中位%+.0fbp <-20%%:%.1f%% <-40%%:%.1f%% 最差%.0f%%'%f(Ls))
# exit-before-delist? last finite close index
C=L.C
last={j:int(np.nonzero(np.isfinite(C[:,j]))[0][-1]) for j in set(t[3] for t in Dl)}
inwin=[t for t in Dl if last[t[3]] <= t[4]+22]; print('持仓期内摘牌/终止交易的笔数',len(inwin), '均%+.0fbp'%(np.mean([t[1] for t in inwin])*1e4) if inwin else '', '最差', min([t[1] for t in inwin])*100 if inwin else '')
for y0,y1 in ((2008,2012),(2013,2016),(2017,2020),(2021,2026)):
    z=[t for t in Dl if y0<=int(d[t[4]][:4])<=y1]; w=[t for t in Ls if y0<=int(d[t[4]][:4])<=y1]
    print(y0,y1,'退市股占比 %.1f%% (%d/%d) 退市股均%+.0fbp 在市股均%+.0fbp'%(len(z)/(len(z)+len(w))*100,len(z),len(z)+len(w),np.mean([t[1] for t in z])*1e4,np.mean([t[1] for t in w])*1e4))
# universe share of delisted among candidates on gate days
n=int(ISD.sum()); print('退市列',n,'总列',len(ISD))

"""Gross vs net and next-day exits for representative breakout rules (research only)."""
import sys, os, numpy as np
sys.path.insert(0,os.path.dirname(__file__)); import lib5
rows={}
for yr in range(2020,2027):
    D=lib5.load(yr); C,Hh,L,V,pc,m=D['C'],D['H'],D['L'],D['V'],D['pc'],D['mret']; n=len(C)
    volr=V/np.where(D['vs20']>0,D['vs20'],np.nan)
    prevmaxC=np.c_[np.full((n,1),-np.inf),np.maximum.accumulate(C,1)[:,:-1]]
    runmaxH=np.maximum.accumulate(Hh,1); prevmaxH=np.c_[np.full((n,1),np.inf),runmaxH[:,:-1]]
    ph=np.full((n,48),np.nan); pl=np.full((n,48),np.nan)
    for i in range(6,48): ph[:,i]=Hh[:,i-6:i].max(1); pl[:,i]=L[:,i-6:i].min(1)
    l5=D['pH5']; w5=(l5-D['pL5'])/D['pL5']
    R={'A 30分钟平台≤2%+放量1.5倍+大盘红':(((ph-pl)/pc[:,None]<=0.02)&(C>ph)&(volr>=1.5)&(m>0),6),
       'B 5日平台≤6%突破+大盘红':((C>l5[:,None])&(prevmaxC<=l5[:,None])&(w5<=0.06)[:,None]&(m>0),1),
       'C 放量2倍突破昨高+大盘红':((C>D['pH1'][:,None])&(prevmaxC<=D['pH1'][:,None])&(volr>=2)&(m>0),6),
       'C 放量3倍创日内新高':((C>prevmaxH)&(volr>=3),6),
       'C 放量3倍创日内新高+大盘涨≥1%':((C>prevmaxH)&(volr>=3)&(m>=0.01),6)}
    for k,(sig,f) in R.items():
        for ex in ('close','nextopen','nextclose'):
            r,e,bp=lib5.trades(D,sig,first=f,last=44,exit=ex)
            a=rows.setdefault((k,ex),{}); a[yr]=(bp,lib5.trades.gross)
for (k,ex),a in rows.items():
    def s(ys):
        b=np.concatenate([a[y][0] for y in ys]); g=np.concatenate([a[y][1] for y in ys]); w=b>0
        return f"净{b.mean():+6.1f} 毛{g.mean():+6.1f} 胜{w.mean()*100:4.1f}% 赔{b[w].mean()/-b[~w].mean():.2f} n{len(b)}"
    print(f"{k:28s} {ex:9s} | 20-22 {s((2020,2021,2022))} | 23-24 {s((2023,2024))} | 25-26 {s((2025,2026))}")

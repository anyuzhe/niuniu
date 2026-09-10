"""Append-only confirmed-fractal/alternating-stroke/three-stroke-center variant.

No inclusion-bar merge or discretionary segment/divergence/buy-point inference.
Same-side later pivots never rewrite the accepted endpoint.
"""
from dataclasses import asdict
from quantlab.structure.pivots import ConfirmedPivotEngine
from quantlab.storage.codec import digest


class ChanStructureAdapter:
    version='confirmed_alternating_v1'

    def __init__(self,left=2,right=2,min_separation=3):
        self.engine=ConfirmedPivotEngine(left,right)
        if type(min_separation) is not int or min_separation<1: raise ValueError('min_separation must be positive')
        self.min_separation=min_separation

    def analyze(self,bars):
        pivots=self.engine.detect(bars); records=[]; last={}; strokes={}
        positions={(r['symbol'],r['datetime']):i for _,g in bars.sort('symbol','datetime').group_by('symbol')
            for i,r in enumerate(g.iter_rows(named=True))}
        # A bar confirmed as both high and low is ambiguous; retain fractals but no stroke endpoint.
        counts={}
        for p in pivots: counts[(p.symbol,p.occurred_at)]=counts.get((p.symbol,p.occurred_at),0)+1
        for p in pivots:
            base=asdict(p); base.update(kind='chan_'+p.kind,version=self.version); records.append(base)
            if counts[(p.symbol,p.occurred_at)]>1: continue
            previous=last.get(p.symbol)
            if previous is None: last[p.symbol]=p; continue
            if previous.kind==p.kind: continue
            if positions[(p.symbol,p.occurred_at)]-positions[(p.symbol,previous.occurred_at)]<self.min_separation: continue
            if (p.kind=='pivot_high' and p.price<=previous.price) or (p.kind=='pivot_low' and p.price>=previous.price): continue
            stroke={'kind':'chan_bi','symbol':p.symbol,'timeframe':p.timeframe,'occurred_at':previous.occurred_at,
                'available_at':p.available_at,'components':[previous.structure_id,p.structure_id],
                'lower':min(previous.price,p.price),'upper':max(previous.price,p.price),
                'direction':1 if p.kind=='pivot_high' else -1,'version':self.version}
            stroke['structure_id']=digest(stroke); records.append(stroke)
            history=strokes.setdefault(p.symbol,[]); history.append(stroke); last[p.symbol]=p
            if len(history)>=3:
                window=history[-3:]; lower=max(v['lower'] for v in window); upper=min(v['upper'] for v in window)
                if lower<upper:
                    center={'kind':'chan_center','symbol':p.symbol,'timeframe':p.timeframe,'occurred_at':window[0]['occurred_at'],
                        'available_at':p.available_at,'components':[v['structure_id'] for v in window],
                        'lower':lower,'upper':upper,'version':self.version}
                    center['structure_id']=digest(center); records.append(center)
        return records

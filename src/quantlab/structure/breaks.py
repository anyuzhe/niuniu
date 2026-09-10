"""SMC-inspired confirmed-swing break variant; no unconfirmed swing or retroactive signal."""
import polars as pl
from quantlab.structure.pivots import ConfirmedPivotEngine
from quantlab.domain import Event, Timeframe
from quantlab.storage.codec import digest


class ConfirmedSwingBreakEngine:
    def __init__(self,left=2,right=2):
        self.pivots=ConfirmedPivotEngine(left,right)

    def analyze(self,bars):
        flags=self.pivots.flags(bars)
        rows=[];events=[];symbol=None;levels={};previous_close=None
        for row in flags.iter_rows(named=True):
            if symbol!=row['symbol']:
                symbol=row['symbol'];levels={};previous_close=None
            for side in ('high','low'):
                if row['ready'] and row['pivot_'+side]:
                    levels[side]={'price':row['pivot_'+side+'_price'],'occurred_at':row['pivot_at'],
                        'available_at':row['available_at'],'broken':False}
            values={}
            for side,direction in [('high',1),('low',-1)]:
                level=levels.get(side)
                crossed=bool(level and not level['broken'] and previous_close is not None and
                    (previous_close<=level['price']<row['close'] if direction==1 else previous_close>=level['price']>row['close']))
                values[side]=float(crossed) if level else None
                if crossed:
                    level['broken']=True
                    identity={'factor_id':'SMC.BOS_UP' if direction==1 else 'SMC.BOS_DOWN',
                        'symbol':symbol,'timeframe':row['timeframe'],'occurred_at':row['datetime'],
                        'available_at':row['available_at'],'direction':direction,
                        'metadata':{'swing_price':level['price'],'swing_at':level['occurred_at'],
                            'swing_available_at':level['available_at'],'left':self.pivots.left,'right':self.pivots.right}}
                    events.append(Event(digest(identity),identity['factor_id'],symbol,Timeframe(row['timeframe']),
                        row['datetime'],row['available_at'],direction=direction,metadata=identity['metadata']))
            rows.append({'symbol':symbol,'datetime':row['datetime'],'available_at':row['available_at'],
                'up':values['high'],'down':values['low']})
            previous_close=row['close']
        return pl.DataFrame(rows, schema_overrides={'up':pl.Float64,'down':pl.Float64}),events

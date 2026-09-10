import polars as pl

from quantlab.data.validation import ordered_bars
from quantlab.domain import Event, Timeframe
from quantlab.storage.codec import digest


class FailedBreakoutEngine:
    """Strict range excursion followed by a close inside the prior range.

    Both sides may trigger on one bar; OHLC does not identify intrabar order.
    """
    def __init__(self, lookback=20):
        if type(lookback) is not int or lookback < 1:
            raise ValueError('lookback must be a positive integer')
        self.lookback = lookback

    def flags(self, bars):
        frame = ordered_bars(bars).with_columns(
            pl.col('high').rolling_max(self.lookback).shift(1).over('symbol').alias('prior_high'),
            pl.col('low').rolling_min(self.lookback).shift(1).over('symbol').alias('prior_low'))
        inside = pl.col('close').is_between(pl.col('prior_low'),pl.col('prior_high'),closed='both')
        ready = pl.col('prior_high').is_not_null() & pl.col('prior_low').is_not_null()
        return frame.with_columns(
            pl.when(ready).then((pl.col('high')>pl.col('prior_high')) & inside).otherwise(None).alias('failed_high'),
            pl.when(ready).then((pl.col('low')<pl.col('prior_low')) & inside).otherwise(None).alias('failed_low'))

    def detect(self, bars):
        events = []
        for row in self.flags(bars).filter(pl.col('failed_high') | pl.col('failed_low')).iter_rows(named=True):
            for side, direction in [('high',-1),('low',1)]:
                if not row[f'failed_{side}']:
                    continue
                level = row[f'prior_{side}']
                strength = (row['high']-level)/level if side=='high' else (level-row['low'])/level
                metadata = {k:row[k] for k in ('prior_high','prior_low','high','low','close')}
                metadata.update({'lookback':self.lookback,'side':side,'level':level})
                identity = {'factor_id':f'EVT.FAILED_BREAKOUT_{side.upper()}', 'version':'1.0.0',
                    'symbol':row['symbol'],'timeframe':row['timeframe'],'occurred_at':row['datetime'],
                    'available_at':row['available_at'], **metadata}
                events.append(Event(digest(identity),identity['factor_id'],row['symbol'],Timeframe(row['timeframe']),
                    row['datetime'],row['available_at'],direction=direction,strength=strength,
                    confirmed_at=row['available_at'],metadata=metadata))
        return sorted(events,key=lambda e:(e.available_at,e.symbol,e.event_id))

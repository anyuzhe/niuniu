"""Completed A-share session bars; lunch breaks never enter an aggregate."""
from datetime import timedelta
import polars as pl
from quantlab.data.validation import ordered_bars
from quantlab.domain import Timeframe


def resample_bars(bars, target, *, require_all=True):
    bars=ordered_bars(bars);source=Timeframe(bars['timeframe'][0]);target=Timeframe(target)
    if source==target:return bars
    if source==Timeframe.DAILY or (target!=Timeframe.DAILY and target.minutes%source.minutes) or target.minutes<=source.minutes:
        raise ValueError('Resample requires a larger divisible intraday timeframe')
    groups={}
    for row in bars.iter_rows(named=True):
        stamp=row['datetime'];minute=stamp.hour*60+stamp.minute
        origin=570 if 570<minute<=690 else 780 if 780<minute<=900 else None
        if origin is None or stamp.second or stamp.microsecond:raise ValueError('Bar outside A-share continuous session')
        end_minute=900 if target==Timeframe.DAILY else origin+((minute-origin-1)//target.minutes+1)*target.minutes
        end=stamp.replace(hour=end_minute//60,minute=end_minute%60)
        groups.setdefault((row['symbol'],end),[]).append(row)
    rows=[]
    for (_,end),part in groups.items():
        expected=([end.replace(hour=minute//60,minute=minute%60) for origin in (570,780) for minute in range(origin+source.minutes,origin+121,source.minutes)] if target==Timeframe.DAILY else
            [end-timedelta(minutes=m) for m in range(target.minutes-source.minutes,-1,-source.minutes)])
        if [r['datetime'] for r in part]!=expected:continue
        first,last=part[0],part[-1]
        rows.append({**last,'datetime':end,'available_at':max(r['available_at'] for r in part),
            'timeframe':target.value,'open':first['open'],'high':max(r['high'] for r in part),
            'low':min(r['low'] for r in part),'volume':sum(r['volume'] for r in part),
            'turnover':sum(r['turnover'] for r in part)})
    if not rows:
        if not require_all:return bars.clear()
        raise ValueError('No complete aggregate bars; missing periods are not filled')
    missing=set(bars['symbol'].to_list())-{row['symbol'] for row in rows}
    if missing and require_all:raise ValueError('No complete aggregate bars for symbols: '+', '.join(sorted(missing)))
    return ordered_bars(pl.DataFrame(rows,schema=bars.schema))

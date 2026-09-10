"""Causal inclusion variant: only publish a merged bar after a non-included successor.

Before a direction exists use a union envelope. Thereafter inclusion merges use
max(high), max(low) upward and min(high), min(low) downward. Unfinished tail is
never published. Synthetic bodies are clipped to the resulting interval and must
not be used as execution prices.
"""
import polars as pl
from quantlab.data.validation import ordered_bars
from quantlab.storage.codec import digest


def finalized_inclusion_bars(bars):
    bars=ordered_bars(bars);output=[];records=[]
    for _,group in bars.group_by('symbol',maintain_order=True):
        current=None;direction=0;components=[];first_open=None
        for row in group.iter_rows(named=True):
            if current is None:
                current=dict(row);components=[row['datetime']];first_open=row['open'];continue
            included=(row['high']<=current['high'] and row['low']>=current['low']) or (row['high']>=current['high'] and row['low']<=current['low'])
            if included:
                high=(max if direction>=0 else min)(current['high'],row['high'])
                low=(max if direction>0 else min)(current['low'],row['low'])
                volume=current['volume']+row['volume'];turnover=current['turnover']+row['turnover']
                current={**row,'high':high,'low':low,'open':min(high,max(low,first_open)),'close':min(high,max(low,row['close'])),
                    'volume':volume,'turnover':turnover}
                components.append(row['datetime']);continue
            finalized={**current,'available_at':row['available_at']};output.append(finalized)
            record={'symbol':row['symbol'],'timeframe':row['timeframe'],'occurred_at':components[0],'available_at':row['available_at'],
                'components':list(components),'lower':current['low'],'upper':current['high'],'direction':direction,
                'confirmed_by':row['datetime'],'version':'finalized_inclusion_v1'}
            record['structure_id']=digest(record);records.append(record)
            direction=1 if row['high']>current['high'] else -1
            current=dict(row);components=[row['datetime']];first_open=row['open']
    return (pl.DataFrame(output,schema=bars.schema) if output else bars.head(0)),records


def center_lifecycle(structures):
    """Non-overlapping episodes: freeze first three-stroke overlap, then extend/exit.

Any positive-area overlap extends the frozen center; a stroke entirely at/above
the upper edge or at/below the lower edge exits. After exit, three fresh strokes
are required. Boundaries and past records are never revised.
"""
    active={};history={};records=[]
    for stroke in sorted((s for s in structures if s['kind']=='chan_bi'),key=lambda s:(s['available_at'],s['symbol'])):
        symbol=stroke['symbol'];center=active.get(symbol)
        if center:
            if stroke['lower']>=center['upper']:kind='center_exit_up';direction=1
            elif stroke['upper']<=center['lower']:kind='center_exit_down';direction=-1
            else:kind='center_extended';direction=0
            record={'kind':'chan_'+kind,'symbol':symbol,'timeframe':stroke['timeframe'],'occurred_at':stroke['occurred_at'],
                'available_at':stroke['available_at'],'lower':center['lower'],'upper':center['upper'],
                'components':[center['structure_id'],stroke['structure_id']],'center_id':center['structure_id'],
                'direction':direction,'version':'frozen_inclusion_center_v1'}
            if direction:active.pop(symbol);history[symbol]=[]
        else:
            window=history.setdefault(symbol,[]);window.append(stroke);history[symbol]=window=window[-3:]
            if len(window)<3:continue
            lower=max(s['lower'] for s in window);upper=min(s['upper'] for s in window)
            if lower>=upper:continue
            record={'kind':'chan_active_center','symbol':symbol,'timeframe':stroke['timeframe'],'occurred_at':window[0]['occurred_at'],
                'available_at':stroke['available_at'],'lower':lower,'upper':upper,'components':[s['structure_id'] for s in window],
                'direction':0,'version':'frozen_inclusion_center_v1'}
        record['structure_id']=digest(record);records.append(record)
        if record['kind']=='chan_active_center':active[symbol]=record
    return records

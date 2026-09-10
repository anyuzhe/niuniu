"""Explicit OHLC background proxies; not discretionary Brooks classifications."""
import math
import polars as pl
from quantlab.data.validation import ordered_bars
from quantlab.domain import Event, FactorType, Timeframe
from quantlab.factors.base import ComputedFactor, FactorDefinition
from quantlab.factors.registry import FactorPack
from quantlab.storage.codec import digest

COMPONENTS = ('range', 'climax_up', 'climax_down', 'always_in', 'flip_up', 'flip_down')


class BrooksContextComponent(ComputedFactor):
    def __init__(self, component):
        if component not in COMPONENTS:
            raise ValueError('Unknown Brooks context component')
        self.component = component
        self.definition = FactorDefinition(
            f'BROOKS.CTX_{component.upper()}', '1.0.0', f'Brooks 背景规则 {component}', 'regime',
            FactorType.SCALAR if component == 'always_in' else FactorType.BOOLEAN,
            ('open', 'high', 'low', 'close', 'volume', 'turnover'), tuple(Timeframe),
            '此前窗口低方向效率及窄区间；当根真实量程和实体扩张事件；强实体突破前区间后锁存方向直到反向突破。',
            'Lagged range/efficiency, prior-TR climax proxy, latched confirmed breakout direction',
            source_theory=('Brooks',))

    def parameters(self, supplied):
        p = {'lookback':20, 'max_width':0.1, 'max_efficiency':0.3,
             'climax_multiple':2., 'climax_body':0.8, 'breakout_body':0.5}
        if set(supplied) - set(p):
            raise ValueError('Unknown Brooks context parameter')
        p.update(supplied)
        if type(p['lookback']) is not int or not 2 <= p['lookback'] <= 10000:
            raise ValueError('lookback must be an integer in [2,10000]')
        for k in set(p) - {'lookback'}:
            v = p[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
                raise ValueError(f'{k} must be finite and positive')
        for k in ('max_efficiency', 'climax_body', 'breakout_body'):
            if p[k] > 1:
                raise ValueError(f'{k} must be <= 1')
        if p['climax_multiple'] <= 1:
            raise ValueError('climax_multiple must be > 1')
        return p

    def trace(self, bars, parameters):
        p = self.parameters(parameters)
        bars = ordered_bars(bars)
        if bars.select(pl.struct('symbol', 'available_at').is_duplicated().any()).item():
            raise ValueError('Brooks context requires unique symbol/available_at')
        output, events = [], []
        n = p['lookback']
        for _, group in bars.group_by('symbol', maintain_order=True):
            rows = group.to_dicts()
            direction = 0
            true_ranges = [max(r['high']-r['low'], abs(r['high']-rows[i-1]['close']),
                abs(r['low']-rows[i-1]['close'])) if i else r['high']-r['low'] for i,r in enumerate(rows)]
            for i, row in enumerate(rows):
                values = dict.fromkeys(COMPONENTS, None)
                # n full true ranges plus their previous close must exist.
                if i >= n+1:
                    window = rows[i-n:i]
                    upper, lower = max(r['high'] for r in window), min(r['low'] for r in window)
                    path = sum(abs(rows[j]['close']-rows[j-1]['close']) for j in range(i-n,i))
                    efficiency = abs(rows[i-1]['close']-rows[i-n-1]['close'])/path if path else 0.
                    relative_width = (upper-lower)/lower
                    prior_tr = sum(true_ranges[i-n:i])/n
                    span = row['high']-row['low']
                    body = row['close']-row['open']
                    body_ratio = abs(body)/span if span else 0.
                    values = dict.fromkeys(COMPONENTS, 0.)
                    values['range'] = float(relative_width <= p['max_width'] and efficiency <= p['max_efficiency'])
                    climax = prior_tr > 0 and true_ranges[i] >= prior_tr*p['climax_multiple'] and body_ratio >= p['climax_body']
                    values['climax_up'] = float(climax and body > 0)
                    values['climax_down'] = float(climax and body < 0)
                    new_direction = (1 if body > 0 and row['close'] > upper else
                        -1 if body < 0 and row['close'] < lower else 0) if body_ratio >= p['breakout_body'] else 0
                    old_direction = direction
                    if new_direction and new_direction != direction:
                        direction = new_direction
                        values['flip_up' if direction == 1 else 'flip_down'] = 1.
                    values['always_in'] = float(direction)
                    for component in ('climax_up', 'climax_down', 'flip_up', 'flip_down'):
                        if not values[component]:
                            continue
                        fid = f'BROOKS.CTX_{component.upper()}'
                        eid = digest({'factor':fid,'symbol':row['symbol'],'timeframe':row['timeframe'],
                            'available_at':row['available_at'],'parameters':p})
                        events.append(Event(eid, fid, row['symbol'], Timeframe(row['timeframe']), row['datetime'],
                            row['available_at'], direction=1 if component.endswith('up') else -1,
                            metadata={'parameters':p,'window_start':window[0]['available_at'],
                                'window_end':window[-1]['available_at'],'efficiency_anchor':rows[i-n-1]['available_at'],
                                'upper':upper,'lower':lower,'relative_width':relative_width,'efficiency':efficiency,
                                'prior_mean_true_range':prior_tr,'true_range':true_ranges[i],'body_ratio':body_ratio,
                                'previous_direction':old_direction,'current_direction':direction,'confirmation_bar':dict(row)}))
                output.append({**{k:row[k] for k in ('symbol','datetime','available_at')},'value':values[self.component]})
        return pl.DataFrame(output, schema_overrides={'value':pl.Float64}), [], events

    def compute(self, bars, parameters):
        return self.trace(bars, parameters)[0]


def brooks_context_pack():
    return FactorPack('BrooksContextPack','1.0.0',tuple(BrooksContextComponent(c) for c in COMPONENTS),('BrooksBasePack',))

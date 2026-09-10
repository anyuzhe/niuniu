"""Explicit close-confirmed breakout/pullback proxy, not discretionary Brooks labeling."""
import math
import polars as pl
from quantlab.data.validation import ordered_bars
from quantlab.domain import Event, SequenceMatch, Timeframe, FactorType
from quantlab.factors.base import ComputedFactor, FactorDefinition
from quantlab.factors.registry import FactorPack
from quantlab.storage.codec import digest

COMPONENTS = ('breakout', 'pullback', 'resumed', 'measured_move', 'failed', 'invalidated', 'expired')


class BrooksBreakoutComponent(ComputedFactor):
    def __init__(self, component, direction):
        if component not in COMPONENTS or direction not in (1, -1):
            raise ValueError('Unknown Brooks breakout component/direction')
        self.component, self.direction = component, direction
        suffix = 'UP' if direction == 1 else 'DOWN'
        self.definition = FactorDefinition(
            f'BROOKS.BP_{component.upper()}_{suffix}', '1.0.0',
            f'Brooks 突破回踩规则 {component} {suffix}', 'sequence', FactorType.BOOLEAN,
            ('open', 'high', 'low', 'close', 'volume', 'turnover'), tuple(Timeframe),
            '前区间收盘突破、后续边界回踩、再收盘越过回踩极值，最后收盘达到一倍区间宽度目标；每步独立确认。',
            'Frozen-range breakout/pullback/continuation and close-based measured move proxy', source_theory=('Brooks',))

    def parameters(self, supplied):
        p = {'lookback': 20, 'max_bars': 40, 'body_fraction': 0.5, 'retest_fraction': 0.1}
        if set(supplied) - set(p):
            raise ValueError('Unknown Brooks breakout parameter')
        p.update(supplied)
        for key in ('lookback', 'max_bars'):
            if type(p[key]) is not int or not 1 <= p[key] <= 10000:
                raise ValueError(f'{key} must be an integer in [1,10000]')
        for key in ('body_fraction', 'retest_fraction'):
            v = p[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 < v <= 1:
                raise ValueError(f'{key} must be finite in (0,1]')
        return p

    def trace(self, bars, parameters):
        p = self.parameters(parameters)
        bars = ordered_bars(bars)
        if bars.select(pl.struct('symbol', 'available_at').is_duplicated().any()).item():
            raise ValueError('Brooks breakout requires unique symbol/available_at')
        output, transitions, events = [], [], []
        d = self.direction
        suffix = 'UP' if d == 1 else 'DOWN'
        for _, group in bars.group_by('symbol', maintain_order=True):
            rows, state = group.to_dicts(), None
            for i, row in enumerate(rows):
                value = None if i < p['lookback'] else 0.
                stage, status = None, 'active'
                if state:
                    if i - state['start_index'] > p['max_bars']:
                        stage, status = 'expired', 'timeout'
                    elif state['stage'] == 'resumed':
                        if d * (row['close'] - state['pullback_stop']) < 0:
                            stage, status = 'invalidated', 'invalidated'
                        elif d * (row['close'] - state['target']) >= 0:
                            stage, status = 'measured_move', 'completed'
                    elif d * (row['close'] - state['boundary']) < 0:
                        stage, status = 'failed', 'invalidated'
                    elif state['stage'] == 'breakout':
                        edge = row['low'] if d == 1 else row['high']
                        if abs(edge - state['boundary']) <= state['width'] * p['retest_fraction']:
                            stage = 'pullback'
                            state['pullback_stop'] = row['low'] if d == 1 else row['high']
                            state['pullback_trigger'] = row['high'] if d == 1 else row['low']
                            state['pullback_bar'] = dict(row)
                    elif d * (row['close'] - state['pullback_trigger']) > 0:
                        stage = 'resumed'
                elif i >= p['lookback']:
                    window = rows[i-p['lookback']:i]
                    upper, lower = max(b['high'] for b in window), min(b['low'] for b in window)
                    width, span = upper - lower, row['high'] - row['low']
                    boundary = upper if d == 1 else lower
                    if (width > 0 and span > 0 and d * (row['close'] - boundary) > 0
                            and d * (row['close'] - row['open']) >= span * p['body_fraction']):
                        stage = 'breakout'
                        state = {'id': digest({'symbol': row['symbol'], 'timeframe': row['timeframe'],
                            'available_at': row['available_at'], 'direction': d, 'parameters': p}),
                            'start_index': i, 'started_at': row['datetime'], 'stage': stage, 'ids': [],
                            'upper': upper, 'lower': lower, 'width': width, 'boundary': boundary,
                            'target': boundary + d * width, 'window_start': window[0]['available_at'],
                            'window_end': window[-1]['available_at'], 'breakout_bar': dict(row)}
                if stage:
                    fid = f'BROOKS.BP_{stage.upper()}_{suffix}'
                    eid = digest({'episode': state['id'], 'stage': stage, 'at': row['available_at']})
                    state['stage'] = stage
                    metadata = {k: v for k, v in state.items() if k != 'ids'}
                    metadata.update(match_id=state['id'], parameters=p, confirmation_bar=dict(row))
                    events.append(Event(eid, fid, row['symbol'], Timeframe(row['timeframe']), row['datetime'],
                        row['available_at'], direction=d, metadata=metadata))
                    state['ids'].append(eid)
                    transitions.append(SequenceMatch(f'BROOKS.BP_MEASURED_MOVE_{suffix}', '1.0.0', row['symbol'],
                        tuple(state['ids']), state['started_at'], row['available_at'], status, state['id'],
                        Timeframe(row['timeframe']), eid if status == 'invalidated' else None))
                    value = float(stage == self.component)
                    if status != 'active':
                        state = None
                output.append({**{k: row[k] for k in ('symbol', 'datetime', 'available_at')}, 'value': value})
        return pl.DataFrame(output, schema_overrides={'value': pl.Float64}), transitions, events

    def compute(self, bars, parameters):
        return self.trace(bars, parameters)[0]


def brooks_breakout_pack():
    return FactorPack('BrooksBreakoutPack', '1.0.0', tuple(BrooksBreakoutComponent(c, d)
        for d in (1, -1) for c in COMPONENTS), ('BrooksBasePack',))

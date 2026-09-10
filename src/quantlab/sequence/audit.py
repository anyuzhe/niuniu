from collections import Counter
from dataclasses import asdict
import polars as pl

from quantlab.factors.brooks import BrooksComponent
from quantlab.factors.brooks_breakout import BrooksBreakoutComponent
from quantlab.factors.brooks_context import BrooksContextComponent
from quantlab.factors.brooks_wedge import BrooksWedgeComponent
from quantlab.factors.ict import ICTComponent
from quantlab.factors.ict_context import Breaker
from quantlab.factors.wyckoff import WyckoffComponent
from quantlab.factors.wyckoff_classic import ClassicWyckoffFactor
from quantlab.factors.wyckoff_phases import WyckoffPhaseComponent
from quantlab.factors.chan import ChanComponent
from quantlab.factors.chan_sequence import ChanOrderedSequence
from quantlab.factors.chan_classic import ClassicChanFactor
from quantlab.factors.chan_multiscale import ClassicChanNestFactor
from quantlab.factors.chan_inclusion import ChanInclusionComponent
from quantlab.factors.order_block import OrderBlockComponent
from quantlab.factors.chan_progression import ChanProgressionComponent
from quantlab.factors.combinations import CombinationFactor
from quantlab.factors.sequences import RepeatedBreakout, FailedLowThenBreakout, CustomOrderedSequence


def collect_sequence_audit(factor, bars, parameters, registry, observations):
    """Capture known sequence factors and direct combination inputs, before filters."""
    candidates = [('main',factor,parameters)]
    if isinstance(factor, CombinationFactor):
        candidates = [(alias,registry.get(spec['factor_id'],spec['version']),spec['parameters'])
            for alias,spec in parameters['inputs'].items()]
    eligible = set(observations.filter(pl.col('value').is_not_null()).select('symbol','available_at').iter_rows())
    sequences = []
    for alias, candidate, params in candidates:
        if not isinstance(candidate,(RepeatedBreakout,FailedLowThenBreakout,CustomOrderedSequence,ChanOrderedSequence,ClassicChanFactor,ClassicChanNestFactor,Breaker,BrooksComponent,BrooksBreakoutComponent,BrooksContextComponent,BrooksWedgeComponent,ICTComponent,WyckoffComponent,ClassicWyckoffFactor,WyckoffPhaseComponent,ChanComponent,ChanInclusionComponent,OrderBlockComponent,ChanProgressionComponent)):
            continue
        _, transitions, events = candidate.trace(bars,params)
        records, last_status = [], {}
        for transition in transitions:
            record = asdict(transition)
            record['completion_selected'] = ((transition.symbol,transition.available_at) in eligible) if transition.status=='completed' else None
            records.append(record)
            last_status[transition.match_id] = transition.status
        sequences.append({'alias':alias,'factor':asdict(candidate.definition),'parameters':candidate.parameters(params),
            'status_record_counts':dict(Counter(t.status for t in transitions)),
            'pending_at_end':sum(status=='active' for status in last_status.values()),
            'selected_completions':sum(r['completion_selected'] is True for r in records),
            'events':[asdict(e) for e in sorted(events,key=lambda e:(e.available_at,e.symbol,e.event_id))],
            'transitions':records})
    return {'version':'1.0.0','scope':'loaded_history_before_universe_regime_context_filters',
        'as_of':bars['available_at'].max(), 'sequences':sequences}

"""Recheck score, market state, and targets on prefixes of the archived real sample."""
import argparse,json
from pathlib import Path
import polars as pl
from polars.testing import assert_frame_equal
from quantlab.app import default_registry
from quantlab.causal import assert_prefix_invariant
from quantlab.regime.config import RegimeConfig
from quantlab.regime.engine import compute_regime
from quantlab.execution.portfolio import TargetWeightBuilder,PortfolioConfig

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('run',type=Path);parser.add_argument('--output',type=Path,required=True);a=parser.parse_args()
    record=json.loads((a.run/'experiment.json').read_text());source=Path(record['children'][0]['artifact_path'])
    source_record=json.loads((source/'experiment.json').read_text());cfg=source_record['manifest']['config']
    bars=pl.read_parquet(source/'bars.parquet');obs=pl.read_parquet(source/'observations.parquet');targets=pl.read_parquet(a.run/'targets.parquet')
    registry=default_registry();model=registry.get('COMB.SCORE','1.0.0')
    cutoffs=sorted(set(bars['available_at']));cutoffs=[cutoffs[len(cutoffs)*i//4] for i in (1,2,3)]
    assert_prefix_invariant(model,bars,cfg['parameters'],cutoffs)
    states,_=compute_regime(bars,registry,RegimeConfig(**cfg['regime']))
    for cutoff in cutoffs:
        prefix=bars.filter(pl.col('available_at')<=cutoff)
        earlier,_=compute_regime(prefix,registry,RegimeConfig(**cfg['regime']))
        assert_frame_equal(earlier,states.filter(pl.col('available_at')<=cutoff),check_exact=True)
        c=record['manifest']['execution']
        t,_=TargetWeightBuilder(PortfolioConfig(**record['manifest']['portfolio'])).build(obs.filter(pl.col('available_at')<=cutoff),prefix,
            top_n=c['top_n'],threshold=c['threshold'],exposure=c['exposure'])
        assert_frame_equal(t,targets.filter(pl.col('available_at')<=cutoff),check_exact=True)
    a.output.write_text(json.dumps({'status':'passed','cutoffs':[c.isoformat() for c in cutoffs],
        'checks':['fixed_score_prefix','all_market_state_dimensions_prefix','target_weight_prefix']},indent=2))
    print('Score, market state and target prefixes: 9 checks passed')

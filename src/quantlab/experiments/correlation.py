"""Research factor redundancy without return labels or automatic selection."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import polars as pl

from quantlab.data.base import DataRequest
from quantlab.experiments.runner import ExperimentRunner, runtime_fingerprint
from quantlab.factors.combinations import ScoreCombination
from quantlab.factors.engine import compute_factor
from quantlab.statistics.correlation import complete_link_groups, cross_section_correlations
from quantlab.storage.codec import digest
from quantlab.domain import FactorType
from quantlab.regime.config import RegimeConfig, RegimeFilter
from quantlab.regime.engine import compute_regime, filter_mask
from quantlab.processing.cross_section import CrossSectionConfig, processing_manifest, transform_cross_section
from quantlab.multitimeframe.config import DailyContextConfig
from quantlab.multitimeframe.engine import MultiTimeframeEngine
from quantlab.factors.combinations import condition
from quantlab.statistics.bootstrap import BootstrapConfig


@dataclass(frozen=True)
class CorrelationConfig:
    research_question: str
    data: DataRequest
    inputs: dict
    min_symbols: int = 3
    min_periods: int = 5
    cluster_threshold: float = 0.8
    processor: CrossSectionConfig | None = None
    regime: RegimeConfig | None = None
    regime_filter: RegimeFilter | None = None
    context: DailyContextConfig | None = None
    bootstrap: BootstrapConfig | None = None
    random_seed: int = 0


@dataclass(frozen=True)
class CorrelationResult:
    experiment_id: str
    run_id: str
    artifact_path: Path
    pairs: list[dict]
    groups: list[list[str]]


class CorrelationRunner:
    def __init__(self, runner: ExperimentRunner):
        self.runner = runner

    def run(self, config: CorrelationConfig) -> CorrelationResult:
        run_id = str(uuid4())
        manifest = {'config': asdict(config), 'runtime': runtime_fingerprint(),
            'method': 'equal_timestamp_pairwise_complete_v1', 'group_method': 'absolute_mean_spearman_complete_link_v1',
            'universe': {'id': self.runner.universe.universe_id, 'version': self.runner.universe.version}}
        record = {'run_id': run_id, 'created_at': datetime.now(timezone.utc).isoformat(),
            'kind': 'correlation', 'manifest': manifest}
        try:
            if type(config.random_seed) is not int:
                raise ValueError('random_seed must be an integer')
            if config.regime_filter is not None and config.regime is None:
                raise ValueError('regime_filter requires regime configuration')
            if config.context is not None:
                config.context.request(config.data)
            if not config.research_question.strip():
                raise ValueError('research_question is required')
            if not isinstance(config.inputs, dict) or not 2 <= len(config.inputs) <= 64:
                raise ValueError('Correlation requires 2 to 64 factor inputs')
            if type(config.min_symbols) is not int or config.min_symbols < 3 or type(config.min_periods) is not int or config.min_periods < 1:
                raise ValueError('Require min_symbols >= 3 and min_periods >= 1')
            complete_link_groups([], [], config.cluster_threshold)
            # Reuse existing leaf-input validation, defaults, and lineage.
            specification = ScoreCombination(self.runner.registry)
            inputs = specification.parameters({'inputs': config.inputs, 'weights': {k: 1 for k in config.inputs}})
            manifest['inputs'] = specification.lineage(inputs)
            if config.processor is not None and any(item['definition']['factor_type'] != FactorType.SCALAR for item in manifest['inputs']):
                raise ValueError('Cross-sectional processing requires scalar factors')
            from quantlab.storage.frozen_inputs import CaptureData, freeze_inputs
            captured = CaptureData(self.runner.data)
            batch = captured.load(config.data)
            manifest['data_snapshot'] = asdict(batch.snapshot)
            mask = self.runner.universe.mask(batch.bars).sort('symbol', 'datetime')
            manifest['universe']['mask_hash'] = digest(mask.write_json())
            panel = batch.bars.select('symbol', 'datetime', 'available_at').join(mask, on=['symbol','datetime'], how='left', validate='1:1')
            if panel['eligible'].null_count():
                raise ValueError('Universe mask must cover every factor row')
            for alias, spec in inputs['inputs'].items():
                factor = self.runner.registry.get(spec['factor_id'], spec['version'])
                values = compute_factor(factor, batch.bars, spec['parameters'])
                if values.filter(pl.col('available_at') != pl.col('datetime')).height:
                    raise ValueError('Correlation requires factors available at their bar close')
                if config.processor is not None:
                    panel = panel.join(values.select('symbol','datetime',pl.col('value').alias(f'raw_factor_{alias}')),
                        on=['symbol','datetime'], validate='1:1')
                    values = transform_cross_section(values, mask, config.processor)
                    manifest['processor'] = processing_manifest(config.processor)
                panel = panel.join(values.select('symbol','datetime',pl.col('value').alias(f'factor_{alias}')),
                    on=['symbol','datetime'], validate='1:1')
            summary = {'universe_rows': panel.filter(pl.col('eligible')).height}
            if config.regime is not None:
                states, manifest['regime'] = compute_regime(batch.bars, self.runner.registry, config.regime)
                from quantlab.regime.breadth import breadth_frame
                states=states.join(breadth_frame(batch.bars,mask,config.regime.lookback),on='datetime',how='left',validate='m:1').with_columns(pl.col('regime_breadth').fill_null('Unknown'))
                manifest['regime']['breadth_scope']='Observed eligible research universe; not exchange-wide'
                columns = ['regime_direction','regime_structure','regime_volatility','regime_liquidity','regime_breadth']
                panel = panel.join(states.select('symbol','datetime',*columns), on=['symbol','datetime'], validate='1:1')
                if config.regime_filter is not None:
                    panel = panel.join(filter_mask(states, config.regime_filter), on=['symbol','datetime'], validate='1:1').with_columns(
                        (pl.col('eligible') & pl.col('regime_eligible')).alias('eligible')).drop('regime_eligible')
            summary['after_regime_rows'] = panel.filter(pl.col('eligible')).height
            if config.context is not None:
                context = config.context
                aligned = MultiTimeframeEngine(captured, self.runner.registry).load(config.data, context.request(config.data),
                    context.factor_id, context.version, context.parameters, low_batch=batch)
                manifest['context'] = {'context_id': aligned.context_id, **aligned.manifest}
                panel = panel.join(aligned.frame.select('symbol','datetime','context_value','context_datetime','context_available_at'),
                    on=['symbol','datetime'], validate='1:1')
                summary['context_ready_rows'] = panel.filter(pl.col('eligible') & pl.col('context_value').is_not_null()).height
                rule, _ = condition({'input':'daily','op':context.op,'value':context.value}, {'daily'})
                panel = panel.with_columns(pl.col('context_value').alias('input_daily')).with_columns(
                    (pl.col('eligible') & rule.fill_null(False)).alias('eligible')).drop('input_daily')
            summary['selected_rows'] = panel.filter(pl.col('eligible')).height
            record['selection_summary'] = summary
            panel = panel.filter(pl.col('eligible')).sort('datetime','symbol')
            aliases = sorted(inputs['inputs'])
            labels=batch.bars.sort('symbol','datetime').with_columns(
                (pl.col('close').shift(-1).over('symbol')/pl.col('close')-1).alias('forward_return')).select('symbol','datetime','forward_return')
            pairs = cross_section_correlations(panel, aliases, config.min_symbols, config.min_periods,
                bootstrap=config.bootstrap, random_seed=config.random_seed,
                return_labels=labels,
                boolean_aliases=[v['alias'] for v in manifest['inputs'] if v['definition']['factor_type']==FactorType.BOOLEAN])
            from quantlab.sequence.audit import collect_sequence_audit
            from quantlab.statistics.sequence_overlap import sequence_overlap
            audits=[]
            for alias,spec in inputs['inputs'].items():
                factor=self.runner.registry.get(spec['factor_id'],spec['version'])
                selected=panel.filter(pl.col('factor_'+alias)==1).select('symbol','available_at',pl.col('factor_'+alias).alias('value'))
                audit=collect_sequence_audit(factor,batch.bars,spec['parameters'],self.runner.registry,selected)
                for sequence in audit['sequences']:
                    sequence['alias']=alias;audits.append(sequence)
            record['sequence_audit']={'version':'1.0.0','as_of':batch.bars['available_at'].max(),'scope':'named_sequence_inputs_with_selected_positive_completions','sequences':audits}
            record['sequence_overlap']=sequence_overlap(record['sequence_audit'])
            overlap={(p['left'],p['right']):p for p in record['sequence_overlap']['pairs']}
            for pair in pairs:pair['sequence_overlap']=overlap.get((pair['left'],pair['right']))
            groups = complete_link_groups(aliases, pairs, config.cluster_threshold)
            frozen = freeze_inputs(captured,self.runner.universe,manifest)
            record.update({'experiment_id': digest(manifest), 'status': 'completed', 'pairs': pairs, 'groups': groups,
                'coverage': {a: {'eligible_rows': panel.height, 'valid_rows': panel[f'factor_{a}'].count()} for a in aliases}})
        except Exception as error:
            record.update({'experiment_id': digest(manifest), 'status': 'failed', 'error': f'{type(error).__name__}: {error}'})
            try:
                self.runner.store.save(run_id, record, None)
            except Exception as storage_error:
                error.add_note(f'Correlation failure record could not be saved: {storage_error}')
            raise
        path = self.runner.store.save(run_id, record, panel, inputs=frozen)
        return CorrelationResult(record['experiment_id'], run_id, path, pairs, groups)

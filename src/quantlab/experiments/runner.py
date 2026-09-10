import hashlib
import importlib.metadata
import platform
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import polars as pl

from quantlab.data.base import DataProvider, UniverseProvider
from quantlab.domain import FactorType
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.research import FactorResearchEngine
from quantlab.factors.engine import compute_factor
from quantlab.factors.combinations import CombinationFactor
from quantlab.factors.chan_classic import ClassicChanFactor
from quantlab.factors.chan_multiscale import ClassicChanNestFactor
from quantlab.factors.liquidity_pool import LiquidityPoolFactor
from quantlab.factors.wyckoff_classic import ClassicWyckoffFactor
from quantlab.factors.registry import FactorRegistry
from quantlab.regime.engine import compute_regime, filter_mask
from quantlab.storage.codec import digest
from quantlab.storage.experiments import ExperimentStore
from quantlab.statistics.bootstrap import bootstrap_statistics
from quantlab.statistics.permutation import permutation_statistics, inference_family
from quantlab.processing.cross_section import processing_manifest, transform_cross_section
from quantlab.multitimeframe.engine import MultiTimeframeEngine
from quantlab.factors.combinations import condition
from quantlab.sequence.audit import collect_sequence_audit
from quantlab.sequence.replay import replay_evidence
from quantlab.processing.pipeline import PipelineConfig, FactorPipeline


def runtime_fingerprint() -> dict:
    root = Path(__file__).resolve().parents[1]
    files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*.py"))}
    return {
        "code_hash": digest(files),
        "python": platform.python_version(),
        "dependencies": {name: importlib.metadata.version(name) for name in ["polars", "pyarrow", "duckdb"]},
    }


@dataclass(frozen=True)
class ExperimentResult:
    experiment_id: str
    run_id: str
    artifact_path: Path
    metrics: dict


class ExperimentRunner:
    def __init__(self, data: DataProvider, registry: FactorRegistry, universe: UniverseProvider, store: ExperimentStore, research: FactorResearchEngine | None = None):
        self.data = data
        self.registry = registry
        self.universe = universe
        self.store = store
        self.research = research or FactorResearchEngine()
        if hasattr(store,'root'):
            from quantlab.factors.cache import FactorCache
            code_hash=runtime_fingerprint()['code_hash'];root=store.root/'_factor_cache'
            cache=getattr(registry,'_factor_cache',None)
            if cache is None or cache.root!=root or cache.code_hash!=code_hash:
                cache=FactorCache(root,code_hash);registry._factor_cache=cache
            for pack in registry._packs.values():
                for factor in pack.factors:factor._persistent_cache=cache

    def run(self, config: ExperimentConfig) -> ExperimentResult:
        run_id = str(uuid4())
        manifest = {"config": asdict(config), "runtime": runtime_fingerprint(), "universe": {"id": self.universe.universe_id, "version": self.universe.version}}
        record = {"run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat(), "manifest": manifest}
        try:
            from quantlab.progress import checkpoint
            checkpoint("开始研究 · "+config.research_question)
            if config.incremental_test:
                raise ValueError('incremental_test requires AblationRunner')
            manifest['universe']['metadata'] = getattr(self.universe,'metadata',{})
            factor = self.registry.get(config.factor_id, config.factor_version)
            if config.processor is not None and factor.definition.factor_type != FactorType.SCALAR:
                raise ValueError("Cross-sectional processing requires a scalar factor")
            parameters = factor.parameters(config.parameters)
            if isinstance(factor,ClassicChanFactor):
                import json
                from quantlab.adapters import chan_classic
                source=Path(chan_classic.__file__)
                manifest['classic_chan']={'profile':chan_classic.PROFILE,'adapter_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                    'core':json.loads((source.parent.parent/'_vendor/chanpy/PROVENANCE.json').read_text())}
            if isinstance(factor, CombinationFactor):
                manifest["combination_inputs"] = factor.lineage(parameters)
            wyckoff=factor if isinstance(factor,ClassicWyckoffFactor) else None
            wyckoff_parameters=parameters
            if isinstance(factor,CombinationFactor):
                inputs=[(self.registry.get(s['factor_id'],s['version']),s['parameters']) for s in parameters['inputs'].values()]
                if inputs and all(isinstance(f,ClassicWyckoffFactor) and p==inputs[0][1] for f,p in inputs):
                    wyckoff,wyckoff_parameters=inputs[0]
            if isinstance(config.processor, PipelineConfig) and (config.processor.fit_start is None or not config.data.start<=config.processor.fit_start<=config.processor.fit_end<=config.data.end):
                raise ValueError('Pipeline fit period must lie inside the requested data range')
            from quantlab.storage.frozen_inputs import CaptureData, freeze_inputs
            from quantlab.experiments.child_checkpoints import checkpoint_active,prepare_child,publish_child
            captured = CaptureData(self.data,memoize=checkpoint_active())
            batch = captured.load(config.data)
            manifest.update({"parameters": parameters, "factor": asdict(factor.definition), "factor_code_hash": self.registry.code_hash(factor), "data_snapshot": asdict(batch.snapshot)})
            child_ticket,reused,precomputed_mask = prepare_child(self,config,manifest,captured,batch)
            if reused is not None:return reused
            values = compute_factor(factor, batch.bars, parameters)
            mask = precomputed_mask if precomputed_mask is not None else self.universe.mask(batch.bars).sort("symbol", "datetime")
            # Hash the actual mask, not just the provider's human-readable name.
            manifest["universe"]["mask_hash"] = hashlib.sha256(mask.write_json().encode()).hexdigest()
            raw_values = None
            if config.processor is not None:
                raw_values = values
                if isinstance(config.processor, PipelineConfig):
                    training_universe = getattr(self.universe, 'source', self.universe)
                    pipeline = FactorPipeline(config.processor).fit(values, training_universe.mask(batch.bars))
                    values = pipeline.transform(values, mask)
                    manifest['processor'] = pipeline.manifest()
                    if pipeline.audit:record['processor_audit'] = pipeline.audit
                else:
                    values = transform_cross_section(values, mask, config.processor)
                    manifest["processor"] = processing_manifest(config.processor)
            states = None
            if config.regime is not None:
                states, manifest["regime"] = compute_regime(batch.bars, self.registry, config.regime)
                from quantlab.regime.breadth import breadth_frame
                breadth=breadth_frame(batch.bars,mask,config.regime.lookback)
                states=states.join(breadth,on='datetime',how='left',validate='m:1').with_columns(pl.col('regime_breadth').fill_null('Unknown'))
                manifest['regime']['breadth_scope']='Observed eligible research universe at each close, not the full exchange; 60%/40% advance fraction thresholds'
                state_columns = ["regime_direction", "regime_structure", "regime_volatility", "regime_liquidity", "regime_breadth"]
                base_states = states.join(mask, on=["symbol", "datetime"], how="left", validate="1:1")
                if base_states["eligible"].null_count():
                    raise ValueError("Universe mask must cover every regime row")
                summary = {"eligible_before": base_states.filter(pl.col("eligible")).height,
                    "state_counts": base_states.filter(pl.col("eligible")).group_by(state_columns).len().sort(state_columns).to_dicts()}
                if config.regime_filter is not None:
                    baseline_metrics, _ = self.research.evaluate(batch.bars, values, mask, config.horizons, config.quantiles,
                        boolean_factor=factor.definition.factor_type == FactorType.BOOLEAN)
                    record["baseline_metrics"] = baseline_metrics
                    mask = mask.join(filter_mask(states, config.regime_filter), on=["symbol", "datetime"], validate="1:1").select(
                        "symbol", "datetime", (pl.col("eligible") & pl.col("regime_eligible")).alias("eligible"))
                summary["eligible_after"] = mask.filter(pl.col("eligible")).height
                record["regime_summary"] = summary
            context_frame = None
            if config.context is not None:
                context = config.context
                aligned = MultiTimeframeEngine(captured, self.registry).load(config.data, context.request(config.data),
                    context.factor_id, context.version, context.parameters, low_batch=batch)
                manifest["context"] = {"context_id": aligned.context_id, **aligned.manifest}
                context_frame = aligned.frame
                rule, _ = condition({"input": "daily", "op": context.op, "value": context.value}, {"daily"})
                context_mask = context_frame.rename({"context_value": "input_daily"}).select("symbol", "datetime",
                    rule.fill_null(False).alias("context_eligible"), pl.col("input_daily").is_not_null().alias("context_ready"))
                before, _ = self.research.evaluate(batch.bars, values, mask, config.horizons, config.quantiles,
                    boolean_factor=factor.definition.factor_type == FactorType.BOOLEAN)
                record["context_baseline_metrics"] = before
                joined = mask.join(context_mask, on=["symbol", "datetime"], validate="1:1")
                record["context_summary"] = {"eligible_before": joined.filter(pl.col("eligible")).height,
                    "context_ready": joined.filter(pl.col("eligible") & pl.col("context_ready")).height,
                    "eligible_after": joined.filter(pl.col("eligible") & pl.col("context_eligible")).height}
                mask = joined.select("symbol", "datetime", (pl.col("eligible") & pl.col("context_eligible")).alias("eligible"))
            checkpoint("统计评价 · "+config.factor_id)
            metrics, observations = self.research.evaluate(batch.bars, values, mask, config.horizons, config.quantiles,
                boolean_factor=factor.definition.factor_type == FactorType.BOOLEAN)
            if wyckoff is not None:
                matrix,_,_=wyckoff.matrix(batch.bars,wyckoff_parameters)
                components=[c for c in matrix.columns if c not in ('symbol','datetime','available_at')]
                observations=observations.join(matrix.select('symbol','datetime',*[pl.col(c).alias('wyckoff_'+c) for c in components]),
                    on=['symbol','datetime'],validate='1:1')
                manifest['wyckoff']={'profile':wyckoff.definition.formula,'components':components,
                    'scope':'Explicit OHLCV A–E profile; rule scores and close-only fixed-box cause projection, not discretionary institutional intent.'}
            if context_frame is not None:
                observations = observations.join(context_frame.select("symbol", "datetime", "context_value",
                    "context_datetime", "context_available_at"), on=["symbol", "datetime"], validate="1:1")
            if raw_values is not None:
                observations = observations.join(raw_values.select("symbol", "datetime", pl.col("value").alias("raw_value"),
                    pl.col("available_at").alias("raw_available_at")), on=["symbol", "datetime"], validate="1:1")
            if states is not None:
                observations = observations.join(states.select("symbol", "datetime", "efficiency", "volatility", "volatility_baseline", *[c for c in states.columns if c.startswith("breadth_")], *state_columns),
                    on=["symbol", "datetime"], validate="1:1").sort("datetime", "symbol")
            if config.replay:
                record['replay'] = ({'version':'classic_snapshots_v1','overlay_rules':{'chan':'classic snapshots at observation time'},
                    'scope':'Classic Chan object revisions are reconstructed from sequence_audit; no generic substitute overlays.'}
                    if isinstance(factor,ClassicChanFactor) else {'version':'wyckoff_ae_v1','overlay_rules':{'wyckoff':'frozen ranges and A–E events at observation close'},'scope':'Wyckoff A–E ranges and phase chain from sequence audit'} if wyckoff is not None else replay_evidence(batch.bars, parameters))
                if isinstance(factor,LiquidityPoolFactor):
                    record['replay']={'version':'equal_extreme_pool_v1','overlay_rules':{'liquidity_pool':factor.definition.formula}}
                if isinstance(factor,ClassicChanNestFactor):
                    record['replay']={'version':'chan_multiscale_v1','overlay_rules':{'chan_multiscale':factor.definition.formula},
                        'scope':'Confirmed actual-timeframe segment links, reconstructed only from events already available.'}
            if config.sequence_audit or (config.replay and (isinstance(factor,(ClassicChanFactor,ClassicChanNestFactor,LiquidityPoolFactor)) or wyckoff is not None)):
                record['sequence_audit'] = collect_sequence_audit(factor, batch.bars, parameters, self.registry, observations)
            if config.bootstrap is not None:
                intervals = bootstrap_statistics(observations, config.horizons, config.bootstrap, config.random_seed,
                    boolean_factor=factor.definition.factor_type == FactorType.BOOLEAN)
                for horizon, estimates in intervals.items():
                    metrics[horizon]["bootstrap"] = estimates
            if config.permutation is not None:
                tests = permutation_statistics(observations, config.horizons, config.permutation, config.random_seed)
                for horizon, values in tests.items():
                    metrics[horizon]['permutation'] = values
                record['inference'] = inference_family({'metrics': metrics}, config.permutation)
            frozen = freeze_inputs(captured, self.universe, manifest) if config.replay else {}
            record.update({"experiment_id": digest(manifest), "status": "completed", "metrics": metrics, "limitations": [
                "close-to-close 未来收益是预测标签；未模拟成交、费用、滑点及涨跌停。",
                "显式股票列表不是 Point-in-Time 可交易股票池；历史状态需要单独接入。",
                "因子预热使用所选数据区间，区间开头可能无因子值。",
                "IC 每时点至少 3 个有效标的；分位统计要求足够标的及不同因子值。",
                "未自动训练或择优；可选 Holm 校正仅覆盖当前研究，不覆盖跨研究探索；未进行全量数据质量审计。",
                f"复权口径：{batch.snapshot.adjustment}；raw 含除权跳变，qfq 尚未核查历史可用性。",
            ]})
        except Exception as error:
            record.update({"experiment_id": digest(manifest), "status": "failed", "error": f"{type(error).__name__}: {error}"})
            try:
                self.store.save(run_id, record, None)
            except Exception as storage_error:
                error.add_note(f"Failure record could not be saved: {storage_error}")
            raise
        if child_ticket is not None:
            record.update(checkpoint_input_hash=child_ticket[3],checkpoint_slot=child_ticket[4])
        path = self.store.save(run_id, record, observations, **({'bars':batch.bars,'inputs':frozen} if config.replay else {}))
        result = ExperimentResult(record["experiment_id"], run_id, path, metrics)
        publish_child(child_ticket,result)
        return result

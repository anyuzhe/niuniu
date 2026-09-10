"""Bridge saved research signals to a separate execution/accounting engine."""
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import polars as pl
from quantlab.execution.backtest import OpenExecutionBacktester
from quantlab.execution.portfolio import TargetWeightBuilder, PortfolioConfig
from quantlab.storage.codec import digest
from quantlab.storage.experiments import load_record
from quantlab.experiments.runner import runtime_fingerprint


@dataclass(frozen=True)
class ExecutionResult:
    experiment_id: str
    run_id: str
    artifact_path: Path
    summary: dict


class ExecutionStudy:
    def __init__(self,runner,execution_data=None):
        self.runner=runner
        self.execution_data=execution_data
    def run(self,config,execution_config,portfolio_config=None,backend="open",market_rules=None):
        execution_config.validate_price_inputs(market_rules)
        if backend not in ("open","vnpy_open","vnpy_rules"):raise ValueError("Unknown execution backend")
        if backend=="vnpy_open" and market_rules is not None:raise ValueError("Use vnpy_rules for dated market rules")
        if backend=="vnpy_open":
            from quantlab.adapters.vnpy import validate_config
            validate_config(execution_config)
        portfolio_config=portfolio_config or PortfolioConfig()
        run_id=str(uuid4())
        manifest={'config':asdict(config),'execution':asdict(execution_config),'portfolio':asdict(portfolio_config),'backend':backend,'market_rules':market_rules.records if market_rules else None,'runtime':runtime_fingerprint()}
        record={'run_id':run_id,'created_at':datetime.now(timezone.utc).isoformat(),'kind':'execution',
            'manifest':manifest,'children':[]}
        try:
            child=self.runner.run(replace(config,replay=True))
            record['children']=[{'run_id':child.run_id,'artifact_path':str(child.artifact_path),'name':'研究信号来源'}]
            source=load_record(child.artifact_path/'experiment.json')
            signal_snapshot=source['manifest']['data_snapshot']
            execution_snapshot=signal_snapshot
            bars=pl.read_parquet(child.artifact_path/'bars.parquet')
            signal_bars=bars
            if execution_config.price_mode=='account' and signal_snapshot['adjustment']!='raw':
                from quantlab.data.mqc import MQCParquetProvider
                if self.execution_data is None and not isinstance(self.runner.data,MQCParquetProvider):
                    raise ValueError('复权信号回测需要对应的不复权行情源')
                raw_batch=(self.execution_data or MQCParquetProvider(self.runner.data.root,'raw')).load(config.data)
                if raw_batch.snapshot.adjustment!='raw':raise ValueError('成交行情必须是不复权 raw 价格')
                keys=['symbol','datetime','available_at']
                if not bars.select(keys).sort(keys).equals(raw_batch.bars.select(keys).sort(keys)):
                    raise ValueError('复权与不复权行情的证券、时间或可用时间不一致，不能混合回测')
                bars=raw_batch.bars
                execution_snapshot=asdict(raw_batch.snapshot)
            manifest['signal_data_snapshot']=signal_snapshot
            observations=pl.read_parquet(child.artifact_path/'observations.parquet')
            if 'sequence_audit' in source:
                record['sequence_audit']=source['sequence_audit']
            targets,target_audit=TargetWeightBuilder(portfolio_config).build(observations,signal_bars,
                top_n=execution_config.top_n,threshold=execution_config.threshold,exposure=execution_config.exposure)
            record['target_audit']=target_audit
            record['targets']=targets.to_dicts()
            reference_engine=OpenExecutionBacktester(execution_config,market_rules)
            reference=reference_engine.run(targets,bars)
            if backend!='vnpy_open':record['execution_audit']=reference_engine.execution_audit
            curve,fills,rejections,summary=reference
            if backend=='vnpy_rules':
                from quantlab.adapters.vnpy_rules import VnpyRulesBacktester
                from quantlab.adapters.vnpy import compare_backends
                adapter=VnpyRulesBacktester(execution_config,market_rules)
                candidate=adapter.run(targets,bars)
                curve,fills,rejections,summary=candidate
                record['backend_comparison']=compare_backends(reference,candidate)
                record['backend_comparison']['scope']='Shared platform rule-aware order preparation; native matching/cash/position reconciliation, not independent market-rule implementation'
                record['backend_details']=adapter.diagnostics
                manifest['backend_version']=adapter.diagnostics['vnpy_version']
            if backend=='vnpy_open':
                from quantlab.adapters.vnpy import VnpyOpenBacktester, compare_backends
                adapter=VnpyOpenBacktester(execution_config)
                candidate=adapter.run(targets,bars)
                curve,fills,rejections,summary=candidate
                record['backend_comparison']=compare_backends(reference,candidate)
                record['backend_details']=adapter.diagnostics
                manifest['backend_version']=adapter.diagnostics['vnpy_version']
            manifest.update(source_experiment_id=child.experiment_id,targets_hash=digest(targets.write_json()),
                data_snapshot=execution_snapshot,universe=source['manifest']['universe'])
            record.update(status='completed',experiment_id=digest(manifest),execution=summary,
                fills=fills,rejections=rejections,replay=source['replay'],limitations=[
                f"信号与K线回放使用 {signal_snapshot['adjustment']}；回测价格使用 {execution_snapshot['adjustment']}。"+('研究价格模式：不重复派息、送股或拆并股，保留交易成本；数量与现金为研究模拟值。' if execution_config.price_mode=='research' else '精细账户模式：使用 raw 价格及显式公司行动记账。'),
                '仓位/敞口/换手限制作用于目标权重；资格退出优先于换手预算。实际持仓可能因 T+1 或未成交偏离目标。',
                '独立模拟净值，假设观察到的下一根开盘价可成交；不以当根最终高低价或成交量判断开盘成交。',
                '允许 5m 收盘与下一根开盘同时间戳的零延迟模型；无盘口、部分成交队列或真实容量保证。',
                'max_volume_participation 可选：以上一根已完成同周期 K 线成交量（股）限制本根数量；日线为上一交易日量。只是滞后量代理，不使用当根最终量，也不代表开盘真实容量。',
                '整手、T+1、费用、税费及价格上下限由配置或逐时点规则决定；不自动匹配历史板块身份。',
                '研究价格模式不处理公司行动；精细账户模式按明确来源与时间处理事件及持有期税。未强平末尾持仓。',
                '逐时点规则只有在 market_rules 提供时才启用；缺失或过期规则阻止下单。规则文件的真实历史覆盖需单独验证。'])
        except Exception as error:
            record.update(status='failed',experiment_id=digest(manifest),error=f'{type(error).__name__}: {error}')
            self.runner.store.save(run_id,record,None)
            raise
        path=self.runner.store.save(run_id,record,curve,bars=bars,targets=targets)
        return ExecutionResult(record['experiment_id'],run_id,path,summary)

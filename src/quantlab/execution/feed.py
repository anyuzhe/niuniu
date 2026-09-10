"""MQC -> causal factor -> targets -> durable paper account, with explicit freshness.

Consumes a separately maintained source lake; never downloads quotes or rewrites MQC.
"""
from datetime import datetime,timezone
from pathlib import Path
from dataclasses import asdict
import json
import polars as pl
from quantlab.app import default_registry
from quantlab.factors.registry import FactorRegistry
from quantlab.data.mqc import MQCParquetProvider
from quantlab.data.base import DataRequest
from quantlab.factors.engine import compute_factor
from quantlab.execution.portfolio import TargetWeightBuilder,PortfolioConfig
from quantlab.execution.rules import MarketRules
from quantlab.execution.paper import PaperAccount
from quantlab.storage.codec import encode,digest


class MQCPaperFeed:
    def __init__(self,root,account,symbols,timeframe,start,factor,parameters,execution,portfolio=None,backend='open',archive_root=None,adjustment='qfq'):
        if adjustment not in ('qfq','raw'):raise ValueError('Paper signal adjustment must be qfq or raw')
        if archive_root and adjustment!='raw':raise ValueError('Raw-only bar archives require explicitly selecting raw signals; qfq is not manufactured')
        self.root=Path(root);self.account=PaperAccount(account);self.symbols=tuple(symbols);self.timeframe=timeframe;self.start=start
        self.factor=default_registry().get(factor,'1.0.0');self.parameters=self.factor.parameters(parameters)
        self.execution=execution;self.portfolio=portfolio or PortfolioConfig();self.backend=backend
        self.adjustment=adjustment
        self.archive_root=Path(archive_root).resolve() if archive_root else None
        self.spec={'root':str(self.root.resolve()),'symbols':self.symbols,'timeframe':timeframe,'start':start,
            'factor':factor,'parameters':self.parameters,'adjustment':adjustment,'execution':asdict(execution),'portfolio':asdict(self.portfolio),'backend':backend,'archive_root':str(self.archive_root) if self.archive_root else None,'producer_code_hash':digest({'factor':FactorRegistry.code_hash(self.factor),'portfolio':Path(__file__).with_name('portfolio.py').read_text(),'feed':Path(__file__).read_text(),'archive':(Path(__file__).parents[1]/'data/archive.py').read_text() if self.archive_root else None})}

    def poll(self,rules_path,now=None,require_fresh=False,max_age_seconds=900):
        from zoneinfo import ZoneInfo
        import math
        if type(max_age_seconds) not in (int,float) or not math.isfinite(max_age_seconds) or max_age_seconds<=0:raise ValueError('Freshness threshold must be positive and finite')
        now=now or datetime.now(timezone.utc)
        if now.tzinfo is None:raise ValueError('Feed clock needs timezone')
        now=now.astimezone(ZoneInfo('Asia/Shanghai'))
        if self.archive_root:
            from quantlab.data.archive import BarArchive
            provider=BarArchive(self.archive_root).at(now)
        else:provider=MQCParquetProvider(self.root,self.adjustment if self.execution.price_mode=='research' else 'raw')
        batch=provider.load(DataRequest(self.symbols,self.timeframe,self.start,now.date()))
        bars=batch.bars.filter(pl.col('available_at')<=now)
        if bars.is_empty():raise ValueError('No completed source bars available')
        if set(bars['symbol'])!=set(self.symbols):raise ValueError('Source has no completed bars for some requested symbols')
        ages={s:(now-bars.filter(pl.col('symbol')==s)['available_at'].max()).total_seconds() for s in self.symbols}
        if require_fresh:
            if max(ages.values())>max_age_seconds:raise ValueError('Stale source: fresh paper delivery rejected before account mutation')
            if len(set(bars.group_by('symbol').agg(pl.col('available_at').max())['available_at']))!=1:
                raise ValueError('Incomplete latest cross-section: fresh paper delivery rejected')
        signal_bars=bars
        signal_batch=batch
        if self.adjustment=='qfq' and self.execution.price_mode=='account':
            signal_batch=MQCParquetProvider(self.root,'qfq').load(DataRequest(self.symbols,self.timeframe,self.start,now.date()))
            signal_bars=signal_batch.bars.filter(pl.col('available_at')<=now)
            keys=['symbol','datetime','available_at']
            if not signal_bars.select(keys).sort(keys).equals(bars.select(keys).sort(keys)):raise ValueError('Paper qfq and raw clocks/symbols differ')
        rules=MarketRules(json.loads(Path(rules_path).read_text()))
        self.execution.validate_price_inputs(rules)
        # Bind the signal producer to this account; changes require a new account.
        binding=self.account.path.with_suffix('.feed.json')
        identity=encode(self.spec)
        with self.account.locked():
            if binding.exists():
                if binding.read_text()!=identity:raise ValueError('Paper signal producer changed; use a new account')
            else:
                with binding.open('x') as handle:handle.write(identity)
        observations=compute_factor(self.factor,signal_bars,self.parameters).with_columns(pl.lit(True).alias('eligible'))
        targets,_=TargetWeightBuilder(self.portfolio).build(observations,signal_bars,top_n=self.execution.top_n,
            threshold=self.execution.threshold,exposure=self.execution.exposure)
        state=self.account.advance(bars,targets,rules,self.execution,self.backend,now)
        return {'revision':state['revision'],'watermark':state['watermark'],'source_snapshot':batch.snapshot.snapshot_id,'signal_adjustment':self.adjustment,'signal_snapshot':signal_batch.snapshot.snapshot_id if self.adjustment=='qfq' else batch.snapshot.snapshot_id,
            'latest_bar_age_seconds':ages,'summary':state['summary'],
            'status':'stale_source' if max(ages.values())>max_age_seconds else 'source_received','freshness_note':'Age is wall-clock lag, including market closures; receipt is not a realtime certification. External MQC producer is required.'}

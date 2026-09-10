import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
from polars.testing import assert_frame_equal

from quantlab.app import default_registry
from quantlab.data.base import DataBatch, DataRequest, DataSnapshot, ExplicitUniverse
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.runner import ExperimentRunner
from quantlab.experiments.holdout import ChronologicalSplit, HoldoutRunner
from quantlab.experiments.walkforward import WalkForwardConfig, WalkForwardRunner
from quantlab.experiments.ablation import AblationRunner
from quantlab.multitimeframe.config import DailyContextConfig
from quantlab.statistics.bootstrap import BootstrapConfig
from quantlab.processing.cross_section import CrossSectionConfig
from quantlab.storage.codec import digest
from quantlab.storage.experiments import LocalExperimentStore, load_record


class ContextProvider:
    def __init__(self, change_future=False):
        self.calls = []
        self.frames = {}
        for timeframe in Timeframe:
            rows = []
            for n in range(14):
                day = date(2024,12,30) + timedelta(days=n)
                if timeframe == Timeframe.MIN5 and day < date(2025,1,1):
                    continue
                for i, symbol in enumerate(("A", "B", "C")):
                    for hour in ([10,14,15] if timeframe == Timeframe.MIN5 else [15]):
                        time = datetime(day.year, day.month, day.day, hour, tzinfo=ZoneInfo("Asia/Shanghai"))
                        close = 100. + i*5 + n*(i+1) + (n % 3)*4 + hour*.01
                        if change_future and timeframe == Timeframe.DAILY and day >= date(2025,1,9):
                            close *= 2
                        rows.append({"symbol": symbol, "datetime": time, "available_at": time, "timeframe": timeframe.value,
                            "open": close, "high": close+1, "low": close-1, "close": close, "volume": 100., "turnover": close*100})
            self.frames[timeframe] = pl.DataFrame(rows)

    def load(self, request):
        self.calls.append(request)
        bars = self.frames[request.timeframe].filter(pl.col("datetime").dt.date().is_between(request.start, request.end))
        return DataBatch(bars, DataSnapshot(digest(bars.write_json()), "fixture", "raw", ()))


def context_config():
    return ExperimentConfig("日线背景研究", DataRequest(("A","B","C"), Timeframe.MIN5, date(2025,1,1), date(2025,1,12)),
        "BASE.MOMENTUM", parameters={"lookback": 1}, horizons=(1,3),
        context=DailyContextConfig(date(2024,12,30), parameters={"lookback": 1}))


def runner(provider, path):
    return ExperimentRunner(provider, default_registry(), ExplicitUniverse(("A","B","C")), LocalExperimentStore(path))


class ContextExperimentTests(unittest.TestCase):
    def test_filter_preserves_labels_and_repeatability(self):
        provider = ContextProvider()
        cfg = replace(context_config(), processor=CrossSectionConfig(), bootstrap=BootstrapConfig(20,1))
        with tempfile.TemporaryDirectory() as tmp:
            engine = runner(provider, Path(tmp))
            a = engine.run(cfg)
            self.assertEqual(len(provider.calls), 2)
            b = engine.run(cfg)
            self.assertEqual(a.experiment_id, b.experiment_id)
            self.assertEqual(a.metrics, b.metrics)
            selected = pl.read_parquet(a.artifact_path/'observations.parquet')
            base = engine.run(replace(cfg, context=None))
            original = pl.read_parquet(base.artifact_path/'observations.parquet')
            matched = selected.select("symbol","datetime").join(original, on=["symbol","datetime"], validate="1:1").sort("symbol","datetime")
            columns = ["symbol","datetime","value","forward_1","forward_3"]
            assert_frame_equal(selected.select(columns).sort("symbol","datetime"), matched.select(columns), check_exact=True)
            self.assertLess(selected.height, original.height)
            self.assertGreater(selected.height, 0)
            self.assertTrue((selected['context_value'] > 0).all())
            self.assertTrue((selected['context_available_at'] <= selected['available_at']).all())
            record = load_record(a.artifact_path/'experiment.json')
            self.assertEqual(record['context_summary']['eligible_after'], selected.height)
            self.assertIn('日线背景筛选', (a.artifact_path/'report.md').read_text())
            empty = engine.run(replace(cfg, context=replace(cfg.context, value=1000)))
            self.assertEqual(empty.metrics['1']['observations'], 0)
            unknown = engine.run(replace(cfg, context=replace(cfg.context, parameters={'lookback':1000}, op='ne')))
            self.assertEqual(unknown.metrics['1']['observations'], 0)
            self.assertEqual(load_record(unknown.artifact_path/'experiment.json')['context_summary']['context_ready'], 0)

    def test_holdout_prefixes_and_future_mutation(self):
        split = ChronologicalSplit(date(2025,1,4), date(2025,1,8))
        with tempfile.TemporaryDirectory() as tmp:
            provider = ContextProvider()
            result = HoldoutRunner(runner(provider, Path(tmp))).run(context_config(), split)
            self.assertEqual(len(provider.calls), 2)
            changed = HoldoutRunner(runner(ContextProvider(True), Path(tmp))).run(context_config(), split)
            for original, other in zip(result.periods[:2], changed.periods[:2]):
                self.assertEqual(original['metrics'], other['metrics'])
                assert_frame_equal(pl.read_parquet(Path(original['artifact_path'])/'observations.parquet'),
                    pl.read_parquet(Path(other['artifact_path'])/'observations.parquet'), check_exact=True)
            for p in result.periods:
                record = load_record(Path(p['artifact_path'])/'experiment.json')
                self.assertEqual(record['manifest']['context']['high_request']['end'], p['end'].isoformat())
                observations = pl.read_parquet(Path(p['artifact_path'])/'observations.parquet')
                self.assertFalse(observations.filter(pl.col('context_datetime').dt.date() > p['end']).height)
                self.assertFalse(observations.filter((pl.col('datetime').dt.date() == p['end']) & (pl.col('datetime').dt.hour() == 15) & pl.col('forward_1').is_not_null()).height)

    def test_walkforward_and_ablation_share_both_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = ContextProvider()
            result = WalkForwardRunner(runner(provider, Path(tmp))).run(context_config(), WalkForwardConfig(4,2,2))
            self.assertEqual(len(provider.calls), 2)
            self.assertEqual(len(result.folds), 3)
            for fold in result.folds:
                for period in fold['periods']:
                    record = load_record(Path(period['artifact_path'])/'experiment.json')
                    self.assertEqual(record['manifest']['context']['high_request']['start'], '2024-12-30')
                    self.assertEqual(record['manifest']['context']['high_request']['end'], period['end'].isoformat())
            provider = ContextProvider()
            cfg = replace(context_config(), factor_id='COMB.SCORE', parameters={"inputs": {
                "m": {"factor_id":"BASE.MOMENTUM", "parameters":{"lookback":1}},
                "e": {"factor_id":"BASE.DIRECTIONAL_EFFICIENCY", "parameters":{"lookback":1}}},
                "weights":{"m":1,"e":1}})
            result = AblationRunner(runner(provider, Path(tmp))).run(cfg)
            self.assertEqual(len(provider.calls), 2)
            record = load_record(result.artifact_path/'experiment.json')
            frames = [pl.read_parquet(Path(c['artifact_path'])/'observations.parquet') for c in record['children']]
            for frame in frames[1:]:
                assert_frame_equal(frame.select('symbol','datetime','context_value'), frames[0].select('symbol','datetime','context_value'))

    def test_context_config_validation(self):
        cfg = context_config()
        with self.assertRaises(ValueError):
            replace(cfg, data=replace(cfg.data, timeframe=Timeframe.DAILY))
        with self.assertRaises(ValueError):
            replace(cfg, context=replace(cfg.context, start=date(2025,1,2)))
        for kwargs in ({'op':'invalid'}, {'value':float('nan')}, {'value':True}):
            with self.assertRaises(ValueError):
                replace(cfg.context, **kwargs)


if __name__ == '__main__':
    unittest.main()

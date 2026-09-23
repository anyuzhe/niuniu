"""Backtests that omit A-share taxes/fees/price limits say so; numbers are unchanged."""
import json
import tempfile
import unittest
from pathlib import Path

import polars as pl
from test_technical import bars

from quantlab.app import default_registry
from quantlab.data.base import DataBatch, DataSnapshot, ExplicitUniverse
from quantlab.execution.backtest import ExecutionConfig, cost_model_warnings
from quantlab.execution.rules import MarketRules
from quantlab.experiments.execution import ExecutionStudy
from quantlab.experiments.runner import ExperimentRunner
from quantlab.storage.codec import digest
from quantlab.storage.experiments import LocalExperimentStore
from quantlab.workbench.jobs import prepare


def rule(limit_up=None, limit_down=None):
    return {'symbol': 'sh.600000', 'effective_at': '2025-01-01T00:00:00+08:00',
            'available_at': '2025-01-01T00:00:00+08:00', 'expires_at': '2026-01-01T00:00:00+08:00',
            'suspended': False, 'st': False, 'limit_up': limit_up, 'limit_down': limit_down,
            'commission_bps': 3, 'minimum_commission': 5, 'sell_tax_bps': 5, 'transfer_bps': 0.1,
            'source': 'fixture'}


class CostModelWarningTests(unittest.TestCase):
    def test_engine_defaults_warn_about_tax_fee_and_limits(self):
        text = '\n'.join(cost_model_warnings(ExecutionConfig()))
        self.assertIn('印花税', text)
        self.assertIn('过户费', text)
        self.assertIn('未模拟涨跌停', text)

    def test_statutory_fees_and_rules_remove_warnings(self):
        only = cost_model_warnings(ExecutionConfig(statutory_fees=True, limit_pct=.1))
        self.assertEqual(len(only), 1)
        self.assertIn('固定比例', only[0])
        self.assertEqual(cost_model_warnings(ExecutionConfig(), MarketRules([rule(11.0, 9.0)])), [])
        self.assertIn('未提供任何涨跌停价', cost_model_warnings(ExecutionConfig(), MarketRules([rule()]))[0])

    def test_execution_record_and_report_carry_warnings(self):
        raw = bars([10. + i * .1 + (i % 7) * .2 for i in range(45)], 'sh.600000')

        class Source:
            def load(self, request):
                return DataBatch(raw, DataSnapshot(digest(raw.write_json()), 'synthetic', 'qfq', ()))
        config = prepare({'question': '成本提示', 'factor': 'BASE.MOMENTUM', 'parameters': {'lookback': 2},
                          'symbols': ['sh.600000'], 'timeframe': '1d', 'start': '2025-01-01', 'end': '2025-02-14',
                          'horizons': [1], 'adjustment': 'qfq', 'replay': True}).config
        with tempfile.TemporaryDirectory() as tmp:
            runner = ExperimentRunner(Source(), default_registry(), ExplicitUniverse(config.data.symbols),
                                      LocalExperimentStore(Path(tmp)))
            result = ExecutionStudy(runner).run(config, ExecutionConfig(initial_cash=10000, top_n=1))
            record = json.loads((result.artifact_path / 'experiment.json').read_text())
            self.assertEqual(len(record['cost_model_warnings']), 3)
            self.assertTrue(record['limitations'][0].startswith('⚠ 未收卖出印花税'))
            self.assertNotIn('cost_model_warnings', record['execution'])
            report = (result.artifact_path / 'report.md').read_text()
            self.assertIn('成本与交易限制提示', report)


if __name__ == '__main__':
    unittest.main()

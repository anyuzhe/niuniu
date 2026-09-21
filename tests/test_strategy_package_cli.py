"""Strategy package host CLI tests: synthetic configuration, no data acquisition."""
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from quantlab.agent.strategy_package_cli import main
from quantlab.storage.codec import encode


def package_fixture():
    return {'format': 'niuniu-strategy-package-v1', 'strategy_key': 'synthetic-momentum',
            'name': '合成样本配置，不是市场建议', 'version': '1.0.0',
            'lifecycle': {'rebalance': 'each_completed_bar', 'holding': 'target_weight',
                          'exit': 'follow_target_reductions', 'end_of_sample': 'mark_to_market_without_forced_exit'},
            'spec': {'question': '合成策略包功能验证', 'symbols': ['sh.600000', 'sz.000001', 'sh.600519'],
                     'timeframe': '1d', 'start': '2025-01-01', 'end': '2025-01-10',
                     'adjustment': 'qfq', 'qualification': 'research_only', 'replay': True, 'mode': 'execution',
                     'factor': 'BASE.MOMENTUM', 'version': '1.0.0', 'parameters': {'lookback': 2}, 'horizons': [1],
                     'execution': {'initial_cash': 10000, 'top_n': 2, 'threshold': 0, 'exposure': 0.5,
                                   'lot_size': 100, 't_plus_one': True, 'price_mode': 'research',
                                   'commission_bps': 3, 'minimum_commission': 5, 'sell_tax_bps': 5,
                                   'transfer_bps': 0.1, 'slippage_bps': 2, 'statutory_fees': False},
                     'portfolio': {'weighting': 'equal', 'max_position': 0.3, 'max_exposure': 0.5,
                                   'max_turnover': None}}}


class StrategyPackageCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.package = self.root / 'strategy.json'
        self.package.write_text(encode(package_fixture()), encoding='utf-8')

    def call(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(list(args))
        return code, json.loads(output.getvalue())

    def test_preview_exports_exact_spec_without_data_reads_or_overwrite(self):
        from quantlab.workbench.jobs import prepare
        exported = self.root / 'spec.json'
        with patch('quantlab.data.mqc.MQCParquetProvider.load', side_effect=AssertionError('no data reads')):
            code, value = self.call('preview', '--package', str(self.package), '--export-spec', str(exported))
        self.assertEqual(code, 0, value)
        self.assertFalse(value['data']['data_checked'])
        self.assertFalse(value['data']['execution_authorized'])
        spec = json.loads(exported.read_text())
        self.assertEqual(spec, value['data']['spec'])
        self.assertEqual(prepare(spec).mode, 'execution')
        before = exported.read_bytes()
        code, value = self.call('preview', '--package', str(self.package), '--export-spec', str(exported))
        self.assertEqual(code, 2)
        self.assertEqual(exported.read_bytes(), before)
        self.assertFalse((self.root / '_jobs').exists())

    def test_duplicate_keys_oversize_and_symlink_are_rejected(self):
        for content in ('{"format":"x","format":"y"}', 'x' * 65537, '{"x":NaN}'):
            self.package.write_text(content)
            code, value = self.call('preview', '--package', str(self.package))
            self.assertEqual(code, 2, value)
        self.package.write_text(encode(package_fixture()))
        linked = self.root / 'link.json'; linked.symlink_to(self.package)
        self.assertEqual(self.call('preview', '--package', str(linked))[0], 2)

    def test_changed_package_is_rejected_before_proposal_service(self):
        code, preview = self.call('preview', '--package', str(self.package))
        self.assertEqual(code, 0, preview)
        changed = deepcopy(package_fixture()); changed['spec']['execution']['initial_cash'] += 100
        self.package.write_text(encode(changed))
        with patch('quantlab.agent.proposals.ProposalService', side_effect=AssertionError('no proposal')):
            code, value = self.call('propose', '--package', str(self.package), '--expected-package-hash',
                preview['data']['package_hash'], '--expected-compiled-spec-hash', preview['data']['compiled_spec_hash'],
                '--output', str(self.root), '--data-root', str(self.root),
                '--request-id', str(uuid4()))
        self.assertEqual(code, 2, value)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['strategy.json'])

    def test_proposal_is_pending_and_duplicate_request_is_idempotent(self):
        from quantlab.agent.proposals import ProposalService
        code, preview = self.call('preview', '--package', str(self.package))
        self.assertEqual(code, 0, preview)
        args = ('propose', '--package', str(self.package), '--expected-package-hash', preview['data']['package_hash'],
                '--expected-compiled-spec-hash', preview['data']['compiled_spec_hash'], '--output', str(self.root), '--data-root', str(self.root), '--request-id', str(uuid4()))
        first_code, first = self.call(*args); second_code, second = self.call(*args)
        self.assertEqual((first_code, second_code), (0, 0), (first, second))
        self.assertEqual(first['data'], second['data'])
        self.assertEqual(first['data']['status'], 'pending')
        self.assertFalse((self.root / '_jobs').exists())
        record = ProposalService(self.root, self.root).get(first['data']['proposal_id'])
        self.assertEqual(record['plan']['spec'], preview['data']['spec'])

    def test_same_config_with_changed_signal_code_rejects_old_compiled_fingerprint(self):
        from quantlab.app import default_registry
        code, preview = self.call('preview', '--package', str(self.package))
        self.assertEqual(code, 0, preview)
        with patch.object(type(default_registry()), 'code_hash', return_value='b' * 64), \
                patch('quantlab.agent.proposals.ProposalService', side_effect=AssertionError('no proposal')):
            code, value = self.call('propose', '--package', str(self.package),
                '--expected-package-hash', preview['data']['package_hash'],
                '--expected-compiled-spec-hash', preview['data']['compiled_spec_hash'],
                '--output', str(self.root), '--data-root', str(self.root), '--request-id', str(uuid4()))
        self.assertEqual(code, 2, value)
        self.assertFalse((self.root / '_agent').exists())


if __name__ == '__main__':
    unittest.main()

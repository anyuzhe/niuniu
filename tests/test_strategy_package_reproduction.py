"""The existing execution reproducer retains strategy identity, not only numerical output."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_core
from test_strategy_package_cli import package_fixture
from quantlab.storage.bundle import reproduce_artifact
from quantlab.storage.codec import digest, encode
from quantlab.workbench.jobs import prepare, execute


class StrategyPackageReproductionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core.CoreTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def original(self):
        from quantlab.trading.strategy_package import compile_strategy
        package = package_fixture(); package['spec']['symbols'] = list(self.fixture.symbols)
        compiled = compile_strategy(package)
        result = execute(prepare(compiled['spec']), self.fixture.root, self.fixture.root / 'runs')
        return result, compiled

    def test_frozen_reproduction_keeps_exact_package_hash_and_manifest(self):
        original, compiled = self.original()
        with patch('quantlab.data.mqc.MQCParquetProvider.load', side_effect=AssertionError('external lake')):
            receipt = reproduce_artifact(original.artifact_path, self.fixture.root / 'reproduced')
        self.assertEqual(receipt['status'], 'numerically_matched')
        result = json.loads((Path(receipt['artifact_path']) / 'experiment.json').read_text())
        self.assertEqual(result['manifest']['strategy_package'], compiled['spec']['strategy_package'])
        self.assertEqual(result['manifest']['strategy_package']['package_hash'], compiled['package_hash'])

    def test_package_tampering_cannot_pass_by_only_rehashing_parent_manifest(self):
        original, _ = self.original()
        path = original.artifact_path / 'experiment.json'
        record = json.loads(path.read_text())
        record['manifest']['strategy_package']['package']['spec']['execution']['initial_cash'] += 1
        record['experiment_id'] = digest(record['manifest'])
        path.write_text(encode(record))
        with self.assertRaises(ValueError):
            reproduce_artifact(original.artifact_path, self.fixture.root / 'rejected')

    def test_rehashed_scope_claim_must_still_match_actual_execution_config(self):
        original, _ = self.original()
        path = original.artifact_path / 'experiment.json'
        record = json.loads(path.read_text())
        envelope = record['manifest']['strategy_package']
        envelope['package']['spec']['symbols'] = ['sh.600999']
        envelope['package_hash'] = digest(envelope['package'])
        record['experiment_id'] = digest(record['manifest'])
        path.write_text(encode(record))
        with self.assertRaises(ValueError):
            reproduce_artifact(original.artifact_path, self.fixture.root / 'scope-rejected')

    def test_declared_price_basis_must_match_actual_frozen_signal_snapshot(self):
        original, _ = self.original()
        path = original.artifact_path / 'experiment.json'
        record = json.loads(path.read_text())
        envelope = record['manifest']['strategy_package']
        envelope['package']['spec']['adjustment'] = 'raw'
        envelope['package_hash'] = digest(envelope['package'])
        record['experiment_id'] = digest(record['manifest'])
        path.write_text(encode(record))
        with self.assertRaisesRegex(ValueError, '价格口径'):
            reproduce_artifact(original.artifact_path, self.fixture.root / 'basis-rejected')

    def test_direct_or_reproduced_packages_cannot_claim_unverified_qualification(self):
        from quantlab.trading.strategy_package import compile_strategy
        for qualification in ('strict_pit', 'official_rule_covered', 'retrospective_reference'):
            package = package_fixture(); package['spec']['qualification'] = qualification
            with self.subTest(qualification=qualification), self.assertRaisesRegex(ValueError, '仅支持 research_only'):
                compile_strategy(package)
        original, _ = self.original()
        path = original.artifact_path / 'experiment.json'; record = json.loads(path.read_text())
        envelope = record['manifest']['strategy_package']
        envelope['package']['spec']['qualification'] = 'strict_pit'
        envelope['package_hash'] = digest(envelope['package'])
        record['experiment_id'] = digest(record['manifest']); path.write_text(encode(record))
        with self.assertRaisesRegex(ValueError, '仅支持 research_only'):
            reproduce_artifact(original.artifact_path, self.fixture.root / 'qualification-rejected')


if __name__ == '__main__':
    unittest.main()

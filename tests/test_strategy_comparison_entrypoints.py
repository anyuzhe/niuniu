"""The public comparison CLI reuses real immutable synthetic execution archives."""
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import unittest
from quantlab.agent.strategy_package_cli import main
from quantlab.storage.codec import encode
from quantlab.trading.strategy_package import compile_strategy
from quantlab.workbench.jobs import execute, prepare
import test_core
from test_strategy_package import package

class StrategyComparisonCLITests(unittest.TestCase):
    def setUp(self):
        fixture = test_core.CoreTests(); fixture.setUp(); self.addCleanup(fixture.tearDown)
        self.root = fixture.root; self.output = self.root/'runs'; self.output.mkdir()

    def cli(self, *args):
        stream = io.StringIO()
        with redirect_stdout(stream): code = main(list(args))
        return code, json.loads(stream.getvalue())

    def archive(self, value):
        return execute(prepare(compile_strategy(value)['spec']), self.root, self.output)

    def fingerprint(self):
        return {str(p.relative_to(self.output)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.output.rglob('*') if p.is_file()}

    def test_version_diff_exposes_same_version_changes_without_writes(self):
        left = package(); right = deepcopy(left); right['spec']['portfolio']['max_position'] = 0.2
        a,b = self.root/'a.json',self.root/'b.json'; a.write_text(encode(left));b.write_text(encode(right))
        before = (a.read_bytes(),b.read_bytes())
        code, result = self.cli('compare-packages','--left-package',str(a),'--right-package',str(b))
        self.assertEqual(code,0,result); self.assertTrue(result['ok'])
        data = result['data']; self.assertTrue(data['same_strategy_key']);self.assertTrue(data['same_version'])
        self.assertTrue(data['warnings']); self.assertTrue(data['changes'])
        self.assertEqual(before,(a.read_bytes(),b.read_bytes()));self.assertEqual(list(self.output.iterdir()),[])

    def test_same_source_results_are_comparable_and_read_only(self):
        a,b = self.archive(package()),self.archive(package())
        before = self.fingerprint()
        code,result = self.cli('compare-runs','--output',str(self.output),'--left-run',a.run_id,'--right-run',b.run_id)
        self.assertEqual(code,0,result); self.assertTrue(result['data']['comparable'])
        self.assertEqual(result['data']['scope'],'DESCRIPTIVE_ONLY')
        for metric in result['data']['metrics']:
            if metric['delta'] is not None:self.assertEqual(metric['delta'],0)
        self.assertEqual(before,self.fingerprint())

    def test_different_costs_return_not_comparable_exit_three(self):
        left = package(); right = deepcopy(left); right['spec']['execution']['commission_bps'] = 9
        a,b = self.archive(left),self.archive(right); before=self.fingerprint()
        code,result=self.cli('compare-runs','--output',str(self.output),'--left-run',a.run_id,'--right-run',b.run_id)
        self.assertEqual(code,3,result); self.assertTrue(result['ok']);self.assertFalse(result['data']['comparable'])
        self.assertTrue(result['data']['blockers'])
        for metric in result['data']['metrics']:self.assertIsNone(metric['delta'])
        self.assertEqual(before,self.fingerprint())

    def test_invalid_id_fails_and_does_not_create_workspace(self):
        missing=self.root/'does-not-exist'
        code,result=self.cli('compare-runs','--output',str(missing),'--left-run','../../secret','--right-run','bad-id')
        self.assertEqual(code,2);self.assertFalse(result['ok']);self.assertFalse(missing.exists())

if __name__ == '__main__': unittest.main()

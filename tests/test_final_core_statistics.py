import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from quantlab.experiments.return_family import run_return_family


class ReturnFamilyTests(unittest.TestCase):
    def test_failed_planned_comparison_keeps_holm_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('a','b','c'):
                (root/name).mkdir()
                for file in ('experiment.json','observations.parquet'):(root/name/file).write_text('fixture')
            plan={'name':'fixed','alpha':.05,'comparisons':[
                {'id':'valid','candidate':str(root/'a'),'baseline':str(root/'b'),'start':'2020-01-01'},
                {'id':'failed','candidate':str(root/'a'),'baseline':str(root/'c'),'start':'2020-01-01'}]}
            result={'run_id':'test','artifact_path':'test','summary':{'permutation':{'status':'computed','p_value':.03}}}
            def compare(*args):
                saved=list((root/'_return_families').glob('*/plan.json'))
                self.assertEqual(len(saved),1)
                self.assertEqual(len(json.loads(saved[0].read_text())['plan']['comparisons']),2)
                if Path(args[1])==(root/'c').resolve():raise ValueError('Incomparable accounts')
                return result
            with patch('quantlab.experiments.return_family.compare_returns',side_effect=compare):report=run_return_family(plan,root)['report']
            self.assertEqual(report['available_tests'],1)
            self.assertEqual(report['tests'][0]['p_holm'],.06)
            self.assertFalse(report['tests'][0]['reject'])
            self.assertEqual(report['tests'][1]['status'],'failed')
            self.assertIsNone(report['tests'][1]['p_holm'])

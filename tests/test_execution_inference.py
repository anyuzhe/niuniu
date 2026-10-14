import json
import tempfile
import unittest
from pathlib import Path
import test_execution_reproduction as base
from quantlab.experiments import execution
from quantlab.statistics import trial_ledger


class ExecutionInferenceTests(unittest.TestCase):
    def run_study(self,root,**options):
        helper=base.ExecutionReproductionTests()
        return helper.original(root,**options)

    def test_record_carries_sampling_uncertainty_and_is_reproducible(self):
        from quantlab.storage.bundle import reproduce_artifact
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);result=self.run_study(root/'runs')
            record=json.loads((result.artifact_path/'experiment.json').read_text())
            block=record['sampling_uncertainty']
            self.assertIn(block['status'],('computed','unavailable'))
            if block['status']=='computed':
                low,high=block['intervals']['sharpe']
                self.assertLessEqual(low,block['observed']['sharpe']+1e-9)
                self.assertGreaterEqual(high,block['observed']['sharpe']-1e-9)
            self.assertEqual(reproduce_artifact(result.artifact_path,root/'again')['status'],'numerically_matched')

    def test_short_curve_is_recorded_as_unavailable_not_raised(self):
        import polars as pl
        from datetime import datetime, timedelta
        curve=pl.DataFrame({'datetime':[datetime(2025,1,2)+timedelta(days=i) for i in range(10)],
                            'equity':[100.+i for i in range(10)]})
        block=execution._sampling_uncertainty(curve,100.)
        self.assertEqual(block['status'],'unavailable')
        self.assertIn('need at least 30',block['reason'])
        bad=curve.with_columns(equity=pl.lit(-5.))
        self.assertEqual(execution._sampling_uncertainty(bad,100.)['status'],'unavailable')

    def test_ledger_is_opt_in_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            plain=self.run_study(root/'plain')
            self.assertIsNone(plain.ledger)
            self.assertFalse((root/'ledger').exists())

    def test_ledger_records_run_and_failure_does_not_lose_the_artifact(self):
        import polars as pl
        from datetime import datetime, timedelta
        curve=pl.DataFrame({'datetime':[datetime(2025,1,2)+timedelta(days=i) for i in range(40)],
                            'equity':[100.+i+(i%3) for i in range(40)]})
        record={'run_id':'abc','experiment_id':'exp1','manifest':{'execution':{'initial_cash':100.}}}
        with tempfile.TemporaryDirectory() as tmp:
            spec={'root':str(Path(tmp)/'ledger'),'family':'demo','note':'t'}
            first=execution._record_trial(spec,record,curve)
            again=execution._record_trial(spec,record,curve)
            self.assertEqual((first['status'],again['status']),('recorded','unchanged'))
            self.assertTrue(trial_ledger.verify_ledger(spec['root'])['ok'])
            bad=execution._record_trial({'root':str(Path(tmp)/'l2'),'family':'bad family!'},record,curve)
            self.assertEqual(bad['status'],'failed')


if __name__=='__main__':
    unittest.main()

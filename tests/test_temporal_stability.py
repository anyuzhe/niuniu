import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from datetime import date
import polars as pl
from test_context_experiments import ContextProvider, context_config, runner
from quantlab.experiments.stability import run_stability
from quantlab.experiments.temporal_stability import label_safe_frame
from quantlab.statistics.independent_blocks import independent_mean_difference
from quantlab.statistics.bootstrap import BootstrapConfig
from quantlab.storage.experiments import load_identity
from quantlab.storage.bundle import reproduce_artifact


class TemporalStabilityTests(unittest.TestCase):
    def source(self, root):
        result = runner(ContextProvider(),root).run(replace(context_config(),context=None,replay=True))
        item = dict(name='early-versus-late',candidate=str(result.artifact_path),baseline=str(result.artifact_path),
            candidate_start='2025-01-01',candidate_end='2025-01-05',baseline_start='2025-01-08',baseline_end='2025-01-12',
            horizon=3,equivalence_margin=.05,candidate_symbols=['A','B','C'],baseline_symbols=['A','B','C'])
        plan = dict(name='temporal fixture',comparison_kind='temporal_subsample_equivalence',comparisons=[item],
            permutation=dict(resamples=200,block_days=1),bootstrap=dict(resamples=200,block_days=1))
        return result,plan

    def test_independent_blocks_unequal_lengths_and_missing(self):
        config=BootstrapConfig(200,1,.9)
        value=independent_mean_difference([.2]*10+[None],[.1]*5,config,3)
        self.assertAlmostEqual(value['estimate'],.1)
        self.assertEqual(value['observed_days'],[11,5])
        self.assertEqual(value,independent_mean_difference([.2]*10+[None],[.1]*5,config,3))
        self.assertLess(value['p_value'],.01)
        self.assertEqual(independent_mean_difference([None],[.1]*10,config,0)['status'],'unavailable')
        with self.assertRaises(ValueError):independent_mean_difference([float('nan')],[1],config,0)

    def test_cutoff_purges_labels_and_old_replay_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            result,plan=self.source(Path(tmp)/'runs');path=result.artifact_path
            record=load_identity(path/'experiment.json')
            safe,purged=label_safe_frame(path,record,3,date(2025,1,1),date(2025,1,5))
            self.assertEqual(purged,9)
            self.assertTrue(safe.filter(pl.col('datetime').dt.date()==date(2025,1,5))['forward_3'].is_null().all())
            obs=pl.read_parquet(path/'observations.parquet')
            obs.drop('label_end_1','label_end_3').write_parquet(path/'observations.parquet')
            old,old_purged=label_safe_frame(path,record,3,date(2025,1,1),date(2025,1,5))
            self.assertEqual(old_purged,purged)
            self.assertEqual(old['forward_3'].to_list(),safe['forward_3'].to_list())
            (path/'bars.parquet').unlink()
            with self.assertRaisesRegex(ValueError,'Label end times'):
                label_safe_frame(path,record,3,date(2025,1,1),date(2025,1,5))

    def test_temporal_archive_and_reproduction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);result,plan=self.source(root/'runs')
            actual=run_stability(plan,root/'runs')
            self.assertEqual(actual['summary']['method'],'temporal_subsample_equivalence')
            row=actual['summary']['comparisons'][0]
            self.assertEqual(row['test']['method'],'independent_circular_date_block_bootstrap_v1')
            self.assertGreater(row['label_boundary_audit'][0]['purged_labels'],0)
            self.assertEqual(reproduce_artifact(actual['artifact_path'],root/'reproduced')['status'],'numerically_matched')

    def test_overlap_parameter_change_and_tail_resolution_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);result,plan=self.source(root/'runs');item=plan['comparisons'][0]
            item['baseline_start']='2025-01-05'
            with self.assertRaisesRegex(ValueError,'overlap'):run_stability(plan,root/'runs')
            item['baseline_start']='2025-01-08';plan['bootstrap']['resamples']=20
            eq=run_stability(plan,root/'runs')['summary']['comparisons'][0]['equivalence']
            self.assertIsNone(eq['equivalent'])
            self.assertEqual(eq['reason'],'insufficient_resamples_in_tail')
            item['candidate_symbols']=['A','A','B']
            with self.assertRaisesRegex(ValueError,'distinct'):run_stability(plan,root/'runs')

"""Negative comparison cases must not silently drop evidence fields or inputs."""
from copy import deepcopy
import json
import unittest
import polars as pl
from quantlab.storage.codec import digest, encode
from quantlab.trading.strategy_comparison import compare_strategy_runs
from quantlab.trading.strategy_package import compile_strategy
from quantlab.workbench.jobs import execute, prepare
from test_strategy_package import package
import test_core

class StrategyComparisonBoundaryTests(unittest.TestCase):
    def setUp(self):
        f=test_core.CoreTests();f.setUp();self.addCleanup(f.tearDown)
        self.data=f.root;self.output=f.root/'boundary-runs';self.output.mkdir()

    def archive(self):return execute(prepare(compile_strategy(package())['spec']),self.data,self.output)

    def test_missing_zero_fee_field_is_corrupt_not_inferred_zero(self):
        run=self.archive();p=run.artifact_path/'experiment.json';record=json.loads(p.read_text())
        self.assertTrue(record['fills']);self.assertEqual(record['fills'][0]['tax'],0)
        del record['fills'][0]['tax'];p.write_text(encode(record))
        with self.assertRaises(ValueError):compare_strategy_runs(self.output,run.run_id,run.run_id)

    def test_additional_frozen_input_cannot_be_ignored_in_data_comparability(self):
        left,right=self.archive(),self.archive();p=right.artifact_path/'experiment.json'
        parent=json.loads(p.read_text());child_path=self.output/parent['children'][0]['run_id']/'experiment.json'
        child=json.loads(child_path.read_text());extra=deepcopy(child['manifest']['frozen_inputs']['data'][0])
        extra['request']['start']='2024-12-01'
        child['manifest']['frozen_inputs']['data'].append(extra)
        child['experiment_id']=digest(child['manifest']);child_path.write_text(encode(child))
        parent['manifest']['source_experiment_id']=child['experiment_id']
        parent['experiment_id']=digest(parent['manifest']);p.write_text(encode(parent))
        # This deliberately inconsistent extra input must either fail validation or block comparison.
        try:result=compare_strategy_runs(self.output,left.run_id,right.run_id)
        except ValueError:return
        self.assertFalse(result['comparable'],result)
        self.assertTrue(result['blockers'])
        self.assertTrue(all(row['delta'] is None for row in result['metrics']))

    def test_duplicate_account_clock_is_not_a_valid_comparison(self):
        run=self.archive();p=run.artifact_path/'observations.parquet';frame=pl.read_parquet(p)
        dates=frame['datetime'].to_list();self.assertGreater(len(dates),1);dates[1]=dates[0]
        frame.with_columns(pl.Series('datetime',dates,dtype=frame.schema['datetime'])).write_parquet(p)
        with self.assertRaises(ValueError):compare_strategy_runs(self.output,run.run_id,run.run_id)

    def test_rehashed_declared_signal_must_match_archived_actual_signal(self):
        run=self.archive();p=run.artifact_path/'experiment.json';record=json.loads(p.read_text())
        envelope=record['manifest']['strategy_package']
        envelope['package']['spec']['parameters']['lookback']=3
        envelope['package_hash']=digest(envelope['package'])
        record['experiment_id']=digest(record['manifest']);p.write_text(encode(record))
        with self.assertRaisesRegex(ValueError,'declared factor'):
            compare_strategy_runs(self.output,run.run_id,run.run_id)

    def test_different_snapshot_ids_do_not_hide_identical_actual_input_bytes(self):
        left,right=self.archive(),self.archive();p=right.artifact_path/'experiment.json'
        parent=json.loads(p.read_text());c=self.output/parent['children'][0]['run_id']/'experiment.json'
        child=json.loads(c.read_text())
        child['manifest']['data_snapshot']['snapshot_id']='different-approval-reference'
        child['manifest']['frozen_inputs']['data'][0]['snapshot']['snapshot_id']='different-approval-reference'
        parent['manifest']['signal_data_snapshot']['snapshot_id']='different-approval-reference'
        parent['manifest']['data_snapshot']['snapshot_id']='different-approval-reference'
        child['experiment_id']=digest(child['manifest']);c.write_text(encode(child))
        parent['manifest']['source_experiment_id']=child['experiment_id']
        parent['experiment_id']=digest(parent['manifest']);p.write_text(encode(parent))
        result=compare_strategy_runs(self.output,left.run_id,right.run_id)
        self.assertTrue(result['comparable'],result['blockers'])
        self.assertTrue(all(row['delta'] in (0,None) for row in result['metrics']))

    def test_historical_universe_metadata_cannot_escape_version_validation(self):
        value=package();symbols=value['spec']['symbols']
        path=self.data/'lake/bronze/provider=baostock/stock_basic/stock_basic.parquet'
        path.parent.mkdir(parents=True,exist_ok=True)
        pl.DataFrame({'code':symbols,'ipoDate':['2000-01-01']*len(symbols),'outDate':['']*len(symbols)}).write_parquet(path)
        value['spec']['universe']={'mode':'listing'}
        run=execute(prepare(compile_strategy(value)['spec']),self.data,self.output)
        self.assertTrue(compare_strategy_runs(self.output,run.run_id,run.run_id)['comparable'])
        p=run.artifact_path/'experiment.json';parent=json.loads(p.read_text())
        c=self.output/parent['children'][0]['run_id']/'experiment.json';child=json.loads(c.read_text())
        child['manifest']['frozen_inputs']['universe']['metadata']['sha256']='0'*64
        child['experiment_id']=digest(child['manifest']);c.write_text(encode(child))
        parent['manifest']['source_experiment_id']=child['experiment_id'];parent['experiment_id']=digest(parent['manifest'])
        p.write_text(encode(parent))
        with self.assertRaises(ValueError):compare_strategy_runs(self.output,run.run_id,run.run_id)

    def test_finite_but_changed_sharpe_is_not_trusted_over_account_curve(self):
        run=self.archive();p=run.artifact_path/'experiment.json';record=json.loads(p.read_text())
        self.assertIsNotNone(record['execution']['sharpe']);record['execution']['sharpe']+=10
        p.write_text(encode(record))
        with self.assertRaises(ValueError):compare_strategy_runs(self.output,run.run_id,run.run_id)

if __name__ == '__main__':unittest.main()

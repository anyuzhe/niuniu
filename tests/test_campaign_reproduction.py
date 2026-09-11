import json
import shutil
import unittest
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
import test_core
from test_campaigns import pack
from quantlab.workbench.jobs import prepare, execute
from quantlab.storage.bundle import reproduce_artifact, export_bundle, restore_bundle
from quantlab.storage.artifact_integrity import snapshot_tree, verify_tree


class CampaignReproductionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core.CoreTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root; self.output = self.root/'runs'
        self.plan = pack(self.fixture.symbols)
    def source(self, execution=False):
        self.plan['nodes'][1]['spec'].update(mode='holdout',
            split={'train_end':'2025-01-04','valid_end':'2025-01-07'})
        if execution:
            spec = deepcopy(self.plan['nodes'][0]['spec'])
            spec.update(mode='execution',execution={'price_mode':'research','top_n':1})
            spec.pop('permutation')
            self.plan['nodes'].append({'node_id':'cost','depends_on':['second'],'spec':spec})
        return execute(prepare(self.plan), self.root, self.output)
    def test_frozen_package_all_nodes_and_data_lake_absent(self):
        source = self.source(execution=True)
        before = snapshot_tree(self.output, source.run_id)
        shutil.rmtree(self.root/'lake')
        with patch('quantlab.data.mqc.MQCParquetProvider.load',side_effect=AssertionError('no lake')):
            result = reproduce_artifact(source.artifact_path, self.root/'reproduced')
        self.assertEqual(result['status'],'numerically_matched')
        self.assertEqual(result['checked_runs'],len(before['runs']))
        self.assertGreater(result['checked_parquet_files'],5)
        actual = json.loads((Path(result['artifact_path'])/'experiment.json').read_text())
        self.assertEqual(actual['experiment_id'],source.experiment_id)
        self.assertEqual(actual['summary']['family']['tests'],source.summary['family']['tests'])
        verify_tree(self.output,before)
    def test_bundle_restore_and_replay_keeps_source_identity(self):
        source = self.source(); bundle = self.root/'research.zip'
        export_bundle(source.artifact_path,bundle)
        restored = restore_bundle(bundle,self.root/'restored')
        copied = Path(restored['artifact_root'])/source.run_id
        result = reproduce_artifact(copied,self.root/'replayed')
        self.assertEqual(result['status'],'numerically_matched')
        self.assertEqual(result['source_run_id'],source.run_id)
    def test_tampered_descendant_rejected_before_any_node_runs(self):
        source = self.source()
        receipt = source.summary['nodes'][1]['artifact_tree']
        leaf = next(k for k,v in receipt['runs'].items() if not v['children'])
        (self.output/leaf/'observations.parquet').write_bytes(b'corrupted')
        destination = self.root/'must-not-start'
        with self.assertRaises((ValueError,OSError)):
            reproduce_artifact(source.artifact_path,destination)
        self.assertFalse(destination.exists())
    def test_failed_campaign_refused_instead_of_changing_original_failure(self):
        self.plan['nodes'][0]['spec']['symbols'] = ['sh.699999']
        source = execute(prepare(self.plan),self.root,self.output)
        destination = self.root/'must-not-start'
        with self.assertRaisesRegex(ValueError,'failed/skipped'):
            reproduce_artifact(source.artifact_path,destination)
        self.assertFalse(destination.exists())
    def test_no_reproduction_output_inside_original_archive(self):
        source = self.source()
        with self.assertRaises(ValueError):
            reproduce_artifact(source.artifact_path,source.artifact_path/'bad-output')
        self.assertFalse((source.artifact_path/'bad-output').exists())

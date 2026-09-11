import json
import unittest
from pathlib import Path
from copy import deepcopy
from uuid import uuid4
import test_core
from test_campaigns import pack
from quantlab.workbench.jobs import prepare
from quantlab.experiments.campaign import run_campaign, verify_receipt
from quantlab.experiments.campaign_state import read_checked
from quantlab.storage.artifact_integrity import snapshot_tree, verify_tree
from quantlab.storage.bundle import export_bundle, restore_bundle
from quantlab.agent.planning import ProposalError


class CampaignIntegrityTests(unittest.TestCase):
    def setUp(self):
        fixture=test_core.CoreTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        self.root=fixture.root;self.output=self.root/'runs';self.output.mkdir()
        self.plan=pack(fixture.symbols)
        self.plan['nodes'][1]['spec'].update(mode='holdout',
            split={'train_end':'2025-01-04','valid_end':'2025-01-07'})
        self.job=str(uuid4());self.result=run_campaign(prepare(self.plan),self.root,self.output,self.job)
        self.state=read_checked(self.output/'_campaigns'/self.job/'state.json')
    def test_covers_all_descendants_and_parquet_not_just_root(self):
        receipt=self.state['nodes']['second'];tree=receipt['artifact_tree']
        self.assertEqual(len(tree['runs']),4)
        data=[self.output/run/name for run,item in tree['runs'].items()
            for name in item['files'] if name.endswith('.parquet')]
        self.assertGreater(len(data),3)
        for path in data:
            before=path.read_bytes()
            try:
                path.write_bytes(before+b'corrupted')
                with self.assertRaises(ProposalError):verify_receipt(self.output,receipt)
            finally:path.write_bytes(before)
        verify_receipt(self.output,receipt)
    def test_deleted_child_and_legacy_receipt_cannot_be_reused(self):
        receipt=self.state['nodes']['second'];legacy=deepcopy(receipt);legacy.pop('artifact_tree')
        with self.assertRaisesRegex(ProposalError,'完整归档树'):verify_receipt(self.output,legacy)
        child=next(r for r in receipt['artifact_tree']['runs'] if r!=receipt['run_id'])
        path=self.output/child/'experiment.json';saved=path.read_bytes();path.unlink()
        try:
            with self.assertRaises(ProposalError):verify_receipt(self.output,receipt)
        finally:path.write_bytes(saved)
    def test_changed_ancillary_evidence_and_symlink_rejected(self):
        tree=snapshot_tree(self.output,self.result.run_id)
        folder=self.result.artifact_path;extra=folder/'extra-evidence.txt';extra.write_text('added')
        with self.assertRaises(ValueError):verify_tree(self.output,tree)
        extra.unlink();(folder/'dangling').symlink_to(self.root/'nonexistent')
        with self.assertRaisesRegex(ValueError,'Symlink'):verify_tree(self.output,tree)
    def test_bundle_restore_preserves_evidence_despite_rebuilt_display_cache(self):
        receipt=self.state['final']
        archive=self.root/'campaign.zip';export_bundle(self.result.artifact_path,archive)
        restored=restore_bundle(archive,self.root/'restored')
        record=verify_receipt(Path(restored['artifact_root']),receipt)
        self.assertEqual(record['experiment_id'],self.result.experiment_id)

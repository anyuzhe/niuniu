"""Exact historical Watch evidence; never replay the factor or create new work."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import unittest

import test_watchlist as fixtures
from quantlab.agent.watchlist import WatchService
from quantlab.experiments.campaign_state import write_checked
from quantlab.storage.artifact_integrity import snapshot_tree
from quantlab.storage.codec import digest


class SnapshotInspectionTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.WatchlistTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.created=self.fx.create();self.wid=self.created['watch_id'];self.sid=self.created['snapshot']['snapshot_id']
        self.service=self.fx.service
    def file_hashes(self):
        return {str(p.relative_to(self.fx.output)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.fx.output.rglob('*') if p.is_file()}
    def test_published_exact_snapshot_is_stable_readonly_and_separate_from_latest(self):
        before=self.file_hashes()
        view=self.service.inspect_snapshot(self.wid,self.sid)
        self.assertTrue(view['is_latest']);self.assertEqual(view['snapshot_position'],1)
        self.assertEqual(view['source_integrity'],'verified');self.assertFalse(view['claim_verified'])
        self.assertFalse(view['verification']['statistics_recomputed'])
        self.assertEqual(view,self.service.inspect_snapshot(self.wid,self.sid,expected_digest=view['view_digest']))
        self.assertEqual(before,self.file_hashes())
        later=self.fx.later();latest=self.service.observe(self.wid,later.run_id)
        old=self.service.inspect_snapshot(self.wid,self.sid)
        new=self.service.inspect_snapshot(self.wid,latest['snapshot']['snapshot_id'])
        self.assertFalse(old['is_latest']);self.assertTrue(new['is_latest'])
        self.assertEqual(old['snapshot_count'],2);self.assertEqual(new['snapshot_position'],2)
        self.assertEqual(old['snapshot'],self.created['snapshot'])
        self.assertEqual(old['snapshot']['source_run_id'],self.fx.source.run_id)
        self.assertEqual(new['snapshot']['source_run_id'],later.run_id)
        with self.assertRaisesRegex(ValueError,'view changed'):
            self.service.inspect_snapshot(self.wid,self.sid,expected_digest=view['view_digest'])
        self.assertEqual(WatchService(self.fx.output).inspect_snapshot(self.wid,self.sid),old)
    def test_old_source_change_never_inherits_latest_integrity(self):
        later=self.fx.later();self.service.observe(self.wid,later.run_id)
        old=self.service.inspect_snapshot(self.wid,self.sid)
        path=self.fx.source.artifact_path/'observations.parquet'
        path.write_bytes(b'changed historical source')
        self.assertEqual(self.service.get(self.wid)['source_integrity'],'verified')
        changed=self.service.inspect_snapshot(self.wid,self.sid)
        self.assertEqual(changed['source_integrity'],'source_changed')
        self.assertFalse(changed['verification']['source_bytes_checked'])
        self.assertEqual(changed['snapshot'],old['snapshot'])
        self.assertNotEqual(changed['view_digest'],old['view_digest'])
        with self.assertRaisesRegex(ValueError,'view changed'):
            self.service.inspect_snapshot(self.wid,self.sid,expected_digest=old['view_digest'])
    def test_unavailable_source_is_explicit_without_recomputing(self):
        before=self.file_hashes()
        with patch('quantlab.agent.watchlist.snapshot_tree',side_effect=OSError('unavailable')):
            view=self.service.inspect_snapshot(self.wid,self.sid)
        self.assertEqual(view['source_integrity'],'unavailable')
        self.assertIsNone(view['current_source_fingerprint'])
        self.assertEqual(view['snapshot'],self.created['snapshot'])
        self.assertEqual(before,self.file_hashes())
    def test_unpublished_or_cross_watch_snapshot_is_not_current_evidence(self):
        orphan={**self.created['snapshot'],'snapshot_id':'a'*64}
        path=self.service.store.folder(self.wid)/'snapshots'/('a'*64+'.json')
        write_checked(path,orphan)
        with self.assertRaisesRegex(ValueError,'not published'):
            self.service.inspect_snapshot(self.wid,'a'*64)
        other=self.fx.create()['watch_id']
        with self.assertRaises((ValueError,OSError)):
            self.service.inspect_snapshot(other,self.sid)
    def test_bad_snapshot_checksum_and_invalid_ids_fail_closed(self):
        for sid in ('latest','../outside','a'*63,'G'*64,None):
            with self.assertRaises((ValueError,TypeError)):
                self.service.inspect_snapshot(self.wid,sid)
        for expected in ('','bad','A'*64,True):
            with self.assertRaises(ValueError):
                self.service.inspect_snapshot(self.wid,self.sid,expected_digest=expected)
        path=self.service.store.folder(self.wid)/'snapshots'/(self.sid+'.json')
        value=json.loads(path.read_text());value['preview']['bars']=999999;path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):self.service.inspect_snapshot(self.wid,self.sid)
    def test_state_change_during_inspection_rejects_joined_view(self):
        def move_state(output,run_id):
            self.service.store.set_active(self.wid,False)
            return snapshot_tree(output,run_id)
        with patch('quantlab.agent.watchlist.snapshot_tree',side_effect=move_state):
            with self.assertRaisesRegex(ValueError,'changed during read'):
                self.service.inspect_snapshot(self.wid,self.sid)
        self.assertFalse(self.service.get(self.wid)['active'])
    def test_pause_uses_locked_compare_and_does_not_override_newer_state(self):
        old=self.service.get(self.wid);self.service.store.set_active(self.wid,False,expected_state_digest=old['state_digest'])
        before=self.file_hashes()
        with self.assertRaisesRegex(ValueError,'state changed'):
            self.service.store.set_active(self.wid,True,expected_state_digest=old['state_digest'])
        self.assertEqual(before,self.file_hashes());self.assertFalse(self.service.get(self.wid)['active'])
        current=self.service.get(self.wid)
        self.service.store.set_active(self.wid,True,expected_state_digest=current['state_digest'])
        self.assertTrue(self.service.get(self.wid)['active'])
        self.assertFalse((self.fx.output/'_jobs').exists())
    def test_existing_model_api_remains_latest_only_and_permissions_unchanged(self):
        from quantlab.agent.watch_tools import WatchResearchAPI
        from quantlab.agent.evidence_review import EVIDENCE_TOOLS
        api=WatchResearchAPI(self.fx.output,self.fx.root)
        self.assertTrue(api.call('get_factor_watch',{'watch_id':self.wid})['ok'])
        self.assertNotIn('get_factor_watch_snapshot',{t['name'] for t in api.schemas()})
        self.assertNotIn('get_factor_watch_snapshot',EVIDENCE_TOOLS)
        for action in ('get_factor_watch_snapshot','create_watch','pause_factor_for_decay','refresh_watch'):
            self.assertFalse(api.call(action,{})['ok'])
    def test_current_state_exposes_saved_history_omissions_not_complete_claim(self):
        definition,state=self.service.store.read(self.wid)
        self.assertEqual(self.service.get(self.wid)['state_digest'],digest(state))
        self.assertEqual(self.service.get(self.wid)['refresh_requests_omitted'],0)


if __name__=='__main__':unittest.main()

"""Checkpoint witnesses preserve cursor guards; never substitute published source rows."""
import gzip,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import test_tdx_distributed as fixtures
from quantlab.agent.tdx_checkpoint_witness import build_witness_bootstrap,install_witness_bootstrap,transport_variant,previous_witness_digest,PREFIX
from quantlab.agent.tdx_distributed import export_results,import_results,file_sha
from quantlab.agent.tdx_collection_cli import Runner
from quantlab.agent.tdx_transfer import TransferServer,download_bootstrap
from quantlab.data.tdx_lake import TdxLake,encode
from quantlab.data.tdx_sharding import sealed,ROLE_FILE

class WitnessTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.DistributedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.full=self.f.fleet()['bundles'][1];self.exchange=self.f.root/'exchange'
        self.receipt=build_witness_bootstrap(self.full,self.exchange/'bootstrap-variants')
        self.worker_root=self.f.root/'witness-worker'
    def install(self):
        return install_witness_bootstrap(self.worker_root,Path(self.receipt['path']),self.receipt['sha256'],self.full['sha256'])
    def worker(self):self.install();return TdxLake(self.worker_root)
    def previous_and_frontier(self,w):
        with w.db(readonly=True) as c:
            prior=dict(c.execute("SELECT * FROM jobs WHERE state='CHECKPOINT' LIMIT 1").fetchone())
            next_job=dict(c.execute("SELECT * FROM jobs WHERE symbol=? AND family=? AND offset=?",(prior['symbol'],prior['family'],prior['offset']+prior['rows'])).fetchone())
        return prior,next_job
    def test_compact_transport_preserves_original_and_no_publication(self):
        before=file_sha(Path(self.full['path']));w=self.worker();prior,j=self.previous_and_frontier(w)
        self.assertEqual(file_sha(Path(self.full['path'])),before)
        self.assertTrue(prior['chunk'].startswith(PREFIX));self.assertEqual(j['offset'],2)
        self.assertEqual(w.read('bars_1m')['rows'],[]);self.assertTrue((w.base/'STOP').exists())
        self.assertFalse(list(w.base.glob('_checkpoints/*/*/manifest.json')))
    def test_repeated_page_and_missing_witness_still_rejected(self):
        w=self.worker();prior,j=self.previous_and_frontier(w);r=Runner(w,self.f.pid)
        with self.assertRaisesRegex(ValueError,'REPEATED_PAGE'):r.validate_page_chain(j,self.f.bars(j['symbol'],10)['bars'])
        with w.db() as c:c.execute('DELETE FROM checkpoint_witnesses WHERE job_id=?',(prior['job_id'],));c.commit()
        with self.assertRaisesRegex(ValueError,'MISSING_CHECKPOINT'):r.validate_page_chain(j,[])
    def test_forged_resealed_witness_cannot_change_frozen_anchor(self):
        w=self.worker();prior,j=self.previous_and_frontier(w)
        with w.db() as c:
            value=json.loads(c.execute('SELECT body FROM checkpoint_witnesses WHERE job_id=?',(prior['job_id'],)).fetchone()[0]);value=sealed({**value,'row_digest':'0'*64})
            c.execute('UPDATE checkpoint_witnesses SET body=? WHERE job_id=?',(encode(value),prior['job_id']));c.commit()
        with self.assertRaisesRegex(ValueError,'checksum changed'):Runner(w,self.f.pid).validate_page_chain(j,[])
    def test_valid_new_page_merges_against_canonical_original(self):
        w=self.worker();prior,j=self.previous_and_frontier(w);packet=self.f.bars(j['symbol'],20)
        Runner(w,self.f.pid).validate_page_chain(j,packet['bars']);w.save_page(j,packet)
        receipt=export_results(w,w.base/'_outbox');first=import_results(self.f.lake,Path(receipt['path']),receipt['sha256']);again=import_results(self.f.lake,Path(receipt['path']),receipt['sha256'])
        self.assertEqual(first['imported_pages'],1);self.assertEqual(again['imported_pages'],0)
    def test_install_same_witness_never_resets_progress(self):
        w=self.worker();prior,j=self.previous_and_frontier(w);w.save_page(j,self.f.bars(j['symbol'],20))
        self.assertTrue(self.install()['already_installed']);self.assertEqual(len(w.read('bars_1m')['rows']),2)
    def test_wrong_parent_sha_rejected_before_install(self):
        with self.assertRaisesRegex(ValueError,'binding'):
            install_witness_bootstrap(self.worker_root,Path(self.receipt['path']),self.receipt['sha256'],'0'*64)
        self.assertFalse(self.worker_root.exists())
    def test_changed_transport_rejected(self):
        p=Path(self.receipt['path']);p.write_bytes(p.read_bytes()+b'x')
        with self.assertRaisesRegex(ValueError,'SHA'):self.install()
    def test_unregistered_transport_variant_not_served(self):
        self.assertIsNone(transport_variant(self.exchange,'0'*64,{self.full['bundle_id']:self.full}))
        with self.assertRaisesRegex(ValueError,'Unregistered'):transport_variant(self.exchange,self.receipt['bundle_id'],{})
    def test_local_service_lock_contention_waits_and_preserves_outbox(self):
        from quantlab.agent.tdx_worker_service import deliver_pending,pending_bundles
        from quantlab.agent.tdx_distributed import BundleDeferred
        w=self.worker();prior,j=self.previous_and_frontier(w);w.save_page(j,self.f.bars(j['symbol'],20))
        receipt=export_results(w,w.base/'_outbox')
        with patch('quantlab.agent.tdx_worker_service.import_results',side_effect=ValueError('Another collector owns the TDX writer lease; not starting duplicate worker')):
            with self.assertRaises(BundleDeferred):deliver_pending(w,canonical_root=self.f.lake.root)
        self.assertTrue(Path(receipt['path']).is_file());self.assertEqual(len(pending_bundles(w)),1)

    def test_actual_http_witness_download_has_full_hash(self):
        server=TransferServer(('127.0.0.1',0),self.f.lake,self.exchange)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            actual=download_bootstrap('http://127.0.0.1:'+str(server.server_port),self.receipt,self.f.root/'download')
            self.assertEqual(file_sha(actual),self.receipt['sha256'])
            result=install_witness_bootstrap(self.worker_root,actual,self.receipt['sha256'],self.full['sha256']);self.assertEqual(result['shard_id'],1)
        finally:server.shutdown();server.server_close();thread.join()

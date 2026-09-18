"""Real loopback transfer tests with synthetic pages; never contacts a provider."""
import http.client
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import test_tdx_distributed as fixtures
from quantlab.agent.tdx_distributed import export_results, BundleConflict, file_sha
from quantlab.agent.tdx_transfer import TransferServer, endpoint, json_get, send_result, download_bootstrap
from quantlab.agent.tdx_worker_service import pending_bundles, acknowledge, deliver_pending, collect_cycle, run_service
from quantlab.data.tdx_lake import write_json


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.DistributedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.worker=self.f.worker(1)
        self.server=TransferServer(('127.0.0.1',0),self.f.lake,self.f.root/'exchange')
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
        def close():
            self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)
        self.addCleanup(close)

    def result(self):
        self.f.produce(self.worker)
        return export_results(self.worker,self.worker.base/'_outbox')

    def test_endpoint_never_allows_public_or_embedded_credentials(self):
        for value in ('http://8.8.8.8:80','https://localhost:443','http://x:y@127.0.0.1:1234','http://127.0.0.1:1234/path'):
            with self.subTest(value=value),self.assertRaises(ValueError):endpoint(value)
        with self.assertRaisesRegex(ValueError,'Public'):
            TransferServer(('0.0.0.0',18943),self.f.lake,self.f.root/'bad-exchange')

    def test_real_bootstrap_resume_and_hash(self):
        receipt=self.f.fleet()['bundles'][1]
        folder=self.f.root/'download';folder.mkdir()
        (folder/(receipt['bundle_id']+'.part')).write_bytes(Path(receipt['path']).read_bytes()[:101])
        downloaded=download_bootstrap(self.url,receipt,folder)
        self.assertEqual(file_sha(downloaded),receipt['sha256'])
        self.assertEqual(download_bootstrap(self.url,receipt,folder),downloaded)

    def test_path_traversal_is_not_served(self):
        status,_=json_get(self.url,'/bootstrap/../../catalog/tdx_ingestion.sqlite3')
        self.assertEqual(status,404)

    def test_bad_upload_hash_never_enters_incoming_or_canonical(self):
        con=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        try:
            con.request('PUT','/result/homepc/'+'a'*64+'.tar',body=b'broken',headers={'X-TDX-SHA256':'b'*64})
            response=con.getresponse();response.read();self.assertEqual(response.status,400)
        finally:con.close()
        self.assertEqual(list(self.server.incoming.glob('*/*.tar')),[])
        self.assertEqual(list(self.server.incoming.glob('*/*.transfer.json')),[])

    def test_upload_is_not_acknowledged_until_merge(self):
        receipt=self.result()
        self.assertIsNone(send_result(self.url,receipt))
        self.assertEqual(len(pending_bundles(self.worker)),1)
        with patch('builtins.print'):self.server.merge_pending()
        ack=send_result(self.url,receipt)
        self.assertEqual(ack['state'],'MERGED')
        self.assertEqual(ack['imported_pages'],1)
        self.assertEqual(list(self.server.incoming.glob('*/*.tar')),[])
        acknowledge(self.worker,receipt,ack)
        self.assertEqual(pending_bundles(self.worker),[])
        self.assertFalse(Path(receipt['path']).exists())
        self.assertEqual(len(self.worker.read('bars_1m')['rows']),2)

    def test_wrong_ack_cannot_delete_pending_transfer(self):
        receipt=self.result()
        with self.assertRaises(BundleConflict):
            acknowledge(self.worker,receipt,{'state':'MERGED','bundle_id':receipt['bundle_id'],'sha256':'0'*64})
        self.assertTrue(Path(receipt['path']).exists())
        self.assertEqual(len(pending_bundles(self.worker)),1)

    def test_local_mac_delivery_uses_same_verified_ack_path(self):
        receipt=self.result()
        self.assertEqual(deliver_pending(self.worker,canonical_root=self.f.lake.root),1)
        self.assertEqual(pending_bundles(self.worker),[])
        self.assertFalse(Path(receipt['path']).exists())
        self.assertEqual(deliver_pending(self.worker,canonical_root=self.f.lake.root),0)

    def test_stop_and_auto_halt_never_call_the_source(self):
        with patch('quantlab.agent.tdx_worker_service.collection_main',side_effect=AssertionError('source called')):
            self.assertEqual(collect_cycle(self.worker)['state'],'USER_STOP')
            result=run_service(self.worker,canonical_root=self.f.lake.root,seconds=1)
            self.assertEqual(result['state'],'USER_STOP')
            (self.worker.base/'STOP').unlink()
            write_json(self.worker.base/'AUTO_HALT.json',{'reason':'fixture'})
            self.assertEqual(collect_cycle(self.worker)['state'],'AUTO_HALTED')
            self.assertEqual(run_service(self.worker,canonical_root=self.f.lake.root,seconds=1)['state'],'AUTO_HALTED')

    def test_service_runtime_interval_is_forwarded_without_policy_change(self):
        (self.worker.base/'STOP').unlink()
        with patch('quantlab.agent.tdx_worker_service.collection_main') as call:
            progress={'state':'STOPPED','processed_this_run':0,'request_interval_seconds':.25}
            write_json(self.worker.base/'progress.json',progress)
            result=collect_cycle(self.worker,seconds=1,max_requests=1,max_new_gib=1,request_interval_seconds=.25)
        args=call.call_args.args[0]
        self.assertEqual(args[args.index('--runtime-request-interval')+1],'0.25')
        self.assertEqual(result['request_interval_seconds'],.25)

    def test_slow_merge_does_not_block_http_health(self):
        from quantlab.agent.tdx_transfer import serve_transfer
        server=TransferServer(('127.0.0.1',0),self.f.lake,self.f.root/'concurrent-exchange')
        entered=threading.Event();release=threading.Event();stop=threading.Event()
        def slow_merge():entered.set();release.wait(5)
        with patch.object(server,'merge_pending',side_effect=slow_merge):
            thread=threading.Thread(target=serve_transfer,args=(server,server.exchange/'SYNC_STOP'),kwargs={'stop_event':stop},daemon=True);thread.start()
            try:
                self.assertTrue(entered.wait(3))
                con=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)
                try:
                    con.request('GET','/health');r=con.getresponse();r.read();self.assertEqual(r.status,200)
                    self.assertFalse(release.is_set())
                finally:con.close()
            finally:stop.set();release.set();thread.join(5);server.server_close()
            self.assertFalse(thread.is_alive())

    def test_sync_stop_prevents_starting_merger(self):
        from quantlab.agent.tdx_transfer import serve_transfer
        marker=self.server.exchange/'SYNC_STOP';marker.write_text('operator stop')
        with patch.object(self.server,'merge_pending',side_effect=AssertionError('must not merge')):
            serve_transfer(self.server,marker)

    def test_background_merge_error_is_not_reported_healthy(self):
        from quantlab.agent.tdx_transfer import serve_transfer
        server=TransferServer(('127.0.0.1',0),self.f.lake,self.f.root/'failed-merge-exchange')
        try:
            with patch.object(server,'merge_pending',side_effect=ValueError('injected merge failure')):
                with self.assertRaisesRegex(ValueError,'injected merge failure'):serve_transfer(server,server.exchange/'SYNC_STOP')
            self.assertTrue((server.exchange/'merge-error.json').exists())
        finally:server.server_close()

    def test_network_failure_keeps_outbox_and_source_pages(self):
        receipt=self.result()
        with patch('quantlab.agent.tdx_worker_service.send_result',side_effect=ConnectionError('tunnel down')):
            with self.assertRaises(ConnectionError):deliver_pending(self.worker,server_url=self.url)
        self.assertEqual(len(pending_bundles(self.worker)),1)
        self.assertTrue(Path(receipt['path']).exists())
        self.assertEqual(len(self.worker.read('bars_1m')['rows']),2)

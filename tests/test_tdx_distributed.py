"""Synthetic offline three-node contracts; no provider, GUI or production writes."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

import polars as pl

from quantlab.data.tdx_lake import TdxLake, digest, encode, frame_for, now, write_json
from quantlab.data.tdx_sharding import shard_for, validate_assignment, sealed, ROLE_FILE
from quantlab.agent.tdx_collection_cli import Runner, POLICY_FORMAT, writer_lease
from quantlab.agent.tdx_distributed import (
    create_bootstraps, install_bootstrap, export_results, import_results,
    aggregate_status, worker_status, unpack_bundle, write_bundle, file_sha,
    BundleConflict, BundleDeferred,
)
from quantlab.agent.tdx_storage import compact_storage, merge_local_workers, retire_local_worker_pages, synchronize_export_history


class DistributedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        disk = patch('quantlab.data.tdx_lake.shutil.disk_usage', return_value=SimpleNamespace(free=200*1024**3))
        disk.start(); self.addCleanup(disk.stop)
        (self.root/'canonical').mkdir()
        self.lake = TdxLake(self.root/'canonical', create=True)
        self.symbols = []
        for index in range(3):
            self.symbols.extend([f'sh.{n:06d}' for n in range(600000, 600060) if shard_for(f'sh.{n:06d}', 3) == index][:2])
        self.plan = {'symbols': self.symbols, 'trading_days': ['2026-09-16', '2026-09-17'],
            'max_offset': 1000000, 'personal_research_only': True, 'commercial_or_trading_use': False}
        self.pid = self.lake.add_plan(self.plan)
        self.policy = sealed({'format': POLICY_FORMAT, 'plan_id': self.pid,
            'lifecycle_bounds': {}, 'family_market_history_floors': {}, 'request_interval_seconds': .35}, 'policy_id')
        write_json(self.lake.base/'scheduler-policy.json', self.policy)
        write_json(self.lake.base/'active-plan.json', {'plan_id': self.pid})
        for symbol in self.symbols:
            job = self.job(self.lake, symbol=symbol, offset=0)
            self.lake.save_page(job, self.bars(symbol, 10))
            self.job(self.lake, symbol=symbol, offset=2, priority=100)
            self.job(self.lake, symbol=symbol, family='auction', priority=1000)
        (self.lake.base/'STOP').write_text('manual-stop')
        self.cluster = None

    def job(self, lake, *, symbol=None, family='bars_1m', offset=0, day='2026-09-17', priority=100):
        symbol = symbol or self.symbols[0]
        jid = lake.enqueue(self.pid, family, symbol, day, offset, priority)
        with lake.db(readonly=True) as con:
            return dict(con.execute('SELECT * FROM jobs WHERE job_id=?', (jid,)).fetchone())

    @staticmethod
    def bars(symbol, price):
        exchange, code = symbol.split('.')
        return {'exchange': exchange, 'code': code, 'bars': [
            {'time': '2026-09-17T09:31:00+08:00', 'open': price, 'high': price+1., 'low': price-.1, 'close': price+.5, 'volume_wire_value': 1000., 'amount': 10500., 'index': 0},
            {'time': '2026-09-17T09:32:00+08:00', 'open': price+1., 'high': price+2., 'low': price+.1, 'close': price+1.5, 'volume_wire_value': 1200., 'amount': 11500., 'index': 1}]}

    def fleet(self):
        if self.cluster is None:
            with patch('builtins.print'):
                self.cluster = create_bootstraps(self.lake, self.pid, self.root/'bootstraps')
        return self.cluster

    def worker(self, index=1):
        receipt = self.fleet()['bundles'][index]
        destination = self.root/('worker-'+str(index))
        install_bootstrap(destination, Path(receipt['path']), receipt['sha256'])
        return TdxLake(destination)

    def produce(self, worker, *, offset=2, price=20, family='bars_1m'):
        status = worker_status(worker)
        symbol = self.fleet()['assignments'][status['shard_id']]['symbols'][0]
        job = self.job(worker, symbol=symbol, offset=offset, family=family)
        packet = self.bars(symbol, price) if family.startswith('bars_') else {'points': []}
        worker.save_page(job, packet)
        return job

    def exported(self, worker):
        return export_results(worker, self.root/'results')

    def alter_bundle(self, receipt, mutate_body=None, mutate_page=None):
        with unpack_bundle(Path(receipt['path']), receipt['sha256'], self.root/'alter-staging') as (root, body):
            if mutate_page:
                mutate_page(root, body)
            if mutate_body:
                mutate_body(body)
            return write_bundle(self.root/('altered-'+str(uuid4())), body,
                {p['source_id']: root/'pages'/p['source_id'] for p in body['pages']})

    def test_shards_are_stable_disjoint_and_cover_all_symbols(self):
        assignments = self.fleet()['assignments']
        sets = [set(a['symbols']) for a in assignments]
        self.assertEqual([len(s) for s in sets], [2, 2, 2])
        self.assertEqual(set.union(*sets), set(self.symbols))
        self.assertFalse(sets[0]&sets[1] or sets[0]&sets[2] or sets[1]&sets[2])
        for symbol in self.symbols:
            expected = int(hashlib.sha256(symbol.encode('utf-8')).hexdigest(), 16) % 3
            self.assertEqual(shard_for(symbol, 3), expected)
        self.assertEqual([a['global_tasks'] for a in assignments], [True, False, False])

    def test_assignment_rehash_does_not_allow_another_symbol(self):
        assignment = self.fleet()['assignments'][1]
        forged = sealed({**assignment, 'symbols': self.symbols}, 'assignment_id')
        with self.assertRaisesRegex(ValueError, 'assignment mismatch'):
            validate_assignment(forged, self.plan, self.pid, self.policy['policy_id'])

    def test_coordinator_can_never_resume_unsharded_collection(self):
        self.fleet()
        with self.assertRaisesRegex(ValueError, 'coordinator'):
            Runner(self.lake, self.pid)
        self.assertTrue((self.lake.base/'STOP').exists())

    def test_bootstrap_minimal_previous_page_preserves_exact_cursor(self):
        worker = self.worker(1)
        with worker.db(readonly=True) as con:
            checkpoints = [dict(r) for r in con.execute("SELECT * FROM jobs WHERE state='CHECKPOINT'")]
            pending_bars = [dict(r) for r in con.execute("SELECT * FROM jobs WHERE family='bars_1m' AND state='PENDING'")]
        self.assertEqual(len(checkpoints), 2)
        self.assertEqual([j['offset'] for j in pending_bars], [2, 2])
        self.assertEqual(len(worker.read('bars_1m')['rows']), 0)
        self.assertEqual(len(list(worker.base.glob('_checkpoints/*/*/manifest.json'))), 2)
        self.assertTrue((worker.base/'STOP').exists())

    def test_reinstall_same_bundle_never_resets_worker_progress(self):
        worker = self.worker(1)
        self.produce(worker)
        before = worker_status(worker)['counts']
        receipt = self.fleet()['bundles'][1]
        result = install_bootstrap(worker.root, Path(receipt['path']), receipt['sha256'])
        self.assertTrue(result['already_installed'])
        self.assertEqual(worker_status(worker)['counts'], before)

    def test_wrong_shard_queue_is_rejected_before_network(self):
        worker = self.worker(1)
        alien = self.fleet()['assignments'][0]['symbols'][0]
        self.job(worker, symbol=alien)
        with patch('quantlab.agent.tdx_collection_cli.Source', side_effect=AssertionError('network')):
            with self.assertRaisesRegex(ValueError, 'different TDX shard'):
                Runner(worker, self.pid)

    def test_policy_change_cannot_silently_change_worker_bounds(self):
        worker = self.worker(1)
        write_json(worker.base/'scheduler-policy.json', sealed({**self.policy, 'request_interval_seconds': .3}, 'policy_id'))
        with self.assertRaisesRegex(ValueError, 'policy mismatch'):
            Runner(worker, self.pid)

    def test_stored_page_is_invisible_until_explicit_commit(self):
        symbol = self.symbols[0]
        job = self.job(self.lake, symbol=symbol, family='bars_daily')
        self.lake.save_page(job, self.bars(symbol, 10), finalize=False)
        self.assertEqual(self.lake.read('bars_daily')['rows'], [])
        with self.lake.db(readonly=True) as con:
            stored = dict(con.execute('SELECT * FROM jobs WHERE job_id=?', (job['job_id'],)).fetchone())
        self.lake.commit_saved_page(stored)
        self.assertEqual(len(self.lake.read('bars_daily')['rows']), 2)

    def test_crash_before_file_promotion_is_reconciled_without_exposing_stored(self):
        symbol = self.symbols[0]
        job = self.job(self.lake, symbol=symbol, family='bars_daily')
        with patch.object(self.lake, '_promote_page', side_effect=OSError('simulated crash')):
            with self.assertRaisesRegex(OSError, 'crash'):
                self.lake.save_page(job, self.bars(symbol, 12))
        self.assertEqual(self.lake.read('bars_daily')['rows'], [])
        self.assertEqual(self.lake.status()['control']['pending_publication_promotions'], 1)
        self.assertEqual(self.lake.reconcile_publications(), 1)
        self.assertEqual(len(self.lake.read('bars_daily')['rows']), 2)

    def test_saved_worker_bytes_resume_without_refetch(self):
        worker = self.worker(1)
        symbol = self.fleet()['assignments'][1]['symbols'][0]
        job = self.job(worker, symbol=symbol, offset=2)
        worker.save_page(job, self.bars(symbol, 20), finalize=False)
        with worker.db() as con:
            con.execute('UPDATE jobs SET priority=-100 WHERE job_id=?', (job['job_id'],)); con.commit()
        (worker.base/'STOP').unlink()
        with patch('quantlab.agent.tdx_collection_cli.Source', side_effect=AssertionError('must reuse bytes')):
            result = Runner(worker, self.pid).run(5, 1, 1)
        self.assertEqual(result['network_attempts'], 0)
        self.assertEqual(result['reused_pages'], 1)
        self.assertEqual(len(worker.read('bars_1m')['rows']), 2)

    def test_missing_previous_page_rejects_even_empty_frontier(self):
        job = self.job(self.lake, symbol=self.symbols[0], offset=50)
        with self.assertRaisesRegex(ValueError, 'MISSING_CHECKPOINT'):
            Runner(self.lake, self.pid).validate_page_chain(job, [])

    def test_repeated_rows_are_not_published(self):
        symbol = self.symbols[0]
        job = self.job(self.lake, symbol=symbol, offset=2)
        with self.assertRaisesRegex(ValueError, 'REPEATED_PAGE'):
            Runner(self.lake, self.pid).validate_page_chain(job, self.bars(symbol, 10)['bars'])

    def test_export_excludes_baseline_checkpoints_and_unfinished_pages(self):
        worker = self.worker(1)
        self.produce(worker)
        another = self.fleet()['assignments'][1]['symbols'][1]
        job = self.job(worker, symbol=another, offset=2)
        worker.save_page(job, self.bars(another, 25), finalize=False)
        receipt = self.exported(worker)
        self.assertEqual(receipt['exported_pages'], 1)
        with unpack_bundle(Path(receipt['path']), receipt['sha256'], self.root/'inspect') as (_, body):
            self.assertEqual(len(body['pages']), 1)
            self.assertEqual(body['pages'][0]['state'], 'SAVED')

    def test_export_reads_exact_page_from_large_file_archive(self):
        worker = self.worker(1)
        self.produce(worker)
        compact_storage(worker, families=('bars_1m',), batch_pages=10)
        receipt = self.exported(worker)
        merged = import_results(self.lake, Path(receipt['path']), receipt['sha256'])
        self.assertEqual(merged['imported_pages'], 1)

    def test_missing_worker_sequence_history_restores_only_from_canonical_ledger(self):
        worker = self.worker(1)
        self.produce(worker)
        receipt = self.exported(worker)
        import_results(self.lake, Path(receipt['path']), receipt['sha256'])
        with worker.db() as con:
            con.execute('DROP TABLE distributed_result_bundles');con.commit()
        result=synchronize_export_history(worker,self.lake)
        self.assertEqual(result['installed_sequences'],1)
        self.assertEqual(result['next_sequence'],2)

    def test_local_merge_uses_normal_verified_bundle_and_ack_path(self):
        worker=self.worker(1)
        self.produce(worker)
        result=merge_local_workers(self.lake,(worker,),batch_pages=10)
        self.assertEqual(result['workers'][0]['imported_pages'],1)
        self.assertEqual(result['workers'][0]['new_bundles'],1)
        with worker.db(readonly=True) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM distributed_result_bundles WHERE acked=1').fetchone()[0],1)
        compact_storage(self.lake,batch_pages=20)
        ready=retire_local_worker_pages(self.lake,(worker,),dry_run=True)
        self.assertEqual(ready['state'],'VERIFIED_READY')
        self.assertTrue(next(worker.base.glob('bars_1m/pages/*/manifest.json')).exists())
        self.assertFalse((worker.base/'retired-to-canonical.json').exists())
        retired=retire_local_worker_pages(self.lake,(worker,))
        self.assertEqual(retired['workers'][0]['publications'],1)
        self.assertEqual(json.loads((worker.base/'retired-to-canonical.json').read_text())['state'],'RETIRED')

    def test_retirement_refuses_unrecorded_page_before_deleting_known_pages(self):
        worker=self.worker(1)
        self.produce(worker)
        merge_local_workers(self.lake,(worker,),batch_pages=10)
        compact_storage(self.lake,batch_pages=20)
        known=next(worker.base.glob('bars_1m/pages/*/manifest.json'))
        orphan=worker.base/'_stored'/'bars_1m'/('f'*64)
        orphan.mkdir(parents=True)
        (orphan/'unique.txt').write_text('not published')
        with self.assertRaisesRegex(ValueError,'Unrecorded worker page'):
            retire_local_worker_pages(self.lake,(worker,))
        self.assertTrue(known.exists())
        self.assertTrue((orphan/'unique.txt').exists())
        self.assertFalse((worker.base/'retired-to-canonical.json').exists())

    def test_retirement_refuses_unpublished_stored_page(self):
        worker=self.worker(1)
        self.produce(worker)
        merge_local_workers(self.lake,(worker,),batch_pages=10)
        compact_storage(self.lake,batch_pages=20)
        symbol=self.fleet()['assignments'][1]['symbols'][1]
        job=self.job(worker,symbol=symbol,offset=2)
        worker.save_page(job,self.bars(symbol,25),finalize=False)
        stored=next(worker.base.glob('_stored/bars_1m/*/manifest.json'))
        with self.assertRaisesRegex(ValueError,'Unpublished worker job'):
            retire_local_worker_pages(self.lake,(worker,))
        self.assertTrue(stored.exists())
        self.assertFalse((worker.base/'retired-to-canonical.json').exists())

    def test_retirement_refuses_extra_or_changed_worker_file(self):
        worker=self.worker(1)
        self.produce(worker)
        merge_local_workers(self.lake,(worker,),batch_pages=10)
        compact_storage(self.lake,batch_pages=20)
        folder=next(worker.base.glob('bars_1m/pages/*'))
        extra=folder/'unique.txt'
        extra.write_text('not part of page')
        with self.assertRaisesRegex(ValueError,'Unexpected file in worker page'):
            retire_local_worker_pages(self.lake,(worker,))
        extra.unlink()
        raw=folder/'response.json.gz'
        raw.write_bytes(raw.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'Worker page differs from canonical archive'):
            retire_local_worker_pages(self.lake,(worker,))
        self.assertTrue(raw.exists())
        self.assertFalse((worker.base/'retired-to-canonical.json').exists())

    def test_retirement_keeps_virtual_checkpoint_witnesses_in_queue(self):
        worker=self.worker(1)
        self.produce(worker)
        merge_local_workers(self.lake,(worker,),batch_pages=10)
        compact_storage(self.lake,batch_pages=20)
        with worker.db() as con:
            checkpoints=[dict(row) for row in con.execute("SELECT job_id,chunk FROM jobs WHERE state='CHECKPOINT'")]
            con.execute('CREATE TABLE checkpoint_witnesses(job_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,body TEXT NOT NULL)')
            for row in checkpoints:
                source_id=Path(row['chunk']).name
                con.execute('INSERT INTO checkpoint_witnesses VALUES (?,?,?)',(row['job_id'],source_id,'{}'))
                con.execute('UPDATE jobs SET chunk=? WHERE job_id=?',('_checkpoint_witnesses/'+source_id,row['job_id']))
            con.commit()
        for row in checkpoints:shutil.rmtree(worker.root/row['chunk'])
        ready=retire_local_worker_pages(self.lake,(worker,),dry_run=True)
        self.assertEqual(ready['state'],'VERIFIED_READY')
        self.assertEqual(ready['workers'][0]['checkpoints'],len(checkpoints))
        self.assertEqual(ready['workers'][0]['physical_page_directories'],1)

    def test_retirement_preflights_every_worker_before_deleting_first(self):
        first=self.worker(1)
        second=self.worker(2)
        self.produce(first)
        self.produce(second)
        merge_local_workers(self.lake,(first,second),batch_pages=10)
        compact_storage(self.lake,batch_pages=20)
        first_page=next(first.base.glob('bars_1m/pages/*/manifest.json'))
        orphan=second.base/'_stored'/'bars_1m'/('f'*64)
        orphan.mkdir(parents=True)
        (orphan/'unique.txt').write_text('keep')
        with self.assertRaisesRegex(ValueError,'Unrecorded worker page'):
            retire_local_worker_pages(self.lake,(first,second))
        self.assertTrue(first_page.exists())
        self.assertFalse((first.base/'retired-to-canonical.json').exists())

    def test_verified_merge_is_idempotent_and_preserves_baseline_bytes(self):
        worker = self.worker(1)
        original = {p: file_sha(p) for p in self.lake.base.glob('*/pages/*/data.parquet')}
        self.produce(worker)
        receipt = self.exported(worker)
        first = import_results(self.lake, Path(receipt['path']), receipt['sha256'])
        second = import_results(self.lake, Path(receipt['path']), receipt['sha256'])
        self.assertEqual(first['imported_pages'], 1)
        self.assertEqual(second['imported_pages'], 0)
        self.assertEqual(second['duplicate_pages'], 1)
        self.assertEqual(len(self.lake.read('bars_1m', limit=100)['rows']), 14)
        self.assertEqual({p: file_sha(p) for p in original}, original)
        self.assertFalse(aggregate_status(self.lake)['history_complete'])

    def test_empty_response_merges_only_as_auditable_empty(self):
        worker = self.worker(1)
        self.produce(worker, family='auction', offset=0)
        receipt = self.exported(worker)
        import_results(self.lake, Path(receipt['path']), receipt['sha256'])
        self.assertEqual(self.lake.read('auction')['rows'], [])
        self.assertEqual(len(list(self.lake.base.glob('_empty_pages/auction/*/manifest.json'))), 1)

    def test_corrupted_raw_bytes_are_quarantined_before_any_publication(self):
        worker = self.worker(1); self.produce(worker)
        receipt = self.exported(worker)
        def corrupt(root, body):
            (root/'pages'/body['pages'][0]['source_id']/'response.json.gz').write_bytes(b'broken')
        altered = self.alter_bundle(receipt, mutate_page=corrupt)
        with self.assertRaisesRegex(BundleConflict, 'checksum'):
            import_results(self.lake, Path(altered['path']), altered['sha256'])
        self.assertEqual(len(self.lake.read('bars_1m', limit=100)['rows']), 12)
        self.assertEqual(aggregate_status(self.lake)['conflicts'], 1)

    def test_forged_status_cannot_partially_import_valid_pages(self):
        worker = self.worker(1); self.produce(worker)
        receipt = self.exported(worker)
        altered = self.alter_bundle(receipt, mutate_body=lambda b: b['status'].update({'assignment_id': '0'*64}))
        with self.assertRaisesRegex(BundleConflict, 'status identity'):
            import_results(self.lake, Path(altered['path']), altered['sha256'])
        self.assertEqual(len(self.lake.read('bars_1m', limit=100)['rows']), 12)

    def test_out_of_order_delivery_defers_without_quarantining(self):
        worker = self.worker(1); self.produce(worker, offset=2, price=20)
        first = self.exported(worker)
        self.produce(worker, offset=4, price=30)
        second = self.exported(worker)
        with self.assertRaises(BundleDeferred):
            import_results(self.lake, Path(second['path']), second['sha256'])
        self.assertEqual(aggregate_status(self.lake)['conflicts'], 0)
        import_results(self.lake, Path(first['path']), first['sha256'])
        import_results(self.lake, Path(second['path']), second['sha256'])
        self.assertEqual(len(self.lake.read('bars_1m', limit=100)['rows']), 16)

    def test_incoming_offset_gap_is_rejected(self):
        worker = self.worker(1); self.produce(worker, offset=50, price=20)
        receipt = self.exported(worker)
        with self.assertRaisesRegex(BundleConflict, 'preceding saved page'):
            import_results(self.lake, Path(receipt['path']), receipt['sha256'])
        self.assertEqual(len(self.lake.read('bars_1m', limit=100)['rows']), 12)

    def test_same_source_id_different_verified_sha_cannot_overwrite(self):
        worker = self.worker(1); self.produce(worker)
        receipt = self.exported(worker)
        import_results(self.lake, Path(receipt['path']), receipt['sha256'])
        before = {p: file_sha(p) for p in self.lake.base.glob('*/pages/*/data.parquet')}
        def change_observation(root, body):
            item = body['pages'][0]; folder = root/'pages'/item['source_id']
            raw = json.loads(gzip.decompress((folder/'response.json.gz').read_bytes()))
            raw['observed_at'] = '2026-09-18T12:00:00+00:00'
            (folder/'response.json.gz').write_bytes(gzip.compress(encode(raw).encode(), mtime=0))
            rows = raw['result']['bars']
            frame_for(item['family'], rows, raw['request'], raw['observed_at'], item['source_id']).write_parquet(folder/'data.parquet')
            manifest = json.loads((folder/'manifest.json').read_text())
            manifest.update({'observed_at': raw['observed_at'], 'raw_sha256': file_sha(folder/'response.json.gz'), 'parquet_sha256': file_sha(folder/'data.parquet')})
            write_json(folder/'manifest.json', sealed(manifest))
            item.update({'raw_sha256': file_sha(folder/'response.json.gz'), 'parquet_sha256': file_sha(folder/'data.parquet'), 'manifest_sha256': file_sha(folder/'manifest.json')})
            body['sequence_no'] = 2
        altered = self.alter_bundle(receipt, mutate_page=change_observation)
        with self.assertRaisesRegex(BundleConflict, 'Same source_id'):
            import_results(self.lake, Path(altered['path']), altered['sha256'])
        self.assertEqual({p: file_sha(p) for p in before}, before)

    def test_archive_traversal_is_rejected(self):
        self.fleet()
        path = self.root/'unsafe.tar'
        with tarfile.open(path, 'w') as archive:
            info = tarfile.TarInfo('../outside'); info.size = 1
            archive.addfile(info, io.BytesIO(b'x'))
        with self.assertRaisesRegex(BundleConflict, 'unsafe'):
            import_results(self.lake, path, file_sha(path))
        self.assertFalse((self.root/'outside').exists())

    def test_writer_contention_is_not_a_data_conflict(self):
        worker = self.worker(1); self.produce(worker)
        receipt = self.exported(worker)
        with writer_lease(self.lake), self.assertRaisesRegex(ValueError, 'writer lease'):
            import_results(self.lake, Path(receipt['path']), receipt['sha256'])
        self.assertEqual(aggregate_status(self.lake)['conflicts'], 0)

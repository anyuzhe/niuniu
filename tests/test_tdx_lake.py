"""TDX persistence correctness with synthetic sources; never connects to market servers."""
import contextlib,gzip,json,tempfile,unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
import duckdb
from quantlab.data.tdx_lake import TdxLake,FAMILIES,rows_for,frame_for,digest,sha
from quantlab.agent.tdx_collection_cli import (Runner,writer_lease,_latest_allowed_day,
    apply_scheduler_policy_to_pending,load_scheduler_policy,POLICY_FORMAT)
from quantlab.agent.tdx_storage import compact_storage

class TdxLakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'catalog').mkdir()
        with duckdb.connect(str(self.root/'catalog/mqc.duckdb')) as con:
            con.execute('CREATE TABLE bronze_stock_kline_daily(x INTEGER)');con.execute('INSERT INTO bronze_stock_kline_daily VALUES (42)')
        from types import SimpleNamespace
        disk=patch('quantlab.data.tdx_lake.shutil.disk_usage',return_value=SimpleNamespace(free=200*1024**3));disk.start();self.addCleanup(disk.stop)
        self.lake=TdxLake(self.root,create=True)
        self.body={'trading_days':['2026-09-16','2026-09-17'],'max_offset':1000000,'personal_research_only':True}
        self.pid=self.lake.add_plan(self.body)
    def job(self,family='bars_1m',offset=0):
        jid=self.lake.enqueue(self.pid,family,'sz.000001','2026-09-17',offset)
        return {'job_id':jid,'plan_id':self.pid,'family':family,'symbol':'sz.000001','day':'2026-09-17','offset':offset}
    def bar(self):
        return {'exchange':'sz','code':'000001','bars':[{'time':'2026-09-17T09:31:00+08:00','open':10.,'high':10.2,'low':9.9,'close':10.1,'volume_wire_value':1000.,'amount':10050.,'extra_original':{'x':7}}]}
    def test_existing_tables_and_all_new_families(self):
        with duckdb.connect(str(self.root/'catalog/mqc.duckdb'),read_only=True) as con:
            self.assertEqual(con.execute('SELECT * FROM bronze_stock_kline_daily').fetchall(),[(42,)])
            for f in FAMILIES:self.assertEqual(con.execute('SELECT count(*) FROM tdx_'+f).fetchone()[0],0)
    def test_raw_parquet_and_duckdb_same_record(self):
        job=self.job();m,rows=self.lake.save_page(job,self.bar(),observed_at='2026-09-18T00:00:00+00:00')
        data=self.lake.read('bars_1m','sz.000001')['rows'][0]
        self.assertEqual(data['volume'],1000);self.assertEqual(data['volume_unit'],'shares_wire_value')
        self.assertEqual(json.loads(data['record_json'])['extra_original'],{'x':7})
        self.assertEqual(data['date'],date(2026,9,17))
        self.assertEqual(self.lake.verify_page('bars_1m',m['source_id'])['rows'],1)
    def test_verified_compaction_preserves_exact_bytes_and_query_rows(self):
        job=self.job();manifest,_=self.lake.save_page(job,self.bar(),observed_at='2026-09-18T00:00:00+00:00')
        source=self.lake.page_source('bars_1m',manifest['source_id'])
        originals={name:source.read_bytes(name) for name in ('response.json.gz','data.parquet','manifest.json')}
        (self.lake.base/'STOP').write_text('maintenance')
        result=compact_storage(self.lake,families=('bars_1m',),batch_pages=10)
        self.assertEqual(result['compacted_pages'],1)
        self.assertFalse((self.lake.base/'bars_1m/pages'/manifest['source_id']).exists())
        archived=self.lake.page_source('bars_1m',manifest['source_id'])
        self.assertIsNone(archived.folder)
        self.assertEqual({name:archived.read_bytes(name) for name in originals},originals)
        self.assertEqual(self.lake.read('bars_1m','sz.000001')['rows'][0]['volume'],1000)
        self.assertEqual(self.lake.verify_page('bars_1m',manifest['source_id'])['rows'],1)
        with self.lake.db(readonly=True) as con:published=dict(con.execute('SELECT * FROM jobs WHERE job_id=?',(job['job_id'],)).fetchone())
        with patch('quantlab.agent.tdx_collection_cli.Source',side_effect=AssertionError('must reuse archived bytes')):
            _,payload,_,error=Runner(self.lake,self.pid).fetch(published)
        self.assertIsNone(error);self.assertEqual(payload,self.bar())
        self.assertEqual(compact_storage(self.lake,families=('bars_1m',),batch_pages=10)['compacted_pages'],0)
    def test_compaction_retry_preserves_unverified_residual_files(self):
        manifest,_=self.lake.save_page(self.job(),self.bar())
        (self.lake.base/'STOP').write_text('maintenance')
        compact_storage(self.lake,families=('bars_1m',),batch_pages=10)
        folder=self.lake.base/'bars_1m/pages'/manifest['source_id']
        folder.mkdir()
        (folder/'unexpected.txt').write_text('unique')
        with self.assertRaisesRegex(ValueError,'Unexpected file'):
            compact_storage(self.lake,families=('bars_1m',),batch_pages=10)
        self.assertTrue((folder/'unexpected.txt').exists())
        (folder/'unexpected.txt').unlink()
        (folder/'response.json.gz').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'differs from archive'):
            compact_storage(self.lake,families=('bars_1m',),batch_pages=10)
        self.assertEqual((folder/'response.json.gz').read_bytes(),b'changed')
    def test_empty_distinct_from_none_or_error(self):
        job=self.job();m,_=self.lake.save_page(job,{'exchange':'sz','code':'000001','bars':[]})
        self.assertEqual(m['rows'],0)
        self.assertEqual(self.lake.status()['jobs'][0]['state'],'EMPTY')
        for result in (None,{'error_code':5,'bars':[]},{}):
            with self.subTest(result=result),self.assertRaises(ValueError):self.lake.save_page(self.job(offset=800),result)
    def test_idempotent_retry_and_no_duplicate_publication(self):
        job=self.job();one,_=self.lake.save_page(job,self.bar());two,_=self.lake.save_page(job,self.bar())
        self.assertEqual(one['source_id'],two['source_id']);self.assertEqual(self.lake.status()['families'][0]['rows'],1)
        self.assertEqual(len(self.lake.read('bars_1m')['rows']),1)
    def test_corrupt_page_rejected(self):
        m,_=self.lake.save_page(self.job(),self.bar())
        path=self.lake.base/'bars_1m/pages'/m['source_id']/'data.parquet';path.write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'Page bytes'):self.lake.verify_page('bars_1m',m['source_id'])
    def test_symbol_and_date_identity_enforced(self):
        bad=self.bar();bad['code']='000002'
        with self.assertRaisesRegex(ValueError,'security'):self.lake.save_page(self.job(),bad)
        trade={'exchange':'sz','code':'000001','trading_date':'2026-09-16','ticks':[]}
        with self.assertRaisesRegex(ValueError,'trading day'):self.lake.save_page(self.job('trades'),trade)
    def test_quote_snapshot_never_backfilled_as_historical_available(self):
        j=self.job('depth');m,_=self.lake.save_page(j,{'records':[{'last_price':10.,'buy_levels':[{'price':10.,'volume':5}]}]},observed_at='2026-09-18T01:00:00+00:00')
        row=self.lake.read('depth')['rows'][0]
        self.assertEqual(row['observed_at'],'2026-09-18T01:00:00+00:00');self.assertIsNone(row['event_time'])
        self.assertEqual(row['date'],date(2026,9,18))
        self.assertEqual(json.loads(row['record_json'])['buy_levels'][0]['volume'],5)
        self.assertFalse(m['complete_history'])
    def test_pages_continue_even_when_short_until_empty(self):
        runner=Runner(self.lake,self.pid);job=self.job();m,rows=self.lake.save_page(job,self.bar())
        runner.follow(job,m,rows)
        with self.lake.db(readonly=True) as con:
            offsets=con.execute('SELECT offset FROM jobs ORDER BY offset').fetchall()
        self.assertEqual([r[0] for r in offsets],[0,1])
    def test_opening_match_retains_exact_trade_row_no_price_volume_fabrication(self):
        row={'trade_datetime':'2026-09-17T09:25:00','event_kind':'opening_match','price':11.68,'volume':3624}
        job=self.job('trades');m,rows=self.lake.save_page(job,{'exchange':'sz','code':'000001','trading_date':'2026-09-17','ticks':[row]})
        Runner(self.lake,self.pid).follow(job,m,rows)
        result=self.lake.read('opening_match')['rows'][0]
        self.assertEqual(json.loads(result['record_json']),row);self.assertIsNone(result['amount'])
        self.assertEqual(result['volume_unit'],'lots_provider')
    def test_history_empty_day_does_not_imply_no_earlier_history(self):
        job=self.job('auction');m,rows=self.lake.save_page(job,{'exchange':'sz','code':'000001','trading_date':'2026-09-17','points':[]})
        Runner(self.lake,self.pid).follow(job,m,rows)
        with self.lake.db(readonly=True) as con:days=[r[0] for r in con.execute('SELECT day FROM jobs ORDER BY day')]
        self.assertEqual(days,['2026-09-16','2026-09-17'])
    def test_queue_claim_recover_errors_and_retry_limits(self):
        job=self.job();self.assertEqual(len(self.lake.next_jobs(self.pid)),1);self.assertEqual(self.lake.next_jobs(self.pid),[])
        self.lake.recover(self.pid);self.assertEqual(len(self.lake.next_jobs(self.pid)),1)
        self.lake.mark(job,'ERROR',error='timeout');self.lake.recover(self.pid)
        self.assertEqual(self.lake.next_jobs(self.pid),[])
        self.lake.recover(self.pid,retry_errors=True);self.assertEqual(len(self.lake.next_jobs(self.pid)),1)
    def test_nonfinite_values_and_unsafe_identifiers_rejected(self):
        with self.assertRaises(ValueError):self.lake.save_page(self.job(),{'bars':[{'x':float('nan')}]})
        with self.assertRaises(ValueError):self.lake.read('bars_1m;DROP TABLE x')
        with self.assertRaises(ValueError):self.lake.read('bars_1m',"' OR 1=1")
    def test_symlink_output_rejected(self):
        other=self.root/'other';other.mkdir();link=self.root/'link'
        try:link.symlink_to(other,target_is_directory=True)
        except OSError as exc:
            import os,subprocess
            if os.name!='nt' or getattr(exc,'winerror',None)!=1314:raise
            # A real Windows junction exercises the same redirection guard without
            # enabling Developer Mode, elevating privileges or mocking the filesystem.
            subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(link),str(other)],check=True,capture_output=True)
            self.assertTrue(link.is_junction())
        self.addCleanup(lambda:link.rmdir() if hasattr(link,'is_junction') and link.is_junction() else link.unlink())
        with self.assertRaises(ValueError):TdxLake(link)
        from quantlab.data.tdx_lake import safe
        with self.assertRaises(ValueError):safe(self.root,link/'payload')
    def test_writer_lease_prevents_duplicate_collectors(self):
        with writer_lease(self.lake):
            with self.assertRaises(ValueError):
                with writer_lease(self.lake):pass
    def test_stop_and_budget_leave_pending_jobs(self):
        self.job();(self.lake.base/'STOP').write_text('stop')
        result=Runner(self.lake,self.pid).run(1,1,1)
        self.assertEqual(result['stop_reason'],'USER_STOP')
        self.assertEqual(self.lake.status()['jobs'][0]['state'],'PENDING')
    def test_read_only_access_never_imports_source_dependency(self):
        with patch('quantlab.agent.tdx_collection_cli.Source',side_effect=AssertionError('network')):
            self.assertTrue(self.lake.status()['configured']);self.assertEqual(self.lake.read('finance')['rows'],[])
    def test_all_other_family_rows_persist_original_content(self):
        packets={'finance':{'records':[{'updated_date':'2026-08-15','liu_tong_gu_ben_raw_float':1940568.5}]},
            'capital_changes':{'records':[{'date':'2025-06-30','category_name':'股本变化','c3_value':1234567}]},
            'topics':{'error_code':0,'result_sets':[{'rows':[{'ztmc':'fixture','rxsj':20260917}]}]},
            'limit_ladder':{'rows':[{'code':'000001','market':'sz','trading_date_value':'20260917','broken_count':2}]},
            'quotes':[{'last_price':10.,'open_amount_yuan':1000.}]}
        for f,packet in packets.items():
            self.lake.save_page(self.job(f),packet)
            self.assertEqual(len(self.lake.read(f)['rows']),1)

    def test_disk_reserve_stops_before_writing_data(self):
        from types import SimpleNamespace
        with patch('quantlab.data.tdx_lake.shutil.disk_usage',return_value=SimpleNamespace(free=1)):
            with self.assertRaisesRegex(ValueError,'DISK_RESERVE'):self.lake.save_page(self.job(),self.bar())
        self.assertEqual(self.lake.status()['families'],[])

    def test_saved_page_crash_resumes_without_network_and_schedules_next_page(self):
        job=self.job();m,rows=self.lake.save_page(job,self.bar(),finalize=False)
        self.lake.recover(self.pid)
        recovered=self.lake.next_jobs(self.pid)[0]
        runner=Runner(self.lake,self.pid)
        with patch('quantlab.agent.tdx_collection_cli.Source',side_effect=AssertionError('must reuse bytes')):
            actual,value,observed,error=runner.fetch(recovered)
        self.assertIsNone(error);self.assertEqual(value,self.bar())
        runner.follow(actual,m,rows)
        with self.lake.db(readonly=True) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM jobs WHERE offset=1').fetchone()[0],1)
    def test_native_runtime_can_read_database_without_network_or_new_grant(self):
        from quantlab.agent.chat_cli import headless_chat_runtime
        self.lake.save_page(self.job(),self.bar())
        workspace=self.root/'workspace';workspace.mkdir()
        with headless_chat_runtime(workspace,self.root,local_data_only=True) as runtime:
            names={t['name'] for t in runtime.api.schemas()}
            self.assertIn('get_tdx_data_status',names);self.assertIn('read_tdx_data',names)
            result=runtime.api.call('read_tdx_data',{'family':'bars_1m','symbol':'sz.000001','start':'','end':'','offset':0,'limit':1})
            self.assertTrue(result['ok'],result);self.assertEqual(result['data']['rows'][0]['original_record']['extra_original'],{'x':7})
            self.assertNotIn('collect_tdx_data',names)


    def test_runtime_request_interval_override_keeps_policy_identity(self):
        runner=Runner(self.lake,self.pid,request_interval_seconds=.25)
        policy_id=runner.policy_id
        self.assertEqual(runner.request_interval_seconds,.25)
        self.assertEqual(runner.policy_id,policy_id)
        with self.assertRaisesRegex(ValueError,'request_interval_seconds'):
            Runner(self.lake,self.pid,request_interval_seconds=.19)

    def test_collection_scope_blocks_excluded_retry_before_network(self):
        from quantlab.agent.tdx_collection_cli import SCOPE_FORMAT
        from quantlab.data.tdx_lake import write_json
        core={'format':SCOPE_FORMAT,'plan_id':self.pid,'excluded_families':['trades'],'reason':'fixture','history_complete':False}
        write_json(self.lake.base/'collection-scope.json',{**core,'scope_id':digest(core)})
        from quantlab.agent.tdx_collection_cli import recover_for_resume
        job=self.job('trades');self.lake.mark(job,'ERROR',error='ConnectionClosedError: closed')
        recover_for_resume(self.lake,self.pid,12)
        with patch('quantlab.agent.tdx_collection_cli.Source',side_effect=AssertionError('network')):
            result=Runner(self.lake,self.pid,workers=1,cooldown_seconds=0).run(1,1,1)
        self.assertEqual(result['network_attempts'],0);self.assertIn('trades',result['excluded_families'])
        with self.lake.db(readonly=True) as con:
            row=con.execute('SELECT state,error FROM jobs WHERE job_id=?',(job['job_id'],)).fetchone()
        self.assertEqual(row['state'],'SKIPPED_POLICY');self.assertIn('collection scope',row['error'])

    def test_transient_request_retries_exact_job_and_rotates_hosts(self):
        connected=[];requested=[]
        class FakeSource:
            def __init__(self,cache,host=None):connected.append(host);self.host=host
            def close(self):pass
            def request(self,job):
                requested.append((job['job_id'],self.host))
                if len(requested)<3:raise ConnectionError('7709 TCP stream closed during response wait')
                return {'records':[{'updated_date':'2026-08-15'}]}
        job=self.job('finance')
        with patch('quantlab.agent.tdx_collection_cli.Source',FakeSource):
            runner=Runner(self.lake,self.pid,workers=1,request_retries=3,retry_backoff=0)
            actual,value,_observed,error=runner.fetch(job)
        self.assertIsNone(error);self.assertEqual(actual['job_id'],job['job_id']);self.assertEqual(len(requested),3)
        self.assertEqual(connected[:3],['116.205.183.150:7709','116.205.171.132:7709','116.205.183.150:7709'])
        self.assertEqual(value['records'][0]['updated_date'],'2026-08-15')

    def test_transient_burst_cools_down_recovers_same_job_and_then_succeeds(self):
        self.job('finance');runner=Runner(self.lake,self.pid,workers=1,request_retries=0,transient_burst=1,recovery_cycles=1,cooldown_seconds=0,max_job_attempts=5)
        calls=[]
        def fake_fetch(job):
            calls.append(job['job_id'])
            if len(calls)==1:return job,None,'2026-09-18T00:00:00+00:00','ConnectionClosedError: closed'
            return job,{'records':[{'updated_date':'2026-08-15'}]},'2026-09-18T00:00:01+00:00',None
        runner.fetch=fake_fetch
        result=runner.run(5,10,1)
        self.assertEqual(result['stop_reason'],'QUEUE_DRAINED');self.assertEqual(result['recovery_cycles'],1);self.assertEqual(len(calls),2)
        with self.lake.db(readonly=True) as con:
            row=con.execute("SELECT state,attempts FROM jobs WHERE family='finance'").fetchone()
        self.assertEqual((row['state'],row['attempts']),('SAVED',2));self.assertFalse((self.lake.base/'AUTO_HALT.json').exists())

    def test_repeated_transient_bursts_halt_instead_of_infinite_loop(self):
        self.job('finance');runner=Runner(self.lake,self.pid,workers=1,request_retries=0,transient_burst=1,recovery_cycles=1,cooldown_seconds=0,max_job_attempts=5)
        runner.fetch=lambda job:(job,None,'2026-09-18T00:00:00+00:00','ConnectionClosedError: closed')
        result=runner.run(5,10,1)
        self.assertEqual(result['stop_reason'],'RECOVERY_EXHAUSTED');self.assertEqual(result['state'],'HALTED');self.assertEqual(result['recovery_cycles'],1)
        halt=json.loads((self.lake.base/'AUTO_HALT.json').read_text())
        self.assertEqual(halt['reason'],'RECOVERY_EXHAUSTED')

    def test_transient_only_recovery_does_not_requeue_protocol_corruption(self):
        job=self.job('trades');self.lake.next_jobs(self.pid);self.lake.mark(job,'ERROR',error='ProtocolError: invalid historical ticks payload')
        self.lake.recover(self.pid,retry_errors=True,max_attempts=12,error_markers=('ConnectionClosedError',))
        with self.lake.db(readonly=True) as con:state=con.execute('SELECT state FROM jobs WHERE job_id=?',(job['job_id'],)).fetchone()[0]
        self.assertEqual(state,'ERROR')

    def test_scheduler_market_floor_never_drops_bse_older_auction(self):
        days=['2025-07-21','2025-07-22','2025-07-23']
        policy={'lifecycle_bounds':{
            'sh.600000':{'listed':'1999-11-10','delisted':None},
            'bj.920010':{'listed':'2020-07-27','delisted':None}},
            'family_market_history_floors':{'auction':{'sh':'2025-07-22','sz':'2025-07-22'}}}
        self.assertIsNone(_latest_allowed_day(days,'auction','sh.600000','2025-07-22',policy,strictly_before=True))
        self.assertEqual(_latest_allowed_day(days,'auction','bj.920010','2025-07-22',policy,strictly_before=True),'2025-07-21')

    def test_scheduler_lifecycle_clamps_delisted_trade_history(self):
        days=['2025-07-21','2025-07-22','2025-07-23','2026-09-17']
        policy={'lifecycle_bounds':{'sh.600000':{'listed':'2025-07-21','delisted':'2025-07-23'}},'family_market_history_floors':{}}
        self.assertEqual(_latest_allowed_day(days,'trades','sh.600000','2026-09-17',policy),'2025-07-23')
        self.assertIsNone(_latest_allowed_day(days,'trades','sh.600000','2025-07-21',policy,strictly_before=True))

    def test_apply_scheduler_policy_marks_skip_and_retargets_without_deletion(self):
        body={'trading_days':['2025-07-21','2025-07-22','2025-07-23','2026-09-17'],'max_offset':1000000,'personal_research_only':True}
        pid=self.lake.add_plan(body)
        old=self.lake.enqueue(pid,'trades','sh.600000','2026-09-17',0,1000)
        policy={'policy_id':'abc','lifecycle_bounds':{'sh.600000':{'listed':'2025-07-21','delisted':'2025-07-23'}},'family_market_history_floors':{}}
        result=apply_scheduler_policy_to_pending(self.lake,pid,policy)
        self.assertEqual(result,{'pending_pruned':1,'pending_retargeted':1})
        with self.lake.db(readonly=True) as con:
            rows=[dict(r) for r in con.execute('SELECT job_id,day,state,error FROM jobs WHERE plan_id=? ORDER BY day',(pid,))]
        self.assertEqual(len(rows),2);self.assertEqual(rows[0]['day'],'2025-07-23');self.assertEqual(rows[0]['state'],'PENDING')
        self.assertEqual(rows[1]['job_id'],old);self.assertEqual(rows[1]['state'],'SKIPPED_POLICY');self.assertIn('policy=abc',rows[1]['error'])
        # Reapplying is idempotent and keeps the auditable skipped row.
        again=apply_scheduler_policy_to_pending(self.lake,pid,policy)
        self.assertEqual(again,{'pending_pruned':1,'pending_retargeted':1})
        with self.lake.db(readonly=True) as con:self.assertEqual(con.execute('SELECT count(*) FROM jobs WHERE plan_id=?',(pid,)).fetchone()[0],2)

    def test_scheduler_policy_checksum_and_plan_binding(self):
        core={'format':POLICY_FORMAT,'plan_id':self.pid,'lifecycle_bounds':{},'family_market_history_floors':{},'request_interval_seconds':0.2}
        from quantlab.data.tdx_lake import write_json
        write_json(self.lake.base/'scheduler-policy.json',{**core,'policy_id':digest(core)})
        self.assertEqual(load_scheduler_policy(self.lake,self.pid)['request_interval_seconds'],0.2)
        with self.assertRaisesRegex(ValueError,'identity'):
            load_scheduler_policy(self.lake,'0'*64)

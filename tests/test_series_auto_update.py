from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch
import unittest
import test_baostock_series as fixtures
from quantlab.agent.series_auto_update import candidate_day,maybe_update_series

NOW=datetime.fromisoformat('2025-01-10T19:00:00+08:00')

class SeriesAutoUpdateTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.BaostockSeriesTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.sid,self.old=self.fx.series();self.root=self.fx.service.folder(self.sid)
        self.grant={'end':'2025-01-10','auto_download':{'enabled':True,'max_downloads':3}}
        self.state={}
    def test_candidate_day_and_disabled(self):
        self.assertEqual(str(candidate_day(NOW,'2025-01-10')),'2025-01-10')
        off={'end':'2025-01-10','auto_download':{'enabled':False,'max_downloads':3}}
        self.assertEqual(maybe_update_series(self.fx.root,self.root,off,{},NOW)['status'],'disabled')
    def fake_download(self, revised=False, fail=False, missing=False):
        from quantlab.data.baostock_ingest import collect,import_root
        from test_baostock_data import SDK
        class Revised(SDK):
            def query_history_k_data_plus(inner,**kw):
                r=super(Revised,inner).query_history_k_data_plus(**kw)
                if revised:
                    for row in r.rows:
                        if row['date']=='2025-01-02':
                            row['close']=str(float(row['close'])*1.01)
                if missing:
                    r.rows=[row for row in r.rows if row['date']!='2025-01-10']
                return r
        def run(output,spec,*,timeout,identifier):
            if fail:
                return {'import_id':identifier,'status':'failed','dataset_ready':False,'error':'network fixture'}
            return collect(spec,import_root(output)/identifier,sdk=Revised(),interval=0)
        return run

    def test_successful_download_publishes(self):
        saves=[]
        with patch('quantlab.agent.series_auto_update.run_import',side_effect=self.fake_download()):
            result=maybe_update_series(self.fx.root,self.root,self.grant,self.state,NOW,
                persist=lambda:saves.append(self.state['data_updates'][-1].copy()))
        self.assertEqual(result['status'],'published')
        self.assertEqual(result['network_requests'],1)
        self.assertEqual(self.fx.service.get(self.sid)['generation'],2)
        self.assertEqual(saves[0]['status'],'downloading')
        self.assertIn('import_id',saves[0])

    def test_revision_stops_for_review(self):
        with patch('quantlab.agent.series_auto_update.run_import',side_effect=self.fake_download(revised=True)):
            result=maybe_update_series(self.fx.root,self.root,self.grant,self.state,NOW)
        self.assertEqual(result['status'],'revision_review')
        self.assertEqual(self.fx.service.get(self.sid)['generation'],1)
    def test_failure_enters_cooldown(self):
        with patch('quantlab.agent.series_auto_update.run_import',side_effect=self.fake_download(fail=True)):
            first=maybe_update_series(self.fx.root,self.root,self.grant,self.state,NOW)
            second=maybe_update_series(self.fx.root,self.root,self.grant,self.state,NOW+timedelta(hours=1))
        self.assertEqual(first['status'],'failed')
        self.assertEqual(second['status'],'cooldown')
        self.assertEqual(len(self.state['data_updates']),1)

    def test_completed_reserved_download_is_recovered_without_network(self):
        from quantlab.data.baostock_ingest import collect,import_root
        from test_baostock_data import SDK
        from uuid import uuid4
        identifier=str(uuid4())
        spec={'symbols':__import__('test_baostock_data').plan()['symbols'],'start':'2025-01-01','end':'2025-01-10',
            'datasets':['calendar','daily_qfq','daily_raw'],'snapshot_dates':[],'quarters':[]}
        result=collect(spec,import_root(self.fx.root)/identifier,sdk=SDK(),interval=0)
        self.assertTrue(result['dataset_ready'])
        self.state['data_updates']=[{'target':'2025-01-10','spec_digest':'x','checked_at':NOW.isoformat(),
            'status':'downloading','import_id':identifier}]
        with patch('quantlab.agent.series_auto_update.run_import',side_effect=AssertionError('no network')):
            recovered=maybe_update_series(self.fx.root,self.root,self.grant,self.state,NOW+timedelta(minutes=1))
        self.assertEqual(recovered['status'],'published')
        self.assertEqual(recovered['network_requests'],0)
        self.assertEqual(self.fx.service.get(self.sid)['generation'],2)
    def test_reserved_without_manifest_waits_before_retry(self):
        from uuid import uuid4
        identifier=str(uuid4())
        self.state['data_updates']=[{'target':'2025-01-10','spec_digest':'x',
            'checked_at':NOW.isoformat(),'status':'downloading','import_id':identifier}]
        with patch('quantlab.agent.series_auto_update.run_import',side_effect=AssertionError('no retry')):
            value=maybe_update_series(self.fx.root,self.root,self.grant,self.state,NOW+timedelta(minutes=5))
        self.assertEqual(value['status'],'downloading')
        self.assertEqual(value['network_requests'],0)
    def test_incomplete_latest_session_never_publishes(self):
        with patch('quantlab.agent.series_auto_update.run_import',side_effect=self.fake_download(missing=True)):
            value=maybe_update_series(self.fx.root,self.root,self.grant,self.state,NOW)
        self.assertEqual(value['status'],'failed')
        self.assertIn('发布审计',value['error'])
        self.assertEqual(self.fx.service.get(self.sid)['generation'],1)

    def test_budget_limit_still_recovers_reserved_download(self):
        from quantlab.data.baostock_ingest import collect,import_root
        from test_baostock_data import SDK
        from uuid import uuid4
        identifier=str(uuid4())
        spec={'symbols':__import__('test_baostock_data').plan()['symbols'],'start':'2025-01-01','end':'2025-01-10',
            'datasets':['calendar','daily_qfq','daily_raw'],'snapshot_dates':[],'quarters':[]}
        collect(spec,import_root(self.fx.root)/identifier,sdk=SDK(),interval=0)
        self.grant['auto_download']['max_downloads']=1
        self.state['data_updates']=[{'target':'2025-01-10','spec_digest':'x','checked_at':NOW.isoformat(),
            'status':'downloading','import_id':identifier}]
        with patch('quantlab.agent.series_auto_update.run_import',side_effect=AssertionError('no network')):
            value=maybe_update_series(self.fx.root,self.root,self.grant,self.state,NOW+timedelta(minutes=1))
        self.assertEqual(value['status'],'published')
        self.assertEqual(value['network_requests'],0)

    def test_published_before_control_receipt_is_recovered(self):
        identifier=self.fx.batch('2025-01-10')
        plan=self.fx.service.preview(self.sid,identifier)
        published=self.fx.service.accept(plan,__import__('quantlab.storage.codec',fromlist=['digest']).digest(plan),confirmed=True)
        self.state['data_updates']=[{'target':'2025-01-10','spec_digest':'x','checked_at':NOW.isoformat(),
            'status':'downloading','import_id':identifier}]
        with patch('quantlab.agent.series_auto_update.run_import',side_effect=AssertionError('no network')):
            value=maybe_update_series(self.fx.root,self.root,self.grant,self.state,NOW+timedelta(minutes=1))
        self.assertEqual(value['status'],'published')
        self.assertTrue(value['recovered'])
        self.assertEqual(value['publication_id'],published['publication']['publication_id'])
        self.assertEqual(self.state['data_updates'][0]['status'],'published')

    def test_external_publication_change_requires_new_authorization(self):
        initial=self.fx.service.get(self.sid)['history'][-1]['publication_id']
        self.grant['series_publication_id']=initial;self.state['accepted_publication_id']=initial
        identifier=self.fx.batch('2025-01-08')
        plan=self.fx.service.preview(self.sid,identifier)
        self.fx.service.accept(plan,__import__('quantlab.storage.codec',fromlist=['digest']).digest(plan),confirmed=True)
        with patch('quantlab.agent.series_auto_update.run_import',side_effect=AssertionError('must stop before network')):
            with self.assertRaisesRegex(ValueError,'其他操作改变'):
                maybe_update_series(self.fx.root,self.root,self.grant,self.state,NOW)
        self.assertEqual(self.state.get('data_updates',[]),[])

    def test_scheduler_download_publish_research_and_sync_end_to_end(self):
        from quantlab.workbench.jobs import prepare,execute,JobQueue
        from quantlab.agent.watchlist import WatchService
        from quantlab.agent.tracking_authorization import preview_control,authorize_control
        from quantlab.agent.tracking_scheduler import TrackingScheduler
        from quantlab.storage.codec import digest
        data=self.root
        spec={'question':'auto e2e','symbols':__import__('test_baostock_data').plan()['symbols'],
            'start':'2025-01-01','end':'2025-01-03','factor':'BASE.MOMENTUM',
            'parameters':{'lookback':1},'horizons':[1],'quantiles':3,'replay':True}
        baseline=execute(prepare(spec),data,self.fx.root)
        watches=WatchService(self.fx.root,data)
        watch=watches.create('auto series',baseline.run_id,windows=[3],min_dates=1)['watch_id']
        start=datetime.fromisoformat('2025-01-06T20:00:00+08:00')
        plan=preview_control(self.fx.root,data,watch,self.old,'2025-01-10',
            (start+timedelta(days=7)).isoformat(),2,60,True,2,now=start)
        authorize_control(self.fx.root,data,plan,digest(plan),confirmed=True,now=start)
        queue=JobQueue(self.fx.root,data);engine=TrackingScheduler(self.fx.root,data,lambda:queue)
        try:
            with patch('quantlab.agent.series_auto_update.run_import',side_effect=self.fake_download()):
                first=engine.tick(now=NOW)
            queue.close();second=TrackingScheduler(self.fx.root,data,lambda:queue).tick(now=NOW+timedelta(hours=1))
        finally:
            queue.close()
        self.assertEqual(first['network_requests'],1);self.assertEqual(second['network_requests'],0)
        self.assertEqual(len(queue.list()),1);self.assertEqual(queue.list()[0]['status'],'completed')
        self.assertEqual(watches.get(watch)['snapshot_count'],2);self.assertEqual(self.fx.service.get(self.sid)['generation'],2)
        state=engine.store.get(watch);self.assertFalse(state['enabled']);self.assertEqual(state['status'],'end_cap_reached')

    def make_scheduler(self,max_downloads=2):
        from quantlab.workbench.jobs import prepare,execute,JobQueue
        from quantlab.agent.watchlist import WatchService
        from quantlab.agent.tracking_authorization import preview_control,authorize_control
        from quantlab.agent.tracking_scheduler import TrackingScheduler
        from quantlab.storage.codec import digest
        data=self.root;spec={'question':'auto scheduler','symbols':__import__('test_baostock_data').plan()['symbols'],
            'start':'2025-01-01','end':'2025-01-03','factor':'BASE.MOMENTUM','parameters':{'lookback':1},
            'horizons':[1],'quantiles':3,'replay':True}
        baseline=execute(prepare(spec),data,self.fx.root);watches=WatchService(self.fx.root,data)
        watch=watches.create('auto scheduler',baseline.run_id,windows=[3],min_dates=1)['watch_id']
        start=datetime.fromisoformat('2025-01-06T20:00:00+08:00')
        plan=preview_control(self.fx.root,data,watch,self.old,'2025-01-10',(start+timedelta(days=7)).isoformat(),
            3,60,True,max_downloads,now=start)
        authorize_control(self.fx.root,data,plan,digest(plan),confirmed=True,now=start)
        queue=JobQueue(self.fx.root,data);engine=TrackingScheduler(self.fx.root,data,lambda:queue)
        return watches,watch,queue,engine

    def test_scheduler_failure_cooldown_then_successful_retry(self):
        watches,watch,queue,engine=self.make_scheduler(max_downloads=2)
        calls={'n':0};success=self.fake_download()
        def flaky(output,spec,*,timeout,identifier):
            calls['n']+=1
            if calls['n']==1:return {'import_id':identifier,'status':'failed','dataset_ready':False,'error':'network fixture'}
            return success(output,spec,timeout=timeout,identifier=identifier)
        try:
            with patch('quantlab.agent.series_auto_update.run_import',side_effect=flaky):
                first=engine.tick(now=NOW)
                second=engine.tick(now=NOW+timedelta(hours=1))
                third=engine.tick(now=NOW+timedelta(hours=7))
            queue.close();fourth=engine.tick(now=NOW+timedelta(hours=8))
        finally:queue.close()
        state=engine.store.get(watch)
        self.assertEqual((first['network_requests'],second['network_requests'],third['network_requests'],fourth['network_requests']),(1,0,1,0))
        self.assertEqual(calls['n'],2);self.assertEqual(len(state['data_updates']),2)
        self.assertEqual([r['status'] for r in state['data_updates']],['failed','published'])
        self.assertEqual(len(queue.list()),1);self.assertEqual(watches.get(watch)['snapshot_count'],2)

    def test_scheduler_external_publication_change_stops_before_download(self):
        watches,watch,queue,engine=self.make_scheduler(max_downloads=2)
        identifier=self.fx.batch('2025-01-08')
        plan=self.fx.service.preview(self.sid,identifier)
        self.fx.service.accept(plan,__import__('quantlab.storage.codec',fromlist=['digest']).digest(plan),confirmed=True)
        try:
            with patch('quantlab.agent.series_auto_update.run_import',side_effect=AssertionError('no network')):
                result=engine.tick(now=NOW)
        finally:queue.close()
        state=engine.store.get(watch)
        self.assertEqual(result['network_requests'],0)
        self.assertFalse(state['enabled']);self.assertEqual(state['status'],'reauthorization_required')
        self.assertEqual(len(queue.list()),0);self.assertEqual(watches.get(watch)['snapshot_count'],1)

    def test_reserved_import_id_is_idempotent_after_receipt_exists(self):
        from uuid import uuid4
        from quantlab.data.baostock_catalog import import_plan
        from quantlab.data.baostock_ingest import collect,import_root,run_import,write_json
        from test_baostock_data import SDK,plan as data_plan
        identifier=str(uuid4());spec={**data_plan(),'datasets':['calendar','daily_raw','daily_qfq'],'quarters':[]}
        normalized,_=import_plan(spec);root=import_root(self.fx.root)
        write_json(root/(identifier+'.request.json'),normalized)
        first=collect(normalized,root/identifier,sdk=SDK(),interval=0)
        with patch('quantlab.data.baostock_ingest.subprocess.Popen',side_effect=AssertionError('no second worker')):
            second=run_import(self.fx.root,normalized,identifier=identifier)
        self.assertEqual(first['import_id'],second['import_id'])
        self.assertEqual(first['status'],second['status']);self.assertTrue(second['dataset_ready'])

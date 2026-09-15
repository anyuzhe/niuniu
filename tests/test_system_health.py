import json
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4

from quantlab.agent.system_health import SystemHealthService
from quantlab.data.daily_market_archive import DailyMarketArchive,EXPECTED_FIELDS
from quantlab.experiments.campaign_state import write_checked


class Response:
    error_code='0';error_msg='success'
    def __init__(self,rows,fields=EXPECTED_FIELDS):self.rows=rows;self.fields=list(fields);self.index=-1
    def next(self):self.index+=1;return self.index<len(self.rows)
    def get_row_data(self):return [self.rows[self.index][key] for key in self.fields]


class SDK:
    __version__='0.9.3'
    def __init__(self,rows):self.rows=rows
    def login(self):return Response([{'ok':'1'}],['ok'])
    def logout(self):pass
    def query_daily_history_k_AStock(self,date=''):return Response(self.rows)


def market_row(day,close='10.5'):
    row={key:'1' for key in EXPECTED_FIELDS}
    row.update(date=day,code='sh.600000',open='10',high='11',low='9.5',close=close,preclose='10',volume='1000',
        amount='10000',adjustflag='3',turn='2',tradestatus='1',pctChg='5',peTTM='12',pbMRQ='1.2',psTTM='2',pcfNcfTTM='3',isST='0')
    return row


class SystemHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.output=self.root/'artifacts';self.data=self.root/'data';self.output.mkdir();self.data.mkdir()
        self.now=datetime(2026,9,15,1,0,tzinfo=timezone.utc)
    def service(self):return SystemHealthService(self.output,self.data,now_fn=lambda:self.now)
    def files(self):return sorted(str(p.relative_to(self.output)) for p in self.output.rglob('*'))

    def test_empty_workspace_is_side_effect_free_and_has_no_health_score(self):
        before=self.files();value=self.service().build();after=self.files()
        self.assertEqual(before,after)
        self.assertIsNone(value['summary']['health_score']);self.assertFalse(value['summary']['automatic_actions'])
        self.assertIn(value['summary']['runtime_status'],('OK','UNKNOWN','NOT_CONFIGURED'))
        self.assertEqual(value['components']['jobs']['status'],'NOT_CONFIGURED')
        self.assertEqual(value['components']['tracking_daemon']['status'],'NOT_CONFIGURED')
        self.assertIn('does not mean a strategy is correct',value['interpretation'])


    def test_artifact_growth_is_read_only_and_fast_top_level_proxy(self):
        (self.output/'sample.bin').write_bytes(b'abc');(self.output/str(uuid4())).mkdir();(self.output/'_jobs').mkdir()
        before=self.files();health=self.service()._artifact_growth(self.now);after=self.files()
        self.assertEqual(before,after);self.assertEqual(health['status'],'OK')
        self.assertEqual(health['evidence']['top_level_entries'],3);self.assertEqual(health['evidence']['run_directories'],1)
        self.assertEqual(health['evidence']['system_directories'],1);self.assertEqual(health['evidence']['top_level_files'],1)

    def test_mcp_reports_adapter_capability_not_fake_process_liveness(self):
        health=self.service().build()['components']['mcp']
        if health['status']=='NOT_CONFIGURED':self.skipTest('optional mcp dependency not installed')
        self.assertEqual(health['status'],'OK');self.assertIsNone(health['evidence']['server_liveness'])
        self.assertIn('stdio',health['evidence']['transports']);self.assertGreater(health['evidence']['tool_count'],0)

    def test_series_cutoff_is_visible_without_pit_certification(self):
        from unittest.mock import patch
        fake={'series':[{'series_id':str(uuid4()),'name':'daily','generation':2,'current':{'end':'2026-09-14',
            'symbols':['sh.600000','sz.000001'],'modes':['raw','qfq']}}],'errors':[]}
        with patch('quantlab.data.baostock_series.SeriesService.list',return_value=fake):health=self.service().build()['components']['market_data_series']
        self.assertEqual(health['status'],'OK');self.assertEqual(health['evidence']['latest_accepted_end'],'2026-09-14')
        self.assertTrue(any('not strict-PIT' in note for note in health['limitations']))

    def test_official_market_rules_v2_inventory_is_visible_and_tampering_warns(self):
        from quantlab.data.official_rule_archive import archive_official_rules
        url='https://www.sse.com.cn/test/rule.html';published='2024-12-31T18:00:00+08:00'
        rules=[{'symbol':'sh.600000','effective_at':'2025-01-02T09:30:00+08:00','available_at':'2025-01-01T09:00:00+08:00',
            'expires_at':'2025-01-03T00:00:00+08:00','suspended':True,'st':False,'limit_up':None,'limit_down':None,
            'commission_bps':0,'minimum_commission':0,'sell_tax_bps':0,'transfer_bps':0,'source':url}]
        class OfficialResponse:
            def geturl(self):return url
            def read(self,_n):return b'official rule health fixture'
        archived=archive_official_rules(self.data,rules,[url],{url:published},confirm_publication_time=True,
            opener=lambda *_a,**_k:OfficialResponse(),now_fn=lambda:self.now)
        health=self.service().build()['components']['pit_playbook'];audit=health['evidence']['official_rule_archive']
        self.assertTrue(health['evidence']['official_rule_archive_verified_present'])
        self.assertTrue(health['evidence']['official_rule_receipt_present']);self.assertEqual(audit['verified_receipts'],1)
        self.assertEqual(audit['invalid_receipts'],0);self.assertIn('global integrity inventory',health['limitations'][0])
        path=Path(archived['path']);value=json.loads(path.read_text());value['rules'][0]['suspended']=False;path.write_text(json.dumps(value))
        broken=self.service().build()['components']['pit_playbook'];audit=broken['evidence']['official_rule_archive']
        self.assertFalse(broken['evidence']['official_rule_archive_verified_present'])
        self.assertFalse(broken['evidence']['official_rule_receipt_present']);self.assertEqual(audit['invalid_receipts'],1)
        self.assertIn('official_rule_receipts_invalid',broken['warnings'])

    def test_unread_notification_is_attention_not_data_correctness(self):
        watch=str(uuid4());folder=self.output/'_tracking_control'/watch;folder.mkdir(parents=True)
        write_checked(folder/'state.json',{'watch_id':watch,'notices':{'n1':{'unread':True}}})
        health=self.service().build()['components']['notifications']
        self.assertEqual(health['status'],'WARN');self.assertEqual(health['evidence']['unread_in_app'],1)
        self.assertIn('unread_in_app_notifications',health['warnings'])

    def test_orphan_running_job_is_blocked(self):
        root=self.output/'_jobs';root.mkdir();job=str(uuid4())
        (root/'worker.lock').write_bytes(b'')
        (root/(job+'.json')).write_text(json.dumps({'job_id':job,'status':'running','created_at':'2026-09-15T00:00:00+00:00',
            'started_at':'2026-09-15T00:05:00+00:00','finished_at':None}))
        value=self.service().build();health=value['components']['jobs']
        self.assertEqual(health['status'],'BLOCKED');self.assertIn('orphan_running_jobs_without_worker_lock',health['blockers'])
        self.assertEqual(health['evidence']['counts']['running'],1)

    def test_tracking_error_and_recent_error_log_are_separate(self):
        root=self.output/'_tracking_daemon';root.mkdir();(root/'daemon.lock').write_bytes(b'')
        write_checked(root/'heartbeat.json',{'format':'tracking-daemon-v1','pid':123,'status':'error','output':str(self.output),
            'data_root':str(self.data),'poll_seconds':60,'updated_at':'2026-09-15T00:59:00+00:00','result':None,'error':'fixture error'})
        (root/'launchd.err.log').write_text('fixture error line')
        value=self.service().build()
        self.assertEqual(value['components']['tracking_daemon']['status'],'BLOCKED')
        self.assertIn('tracking_daemon_last_tick_error',value['components']['tracking_daemon']['blockers'])
        self.assertEqual(value['components']['logs']['status'],'WARN')
        self.assertNotIn('fixture error line',json.dumps(value['components']['logs']))

    def test_daily_market_revision_review_is_blocked(self):
        archive=DailyMarketArchive(self.output,now_fn=lambda:self.now)
        archive.capture('2026-09-14',sdk=SDK([market_row('2026-09-14','10.5')]))
        archive.capture('2026-09-14',sdk=SDK([market_row('2026-09-14','10.6')]))
        health=self.service().build()['components']['daily_market']
        self.assertEqual(health['status'],'BLOCKED')
        self.assertIn('daily_market_revision_review_pending',health['blockers'])

    def test_orchestrator_blocker_is_visible(self):
        root=self.output/'_daily_orchestrator';root.mkdir()
        state={'format':'daily-playbook-orchestrator-v1','trading_day':'2026-09-15','as_of_session':'2026-09-14',
            'status':'BLOCKED_PREP_DATA','updated_at':'2026-09-15T00:58:00+00:00','daily_market':{'status':'READY'},
            'prep':{'status':'PENDING'},'auction':{'status':'PENDING'},'r1':{'status':'PENDING'}}
        write_checked(root/'2026-09-15.json',state)
        health=self.service().build()['components']['daily_orchestrator']
        self.assertEqual(health['status'],'BLOCKED');self.assertIn('orchestrator_blocked_prep_data',health['blockers'])

    def test_active_devtask_missing_worktree_is_blocked(self):
        task=str(uuid4());folder=self.output/'_devstudio'/'tasks'/task;folder.mkdir(parents=True)
        state={'format':'niuniu-devtask-v1','task_id':task,'spec':{},'repo_root':'/repo','base_branch':'main','base_sha':'a'*40,
            'worktree_path':str(self.root/'missing-worktree'),'state':'RUNNING','created_at':'2026-09-15T00:00:00+00:00',
            'updated_at':'2026-09-15T00:30:00+00:00','subtasks':[],'test_runs':[],'main_acceptance':None,'merge':None,'events':[]}
        write_checked(folder/'state.json',state)
        health=self.service().build()['components']['dev_studio']
        self.assertEqual(health['status'],'BLOCKED');self.assertIn('active_devtask_worktree_missing',health['blockers'])


if __name__=='__main__':unittest.main()

class SystemHealthSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.output=self.root/'artifacts';self.data=self.root/'data';self.output.mkdir();self.data.mkdir()

    def test_ai_tool_is_read_only_and_cli_is_side_effect_free(self):
        from io import StringIO
        from contextlib import redirect_stdout
        from quantlab.agent.market_data_tools import MarketDataResearchAPI
        from quantlab.agent.system_health_cli import main
        api=MarketDataResearchAPI(self.output,self.data);names={tool['name'] for tool in api.schemas()}
        self.assertIn('get_system_health',names)
        self.assertFalse({'restart_service','retry_job','download_data','merge_dev_task'} & names)
        before=sorted(str(p.relative_to(self.output)) for p in self.output.rglob('*'))
        reply=api.call('get_system_health',{});self.assertTrue(reply['ok']);self.assertIsNone(reply['data']['summary']['health_score'])
        stream=StringIO()
        with redirect_stdout(stream):code=main(['--output',str(self.output),'--data-root',str(self.data)])
        self.assertEqual(code,0);self.assertIn('niuniu-system-health-v1',stream.getvalue())
        after=sorted(str(p.relative_to(self.output)) for p in self.output.rglob('*'))
        self.assertEqual(before,after)


class SystemHealthSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.output=self.root/'artifacts';self.data=self.root/'data';self.output.mkdir();self.data.mkdir()
        self.now=datetime(2026,9,15,1,0,tzinfo=timezone.utc)
    def service(self):return SystemHealthService(self.output,self.data,now_fn=lambda:self.now)

    def test_operational_liveness_does_not_override_research_blocker(self):
        archive=DailyMarketArchive(self.output,now_fn=lambda:self.now)
        archive.capture('2026-09-14',sdk=SDK([market_row('2026-09-14','10.5')]))
        archive.capture('2026-09-14',sdk=SDK([market_row('2026-09-14','10.6')]))
        from unittest.mock import patch
        healthy={'format':'tracking-daemon-v1','pid':123,'status':'ok','output':str(self.output),'data_root':str(self.data),
            'poll_seconds':60,'updated_at':'2026-09-15T00:59:30+00:00','result':{},'error':None,'active':True,'stale':False}
        with patch('quantlab.agent.tracking_daemon.daemon_status',return_value=healthy):value=self.service().build()
        self.assertEqual(value['components']['tracking_daemon']['status'],'OK')
        self.assertEqual(value['components']['daily_market']['status'],'BLOCKED')
        self.assertEqual(value['summary']['runtime_status'],'OK')
        self.assertEqual(value['summary']['research_readiness_status'],'BLOCKED')

    def test_historical_orchestrator_block_is_warning_not_current_blocker(self):
        root=self.output/'_daily_orchestrator';root.mkdir()
        state={'format':'daily-playbook-orchestrator-v1','trading_day':'2026-09-14','as_of_session':'2026-09-13',
            'status':'BLOCKED_PREP_DATA','updated_at':'2026-09-14T02:00:00+00:00','daily_market':{'status':'READY'},
            'prep':{'status':'PENDING'},'auction':{'status':'PENDING'},'r1':{'status':'PENDING'}}
        write_checked(root/'2026-09-14.json',state)
        health=self.service().build()['components']['daily_orchestrator']
        self.assertEqual(health['status'],'WARN');self.assertFalse(health['blockers'])
        self.assertIn('historical_orchestrator_blocked_prep_data',health['warnings'])

import json,shutil,tempfile,time,unittest
from dataclasses import replace
from pathlib import Path
from datetime import datetime,timezone
from types import SimpleNamespace
from uuid import uuid4

import polars as pl
import test_core
from test_workbench_jobs import spec as job_spec

from quantlab.agent.campaign_plan import prepare_campaign
from quantlab.agent.planning import ResearchBudget
from quantlab.agent.proposals import ProposalService
from quantlab.data.provider import local_data_provider
from quantlab.data.universe import build_universe
from quantlab.storage.approval_inputs import ApprovalInputFreezeStore
from quantlab.workbench.jobs import JobQueue,prepare


class ApprovalInputFreezeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_core.CoreTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.root=self.fixture.root;self.output=self.root/'approval-runs';self.output.mkdir();self.queue=None
        self.addCleanup(lambda:self.queue.close() if self.queue else None)
        self.spec=job_spec(symbols=list(self.fixture.symbols),replay=True)

    def get_queue(self):
        if self.queue is None:self.queue=JobQueue(self.output,self.root)
        return self.queue

    def settled(self,job_id):
        deadline=time.time()+20
        while time.time()<deadline:
            row=next(v for v in self.queue.list() if v['job_id']==job_id)
            if row['status'] not in ('queued','running'):return row
            time.sleep(.02)
        self.fail('job did not settle')

    def test_approved_job_uses_frozen_bytes_after_source_changes(self):
        service=ProposalService(self.output,self.root,budget=replace(ResearchBudget(),max_active_jobs=1))
        proposal=service.propose(str(uuid4()),self.spec)
        full=SimpleNamespace(root=self.output,data_root=self.root,list=lambda:[{'job_id':str(uuid4()),'status':'running'}])
        with self.assertRaises(Exception):service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],lambda:full)
        approved=service.store.get(proposal['proposal_id']);self.assertEqual(approved['status'],'approved')
        freeze=ApprovalInputFreezeStore(self.output,self.root).path(proposal['proposal_id']);self.assertTrue((freeze/'manifest.json').is_file())
        path=self.root/'lake/silver/qfq_kline_daily'/f"{self.fixture.symbols[0].replace('.', '_')}.parquet"
        frame=pl.read_parquet(path);frame.with_columns((pl.col('close')*1.25).alias('close')).write_parquet(path)
        shutil.move(str(path.parent),str(self.root/'qfq-source-offline'))
        queried=service.get(proposal['proposal_id']);self.assertEqual(queried['approval_freeze']['freeze_id'],proposal['proposal_id'])
        result=service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],self.get_queue)
        final=self.settled(result['job']['job_id']);self.assertEqual(final['status'],'completed',final)
        record=json.loads((self.output/final['run_id']/'experiment.json').read_text())
        self.assertEqual(record['manifest']['data_snapshot']['source'],'mqc_parquet')
        self.assertTrue(record['manifest']['data_snapshot']['files'][0]['approval_time_frozen'])
        self.assertEqual(result['approval_freeze']['freeze_id'],proposal['proposal_id'])

    def test_freeze_tamper_blocks_retry(self):
        service=ProposalService(self.output,self.root,budget=replace(ResearchBudget(),max_active_jobs=1));proposal=service.propose(str(uuid4()),self.spec)
        full=SimpleNamespace(root=self.output,data_root=self.root,list=lambda:[{'job_id':str(uuid4()),'status':'running'}])
        with self.assertRaises(Exception):service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],lambda:full)
        folder=ApprovalInputFreezeStore(self.output,self.root).path(proposal['proposal_id']);manifest=json.loads((folder/'manifest.json').read_text())['manifest']
        target=folder/manifest['data_entries'][0]['file'];target.write_bytes(target.read_bytes()+b'x')
        with self.assertRaisesRegex(ValueError,'approval freeze'):service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],self.get_queue)
        self.assertIsNone(self.queue)

    def test_holdout_children_read_bounded_ranges_from_freeze(self):
        spec={**self.spec,'mode':'holdout','split':{'train_end':'2025-01-04','valid_end':'2025-01-07'}}
        service=ProposalService(self.output,self.root);proposal=service.propose(str(uuid4()),spec)
        result=service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],self.get_queue);final=self.settled(result['job']['job_id'])
        self.assertEqual(final['status'],'completed',final)
        record=json.loads((self.output/final['run_id']/'experiment.json').read_text());self.assertEqual(len(record['periods']),3)
        self.assertTrue(all((self.output/p['run_id']/'experiment.json').is_file() for p in record['periods']))

    def test_campaign_nodes_share_one_approval_bundle(self):
        base={**self.spec,'permutation':{'resamples':20,'block_days':1}}
        plan={'mode':'campaign','question':'freeze campaign','alpha':.05,'failure_policy':'continue_independent','nodes':[
            {'node_id':'first','depends_on':[],'spec':base},
            {'node_id':'second','depends_on':['first'],'spec':{**base,'parameters':{'lookback':3}}}]}
        prepare_campaign(plan);service=ProposalService(self.output,self.root);proposal=service.propose(str(uuid4()),plan)
        result=service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],self.get_queue);final=self.settled(result['job']['job_id'])
        self.assertEqual(final['status'],'completed',final)
        folder=ApprovalInputFreezeStore(self.output,self.root).path(proposal['proposal_id']);manifest=json.loads((folder/'manifest.json').read_text())['manifest']
        self.assertGreaterEqual(len(manifest['data_entries']),1);self.assertEqual(len(manifest['universes']),1)
        campaign=json.loads((self.output/final['run_id']/'experiment.json').read_text());self.assertEqual(campaign['summary']['counts']['completed'],2)

    def test_execution_freezes_qfq_signal_and_raw_account_prices(self):
        spec={**self.spec,'mode':'execution','execution':{'top_n':1,'price_mode':'account'}}
        service=ProposalService(self.output,self.root);proposal=service.propose(str(uuid4()),spec)
        result=service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],self.get_queue);final=self.settled(result['job']['job_id'])
        self.assertEqual(final['status'],'completed',final)
        folder=ApprovalInputFreezeStore(self.output,self.root).path(proposal['proposal_id']);manifest=json.loads((folder/'manifest.json').read_text())['manifest']
        self.assertEqual({row['adjustment'] for row in manifest['data_entries']},{'qfq','raw'})
        record=json.loads((self.output/final['run_id']/'experiment.json').read_text())
        self.assertEqual(record['manifest']['signal_data_snapshot']['source'],'mqc_parquet')
        self.assertEqual(record['manifest']['data_snapshot']['source'],'mqc_parquet')
        self.assertTrue(record['manifest']['data_snapshot']['files'][0]['approval_time_frozen'])

    def test_pit_universe_mask_is_frozen_and_used(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        folder=self.root/'research';folder.mkdir(exist_ok=True);tz=ZoneInfo('Asia/Shanghai')
        rows=[{'symbol':symbol,'effective_at':datetime(2024,12,31,15,tzinfo=tz),
            'available_at':datetime(2024,12,31,15,tzinfo=tz),'eligible':symbol!=self.fixture.symbols[-1]} for symbol in self.fixture.symbols]
        pl.DataFrame(rows).write_parquet(folder/'universe_events.parquet')
        spec={**self.spec,'universe':{'mode':'pit'}};service=ProposalService(self.output,self.root);proposal=service.propose(str(uuid4()),spec)
        result=service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],self.get_queue);final=self.settled(result['job']['job_id'])
        self.assertEqual(final['status'],'completed',final)
        freeze=ApprovalInputFreezeStore(self.output,self.root).path(proposal['proposal_id']);manifest=json.loads((freeze/'manifest.json').read_text())['manifest']
        self.assertEqual(len(manifest['universes']),1);self.assertEqual(manifest['universes'][0]['config']['mode'],'pit')
        bars=local_data_provider(freeze,'qfq').load(prepare(spec).config.data).bars
        mask=build_universe(freeze,tuple(spec['symbols']),prepare(spec).universe).mask(bars)
        self.assertFalse(mask.filter(pl.col('symbol')==self.fixture.symbols[-1])['eligible'].any())

    def test_system_health_reports_freeze_metadata_without_rehashing_semantics(self):
        from quantlab.agent.system_health import SystemHealthService
        service=ProposalService(self.output,self.root,budget=replace(ResearchBudget(),max_active_jobs=1));proposal=service.propose(str(uuid4()),self.spec)
        full=SimpleNamespace(root=self.output,data_root=self.root,list=lambda:[{'job_id':str(uuid4()),'status':'running'}])
        with self.assertRaises(Exception):service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],lambda:full)
        health=SystemHealthService(self.output,self.root,now_fn=lambda:datetime(2026,9,15,3,30,tzinfo=timezone.utc)).build()['components']['approval_input_freezes']
        self.assertEqual(health['status'],'OK');self.assertEqual(health['evidence']['valid_freezes'],1)
        self.assertEqual(health['evidence']['invalid_freezes'],0);self.assertGreaterEqual(health['evidence']['referenced_data_files'],1)


if __name__=='__main__':unittest.main()

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch

import polars as pl
from quantlab.data import published_daily_research as pub
from quantlab.data.base import DataRequest
from quantlab.data.provider import local_data_provider
from quantlab.data.validation import validate_bars, ordered_bars, SUSPENSION_INPUT_CONTRACT
from quantlab.domain import Timeframe
from quantlab.storage.codec import digest


class PublishedDailyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.data=self.root/'data';self.out=self.root/'package'
        self.data.mkdir();self.symbols=['sh.600001','sz.000001','sz.300001'];self.start=date(2024,1,1);self.end=date(2024,1,12)
        for p in (pub.QFQ,pub.STATUS,pub.SNAPSHOT,'catalog'):(self.data/p).mkdir(parents=True)
        registry={'format':'niuniu-dataset-registry-v1','datasets':{'bars.daily.qfq':{'status':'current','kind':'per_symbol_parquet','path':pub.QFQ,'qualification':'research_only','producer':'synthetic-test'}}}
        (self.data/'catalog/dataset_registry.json').write_text(json.dumps(registry))
        (self.data/pub.QFQ/'_meta').mkdir()
        pl.DataFrame({'code':self.symbols,'valid_from':['2020-01-01']*3,'history_truncated':[False]*3}).write_parquet(self.data/pub.QFQ/'_meta/coverage.parquet')
        dates=[self.start+timedelta(days=i) for i in range(12)]
        pl.DataFrame({'calendar_date':[d.isoformat() for d in dates],'is_trading_day':['1']*12}).write_parquet(self.data/pub.SNAPSHOT/'trade_calendar.parquet')
        for j,s in enumerate(self.symbols):
            rows=[];states=[]
            for i,d in enumerate(dates):
                suspended=i==5 and j==0;close=10+j+.1*(i-1 if suspended else i)
                rows.append({'date':d,'code':s,'open':close,'high':close if suspended else close+.2,'low':close if suspended else close-.2,'close':close,'volume':None if suspended else 1000.,'amount':None if suspended else close*1000,'factor':.8})
                states.append({'date':d.isoformat(),'code':s,'tradestatus':'0' if suspended else '1','isST':'1' if j==1 else '0'})
            pl.DataFrame(rows).write_parquet(self.path(s));pl.DataFrame(states).write_parquet(self.path(s,status=True))
    def path(self,s,status=False):return self.data/(pub.STATUS if status else pub.QFQ)/(s.replace('.','_')+'.parquet')
    def preview(self):return pub.preview(self.data,self.symbols,self.start,self.end)
    def export(self):
        plan=self.preview();return pub.export(self.data,self.symbols,self.start,self.end,self.out,expected_digest=plan['dataset_id'],confirm_create=True)
    def read(self):return local_data_provider(self.out,'qfq').load(DataRequest(tuple(self.symbols),Timeframe.DAILY,self.start,self.end))
    def mutate(self,path,fn):fn(pl.read_parquet(path)).write_parquet(path)
    def test_preview_is_read_only_export_preserves_exact_source_and_all_sessions(self):
        before={str(p):p.read_bytes() for p in self.data.rglob('*') if p.is_file()}
        plan=self.preview();self.assertFalse(self.out.exists());self.assertEqual(plan['rows'],36);self.assertEqual(plan['suspended_rows'],1)
        self.export();manifest,bars=pub.inspect(self.out)
        self.assertEqual(bars.height,36);self.assertNotIn('vendor_previous_close',bars.columns)
        suspension=bars.filter(pl.col('bs_trade_status')==0)
        self.assertTrue(all(suspension[c].null_count()==1 for c in ('open','high','low','close','volume','turnover')))
        self.assertEqual(bars.filter(pl.col('bs_is_st')==1).height,12)
        for e in manifest['files']:self.assertEqual((self.out/e['path']).read_bytes(),Path(e['source_path']).read_bytes())
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.data.rglob('*') if p.is_file()})
        self.assertFalse((self.out/pub.PENDING).exists());self.assertEqual(manifest['dataset_id'],plan['dataset_id'])
    def test_same_inputs_have_stable_identity_and_subrange_keeps_suspension(self):
        self.assertEqual(self.preview(),self.preview());self.export()
        p=local_data_provider(self.out,'qfq');request=DataRequest((self.symbols[0],),Timeframe.DAILY,date(2024,1,5),date(2024,1,8))
        a=p.load(request);b=p.load(request);self.assertEqual(a.snapshot.snapshot_id,b.snapshot.snapshot_id)
        self.assertEqual(a.bars.height,4);self.assertEqual(a.bars['bs_trade_status'].to_list(),[1,0,1,1])
    def test_no_execution_allowed_even_when_requested_slice_has_no_suspension(self):
        from quantlab.execution.backtest import OpenExecutionBacktester
        from quantlab.adapters.vnpy import VnpyOpenBacktester
        self.export();bars=self.read().bars.filter(pl.col('bs_trade_status')==1)
        with self.assertRaisesRegex(ValueError,'execution is forbidden'):ordered_bars(bars,for_execution=True)
        with self.assertRaisesRegex(ValueError,'execution is forbidden'):OpenExecutionBacktester().run(pl.DataFrame(),bars)
        with self.assertRaisesRegex(ValueError,'execution is forbidden'):VnpyOpenBacktester.__new__(VnpyOpenBacktester).run(pl.DataFrame(),bars)
    def test_legacy_contract_still_requires_vendor_valuation_and_plain_bars_reject_null(self):
        self.export();bars=self.read().bars
        with self.assertRaisesRegex(ValueError,'vendor_previous_close'):validate_bars(bars.with_columns(pl.lit(SUSPENSION_INPUT_CONTRACT).alias('input_contract')))
        with self.assertRaisesRegex(ValueError,'Null in required'):validate_bars(bars.drop('input_contract'))
    def test_unknown_status_and_missing_day_are_blockers_not_sample_changes(self):
        path=self.path(self.symbols[0],True);original=path.read_bytes()
        self.mutate(path,lambda f:f.with_columns(pl.when(pl.col('tradestatus')=='0').then(None).otherwise(pl.col('tradestatus')).alias('tradestatus')))
        with self.assertRaisesRegex(ValueError,'status is unknown'):self.preview()
        path.write_bytes(original);self.mutate(path,lambda f:f.slice(1))
        with self.assertRaisesRegex(ValueError,'session coverage'):self.preview()
    def test_tradable_nulls_and_suspended_nonzero_volume_are_rejected(self):
        path=self.path(self.symbols[0]);original=path.read_bytes()
        self.mutate(path,lambda f:f.with_columns(pl.when(pl.col('date')==self.start).then(None).otherwise(pl.col('volume')).alias('volume')))
        with self.assertRaisesRegex(ValueError,'Tradable rows require'):self.preview()
        path.write_bytes(original);self.mutate(path,lambda f:f.with_columns(pl.col('volume').fill_null(1)))
        with self.assertRaisesRegex(ValueError,'nonzero activity'):self.preview()
    def test_qfq_cutoff_and_bad_factor_not_downgraded_to_raw(self):
        path=self.data/pub.QFQ/'_meta/coverage.parquet';original=path.read_bytes()
        self.mutate(path,lambda f:f.with_columns(pl.lit('2024-01-03').alias('valid_from'),pl.lit(True).alias('history_truncated')))
        with self.assertRaisesRegex(ValueError,'qfq unavailable'):self.preview()
        path.write_bytes(original);self.mutate(self.path(self.symbols[0]),lambda f:f.with_columns(pl.lit(float('nan')).alias('factor')))
        with self.assertRaisesRegex(ValueError,'qfq factor'):self.preview()
    def test_duplicate_key_and_wrong_security_rejected(self):
        path=self.path(self.symbols[0]);original=path.read_bytes()
        self.mutate(path,lambda f:pl.concat([f,f.head(1)]))
        with self.assertRaisesRegex(ValueError,'coverage mismatch'):self.preview()
        path.write_bytes(original);self.mutate(path,lambda f:f.with_columns(pl.lit('sh.999999').alias('code')))
        with self.assertRaisesRegex(ValueError,'identity mismatch'):self.preview()
    def test_export_requires_confirmation_unchanged_preview_and_new_destination(self):
        plan=self.preview()
        with self.assertRaisesRegex(ValueError,'confirmation'):pub.export(self.data,self.symbols,self.start,self.end,self.out,expected_digest=plan['dataset_id'])
        self.mutate(self.path(self.symbols[1]),lambda f:f.with_columns(pl.col('amount')+1))
        with self.assertRaisesRegex(ValueError,'changed since preview'):pub.export(self.data,self.symbols,self.start,self.end,self.out,expected_digest=plan['dataset_id'],confirm_create=True)
        self.assertFalse(self.out.exists());self.export()
        with self.assertRaises(FileExistsError):self.export()
    def test_corrupt_source_or_manifest_never_falls_back(self):
        self.export();path=self.out/'bars'/f'{self.symbols[0]}.parquet';original=path.read_bytes();path.write_bytes(original+b'changed')
        with self.assertRaisesRegex(ValueError,'hash/size'):self.read()
        path.write_bytes(original);marker=self.out/pub.MARKER;value=json.loads(marker.read_text());value['rows']+=1;marker.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'checksum'):self.read()
    def test_input_scope_conflict_pending_and_raw_refused(self):
        self.export()
        with self.assertRaisesRegex(ValueError,'only supports'):local_data_provider(self.out,'raw')
        p=local_data_provider(self.out,'qfq')
        with self.assertRaisesRegex(ValueError,'outside'):p.load(DataRequest((self.symbols[0],),Timeframe.MIN5,self.start,self.end))
        (self.out/pub.PENDING).write_text('incomplete')
        with self.assertRaisesRegex(ValueError,'incomplete'):local_data_provider(self.out,'qfq')
        (self.out/pub.PENDING).unlink();(self.out/'manifest.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Conflicting'):local_data_provider(self.out,'qfq')
    def test_source_symlink_and_budget_refused(self):
        path=self.path(self.symbols[0]);renamed=path.with_suffix('.saved');path.rename(renamed);path.symlink_to(renamed)
        with self.assertRaisesRegex(ValueError,'symlink'):self.preview()
        path.unlink();renamed.rename(path)
        with patch.object(pub,'MAX_TOTAL',10):
            with self.assertRaisesRegex(ValueError,'byte budget'):self.preview()
        with self.assertRaises(ValueError):pub.preview(self.data,self.symbols*100,self.start,self.end)
    def test_export_inside_data_root_and_oversized_parquet_refused(self):
        plan=self.preview()
        with self.assertRaisesRegex(ValueError,'DATA source root'):
            pub.export(self.data,self.symbols,self.start,self.end,self.data/'forbidden',expected_digest=plan['dataset_id'],confirm_create=True)
        from io import BytesIO
        stream=BytesIO();pl.DataFrame({'x':range(50001)}).write_parquet(stream)
        with self.assertRaisesRegex(ValueError,'decoded size'):pub._table(stream.getvalue())
    def test_approval_freeze_survives_source_removal_with_contract_preserved(self):
        import time
        from types import SimpleNamespace
        from uuid import uuid4
        from quantlab.agent.proposals import ProposalService
        from quantlab.workbench.jobs import JobQueue
        self.export();output=self.root/'approved';output.mkdir()
        spec={'question':'published freeze test','symbols':self.symbols,'start':self.start.isoformat(),'end':self.end.isoformat(),'timeframe':'1d','adjustment':'qfq','qualification':'research_only','factor':'BASE.MOMENTUM','parameters':{'lookback':1},'horizons':[1],'quantiles':3,'replay':True,'mode':'single'}
        service=ProposalService(output,self.out);proposal=service.propose(str(uuid4()),spec)
        full=SimpleNamespace(root=output,data_root=self.out,list=lambda:[{'job_id':str(uuid4()),'status':'running'}])
        with self.assertRaises(Exception):service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],lambda:full)
        self.assertEqual(service.store.get(proposal['proposal_id'])['status'],'approved')
        (self.out/'bars').rename(self.out/'source-offline')
        queue=JobQueue(output,self.out);self.addCleanup(queue.close)
        result=service.approve_and_submit(proposal['proposal_id'],proposal['proposal_digest'],lambda:queue)
        deadline=time.monotonic()+20;job=None
        while time.monotonic()<deadline:
            job=next(v for v in queue.list() if v['job_id']==result['job']['job_id'])
            if job['status'] not in ('queued','running'):break
            time.sleep(.02)
        self.assertEqual(job['status'],'completed',job)
        record=json.loads((output/job['run_id']/'experiment.json').read_text())
        self.assertEqual(record['manifest']['data_snapshot']['source'],'data_published_qfq_research')
        self.assertEqual(record['manifest']['data_snapshot']['files'][0]['input_contract'],pub.PUBLISHED_RESEARCH_CONTRACT)
    def test_host_cli_preview_export_inspect_and_no_implicit_confirmation(self):
        from contextlib import redirect_stdout,redirect_stderr
        from io import StringIO
        common=['--source-root',str(self.data),'--symbols',','.join(self.symbols),'--start',self.start.isoformat(),'--end',self.end.isoformat()]
        out=StringIO()
        with redirect_stdout(out):self.assertEqual(pub.main(['preview',*common]),0)
        value=json.loads(out.getvalue());self.assertFalse(self.out.exists())
        with redirect_stderr(StringIO()),self.assertRaises(SystemExit):pub.main(['export',*common,'--destination',str(self.out)])
        with redirect_stdout(StringIO()):self.assertEqual(pub.main(['export',*common,'--destination',str(self.out),'--expected-digest',value['dataset_id'],'--confirm-create']),0)
        with redirect_stdout(StringIO()):self.assertEqual(pub.main(['inspect','--destination',str(self.out)]),0)
    def test_factor_runner_keeps_suspended_session_in_labels_and_mask(self):
        from quantlab.workbench.jobs import prepare,execute
        self.export()
        spec={'question':'synthetic published contract test','symbols':self.symbols,'start':self.start.isoformat(),'end':self.end.isoformat(),'timeframe':'1d','adjustment':'qfq','qualification':'research_only','factor':'BASE.MOMENTUM','parameters':{'lookback':1},'horizons':[1,2],'quantiles':3,'replay':True,'mode':'single'}
        result=execute(prepare(spec),self.out,self.root/'experiments')
        obs=pl.read_parquet(result.artifact_path/'observations.parquet')
        self.assertFalse(obs.filter((pl.col('symbol')==self.symbols[0])&(pl.col('datetime').dt.date()==date(2024,1,6))).height)
        before=obs.filter((pl.col('symbol')==self.symbols[0])&(pl.col('datetime').dt.date()==date(2024,1,5)))
        self.assertEqual(before.height,1);self.assertIsNone(before['forward_1'][0]);self.assertIsNotNone(before['forward_2'][0])
        self.assertIsNone(before['mae_2'][0])
        self.assertEqual(json.loads((result.artifact_path/'experiment.json').read_text())['status'],'completed')

if __name__=='__main__':unittest.main()

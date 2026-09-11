import json
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from dataclasses import replace
from pathlib import Path
import polars as pl
from test_context_experiments import ContextProvider,context_config,runner
from quantlab.agent.tracking_metrics import compute_tracking
from quantlab.agent.tracking_preview import tracking_preview
from quantlab.agent.tracking_tools import TrackingResearchAPI
from quantlab.storage.experiments import load_record_fields
from quantlab.storage.artifact_integrity import snapshot_tree


class TrackingPreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.output=self.root/'runs'
        cfg=replace(context_config(),context=None,replay=True)
        self.run=runner(ContextProvider(),self.output).run(cfg)
        self.bars=pl.read_parquet(self.run.artifact_path/'bars.parquet')
        self.obs=pl.read_parquet(self.run.artifact_path/'observations.parquet')
        self.cfg=load_record_fields(self.run.artifact_path/'experiment.json',{'manifest'})['manifest']['config']
        self.cutoff=datetime.fromisoformat('2025-01-05T15:00:00+08:00').astimezone(ZoneInfo('Asia/Shanghai'))
    def compute(self,bars=None,obs=None):
        return compute_tracking(self.bars if bars is None else bars,self.obs if obs is None else obs,
            self.cfg,self.cutoff,[5],1)[0]
    def test_future_bars_and_saved_forward_labels_do_not_leak(self):
        first=self.compute();future=pl.col('available_at')>self.cutoff
        changed=self.bars.with_columns(*[pl.when(future).then(pl.col(k)*9).otherwise(pl.col(k)).alias(k)
            for k in ('open','high','low','close')])
        fake=self.obs.with_columns(pl.lit(999.).alias('forward_3'))
        self.assertEqual(first,self.compute(changed,fake))
        h=first['windows']['5']['horizons']['3']
        self.assertEqual(h['pending_observations'],9)
        self.assertLess(h['latest_mature_signal_at'],self.cutoff)
        for w in first['watermarks'].values():self.assertLess(w['labels']['3'],w['data_at'])
    def test_prefix_source_equals_full_source_at_same_cutoff(self):
        full=self.compute()
        prefix=self.compute(self.bars.filter(pl.col('available_at')<=self.cutoff),
            self.obs.filter(pl.col('available_at')<=self.cutoff))
        self.assertEqual(full,prefix)
    def test_insufficient_and_constant_sections_not_zero_rank_ic(self):
        flat=self.obs.with_columns(pl.lit(1.).alias('value'))
        h=self.compute(obs=flat)['windows']['5']['horizons']['1']
        self.assertEqual(h['status'],'insufficient_mature_dates')
        self.assertIsNone(h['metrics']['rank_ic'])
        self.assertGreater(h['mature_observations'],0)
        stats=compute_tracking(self.bars,self.obs,self.cfg,self.cutoff,[5],20)[0]
        self.assertEqual(stats['windows']['5']['horizons']['1']['status'],'insufficient_mature_dates')
    def test_delayed_and_timezone_naive_cutoffs_rejected(self):
        with self.assertRaisesRegex(ValueError,'Delayed'):
            self.compute(self.bars.with_columns(pl.col('available_at')+pl.duration(hours=1)))
        with self.assertRaises(ValueError):tracking_preview(self.output,self.run.run_id,'2025-01-05')
    def test_read_only_api_preserves_source_and_does_not_schedule(self):
        before=snapshot_tree(self.output,self.run.run_id);api=TrackingResearchAPI(self.output)
        args={'run_id':self.run.run_id,'as_of':self.cutoff.isoformat(),'windows_json':'[5]','min_dates':1}
        result=api.call('get_tracking_preview',args)
        self.assertTrue(result['ok'],result)
        self.assertFalse(result['data']['automatic_tracking']);self.assertEqual(result['data']['new_research_jobs'],0)
        self.assertEqual(before,snapshot_tree(self.output,self.run.run_id))
        self.assertFalse((self.output/'_tracking').exists());self.assertFalse((self.output/'_jobs').exists())
        self.assertFalse(api.call('create_tracking_job',{})['ok'])
        self.assertFalse(api.call('get_tracking_preview',{**args,'shell':'ignored'})['ok'])
        for bad in ('[true]','[0]','[5,5]','[1,2,3,4,5]','{"a":5}'):
            self.assertFalse(api.call('get_tracking_preview',{**args,'windows_json':bad})['ok'])
    def test_weekend_is_not_a_missing_label_bar(self):
        days=[datetime.fromisoformat('2025-01-'+d+'T15:00:00+08:00') for d in ('03','06','07')]
        rows=[]
        for s in range(3):
            for i,t in enumerate(days):
                c=100+s+i*(s+1)
                rows.append({'symbol':str(s),'datetime':t,'available_at':t,'timeframe':'1d',
                    'open':float(c),'high':float(c+1),'low':float(c-1),'close':float(c),
                    'volume':100.,'turnover':100.*c,'value':float(s+1)})
        bars=pl.DataFrame(rows);values=bars.select('symbol','datetime','available_at','value')
        cfg={'horizons':[2],'quantiles':3,'data':{'symbols':['0','1','2']}}
        monday=compute_tracking(bars,values,cfg,days[1],[3],1)[0]['windows']['3']['horizons']['2']
        tuesday=compute_tracking(bars,values,cfg,days[2],[3],1)[0]['windows']['3']['horizons']['2']
        self.assertEqual(monday['mature_observations'],0)
        self.assertEqual(tuesday['mature_observations'],3)
        self.assertEqual(tuesday['latest_mature_signal_at'],days[0])

import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
import polars as pl
from polars.testing import assert_frame_equal
import test_baostock_data as fixture
from quantlab.app import default_registry,build_runner
from quantlab.factors.engine import compute_factor
from quantlab.data.provider import local_data_provider
from quantlab.workbench.jobs import prepare,JobQueue,execute
from quantlab.storage.bundle import reproduce_artifact
from quantlab.storage.experiments import load_record_fields


class BaostockFactorTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.BaostockDataTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups);self.fixture.imported()
        self.root=self.fixture.root;self.dataset=self.fixture.directory/'dataset'
        self.output=self.root/'runs';self.output.mkdir()
        self.spec={'symbols':fixture.plan()['symbols'],'start':'2025-01-01','end':'2025-01-10',
            'factor':'BAO.PE_TTM','parameters':{'lag_bars':1},'horizons':[1],
            'quantiles':3,'replay':True,'question':'lagged ratio fixture'}

    def test_lag_nulls_negative_values_and_prefix_invariance(self):
        bars=local_data_provider(self.dataset,'qfq').load(prepare(self.spec).config.data).bars
        registry=default_registry();pe=registry.get('BAO.PE_TTM','1.0.0')
        values=compute_factor(pe,bars,pe.parameters({}))
        self.assertEqual(values['value'].null_count(),3)
        self.assertEqual(values['value'].drop_nulls().unique().to_list(),[12.])
        for name in ('TURN_PCT','PCF_NCF_TTM'):
            f=registry.get('BAO.'+name,'1.0.0');value=compute_factor(f,bars,f.parameters({}))
            if name=='TURN_PCT':self.assertEqual(value['value'].null_count(),6)
            else:self.assertTrue(value['value'].drop_nulls().eq(-2.).all())
        prefix=bars.filter(pl.col('datetime').dt.day()<=6)
        expected=values.filter(pl.col('datetime').dt.day()<=6)
        assert_frame_equal(compute_factor(pe,prefix,pe.parameters({})),expected)
        for lag in (0,-1,True,253):
            with self.assertRaises(ValueError):pe.parameters({'lag_bars':lag})
        with self.assertRaisesRegex(ValueError,'Missing required'):
            compute_factor(pe,bars.drop('bs_pe_ttm'),pe.parameters({}))

    def test_original_queue_execution_and_frozen_reproduction(self):
        q=JobQueue(self.output,self.dataset)
        try:q.submit(str(uuid4()),self.spec)
        finally:q.close()
        job=q.list()[0];self.assertEqual(job['status'],'completed',job)
        path=self.output/job['run_id']
        record=load_record_fields(path/'experiment.json',{'manifest'})
        self.assertEqual(record['manifest']['data_snapshot']['source'],'baostock_managed_snapshot')
        with patch('quantlab.data.mqc.MQCParquetProvider.load',side_effect=AssertionError('no lake')):
            proof=reproduce_artifact(path,self.root/'reproduced')
        self.assertEqual(proof['status'],'numerically_matched')

    def test_cost_simulation_and_complete_campaign_reproduce(self):
        spec={**self.spec,'mode':'execution','execution':{'price_mode':'research','top_n':1}}
        result=execute(prepare(spec),self.dataset,self.output)
        self.assertEqual(reproduce_artifact(result.artifact_path,self.root/'cost-replay')['status'],
                         'numerically_matched')
        first={**self.spec,'permutation':{'resamples':20,'block_days':1}}
        plan={'mode':'campaign','question':'ratio pack','alpha':.05,'failure_policy':'stop',
            'nodes':[{'node_id':'pe','depends_on':[],'spec':first},
                {'node_id':'pb','depends_on':['pe'],'spec':{**first,'factor':'BAO.PB_MRQ'}}]}
        result=execute(prepare(plan),self.dataset,self.output)
        self.assertEqual(result.summary['counts']['completed'],2)
        with patch('quantlab.data.mqc.MQCParquetProvider.load',side_effect=AssertionError('no lake')):
            proof=reproduce_artifact(result.artifact_path,self.root/'campaign-replay')
        self.assertEqual(proof['status'],'numerically_matched')

    def test_managed_marker_and_source_corruption_cannot_fall_back(self):
        req=prepare(self.spec).config.data;marker=self.dataset/'baostock-dataset.json'
        original=marker.read_bytes();marker.write_bytes(b'{}')
        with self.assertRaises(ValueError):local_data_provider(self.dataset,'qfq').load(req)
        marker.write_bytes(original)
        source=next((self.dataset/'lake/silver/qfq_kline_daily').glob('*.parquet'))
        source.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):local_data_provider(self.dataset,'qfq').load(req)

import math
from datetime import datetime,timedelta,date
from zoneinfo import ZoneInfo
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import polars as pl
from polars.testing import assert_frame_equal
from quantlab.processing.neutralization import CrossSectionNeutralizer,SizeHistory
from quantlab.processing.pipeline import FactorPipeline,PipelineConfig
from quantlab.app import default_registry
from quantlab.data.base import DataBatch,DataRequest,DataSnapshot,ExplicitUniverse
from quantlab.domain import Timeframe
from quantlab.experiments.runner import ExperimentRunner
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.holdout import HoldoutRunner,ChronologicalSplit
from quantlab.storage.experiments import LocalExperimentStore,load_record


def fixture(days=1):
    at=datetime(2025,1,1,15,tzinfo=ZoneInfo('Asia/Shanghai'));symbols=[f'S{i}' for i in range(6)]
    rows=[];industry=[];sizes=[]
    for i,s in enumerate(symbols):
        x=3+i%3+3*(i//3)
        industry.append({'symbol':s,'sector':'A' if i<3 else 'B','effective_at':at,'available_at':at,'source':'synthetic known industry'})
        sizes.append({'symbol':s,'market_cap':math.exp(x),'effective_at':at,'available_at':at,'expires_at':at+timedelta(days=20),'source':'synthetic known cap; shared unit'})
        for d in range(days):
            t=at+timedelta(days=d);rows.append({'symbol':s,'datetime':t,'available_at':t,'value':float(10*(i//3)+2*x+[1,-2,1][i%3]+d)})
    frame=pl.DataFrame(rows);mask=frame.select('symbol','datetime').with_columns(pl.lit(True).alias('eligible'))
    return frame,mask,industry,sizes


class NeutralizationTests(unittest.TestCase):
    def test_joint_projection_and_degenerate_cross_section(self):
        values,mask,industry,sizes=fixture()
        result,audit=CrossSectionNeutralizer(industry,sizes).transform(values,mask,'neutralization')
        for actual,expected in zip(result['value'],[1.,-2.,1.,1.,-2.,1.]):self.assertAlmostEqual(actual,expected)
        self.assertAlmostEqual(audit[0]['log_cap_slope'],2.)
        self.assertEqual(audit[0]['residual_degrees_of_freedom'],3)
        # Values constant within each industry's cap expose a collinear control.
        sizes=[{**r,'market_cap':100. if i<3 else 200.} for i,r in enumerate(sizes)]
        result,audit=CrossSectionNeutralizer(industry,sizes).transform(values,mask,'neutralization')
        self.assertEqual(result['value'].null_count(),6)
        self.assertEqual(audit[0]['status'],'constant_or_industry_collinear_size')
        result,audit=CrossSectionNeutralizer(industry,sizes).transform(values.head(1),mask.head(1),'industry_neutralization')
        self.assertEqual(audit[0]['status'],'insufficient_degrees_of_freedom')

    def test_late_controls_expiry_and_future_prefix(self):
        values,mask,industry,sizes=fixture(3);at=values['datetime'].min()
        delayed={**sizes[0],'effective_at':at+timedelta(days=1),'available_at':at+timedelta(days=2),'market_cap':1e8}
        before,_=CrossSectionNeutralizer(industry,sizes).transform(values,mask,'neutralization')
        after,_=CrossSectionNeutralizer(industry,sizes+[delayed]).transform(values,mask,'neutralization')
        assert_frame_equal(before.filter(pl.col('datetime')<delayed['available_at']),after.filter(pl.col('datetime')<delayed['available_at']))
        history=SizeHistory(sizes+[{**delayed,'expires_at':at+timedelta(days=3)}])
        self.assertIsNone(history.at(sizes[0]['symbol'],at+timedelta(days=4)))
        unknown=[{**r,'available_at':at+timedelta(days=4)} for r in industry]
        result,audit=CrossSectionNeutralizer(unknown,sizes).transform(values,mask,'neutralization')
        self.assertEqual(result['value'].null_count(),18)
        self.assertTrue(all(r['missing_industry_rows']==6 for r in audit))
        with self.assertRaisesRegex(ValueError,'FillNA'):PipelineConfig([{'method':'industry_neutralization'},{'method':'fill_na'}],industry_events=[])

    def test_pipeline_holdout_and_archived_audit(self):
        values,mask,industry,sizes=fixture(12)
        market=values.rename({'value':'close'}).with_columns(pl.lit('1d').alias('timeframe'),
            (pl.col('close')+1).alias('high'),(pl.col('close')-1).alias('low'))
        class Provider:
            def load(self,request):return DataBatch(market,DataSnapshot('synthetic-neutralization','fixture','raw',()))
        symbols=tuple(sorted(market['symbol'].unique()))
        cfg=ExperimentConfig('Synthetic PIT controls integration',DataRequest(symbols,Timeframe.DAILY,date(2025,1,1),date(2025,1,12)),
            'BASE.MOMENTUM',parameters={'lookback':1},horizons=(1,),processor=PipelineConfig(
                [{'method':'replace_inf'},{'method':'winsorize'},{'method':'neutralization'}],industry_events=industry,size_events=sizes))
        with TemporaryDirectory() as tmp:
            runner=ExperimentRunner(Provider(),default_registry(),ExplicitUniverse(symbols),LocalExperimentStore(Path(tmp)))
            result=HoldoutRunner(runner).run(cfg,ChronologicalSplit(date(2025,1,4),date(2025,1,8)))
            records=[load_record(Path(p['artifact_path'])/'experiment.json') for p in result.periods]
            self.assertEqual(len(set(r['manifest']['processor']['state_hash'] for r in records)),1)
            self.assertTrue(all('processor_audit' in r for r in records))
            frame=pl.read_parquet(Path(result.periods[1]['artifact_path'])/'observations.parquet')
            self.assertEqual(frame['value'].null_count(),0)
            self.assertTrue(all(abs(n)<1e-10 for n in frame.group_by('datetime').agg(pl.col('value').sum())['value']))

    def test_exact_linear_size_signal_zeroes_roundoff(self):
        values,mask,industry,sizes=fixture()
        values=values.with_columns(pl.Series('value',[2*math.log(r['market_cap'])+7 for r in sizes]))
        result,_=CrossSectionNeutralizer(size_events=sizes).transform(values,mask,'size_neutralization')
        self.assertEqual(result['value'].to_list(),[0.]*6)

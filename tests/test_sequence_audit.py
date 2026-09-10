import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

import polars as pl
from test_reclaim_sequence import make_frame
from test_context_experiments import ContextProvider, context_config, runner
from quantlab.data.base import DataBatch, DataSnapshot, DataRequest
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.ablation import AblationRunner
from quantlab.experiments.holdout import HoldoutRunner, ChronologicalSplit
from quantlab.storage.codec import digest
from quantlab.storage.experiments import load_record
from quantlab.theory.templates import resolve_template


class Provider:
    def load(self, request):
        bars=make_frame([(7.,10.,9.),(8.,12.,12.),(6.,11.,10.)])
        return DataBatch(bars,DataSnapshot(digest(bars.write_json()),'fixture','raw',()))


class SequenceAuditTests(unittest.TestCase):
    def test_persisted_links_counts_and_unchanged_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine=runner(Provider(),Path(tmp))
            cfg=ExperimentConfig('审计',DataRequest(('A',),Timeframe.DAILY,date(2025,1,1),date(2025,1,5)),
                'SEQ.FAILED_LOW_THEN_BREAKOUT',parameters={'lookback':2},horizons=(1,),sequence_audit=True)
            a=engine.run(cfg)
            b=engine.run(cfg)
            plain=engine.run(replace(cfg,sequence_audit=False))
            self.assertEqual(a.metrics,plain.metrics)
            self.assertEqual(a.experiment_id,b.experiment_id)
            record=load_record(a.artifact_path/'experiment.json')
            self.assertEqual(record['sequence_audit'],load_record(b.artifact_path/'experiment.json')['sequence_audit'])
            sequence=record['sequence_audit']['sequences'][0]
            self.assertEqual(sequence['pending_at_end'],1)
            self.assertEqual(sequence['selected_completions'],1)
            self.assertEqual(sequence['status_record_counts']['completed'],a.metrics['1']['triggered']['event_count'])
            event_ids={e['event_id'] for e in sequence['events']}
            for transition in sequence['transitions']:
                self.assertTrue(set(transition['event_ids'])<=event_ids)
                if transition['invalidating_event_id']:
                    self.assertIn(transition['invalidating_event_id'],event_ids)
            self.assertNotIn('sequence_audit',load_record(plain.artifact_path/'experiment.json'))
            self.assertIn('序列审计',(a.artifact_path/'report.md').read_text())
            repeated=engine.run(replace(cfg,factor_id='SEQ.REPEATED_BREAKOUT'))
            trace=load_record(repeated.artifact_path/'experiment.json')['sequence_audit']['sequences'][0]
            self.assertEqual(trace['pending_at_end'],1)
            self.assertEqual(len(trace['events']),1)

    def test_template_ablation_and_holdout_propagation(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine=runner(ContextProvider(),Path(tmp))
            parameters,origin=resolve_template('RESEARCH.RECLAIM_CONFIRMATION',engine.registry)
            cfg=replace(context_config(),factor_id='COMB.CONDITION',parameters=parameters,theory_origin=origin,sequence_audit=True)
            ablation=AblationRunner(engine).run(cfg)
            parent=load_record(ablation.artifact_path/'experiment.json')
            for child in parent['children']:
                audit=load_record(Path(child['artifact_path'])/'experiment.json')['sequence_audit']
                self.assertEqual(len(audit['sequences']),0 if child['removed']=='confirmation' else 1)
            holdout=HoldoutRunner(engine).run(cfg,ChronologicalSplit(date(2025,1,4),date(2025,1,8)))
            for period in holdout.periods:
                record=load_record(Path(period['artifact_path'])/'experiment.json')
                for sequence in record['sequence_audit']['sequences']:
                    for transition in sequence['transitions']:
                        self.assertLessEqual(transition['available_at'][:10],period['end'].isoformat())

    def test_filtered_completions_are_distinguished(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine=runner(Provider(),Path(tmp))
            class EmptyUniverse:
                universe_id='none'
                version='1'
                def mask(self,bars):
                    return bars.select('symbol','datetime',pl.lit(False).alias('eligible'))
            engine.universe=EmptyUniverse()
            cfg=ExperimentConfig('空池审计',DataRequest(('A',),Timeframe.DAILY,date(2025,1,1),date(2025,1,5)),
                'SEQ.FAILED_LOW_THEN_BREAKOUT',parameters={'lookback':2},horizons=(1,),sequence_audit=True)
            result=engine.run(cfg)
            audit=load_record(result.artifact_path/'experiment.json')['sequence_audit']['sequences'][0]
            self.assertEqual(audit['status_record_counts']['completed'],1)
            self.assertEqual(audit['selected_completions'],0)
            self.assertEqual(result.metrics['1']['triggered']['event_count'],0)


if __name__=='__main__':
    unittest.main()

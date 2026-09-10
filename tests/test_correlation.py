import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import polars as pl
from polars.testing import assert_frame_equal

from test_context_experiments import ContextProvider, context_config, runner
from quantlab.experiments.correlation import CorrelationConfig, CorrelationRunner
from quantlab.factors.builtin import Momentum
from quantlab.factors.registry import FactorPack
from quantlab.statistics.correlation import complete_link_groups, cross_section_correlations
from quantlab.storage.experiments import load_record


class DelayedMomentum(Momentum):
    definition = replace(Momentum.definition, factor_id='TEST.DELAYED')

    def compute(self, bars, parameters):
        return super().compute(bars, parameters).with_columns(pl.col('available_at') + pl.duration(hours=1))


class CorrelationTests(unittest.TestCase):
    def test_ic_correlation_uses_paired_labelled_rows(self):
        rows=[];labels=[]
        for day in range(1,7):
            for i in range(20):
                rows.append({'symbol':str(i),'datetime':datetime(2025,1,day),'factor_a':float(i),'factor_b':float(-i)})
                labels.append({'symbol':str(i),'datetime':datetime(2025,1,day),'forward_return':float(i if day%2 else -i) if i else None})
        pairs=cross_section_correlations(pl.DataFrame(rows),['a','b'],return_labels=pl.DataFrame(labels))
        result=next(p for p in pairs if p['left']=='a' and p['right']=='b')['ic_correlation']
        self.assertEqual(result['valid_periods'],6);self.assertAlmostEqual(result['estimate'],-1.)

    def test_information_and_boolean_overlap(self):
        import math
        panel=pl.DataFrame([{'symbol':str(i),'datetime':datetime(2025,1,1),
            'factor_a':float(i%2),'factor_same':float(i%2),'factor_independent':float((i//2)%2),'factor_none':None}
            for i in range(40)],schema_overrides={'factor_none':pl.Float64})
        pairs=cross_section_correlations(panel,['a','same','independent','none'],min_periods=1,boolean_aliases=['a','same','independent'])
        same=next(p for p in pairs if (p['left'],p['right'])==('a','same'))
        self.assertAlmostEqual(same['mutual_information']['estimate'],math.log(2))
        self.assertAlmostEqual(same['mutual_information']['normalized'],1)
        self.assertEqual(same['signal_overlap']['jaccard'],1)
        other=next(p for p in pairs if (p['left'],p['right'])==('a','independent'))
        self.assertAlmostEqual(other['mutual_information']['estimate'],0)
        self.assertAlmostEqual(other['signal_overlap']['jaccard'],1/3)
        missing=next(p for p in pairs if (p['left'],p['right'])==('a','none'))
        self.assertIsNone(missing['mutual_information']['estimate'])
        self.assertNotIn('signal_overlap',missing)

    def test_equal_timestamp_means_pairwise_missing_and_constants(self):
        rows = []
        for day, size, sign in [(1,3,1), (2,4,-1)]:
            for i in range(size):
                rows.append({'symbol':str(i), 'datetime':datetime(2025,1,day),
                    'factor_x':float(i), 'factor_y':float(i)*sign, 'factor_constant':1.,
                    'factor_sparse':float(i) if i < 2 else None})
        panel = pl.DataFrame(rows)
        pairs = cross_section_correlations(panel, ['x','y','constant','sparse'], min_periods=2)
        xy = next(p for p in pairs if (p['left'],p['right']) == ('x','y'))
        self.assertAlmostEqual(xy['pearson'], 0)
        self.assertAlmostEqual(xy['spearman'], 0)
        self.assertEqual(xy['common_rows'], 7)
        self.assertEqual(xy['spearman_periods'], 2)
        for pair in pairs:
            if 'constant' in (pair['left'],pair['right']) or 'sparse' in (pair['left'],pair['right']):
                self.assertIsNone(pair['spearman'])
        self.assertEqual(pairs, cross_section_correlations(panel.reverse(), ['sparse','y','x','constant'], min_periods=2))
        insufficient = cross_section_correlations(panel, ['x','y'], min_periods=3)
        self.assertTrue(all(p['pearson'] is None for p in insufficient))
        empty = cross_section_correlations(panel.head(0), ['x','y'])
        self.assertTrue(all(p['common_rows'] == 0 and p['spearman'] is None for p in empty))

    def test_complete_link_avoids_chains_and_retains_unknowns(self):
        pairs = [{'left':'a','right':'b','spearman':-.9}, {'left':'b','right':'c','spearman':.9},
            {'left':'a','right':'c','spearman':.2}, {'left':'a','right':'d','spearman':None}]
        expected = [['a','b'],['c'],['d']]
        self.assertEqual(complete_link_groups(['a','b','c','d'], pairs, .8), expected)
        self.assertEqual(complete_link_groups(['d','c','b','a'], pairs[::-1], .8), expected)
        self.assertEqual(complete_link_groups(['a','b'], pairs, .9), [['a','b']])
        with self.assertRaises(ValueError):
            complete_link_groups(['a','b'], pairs, float('nan'))

    def config(self):
        return CorrelationConfig('因子冗余研究', context_config().data, {
            'short': {'factor_id':'BASE.MOMENTUM','parameters':{'lookback':1}},
            'copy': {'factor_id':'BASE.MOMENTUM','parameters':{'lookback':1}},
            'long': {'factor_id':'BASE.MOMENTUM','parameters':{'lookback':4}}})

    def test_workflow_reproducibility_lineage_and_prefix_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = ContextProvider()
            engine = CorrelationRunner(runner(provider, Path(tmp)))
            cfg = self.config()
            first = engine.run(cfg)
            self.assertEqual(len(provider.calls), 1)
            repeated = engine.run(cfg)
            self.assertEqual(first.experiment_id, repeated.experiment_id)
            self.assertEqual(first.pairs, repeated.pairs)
            self.assertEqual(first.groups, repeated.groups)
            pair = next(p for p in first.pairs if (p['left'],p['right']) == ('copy','short'))
            self.assertAlmostEqual(pair['spearman'], 1)
            panel = pl.read_parquet(first.artifact_path/'observations.parquet')
            end = date(2025,1,8)
            truncated = engine.run(replace(cfg, data=replace(cfg.data, end=end)))
            assert_frame_equal(panel.filter(pl.col('datetime').dt.date() <= end),
                pl.read_parquet(truncated.artifact_path/'observations.parquet'), check_exact=True)
            record = load_record(first.artifact_path/'experiment.json')
            self.assertEqual(len(record['manifest']['inputs']), 3)
            self.assertEqual(record['coverage']['copy']['eligible_rows'], panel.height)
            self.assertIn('完全链接', (first.artifact_path/'report.md').read_text())

    def test_validation_and_delayed_factors_record_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = ContextProvider()
            base = runner(provider, Path(tmp))
            engine = CorrelationRunner(base)
            with self.assertRaises(ValueError):
                engine.run(replace(self.config(), min_symbols=2))
            self.assertEqual(provider.calls, [])
            base.registry.register_pack(FactorPack('DelayedPack','1.0.0',(DelayedMomentum(),)))
            inputs = {**self.config().inputs, 'late': {'factor_id':'TEST.DELAYED','parameters':{'lookback':1}}}
            with self.assertRaisesRegex(ValueError, 'bar close'):
                engine.run(replace(self.config(), inputs=inputs))
            records = [load_record(p) for p in Path(tmp).glob('*/experiment.json')]
            self.assertEqual(len(records), 2)
            self.assertTrue(all(r['status']=='failed' and r['kind']=='correlation' for r in records))


if __name__ == '__main__':
    unittest.main()

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import polars as pl
from polars.testing import assert_frame_equal

from test_context_experiments import ContextProvider, context_config, runner
from quantlab.app import default_registry
from quantlab.experiments.ablation import AblationRunner
from quantlab.theory.templates import templates, resolve_template
from quantlab.storage.experiments import load_record


class TheoryTests(unittest.TestCase):
    def test_catalog_versions_and_mutation_isolation(self):
        registry = default_registry()
        for template in templates():
            parameters, origin = resolve_template(template['template_id'], registry)
            self.assertEqual(set(origin['concepts']),set(parameters['inputs']))
            self.assertEqual(origin['parameters'],parameters)
            self.assertTrue(origin['code_hash'])
            parameters['inputs'].clear()
            self.assertEqual(len(origin['parameters']['inputs']),2)
            self.assertEqual(len(resolve_template(template['template_id'],registry)[0]['inputs']),2)
        with self.assertRaises(ValueError):
            resolve_template('RESEARCH.TREND_BREAKOUT',registry,'9.0.0')

    def test_templates_equal_explicit_combinations_and_keep_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = runner(ContextProvider(),Path(tmp))
            for template in templates():
                parameters, origin = resolve_template(template['template_id'],engine.registry)
                cfg = replace(context_config(),context=None,factor_id='COMB.CONDITION',parameters=parameters,theory_origin=origin)
                a = engine.run(cfg)
                explicit = engine.run(replace(cfg,theory_origin=None))
                self.assertEqual(a.metrics,explicit.metrics)
                assert_frame_equal(pl.read_parquet(a.artifact_path/'observations.parquet'),
                    pl.read_parquet(explicit.artifact_path/'observations.parquet'),check_exact=True)
                self.assertIn('研究模板来源',(a.artifact_path/'report.md').read_text())
                repeat = engine.run(cfg)
                self.assertEqual(a.experiment_id,repeat.experiment_id)

    def test_ablation_records_origin_and_actual_reduced_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = runner(ContextProvider(),Path(tmp))
            parameters, origin = resolve_template('RESEARCH.TREND_BREAKOUT',engine.registry)
            cfg = replace(context_config(),context=None,factor_id='COMB.CONDITION',parameters=parameters,theory_origin=origin)
            result = AblationRunner(engine).run(cfg)
            record = load_record(result.artifact_path/'experiment.json')
            self.assertEqual(len(record['children']),3)
            for child in record['children']:
                detail = load_record(Path(child['artifact_path'])/'experiment.json')
                self.assertEqual(len(detail['manifest']['config']['theory_origin']['parameters']['inputs']),2)
                self.assertEqual(len(detail['manifest']['parameters']['inputs']),2 if child['removed'] is None else 1)


if __name__ == '__main__':
    unittest.main()

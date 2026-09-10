import unittest
from datetime import date
import test_core
from quantlab.app import build_runner
from quantlab.experiments.config import ExperimentConfig
from quantlab.theory.templates import resolve_template
from quantlab.experiments.theory_study import TheoryStudyPlan, TheoryStudyRunner, stability_summary
from quantlab.storage.experiments import load_record

class TheoryStudyTests(unittest.TestCase):
    def test_whole_study_and_phase_sensitivity(self):
        fixture=test_core.CoreTests();fixture.setUp()
        try:
            runner=build_runner(fixture.root,fixture.root/'artifacts',fixture.symbols)
            params,origin=resolve_template('RESEARCH.BROOKS_SECOND_ENTRY',runner.registry)
            for spec in params['inputs'].values():spec['parameters']={'trend_lookback':2,'max_bars':5}
            cfg=ExperimentConfig('study',fixture.request,'COMB.CONDITION',parameters=params,horizons=(1,),theory_origin=origin)
            plan=TheoryStudyPlan.parse({'split':{'train_end':'2025-01-04','valid_end':'2025-01-07'},
                'schedule':{'train_days':4,'valid_days':3,'test_days':3},'input':'entry','grid':{'trend_lookback':[2,3]}})
            result=TheoryStudyRunner(runner).run(cfg,plan)
            record=load_record(result.artifact_path/'experiment.json')
            self.assertEqual(record['status'],'completed')
            names=[c['name'] for c in record['children']]
            self.assertEqual(len(names),10)
            self.assertIn('固定样本外',names);self.assertIn('逐输入消融',names)
            self.assertEqual({r['phase'] for r in record['stability']['rows']},{'train','valid','test'})
            self.assertFalse(record['stability']['automatic_selection'])
        finally:fixture.tearDown()
    def test_summary_missing_and_sign_changes(self):
        children=[{'evaluations':[{'phase':'test','metrics':{'1':{'ic':v}}}]} for v in (.2,-.1,None)]
        row=next(r for r in stability_summary(children)['rows'] if r['metric']=='ic')
        self.assertEqual(row['available_variants'],2)
        self.assertAlmostEqual(row['range'],.3)
        self.assertEqual(row['positive_fraction'],.5)

import json,tempfile,unittest
from pathlib import Path
from dataclasses import replace
from datetime import date
from test_context_experiments import ContextProvider,context_config,runner
from quantlab.statistics.permutation import PermutationConfig
from quantlab.experiments.trial_registry import create_registry,bind_result,report_registry
from quantlab.experiments.holdout import HoldoutRunner,ChronologicalSplit
from quantlab.storage.trial_reproduction import archive_registry
from quantlab.storage.bundle import export_bundle,restore_bundle,reproduce_artifact
from quantlab.storage.codec import encode,digest

class TrialReproductionTests(unittest.TestCase):
    def setup_archive(self,root,parent=False,mixed=False):
        cfg=replace(context_config(),context=None,replay=True,permutation=PermutationConfig(resamples=20,block_days=1))
        config=json.loads(encode(cfg));trial={'trial_id':'main','config':config}
        split=ChronologicalSplit(date(2025,1,4),date(2025,1,8))
        if parent:trial['study']={'kind':'holdout','design':{'split':json.loads(encode(split))}}
        trials=[trial]
        if mixed:
            trials += [{'trial_id':name,'config':{**config,'research_question':name}} for name in ('failed','unrun')]
        registry=create_registry({'name':'portable trials','alpha':.05,'trials':trials},root/'registry')
        engine=runner(ContextProvider(),root/'runs')
        result=HoldoutRunner(engine).run(cfg,split) if parent else engine.run(cfg)
        bind_result(root/'registry','main',result.artifact_path)
        if mixed:
            failure={'run_id':'failed-evidence','created_at':registry['created_at'],'status':'failed','manifest':{'config':trials[1]['config']},'error':'intentional'}
            path=root/'failed.json';path.write_text(encode(failure));bind_result(root/'registry','failed',path)
        report_registry(root/'registry',root/'report')
        return archive_registry(root/'report',root/'runs')

    def test_restore_without_originals_preserves_failed_unrun_and_timing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original=self.setup_archive(root,mixed=True)
            export_bundle(original['artifact_path'],root/'bundle.zip');restore_bundle(root/'bundle.zip',root/'restored')
            (root/'runs').rename(root/'hidden-runs');(root/'registry').rename(root/'hidden-registry')
            result=reproduce_artifact(root/'restored/runs'/original['run_id'],root/'out')
            self.assertEqual(result['status'],'available_results_matched');self.assertEqual(result['preserved_trials'],2)
            a=json.loads((Path(original['artifact_path'].replace('/runs/','/hidden-runs/'))/'experiment.json').read_text())
            b=json.loads((Path(result['artifact_path'])/'experiment.json').read_text())
            self.assertEqual(a['summary'],b['summary']);self.assertEqual(a['manifest'],b['manifest'])
            self.assertNotEqual(a['children'],b['children'])
            # A reproduced registry is itself a portable reproduction source.
            self.assertEqual(reproduce_artifact(result['artifact_path'],root/'again')['status'],'available_results_matched')

    def test_parent_layout_recomputes_all_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original=self.setup_archive(root,parent=True)
            result=reproduce_artifact(original['artifact_path'],root/'out')
            self.assertEqual(result['status'],'numerically_matched');self.assertEqual(result['recomputed_trials'],1)
            self.assertGreater(result['planned_tests'],2)

    def test_report_tampering_rejected_before_reproduction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original=self.setup_archive(root)
            path=Path(original['artifact_path'])/'experiment.json';r=json.loads(path.read_text())
            r['summary']['tests'][0]['p_holm']=.123456
            r['manifest']['report_hash']=digest(r['summary']);r['experiment_id']=digest(r['manifest']);path.write_text(encode(r))
            with self.assertRaisesRegex(ValueError,'registry/report'):reproduce_artifact(path.parent,root/'out')
            self.assertFalse((root/'out').exists())

    def test_failed_rerun_has_persistent_failed_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original=self.setup_archive(root)
            record=json.loads((Path(original['artifact_path'])/'experiment.json').read_text())
            child=root/'runs'/record['children'][0]['run_id']/'experiment.json'
            r=json.loads(child.read_text());h=next(iter(r['metrics']))
            r['metrics'][h]['mean_ic']=987654;child.write_text(encode(r))
            with self.assertRaisesRegex(ValueError,'核对记录'):reproduce_artifact(original['artifact_path'],root/'out')
            attempts=[json.loads(p.read_text()) for p in (root/'out').glob('*/experiment.json')]
            failed=[r for r in attempts if r.get('kind')=='trial_registry']
            self.assertEqual(len(failed),1);self.assertEqual(failed[0]['status'],'failed')
            result=json.loads((root/'out'/failed[0]['run_id']/'reproduction.json').read_text())
            self.assertEqual(result['status'],'mismatch')

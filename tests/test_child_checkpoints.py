import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from uuid import uuid4
from unittest.mock import patch
from test_context_experiments import ContextProvider, context_config, runner
from quantlab.experiments.child_checkpoints import child_checkpoint_scope
from quantlab.storage.bundle import reproduce_artifact


class ChildCheckpointTests(unittest.TestCase):
    def test_completed_children_survive_parent_failure_and_keep_distinct_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);job=str(uuid4());cfg=replace(context_config(),context=None,replay=True)
            engine=runner(ContextProvider(),output)
            with child_checkpoint_scope(output,job,{'plan':'fixed'}):
                first=engine.run(cfg);second=engine.run(cfg)
                with patch('quantlab.experiments.runner.compute_factor',side_effect=RuntimeError('interrupted child')):
                    with self.assertRaises(RuntimeError):engine.run(replace(cfg,parameters={'lookback':2}))
            self.assertNotEqual(first.run_id,second.run_id)
            with child_checkpoint_scope(output,job,{'plan':'fixed'}) as scope:
                with patch('quantlab.experiments.runner.compute_factor',side_effect=AssertionError('must reuse')):
                    self.assertEqual(engine.run(cfg).run_id,first.run_id)
                    self.assertEqual(engine.run(cfg).run_id,second.run_id)
                third=engine.run(replace(cfg,parameters={'lookback':2}))
                self.assertEqual(scope.summary()['completed_children_reused'],2)
                self.assertEqual(scope.summary()['completed_children_published'],1)
                self.assertNotIn(third.run_id,(first.run_id,second.run_id))
            self.assertEqual(reproduce_artifact(first.artifact_path,output/'reproduced')['status'],'numerically_matched')

    def test_changed_context_source_invalidates_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);job=str(uuid4());cfg=replace(context_config(),replay=True)
            with child_checkpoint_scope(output,job,{}):
                first=runner(ContextProvider(),output).run(cfg)
            with child_checkpoint_scope(output,job,{}) as scope:
                second=runner(ContextProvider(True),output).run(cfg)
                self.assertEqual(scope.summary()['completed_children_reused'],0)
            self.assertNotEqual(first.run_id,second.run_id)

    def test_corrupt_artifact_and_changed_plan_do_not_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);job=str(uuid4());cfg=replace(context_config(),context=None,replay=True)
            engine=runner(ContextProvider(),output)
            with child_checkpoint_scope(output,job,{'v':1}):first=engine.run(cfg)
            report=first.artifact_path/'report.md';report.write_text(report.read_text()+'\nmodified\n')
            with child_checkpoint_scope(output,job,{'v':1}) as scope:
                second=engine.run(cfg)
                self.assertEqual(scope.summary()['completed_children_reused'],0)
            with child_checkpoint_scope(output,job,{'v':2}) as scope:
                third=engine.run(cfg)
                self.assertEqual(scope.summary()['completed_children_reused'],0)
            self.assertEqual(len({first.run_id,second.run_id,third.run_id}),3)

    def test_real_sweep_job_resume_reuses_completed_child(self):
        import time,json
        import test_core
        from quantlab.workbench.jobs import JobQueue
        from quantlab.factors.engine import compute_factor
        from quantlab.progress import ResearchCancelled
        fixture=test_core.CoreTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        output=fixture.root/'artifacts';output.mkdir();job=str(uuid4());queue=JobQueue(output,fixture.root)
        self.addCleanup(queue.close)
        spec={'question':'resume fixture','symbols':list(fixture.symbols),'start':'2025-01-01',
            'end':'2025-01-10','factor':'BASE.MOMENTUM','parameters':{'lookback':2},'horizons':[1],
            'mode':'sweep','grid':{'lookback':[2,3]}}
        def interrupt(factor,bars,parameters):
            if parameters.get('lookback')==3: raise ResearchCancelled('interrupted second child')
            return compute_factor(factor,bars,parameters)
        def settled():
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                item=next(r for r in queue.list() if r['job_id']==job)
                if item['status'] not in ('queued','running'):return item
                time.sleep(.02)
            self.fail('Job did not settle')
        with patch('quantlab.experiments.runner.compute_factor',side_effect=interrupt):
            queue.submit(job,spec);self.assertEqual(settled()['status'],'cancelled')
        completed=[]
        for path in output.glob('*/experiment.json'):
            record=json.loads(path.read_text())
            if record['status']=='completed' and record.get('kind','factor')=='factor':completed.append(record['run_id'])
        self.assertTrue(completed)
        queue.resume(job);result=settled()
        self.assertEqual(result['status'],'completed',result)
        self.assertGreaterEqual(result['checkpoint_summary']['completed_children_reused'],1)
        parent=json.loads((output/result['run_id']/'experiment.json').read_text())
        self.assertTrue(set(completed)<={c['run_id'] for c in parent['children']})

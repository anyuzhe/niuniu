import tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from test_workbench_jobs import spec
from quantlab.workbench.jobs import JobQueue,prepare,execute
from quantlab.progress import checkpoint
from quantlab.experiments.walkforward import WalkForwardConfig
from quantlab.data.base import DataRequest
from quantlab.domain import Timeframe
from datetime import date

class CompletionJobsTests(unittest.TestCase):
    def test_resume_queued_cancellation_does_not_execute_stale_attempt(self):
        from types import SimpleNamespace
        entered=threading.Event();release=threading.Event()
        def work(*args):
            entered.set();release.wait(5)
            return SimpleNamespace(run_id='result',experiment_id='experiment')
        with tempfile.TemporaryDirectory() as tmp,patch('quantlab.workbench.jobs.execute',side_effect=work) as execution:
            queue=JobQueue(tmp,tmp);first,second=str(uuid4()),str(uuid4())
            try:
                queue.submit(first,spec());self.assertTrue(entered.wait(5))
                queue.submit(second,spec());queue.cancel(second)
                resumed=queue.resume(second);self.assertEqual(resumed['attempt'],2)
                self.assertEqual(resumed['attempts'][0]['status'],'cancelled')
                with self.assertRaises(ValueError):queue.resume(second)
            finally:release.set();queue.close()
            self.assertEqual(execution.call_count,2)
            self.assertTrue(all(j['status']=='completed' for j in queue.list()))

    def test_restart_interrupted_job_preserves_spec_and_attempt_history(self):
        import json
        from types import SimpleNamespace
        from quantlab.storage.codec import encode
        identifier=str(uuid4());original=spec()
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'_jobs';directory.mkdir()
            (directory/(identifier+'.json')).write_text(encode({'job_id':identifier,'status':'running',
                'created_at':'2026-09-01','started_at':'2026-09-01','finished_at':None,'spec':original,
                'resolved':prepare(original).preview(),'run_id':None,'error':None}))
            with patch('quantlab.workbench.jobs.execute',return_value=SimpleNamespace(run_id='restored',experiment_id='e')) as execution:
                queue=JobQueue(tmp,tmp)
                try:
                    self.assertEqual(queue.list()[0]['status'],'interrupted');queue.resume(identifier)
                finally:queue.close()
            saved=json.loads((directory/(identifier+'.json')).read_text())
            self.assertEqual(saved['status'],'completed');self.assertEqual(saved['spec'],original)
            self.assertEqual(saved['attempts'][0]['status'],'interrupted');self.assertEqual(execution.call_count,1)

    def test_queued_cancellation_is_immediate_and_never_executes(self):
        from types import SimpleNamespace
        entered=threading.Event();release=threading.Event()
        def work(*args):
            entered.set();release.wait(5)
            return SimpleNamespace(run_id='completed-first',experiment_id='first')
        with tempfile.TemporaryDirectory() as tmp,patch('quantlab.workbench.jobs.execute',side_effect=work) as execution:
            queue=JobQueue(tmp,tmp);first,second=str(uuid4()),str(uuid4())
            try:
                queue.submit(first,spec());self.assertTrue(entered.wait(5))
                queue.submit(second,spec());self.assertEqual(queue.cancel(second)['status'],'cancelled')
                cancelled=next(j for j in queue.list() if j['job_id']==second)
                self.assertEqual(cancelled['status'],'cancelled');self.assertIsNone(cancelled['started_at'])
                self.assertIsNotNone(cancelled['finished_at'])
            finally:release.set();queue.close()
            self.assertEqual(execution.call_count,1)
            self.assertEqual(next(j for j in queue.list() if j['job_id']==first)['status'],'completed')

    def test_cancel_reaches_real_checkpoint_and_does_not_call_next_job(self):
        entered=threading.Event();release=threading.Event()
        def work(*args):
            entered.set();release.wait(5);checkpoint('计算中',1,2)
            raise AssertionError('Cancellation must stop execution')
        with tempfile.TemporaryDirectory() as tmp,patch('quantlab.workbench.jobs.execute',side_effect=work):
            queue=JobQueue(tmp,tmp);identifier=str(uuid4())
            try:
                queue.submit(identifier,spec());self.assertTrue(entered.wait(5));self.assertEqual(queue.cancel(identifier)['status'],'cancel_requested');release.set()
            finally:release.set();queue.close()
            result=queue.list()[0];self.assertEqual(result['status'],'cancelled');self.assertIsNone(result['run_id'])
    def test_correlation_submission_and_expanding_windows(self):
        params={'inputs':{'a':{'factor_id':'BASE.MOMENTUM','parameters':{'lookback':2}},'b':{'factor_id':'BASE.MOMENTUM','parameters':{'lookback':3}}},'weights':{'a':1,'b':1}}
        submission=prepare(spec(mode='correlation',factor='COMB.SCORE',parameters=params))
        self.assertEqual(submission.correlation['min_symbols'],3)
        with self.assertRaises(ValueError):prepare(spec(mode='correlation'))
        request=DataRequest(('A',),Timeframe.DAILY,date(2020,1,1),date(2020,1,30))
        windows=WalkForwardConfig(10,5,5,expanding=True).windows(request)
        self.assertEqual([w['start'] for w in windows],[request.start]*3)
        self.assertEqual([w['train_end'].day for w in windows],[10,15,20])
        self.assertLess(windows[0]['end'],date.fromordinal(windows[1]['valid_end'].toordinal()+1))

if __name__=='__main__':unittest.main()

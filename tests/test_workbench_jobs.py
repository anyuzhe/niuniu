import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import test_core
from quantlab.workbench.jobs import JobQueue, prepare
from quantlab.workbench.server import make_server


def spec(**overrides):
    return {'question':'任务测试','symbols':['sh.600000','sh.600001','sh.600002'],
        'start':'2025-01-01','end':'2025-01-10','factor':'BASE.MOMENTUM',
        'parameters':{'lookback':2},'horizons':[1], **overrides}


class JobTests(unittest.TestCase):
    def test_validation_and_template_resolution(self):
        self.assertEqual(prepare(spec()).adjustment,'qfq')
        self.assertEqual(prepare(spec(adjustment='raw')).adjustment,'raw')
        self.assertEqual(prepare(spec()).config.parameters,{'lookback':2})
        template=spec(theory='RESEARCH.RECLAIM_CONFIRMATION')
        del template['factor'];del template['parameters']
        self.assertEqual(prepare(template).config.factor_id,'COMB.CONDITION')
        for changes in [{'parameters':{'lookback':0}}, {'symbols':['../../file']},
                {'start':'2025-02-01'}, {'mode':'holdout'}, {'mode':'walkforward'},
                {'mode':'ablation'}, {'grid':{'lookback':[2]}}, {'data_root':'/tmp'},
                {'mode':'sweep','grid':{'lookback':[2,2]}}, {'factor':'COMB.CONDITION','parameters':{},'processor':'cs_rank'},
                {'horizons':[1,1]}, {'sequence_audit':'true'}, {'question':''}]:
            with self.subTest(changes=changes),self.assertRaises((ValueError,TypeError)):
                prepare(spec(**changes))
        self.assertEqual(prepare(spec(regime_filter={'direction':'Bull'})).config.regime.lookback,20)

    def test_serial_idempotent_failure_and_restart(self):
        entered,release=threading.Event(),threading.Event()
        starts=[]
        def fake(submission,*args):
            starts.append(submission.config.research_question)
            if len(starts)==1:
                entered.set();release.wait(5)
                raise ValueError('expected failure')
            return SimpleNamespace(run_id=str(uuid4()),experiment_id='result')
        with tempfile.TemporaryDirectory() as directory,patch('quantlab.workbench.jobs.execute',side_effect=fake):
            queue=JobQueue(directory,directory)
            first,second=str(uuid4()),str(uuid4())
            try:
                queue.submit(first,spec(question='first'))
                self.assertTrue(entered.wait(5))
                queue.submit(second,spec(question='second'))
                queue.submit(second,spec(question='second'))
                self.assertEqual(starts,['first'])
                self.assertEqual({j['job_id']:j['status'] for j in queue.list()}[second],'queued')
                with self.assertRaises(ValueError):queue.submit(second,spec(question='changed'))
                with self.assertRaises(ValueError):JobQueue(directory,directory)
            finally:
                release.set();queue.close()
            self.assertEqual(starts,['first','second'])
            self.assertEqual({j['status'] for j in queue.list()},{'completed','failed'})
            path=Path(directory)/'_jobs'/f'{first}.json'
            record=json.loads(path.read_text());record['status']='running';path.write_text(json.dumps(record))
            restarted=JobQueue(directory,directory)
            try:
                self.assertEqual({j['job_id']:j['status'] for j in restarted.list()}[first],'interrupted')
                self.assertEqual(starts,['first','second'])
            finally:restarted.close()

    def test_http_to_real_research_all_modes(self):
        fixture=test_core.CoreTests();fixture.setUp()
        output=fixture.root/'artifacts';output.mkdir()
        server=make_server(output,0,fixture.root)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url=f'http://127.0.0.1:{server.server_port}'
        def call(path,payload=None,origin=url):
            headers={'Origin':origin,'Content-Type':'application/json'}
            request=Request(url+path,data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
            with urlopen(request,timeout=10) as response:return json.load(response)
        try:
            self.assertTrue(call('/api/settings')['execution_enabled'])
            self.assertEqual(call('/api/validate',spec())['config']['parameters'],{'lookback':2})
            self.assertFalse(list(output.glob('*/experiment.json')))
            for origin in ['', 'https://evil.test']:
                with self.assertRaises(HTTPError) as raised:call('/api/jobs',{'job_id':str(uuid4()),'spec':spec()},origin)
                self.assertEqual(raised.exception.code,403);raised.exception.close()
            with self.assertRaises(HTTPError) as raised:call('/api/validate',spec(parameters={'lookback':0}))
            self.assertEqual(raised.exception.code,400);raised.exception.close()
            requests=[spec(),spec(mode='holdout',split={'train_end':'2025-01-04','valid_end':'2025-01-07'}),
                spec(mode='walkforward',schedule={'train_days':4,'valid_days':2,'test_days':2}),
                spec(mode='sweep',grid={'lookback':[2,3]}),
                spec(mode='ablation',factor='COMB.SCORE',parameters={'inputs':{
                    'a':{'factor_id':'BASE.MOMENTUM','parameters':{'lookback':2}},
                    'b':{'factor_id':'BASE.DIRECTIONAL_EFFICIENCY','parameters':{'lookback':2}}},'weights':{'a':1,'b':1}}),
                spec(symbols=['sh.699999'])]
            ids=[]
            for config in requests:
                id=str(uuid4());ids.append(id);call('/api/jobs',{'job_id':id,'spec':config})
            deadline=time.monotonic()+30
            while any(j['status'] in {'queued','running'} for j in call('/api/jobs')['jobs']) and time.monotonic()<deadline:
                time.sleep(.05)
            for id in ids[:-1]:
                job=call('/api/jobs/'+id)
                self.assertEqual(job['status'],'completed',job)
                detail=call('/api/runs/'+job['run_id'])
                self.assertEqual(detail['record']['status'],'completed')
                self.assertIn('report.md',detail['files'])
            self.assertEqual(call('/api/jobs/'+ids[-1])['status'],'failed')
            self.assertEqual(call('/api/runs?status=failed')['total'],1)
            job=call('/api/jobs/'+ids[0])
            self.assertEqual(call('/api/jobs',{'job_id':ids[0],'spec':requests[0]})['run_id'],job['run_id'])
            rows=call('/api/runs/'+job['run_id']+'/observations')['rows']
            self.assertTrue(rows)
            self.assertTrue(any(row['value'] is not None for row in rows))
        finally:
            server.shutdown();server.server_close();thread.join();fixture.tearDown()

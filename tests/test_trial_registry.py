import json
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from quantlab.experiments.trial_registry import create_registry,bind_result,report_registry
from quantlab.storage.codec import encode


class TrialRegistryTests(unittest.TestCase):
    def plan(self):
        return {'name':'fixed family','alpha':.05,'trials':[{'trial_id':name,'config':{
            'factor_id':'BASE.MOMENTUM','research_question':name,'horizons':[1],
            'permutation':{'resamples':99,'block_days':1,'alpha':.05}}} for name in ('a','b','c')]}

    def artifact(self,root,trial,name='run',status='completed',p=.01):
        test={'method':'nonoverlapping_date_block_sign_v1','status':'computed','block_days':1,'p_value':p,'p_holm':0.}
        r={'run_id':name,'created_at':'2020-01-01T00:00:00+00:00','status':status,'manifest':{'config':trial['config']},
           'metrics':{'1':{'permutation':{'daily_mean_ic':test,'daily_mean_rank_ic':{**test,'p_value':.04}}}}}
        path=root/f'{name}.json';path.write_text(encode(r));return path

    def test_missing_failed_and_raw_p_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan=self.plan();reg=root/'registry';create_registry(plan,reg)
            a=self.artifact(root,plan['trials'][0]);bind_result(reg,'a',a)
            b=self.artifact(root,plan['trials'][1],'failed',status='failed');bind_result(reg,'b',b)
            result=report_registry(reg,root/'report')
            self.assertEqual((result['planned_tests'],result['available_tests']),(6,2))
            self.assertEqual([t['p_holm'] for t in result['tests']],[.06,.2,None,None,None,None])
            self.assertEqual([t['status'] for t in result['trials']],['completed','failed','not_run'])
            self.assertEqual(result['trials'][0]['timing'],'retrospective')
            a.unlink();b.unlink()
            repeat=report_registry(reg,root/'repeat')
            self.assertEqual(result['tests'],repeat['tests'])
            with self.assertRaises(FileExistsError):report_registry(reg,root/'report')

    def test_idempotence_mismatch_incomplete_and_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan=self.plan();reg=root/'registry';create_registry(plan,reg)
            path=self.artifact(root,plan['trials'][0]);bind_result(reg,'a',path)
            self.assertEqual(bind_result(reg,'a',path)['status'],'unchanged')
            alternative=self.artifact(root,plan['trials'][0],'other',p=.001)
            with self.assertRaisesRegex(ValueError,'already bound'):bind_result(reg,'a',alternative)
            with self.assertRaisesRegex(ValueError,'configuration'):bind_result(reg,'b',alternative)
            missing=self.artifact(root,plan['trials'][1],'missing');r=json.loads(missing.read_text())
            del r['metrics']['1']['permutation']['daily_mean_ic'];missing.write_text(encode(r))
            with self.assertRaisesRegex(ValueError,'every planned'):bind_result(reg,'b',missing)
            parent=self.artifact(root,plan['trials'][1],'parent');r=json.loads(parent.read_text());r['kind']='theory_study';parent.write_text(encode(r))
            with self.assertRaisesRegex(ValueError,'not parent'):bind_result(reg,'b',parent)
            binding=reg/'results/a.json';r=json.loads(binding.read_text());r['record']['status']='failed';binding.write_text(encode(r))
            with self.assertRaisesRegex(ValueError,'fingerprint'):report_registry(reg,root/'bad')

    def test_competing_bindings_publish_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan=self.plan();reg=root/'registry';create_registry(plan,reg)
            paths=[self.artifact(root,plan['trials'][0],f'run{i}',p=.01+i*.01) for i in range(2)]
            def attempt(p):
                try:return bind_result(reg,'a',p)['status']
                except ValueError:return 'rejected'
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,paths))
            self.assertEqual(sorted(results),['bound','rejected'])
            report=report_registry(reg,root/'report')
            self.assertIn(report['tests'][0]['p_value'],(.01,.02))
            self.assertEqual(len(list((reg/'results').iterdir())),1)

    def test_invalid_plan_and_unavailable_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for change in ('id','config','alpha'):
                plan=self.plan()
                if change=='id':plan['trials'][0]['trial_id']='../escape'
                if change=='config':plan['trials'][1]['config']=plan['trials'][0]['config']
                if change=='alpha':plan['alpha']=True
                with self.assertRaises(ValueError):create_registry(plan,root/change)
            plan=self.plan();reg=root/'registry';create_registry(plan,reg)
            p=self.artifact(root,plan['trials'][0]);r=json.loads(p.read_text())
            t=r['metrics']['1']['permutation']['daily_mean_ic'];t.update(status='unavailable',p_value=None,reason='insufficient_nonempty_blocks');p.write_text(encode(r))
            bind_result(reg,'a',p);report=report_registry(reg,root/'report')
            self.assertEqual(report['available_tests'],1)
            self.assertIsNone(report['tests'][0]['reject_holm'])

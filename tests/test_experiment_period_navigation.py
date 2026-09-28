"""Read-only parent navigation must survive large manifests without inventing evidence."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4
import hashlib,json
from quantlab.agent.catalog import ReadOnlyResearchAPI
from quantlab.agent.memory_evidence import EvidenceResolver
from quantlab.storage.codec import digest,encode


class ExperimentPeriodNavigationTests(TestCase):
    def setUp(self):
        t=TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.api=ReadOnlyResearchAPI(self.root)
    def record(self,kind='factor',**extra):
        rid=str(uuid4());manifest={'config':{'factor_id':'BASE.MOMENTUM','factor_version':'1.0.0','parameters':{'lookback':20}}}
        value={'run_id':rid,'experiment_id':digest(manifest),'manifest':manifest,'status':'completed','kind':kind,'created_at':'2026-09-28T00:00:00+00:00',**extra}
        folder=self.root/rid;folder.mkdir();(folder/'experiment.json').write_text(encode(value));return rid
    def test_parent_periods_guide_to_actual_child_values_without_paths(self):
        children=[]
        for name,v in (('train',-.02),('valid',None),('test',.03)):
            rid=self.record(metrics={'5':{'rank_ic':v}})
            children.append({'name':name,'run_id':rid,'start':'2023-01-01','end':'2023-12-31','artifact_path':'/private/not-for-model','metrics':{'invented_summary':123}})
        parent=self.record('holdout',periods=children)
        before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*.json')}
        result=self.api.call('get_experiment',{'run_id':parent})
        self.assertTrue(result['ok'],result);view=result['data'];self.assertEqual(view['periods_count'],3)
        self.assertTrue(view['periods_are_references_only']);self.assertEqual(view['periods_omitted'],0)
        self.assertNotIn('artifact_path',encode(result));self.assertNotIn('invented_summary',encode(result))
        for ref,expected in zip(view['periods'],[-.02,None,.03]):
            data=self.api.call('get_experiment',{'run_id':ref['run_id']})
            self.assertEqual(data['data']['metrics']['5']['rank_ic'],expected)
            self.assertEqual(EvidenceResolver(self.root).capture(ref['run_id'],'/metrics/5/rank_ic')['value'],expected)
        self.assertEqual(before,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*.json')})
    def test_large_provenance_does_not_remove_small_parent_navigation(self):
        child=self.record(metrics={'5':{'rank_ic':-.01}});rid=self.record('holdout',periods=[{'name':'test','run_id':child}])
        path=self.root/rid/'experiment.json';record=json.loads(path.read_text())
        record['manifest']['large_source_provenance']='x'*9_000_000;record['experiment_id']=digest(record['manifest']);path.write_text(encode(record))
        view=self.api.call('get_experiment',{'run_id':rid})
        self.assertTrue(view['ok'],view);self.assertEqual(view['data']['periods'][0]['run_id'],child)
        self.assertLess(len(encode(view)),24000);self.assertNotIn('large_source_provenance',encode(view))
    def test_truncated_period_list_is_explicit(self):
        rid=self.record('holdout',periods=[{'name':str(i),'run_id':str(uuid4())} for i in range(31)])
        result=self.api.call('get_experiment',{'run_id':rid});self.assertTrue(result['ok'],result)
        self.assertEqual(len(result['data']['periods']),30);self.assertEqual(result['data']['periods_count'],31)
        self.assertEqual(result['data']['periods_omitted'],1)
    def test_invalid_reference_does_not_fall_back_to_another_run(self):
        for value in ({},[{'name':'test'}],[{'name':'test','run_id':'../escape'}]):
            rid=self.record('holdout',periods=value)
            self.assertFalse(self.api.call('get_experiment',{'run_id':rid})['ok'])
    def test_oversized_metrics_keep_explicit_navigation_but_not_partial_numbers(self):
        child=self.record(metrics={'5':{'rank_ic':None}})
        rid=self.record('holdout',periods=[{'name':'test','run_id':child}],metrics={str(i):'x'*1500 for i in range(40)})
        result=self.api.call('get_experiment',{'run_id':rid});self.assertTrue(result['ok'],result)
        self.assertTrue(result['data']['omitted']);self.assertNotIn('metrics',result['data'])
        self.assertEqual(result['data']['periods'][0]['run_id'],child)
        self.assertLess(len(encode(result)),24000)
    def test_formal_headless_api_has_same_navigation_without_queue(self):
        from quantlab.agent.chat_runtime import ChatRuntime
        child=self.record(metrics={'5':{'rank_ic':None}});rid=self.record('holdout',periods=[{'name':'test','run_id':child}])
        runtime=ChatRuntime(self.root,self.root,lambda:self.fail('must not acquire queue'),local_data_only=True)
        result=runtime.api.call('get_experiment',{'run_id':rid});self.assertTrue(result['ok'],result)
        self.assertEqual(result['data']['periods'][0]['run_id'],child)
        self.assertFalse((self.root/'_jobs').exists())

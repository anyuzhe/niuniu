import json
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from test_context_experiments import ContextProvider, context_config, runner
from quantlab.agent.research_memory import ResearchMemory, payload
from quantlab.agent.memory_store import MemoryError
from quantlab.agent.memory_tools import ResearchMemoryAPI


def hypothesis(**changes):
    return {'title':'动量待验证假设','statement':'历史动量可能有预测信息，尚未验证。',
            'factor_id':'BASE.MOMENTUM','factor_version':'1.0.0','parameters':{'lookback':1},
            'mechanism':'价格延续只是待检验机制。','falsification':'若样本外与成本后表现不足则不采纳。',
            'supersedes':None,**changes}


def finding(hid, run_id, **changes):
    return {'hypothesis_id':hid,'title':'有限样本研究记录','statement':'保存本次指标，不推广为未来Alpha。',
            'assessment':'inconclusive','limitations':'合成夹具，仅做接口和来源测试。','next_action':'补实际样本。',
            'evidence':[{'run_id':run_id,'pointer':'/metrics/1/rank_ic','relation':'context'}],
            'supersedes':None,**changes}


class ResearchMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.memory = ResearchMemory(self.root)

    def source(self):
        return runner(ContextProvider(),self.root).run(replace(context_config(),context=None,replay=True))

    def save_hypothesis(self, **changes):
        return self.memory.save('hypothesis',str(uuid4()),hypothesis(**changes))['record']['memory_id']

    def test_empty_search_does_not_create_store(self):
        self.assertEqual(self.memory.store.search()['total'],0)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_hypothesis_idempotence_normalization_and_conflicts(self):
        request = str(uuid4()); spec = hypothesis(parameters={})
        a = self.memory.save('hypothesis',request,spec)
        b = self.memory.save('hypothesis',request,spec)
        self.assertEqual(a['record']['memory_id'],b['record']['memory_id'])
        self.assertEqual(a['record']['parameters'],{'lookback':20})
        self.assertFalse(a['claim_verified']); self.assertEqual(a['source_integrity'],'no_evidence')
        with self.assertRaisesRegex(MemoryError,'同一请求'):
            self.memory.save('hypothesis',request,{**spec,'statement':'不同的研究陈述'})
        with self.assertRaises(MemoryError): self.save_hypothesis(factor_id='NOT_REGISTERED')
        self.assertEqual(self.memory.store.search()['total'],1)

    def test_actual_values_and_source_context_are_read_from_archive(self):
        source = self.source(); hid = self.save_hypothesis()
        before = (source.artifact_path/'experiment.json').read_bytes()
        result = self.memory.save('finding',str(uuid4()),finding(hid,source.run_id))
        evidence = result['record']['evidence'][0]
        self.assertEqual(evidence['value'],source.metrics['1']['rank_ic'])
        self.assertEqual(evidence['context']['parameters'],{'lookback':1})
        self.assertEqual(evidence['context']['symbols'],['A','B','C'])
        self.assertEqual(result['source_integrity'],'verified')
        self.assertEqual(before,(source.artifact_path/'experiment.json').read_bytes())
        forged = finding(hid,source.run_id); forged['evidence'][0]['value'] = 999
        with self.assertRaisesRegex(MemoryError,'不得自行填数值'):
            self.memory.save('finding',str(uuid4()),forged)

    def test_changed_missing_source_does_not_rewrite_old_note(self):
        source = self.source(); hid = self.save_hypothesis(); request = str(uuid4())
        spec = finding(hid,source.run_id)
        result = self.memory.save('finding',request,spec); note = result['record']
        path = source.artifact_path/'experiment.json'; raw = json.loads(path.read_text())
        raw['metrics']['1']['rank_ic'] = 0.987; path.write_text(json.dumps(raw))
        changed = self.memory.get(note['memory_id'])
        self.assertEqual(changed['source_integrity'],'source_changed')
        self.assertEqual(changed['record']['evidence'],note['evidence'])
        self.assertEqual(self.memory.save('finding',request,spec)['record']['memory_id'],note['memory_id'])
        path.rename(path.with_suffix('.hidden'))
        self.assertEqual(self.memory.get(note['memory_id'])['source_integrity'],'unavailable')

    def test_failed_study_is_evidence_not_zero_return(self):
        engine = runner(ContextProvider(),self.root)
        with patch('quantlab.experiments.runner.compute_factor',side_effect=RuntimeError('fixture unavailable')):
            with self.assertRaises(RuntimeError): engine.run(replace(context_config(),context=None))
        path = next(self.root.glob('*/experiment.json')); hid = self.save_hypothesis()
        spec = finding(hid,path.parent.name,assessment='implementation_failure',
            evidence=[{'run_id':path.parent.name,'pointer':'/error','relation':'context'}])
        note = self.memory.save('finding',str(uuid4()),spec)
        self.assertIn('fixture unavailable',note['record']['evidence'][0]['value'])
        self.assertEqual(note['source_integrity'],'verified')
        with self.assertRaisesRegex(MemoryError,'有效数值'):
            self.memory.save('finding',str(uuid4()),{**spec,'assessment':'supported'})

    def test_revisions_preserve_history_and_reject_branches(self):
        old = self.save_hypothesis(); original = self.memory.get(old)['record']
        new = self.save_hypothesis(title='修订后的假设',supersedes=old)
        self.assertEqual(self.memory.get(old)['record']['superseded_by'],new)
        self.assertEqual(self.memory.get(old)['record']['statement'],original['statement'])
        self.assertEqual(self.memory.store.search()['total'],1)
        self.assertEqual(self.memory.store.search(include_superseded=True)['total'],2)
        with self.assertRaisesRegex(MemoryError,'后续修订'):
            self.save_hypothesis(title='错误分支',supersedes=old)
        with self.assertRaisesRegex(MemoryError,'其他类型'):
            self.save_hypothesis(parameters={'lookback':5},supersedes=new)
        self.assertEqual(self.memory.store.search(include_superseded=True)['total'],2)

    def test_concurrent_retries_and_unicode_literal_search(self):
        request = str(uuid4()); spec = hypothesis(title='中文反转假设')
        def write(_): return ResearchMemory(self.root).save('hypothesis',request,spec)['record']['memory_id']
        with ThreadPoolExecutor(max_workers=4) as pool: ids = list(pool.map(write,range(4)))
        self.assertEqual(len(set(ids)),1)
        self.assertEqual(self.memory.store.search(query='中文反转')['total'],1)
        self.assertEqual(self.memory.store.search(query="' OR 1=1 --")['total'],0)
        self.assertEqual(self.memory.store.search(factor_id='BASE.MOMENTUM')['total'],1)
        with self.assertRaises(MemoryError): self.memory.store.search(limit=True)
        with self.assertRaises(MemoryError): self.memory.store.search(offset=-1)

    def test_tampered_record_is_rejected(self):
        hid = self.save_hypothesis()
        db = sqlite3.connect(self.memory.store.path)
        try:
            db.execute('UPDATE memory_entries SET checksum=? WHERE id=?', ('invalid',hid)); db.commit()
        finally: db.close()
        with self.assertRaisesRegex(MemoryError,'校验失败'): self.memory.get(hid)

    def test_bad_pointer_uuid_nonfinite_and_unknown_fields(self):
        source = self.source(); resolver = self.memory.resolver
        for pointer in ('/fills','/manifest/runtime','/metrics/~2bad','/metrics/999/ic','not-a-pointer'):
            with self.assertRaises(MemoryError): resolver.capture(source.run_id,pointer)
        with self.assertRaises(MemoryError): resolver.capture('../outside','/status')
        for text in ('{"x":1,"x":2}','{"x":NaN}','{"x":1e309}','[]'):
            with self.assertRaises(MemoryError): payload(text)
        with self.assertRaises(MemoryError): self.save_hypothesis(extra='unexpected')

    def test_api_contracts_no_approval_or_numeric_fabrication(self):
        api = ResearchMemoryAPI(self.root)
        names = {s['name'] for s in api.schemas()}
        self.assertIn('record_hypothesis',names); self.assertNotIn('approve_experiment',names)
        self.assertFalse(api.call('approve_experiment',{})['ok'])
        self.assertFalse(api.call('record_hypothesis',{'request_id':str(uuid4())})['ok'])
        result = api.call('record_hypothesis',{'request_id':str(uuid4()),'hypothesis_json':json.dumps(hypothesis())})
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['evidence'][0]['kind'],'memory')
        self.assertTrue(api.call('get_capabilities',{})['data']['research_memory_available'])
        self.assertFalse(list(self.root.glob('_jobs/*.json')))

    def test_cross_conversation_tools_and_turn_retry_deduplication(self):
        from quantlab.agent.chat_runtime import ChatRuntime
        from quantlab.agent.model_config import ModelConfig
        calls = []
        class Writer:
            def run(self, system, messages, tools, dispatch, emit, stop):
                args = {'request_id':str(uuid4()),'hypothesis_json':json.dumps(hypothesis())}
                for n in range(2): calls.append(dispatch('record_hypothesis',args,str(n)))
                return {'text':'已保存假设，未执行研究。','model':'fixture','provider':'fixture'}
        runtime = ChatRuntime(self.root); cid = runtime.store.create('first')
        result = runtime.send(cid,'保存这个待验证假设',ModelConfig(),allow_send=True,provider=Writer())
        ids = [v['data']['record']['memory_id'] for v in calls]
        self.assertEqual(ids[0],ids[1]); self.assertEqual(result['tool_calls'],2)
        reopened = ChatRuntime(self.root); second = reopened.store.create('second')
        self.assertNotEqual(cid,second)
        saved = reopened.api.call('get_research_memory',{'memory_id':ids[0]})
        self.assertTrue(saved['ok'],saved)
        self.assertEqual(saved['data']['record']['title'],'动量待验证假设')
        self.assertEqual(reopened.api.memory.store.search()['total'],1)
        self.assertFalse(list(self.root.glob('_jobs/*.json')))

    def test_finding_revision_does_not_remove_opposing_evidence(self):
        a = self.source(); hid = self.save_hypothesis()
        first = self.memory.save('finding',str(uuid4()),finding(hid,a.run_id))['record']
        revision = finding(hid,a.run_id,supersedes=first['memory_id'],statement='修订解释，保留原结论。')
        revision['evidence'].append({'run_id':a.run_id,'pointer':'/metrics/3/rank_ic','relation':'contradicts'})
        second = self.memory.save('finding',str(uuid4()),revision)['record']
        self.assertEqual(self.memory.get(first['memory_id'])['record']['superseded_by'],second['memory_id'])
        self.assertEqual(self.memory.get(first['memory_id'])['record']['evidence'],first['evidence'])
        self.assertEqual(second['evidence'][1]['relation'],'contradicts')
        self.assertFalse(second['claim_verified'])

    def test_null_metrics_stay_unknown_and_cannot_support_a_claim(self):
        source=self.source(); hid=self.save_hypothesis(); path=source.artifact_path/'experiment.json'
        data=json.loads(path.read_text()); data['metrics']['1']['rank_ic']=None
        path.write_text(json.dumps(data))
        spec=finding(hid,source.run_id,assessment='unavailable')
        result=self.memory.save('finding',str(uuid4()),spec)
        self.assertIsNone(result['record']['evidence'][0]['value'])
        self.assertEqual(result['source_integrity'],'verified')
        with self.assertRaisesRegex(MemoryError,'有效数值'):
            self.memory.save('finding',str(uuid4()),{**spec,'assessment':'supported'})

    def test_workspace_isolation_and_symlink_guard(self):
        hid=self.save_hypothesis()
        with tempfile.TemporaryDirectory() as other:
            isolated=ResearchMemory(other)
            self.assertEqual(isolated.store.search()['total'],0)
            with self.assertRaises(MemoryError): isolated.get(hid)
            directory=Path(other)/'_assistant'; directory.mkdir()
            (directory/'research_memory.sqlite3').symlink_to(self.memory.store.path)
            with self.assertRaisesRegex(MemoryError,'符号链接'): isolated.store.search()
            with self.assertRaisesRegex(MemoryError,'符号链接'):
                isolated.save('hypothesis',str(uuid4()),hypothesis())

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from quantlab.agent.memory_projection import large_memory_view
from quantlab.agent.memory_tools import ResearchMemoryAPI
from quantlab.storage.codec import digest,encode

class MemoryProjectionTests(unittest.TestCase):
    def sample(self,status='verified',count=6):
        return {'record':{'memory_id':'12345678-1234-1234-1234-123456789abc','kind':'finding','hypothesis_id':'22345678-1234-1234-1234-123456789abc','title':'中文研究结论','statement':'方向不稳定，不能认证Alpha。','limitations':'已见小样本，无成本。','next_action':'另行冻结研究。','parameters':{'lookback':20},'evidence':[{'run_id':'32345678-1234-1234-1234-123456789abc','pointer':f'/metrics/{i}/rank_ic','relation':'context','value':-.01,'value_hash':digest(-.01),'source_sha256':'a'*64,'context':{'universe':{'members':['large'*100 for _ in range(20)]},'symbols':['A','B']}} for i in range(count)]},'source_integrity':status,'evidence_checks':[{'run_id':'32345678-1234-1234-1234-123456789abc','pointer':f'/metrics/{i}/rank_ic','status':status} for i in range(count)],'claim_verified':False,'finding_parent_id':'22345678-1234-1234-1234-123456789abc'}
    def test_full_text_and_small_numbers_preserved_no_input_mutation(self):
        data=self.sample();before=deepcopy(data);view=large_memory_view(data)
        self.assertEqual(data,before);self.assertLess(len(encode(view)),24000)
        for key in ('title','statement','limitations','next_action'):self.assertEqual(view['record'][key],data['record'][key])
        self.assertEqual(view['record']['evidence'][0]['value'],-.01)
        self.assertEqual(view['projection']['record_digest'],digest(data['record']))
        self.assertFalse(view['projection']['complete_record']);self.assertEqual(len(view['projection']['omitted_fields']),6)
    def test_large_values_and_parameters_are_explicitly_omitted(self):
        data=self.sample();data['record']['parameters']={'ast':'x'*3000};data['record']['evidence'][0]['value']=['x'*1000]
        view=large_memory_view(data);self.assertNotIn('parameters',view['record']);self.assertTrue(view['record']['evidence'][0]['value_omitted'])
        fields={v['pointer'] for v in view['projection']['omitted_fields']};self.assertIn('/record/parameters',fields);self.assertIn('/record/evidence/0/value',fields)
    def test_api_large_read_keeps_text_and_truthful_source_status(self):
        with tempfile.TemporaryDirectory() as root:
            api=ResearchMemoryAPI(root)
            for status in ('verified','source_changed','unavailable'):
                data=self.sample(status)
                with patch.object(api.memory,'get',return_value=data):result=api.call('get_research_memory',{'memory_id':data['record']['memory_id']})
                self.assertTrue(result['ok'],result);self.assertLessEqual(len(encode(result)),24000)
                self.assertEqual(result['data']['record']['statement'],data['record']['statement']);self.assertEqual(result['data']['source_integrity'],status)
                self.assertFalse(result['data']['claim_verified']);self.assertFalse(result['data']['projection']['complete_record'])
            self.assertEqual(list(Path(root).iterdir()),[])
    def test_normal_small_response_preserves_existing_contract(self):
        with tempfile.TemporaryDirectory() as root:
            api=ResearchMemoryAPI(root);data=self.sample(count=0)
            with patch.object(api.memory,'get',return_value=data):result=api.call('get_research_memory',{'memory_id':data['record']['memory_id']})
            self.assertTrue(result['ok']);self.assertNotIn('projection',result['data']);self.assertEqual(result['data']['record'],data['record'])
    def test_overlong_body_does_not_sneak_past_response_budget(self):
        with tempfile.TemporaryDirectory() as root:
            api=ResearchMemoryAPI(root);data=self.sample();data['record']['statement']='x'*25000
            with patch.object(api.memory,'get',return_value=data):result=api.call('get_research_memory',{'memory_id':data['record']['memory_id']})
            self.assertTrue(result['data']['omitted']);self.assertLess(len(encode(result)),24000)
    def test_scalar_zero_and_null_remain_distinct(self):
        data=self.sample();data['record']['evidence'][0]['value']=None;data['record']['evidence'][1]['value']=0
        view=large_memory_view(data);self.assertIsNone(view['record']['evidence'][0]['value']);self.assertEqual(view['record']['evidence'][1]['value'],0)
if __name__=='__main__':unittest.main()

"""Regression for the native model's misplaced holdout split; no real model/data."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json
from quantlab.agent.proposal_tools import ResearchProposalAPI
from quantlab.agent.chat_cli import headless_chat_runtime
from quantlab.agent.model_config import ModelConfig
from quantlab.workbench.jobs import prepare


class HoldoutToolContractTests(TestCase):
    def setUp(self):
        tmp=TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.out=self.root/'out';self.out.mkdir();self.data=self.root/'data';self.data.mkdir()
        self.api=ResearchProposalAPI(self.out,self.data)
        self.spec={'question':'fixed synthetic configuration only','symbols':['sh.600001','sz.000002','sz.000003'],
            'start':'2025-01-01','end':'2025-01-10','timeframe':'1d','adjustment':'raw','mode':'holdout',
            'factor':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':2},'horizons':[1],
            'quantiles':2,'qualification':'research_only','replay':True,
            'split':{'train_end':'2025-01-04','valid_end':'2025-01-07'}}
    def test_exposed_description_specifies_nested_split_and_no_execution(self):
        with headless_chat_runtime(self.out,self.data,local_data_only=True) as runtime:
            description=next(t['description'] for t in runtime.api.schemas() if t['name']=='preview_experiment')
        self.assertIn('split={"train_end":"YYYY-MM-DD","valid_end":"YYYY-MM-DD"}',description)
        self.assertIn('不能放在顶层',description);self.assertIn('不创建任务',description)
    def test_top_level_dates_fail_with_actionable_error_and_do_not_mutate_input(self):
        for fields in ({'train_end':'2025-01-04'},{'valid_end':'2025-01-07'},self.spec['split']):
            value={**self.spec,**fields};original=deepcopy(value)
            result=self.api.call('preview_experiment',{'spec_json':json.dumps(value)})
            self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'INVALID_ARGUMENT')
            self.assertIn('split={',result['error']['message']);self.assertIn('不能位于顶层',result['error']['message'])
            self.assertEqual(value,original);self.assertEqual(list(self.out.iterdir()),[])
    def test_correct_nested_split_preserves_dates_and_uses_no_data_or_queue(self):
        before=deepcopy(self.spec)
        with patch('quantlab.data.mqc.MQCParquetProvider.load',side_effect=AssertionError('no data read')):
            result=self.api.call('preview_experiment',{'spec_json':json.dumps(self.spec)})
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['data']['estimate']['leaf_studies'],3)
        self.assertEqual(self.spec,before);self.assertEqual(list(self.out.iterdir()),[])
        study=prepare(self.spec)
        self.assertEqual(study.split.train_end.isoformat(),'2025-01-04')
        self.assertEqual(study.split.valid_end.isoformat(),'2025-01-07')
    def test_date_order_and_extra_fields_remain_invalid(self):
        for split in ({'train_end':'2025-01-08','valid_end':'2025-01-07'},
                      {'train_end':'2025-01-04','valid_end':'2025-01-10'},
                      {'train_end':'2025-01-04','valid_end':'2025-01-07','unexpected':'2025-01-08'}):
            result=self.api.call('preview_experiment',{'spec_json':json.dumps({**self.spec,'split':split})})
            self.assertFalse(result['ok'],result)
        self.assertEqual(list(self.out.iterdir()),[])
    def test_factor_version_and_parameters_contract_is_not_relaxed(self):
        bad={**self.spec,'factor_version':'1.0.0'};bad.pop('version')
        result=self.api.call('preview_experiment',{'spec_json':json.dumps(bad)})
        self.assertFalse(result['ok']);self.assertIn('factor/version',result['error']['message'])
        bad={**self.spec,'parameters':{'lookback':2,**self.spec['split']}}
        self.assertFalse(self.api.call('preview_experiment',{'spec_json':json.dumps(bad)})['ok'])
    def test_native_runtime_can_correct_structure_without_running_research(self):
        spec=deepcopy(self.spec)
        class Provider:
            def run(inner,system,messages,tools,dispatch,emit,stop):
                bad=deepcopy(spec);bad.update(bad.pop('split'))
                error=dispatch('preview_experiment',{'spec_json':json.dumps(bad)},'bad')
                inner.error=error
                inner.correct=dispatch('preview_experiment',{'spec_json':json.dumps(spec)},'correct')
                return {'text':'配置结构已修正，仅预检，无研究执行。','model':'fixture','provider':'fixture','usage':{}}
        provider=Provider()
        with headless_chat_runtime(self.out,self.data,local_data_only=True) as runtime:
            result=runtime.send(runtime.store.create(),'预检固定配置',ModelConfig(),allow_send=True,provider=provider)
        self.assertEqual(result['tool_calls'],2)
        self.assertFalse(provider.error['ok']);self.assertTrue(provider.correct['ok'])
        self.assertFalse((self.out/'_jobs').exists());self.assertFalse(list(self.out.glob('*/experiment.json')))

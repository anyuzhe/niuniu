from copy import deepcopy
from uuid import uuid4
import unittest
import polars as pl
import test_core
from quantlab.app import build_runner,default_registry
from quantlab.experiments.config import ExperimentConfig
from quantlab.factors.engine import compute_factor
from quantlab.agent.dsl_candidates import DslCandidateService
from quantlab.agent.market_data_tools import MarketDataResearchAPI
from quantlab.workbench.jobs import prepare,execute
from quantlab.storage.bundle import reproduce_artifact


def sample_ast():
    return {'op':'div','left':{'op':'delta','arg':{'op':'field','name':'close'},'bars':2},
        'right':{'op':'rolling_mean','arg':{'op':'field','name':'close'},'window':3}}


class RestrictedDslTests(unittest.TestCase):
    def setUp(self):
        self.fx=test_core.CoreTests();self.fx.setUp();self.addCleanup(self.fx.tearDown)
        self.output=self.fx.root/'dsl-runs';self.output.mkdir()
        self.factor=default_registry().get('DSL.RESTRICTED','1.0.0')
    def source(self,replay=True):
        cfg=ExperimentConfig('DSL validation source',self.fx.request,'BASE.MOMENTUM',parameters={'lookback':2},horizons=(1,),replay=replay)
        return build_runner(self.fx.root,self.output,self.fx.symbols).run(cfg)
    def test_ast_whitelist_and_temporal_limits(self):
        params=self.factor.parameters({'ast':sample_ast()});self.assertEqual(params['ast'],sample_ast())
        bars=self.fx.provider.load(self.fx.request).bars
        values=compute_factor(self.factor,bars,params);self.assertEqual(values.height,bars.height)
        self.assertEqual(values['value'].null_count(),10)
        bad=[{'op':'eval','code':'__import__("os")'},
            {'op':'lag','arg':{'op':'field','name':'close'},'bars':-1},
            {'op':'rolling_mean','arg':{'op':'field','name':'close'},'window':253},
            {'op':'field','name':'secret'},
            {'op':'add','left':{'op':'field','name':'close'},'right':{'op':'const','value':float('inf')}}]
        for ast in bad:
            with self.assertRaises(ValueError):self.factor.parameters({'ast':ast})
        nested={'op':'lag','bars':1,'arg':{'op':'rolling_mean','window':3,'arg':{'op':'field','name':'close'}}}
        with self.assertRaisesRegex(ValueError,'不允许时序窗口嵌套'):self.factor.parameters({'ast':nested})
    def test_node_and_depth_budgets(self):
        node={'op':'field','name':'close'}
        for _ in range(14):node={'op':'abs','arg':node}
        with self.assertRaises(ValueError):self.factor.parameters({'ast':node})
        wide={'op':'field','name':'close'}
        for _ in range(65):wide={'op':'add','left':wide,'right':{'op':'const','value':1}}
        with self.assertRaises(ValueError):self.factor.parameters({'ast':wide})
    def test_original_queue_and_frozen_reproduction(self):
        spec={'question':'restricted DSL research','symbols':list(self.fx.symbols),'start':str(self.fx.start),'end':str(self.fx.end),
            'factor':'DSL.RESTRICTED','parameters':{'ast':sample_ast()},'horizons':[1],'quantiles':3,'replay':True}
        result=execute(prepare(spec),self.fx.root,self.output)
        import json
        self.assertEqual(json.loads((result.artifact_path/'experiment.json').read_text())['status'],'completed')
        self.assertEqual(reproduce_artifact(result.artifact_path,self.fx.root/'dsl-replay')['status'],'numerically_matched')
    def test_candidate_preview_propose_register_and_source_change_block(self):
        source=self.source();service=DslCandidateService(self.output);ast=sample_ast()
        preview=service.preview('DSL候选',ast,source.run_id)
        self.assertTrue(preview['validation']['prefix_invariant']);self.assertFalse(preview['validation']['labels_used'])
        self.assertFalse((self.output/'_jobs').exists())
        request=str(uuid4());proposal=service.propose(request,'DSL候选',ast,source.run_id)
        with self.assertRaises(ValueError):service.register(request,proposal['plan_digest'])
        registered=service.register(request,proposal['plan_digest'],confirmed=True)
        self.assertEqual(registered['candidate_id'],preview['candidate_id'])
        self.assertEqual(service.register(request,proposal['plan_digest'],confirmed=True)['candidate_id'],preview['candidate_id'])
        path=source.artifact_path/'bars.parquet';frame=pl.read_parquet(path);frame.with_columns((pl.col('close')+1).alias('close')).write_parquet(path)
        request2=str(uuid4());proposal2=service.propose(request2,'DSL候选2',ast,source.run_id)
        pl.read_parquet(path).with_columns((pl.col('close')+1).alias('close')).write_parquet(path)
        with self.assertRaisesRegex(ValueError,'变化'):service.register(request2,proposal2['plan_digest'],confirmed=True)
    def test_agent_can_propose_but_not_register(self):
        source=self.source();api=MarketDataResearchAPI(self.output,self.fx.root)
        import json
        args={'name':'Agent DSL','ast_json':json.dumps(sample_ast()),'source_run_id':source.run_id}
        preview=api.call('preview_dsl_candidate',args);self.assertTrue(preview['ok'],preview)
        request=str(uuid4());proposal=api.call('propose_dsl_candidate',{'request_id':request,**args})
        self.assertTrue(proposal['ok'],proposal)
        self.assertFalse(api.call('register_dsl_candidate',{})['ok'])
        self.assertEqual(DslCandidateService(self.output).pending()['proposals'][0]['status'],'pending')
        self.assertFalse((self.output/'_jobs').exists())
    def test_non_replay_source_and_missing_fields_rejected(self):
        source=self.source(replay=False);service=DslCandidateService(self.output)
        with self.assertRaises(FileNotFoundError):service.preview('no bars',sample_ast(),source.run_id)
        bars=self.fx.provider.load(self.fx.request).bars.drop('turnover')
        ast={'op':'rolling_mean','arg':{'op':'field','name':'turnover'},'window':3}
        with self.assertRaisesRegex(ValueError,'缺少行情字段'):compute_factor(self.factor,bars,{'ast':ast})

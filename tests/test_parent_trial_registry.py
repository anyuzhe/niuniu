import copy
import json
import tempfile
import unittest
from pathlib import Path
from quantlab.app import default_registry
from quantlab.theory.templates import resolve_template
from quantlab.experiments.trial_registry import create_registry,bind_result,report_registry
from quantlab.experiments.trial_layout import hypotheses,COLLECTIONS
from quantlab.storage.codec import encode


class ParentTrialRegistryTests(unittest.TestCase):
    def trial(self,kind='ablation'):
        params,_=resolve_template('RESEARCH.TREND_BREAKOUT',default_registry())
        cfg={'research_question':'parent','factor_id':'COMB.CONDITION','factor_version':'1.0.0','parameters':params,
            'horizons':[1],'permutation':{'resamples':99,'block_days':1,'alpha':.05},'incremental_test':kind=='ablation',
            'data':{'symbols':['A'],'timeframe':'1d','start':'2025-01-01','end':'2025-02-01'}}
        design={'ablation':{},'holdout':{'split':{'train_end':'2025-01-10','valid_end':'2025-01-20'}},
            'walkforward':{'schedule':{'train_days':10,'valid_days':5,'test_days':10}},
            'sweep':{'grid':{'parameters':{'lookback':[5,10]}},'split':{'train_end':'2025-01-10','valid_end':'2025-01-20'},'schedule':None}}[kind]
        if kind=='sweep':cfg.update(factor_id='BASE.MOMENTUM',parameters={'lookback':5})
        return {'trial_id':'parent','config':cfg,'study':{'kind':kind,'design':design}}

    def artifact(self,root,trial):
        def fill(node,path):
            out={k:v for k,v in node.items() if k not in COLLECTIONS and k!='_metrics'}
            out['run_id']=path
            if '_metrics' in node:
                suffix='_difference' if node['_metrics']=='paired' else ''
                raw={'method':'nonoverlapping_date_block_sign_v1','status':'computed','block_days':1,'p_value':.01,'p_holm':0.}
                out['metrics']={'1':{'permutation':{m+suffix:raw for m in ('daily_mean_ic','daily_mean_rank_ic')}}}
            for key in COLLECTIONS:
                if key in node:out[key]=[fill(v,f'{path}-{key}-{i}') for i,v in enumerate(node[key])]
            return out
        record=fill(trial['layout'],'root')
        record.update(created_at='2025-01-01T00:00:00+00:00',status='completed',kind=trial['study']['kind'],
            manifest={'config':trial['config'],**trial['study']['design']})
        path=root/'parent.json';path.write_text(encode(record));return path,record

    def test_generated_layouts_and_full_raw_family(self):
        for kind,count in [('ablation',10),('holdout',6),('walkforward',6),('sweep',12)]:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);reg=root/'registry'
                registry=create_registry({'name':'family','alpha':.05,'trials':[self.trial(kind)]},reg)
                trial=registry['plan']['trials'][0]
                self.assertEqual(len(hypotheses(trial)),count)
                path,record=self.artifact(root,trial)
                # Child order is not identity: aliases/parameters/phases are.
                if 'children' in record:record['children'].reverse();path.write_text(encode(record))
                bind_result(reg,'parent',path);r=report_registry(reg,root/'report')
                self.assertEqual(r['planned_tests'],count)
                self.assertEqual(r['available_tests'],count)
                self.assertTrue(all(t['p_holm']==.01*count for t in r['tests']))
                if kind=='ablation':self.assertEqual(sum(t['metric'].endswith('_difference') for t in r['tests']),4)

    def test_design_missing_duplicate_and_extra_nodes_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);reg=root/'registry'
            registry=create_registry({'name':'family','alpha':.05,'trials':[self.trial('sweep')]},reg)
            path,record=self.artifact(root,registry['plan']['trials'][0])
            for change in ('design','missing','duplicate','extra','metrics'):
                r=copy.deepcopy(record)
                if change=='design':r['manifest']['grid']['parameters']['lookback']=[3,10]
                elif change=='missing':r['children'].pop()
                elif change=='duplicate':r['children'][1]=r['children'][0]
                elif change=='extra':r['contrasts']=[{}]
                else:del r['children'][0]['evaluations'][0]['metrics']['1']['permutation']['daily_mean_ic']
                path.write_text(encode(r))
                with self.assertRaises(ValueError):bind_result(reg,'parent',path)

    def test_partial_failure_preserves_observed_and_reserves_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);reg=root/'registry';trial=self.trial()
            unrun=copy.deepcopy(trial);unrun['trial_id']='unrun';unrun['config']['research_question']='reserved'
            registry=create_registry({'name':'family','alpha':.05,'trials':[trial,unrun]},reg)
            path,record=self.artifact(root,registry['plan']['trials'][0])
            record.update(status='failed',error='intentional interruption',children=record['children'][:1],contrasts=[])
            path.write_text(encode(record));bind_result(reg,'parent',path)
            r=report_registry(reg,root/'report')
            self.assertEqual((r['planned_tests'],r['available_tests']),(20,2))
            self.assertEqual([t['p_holm'] for t in r['tests'][:2]],[.2,.2])
            self.assertEqual(sum(t['status']=='failed' for t in r['tests']),8)
            self.assertEqual(sum(t['status']=='not_run' for t in r['tests']),10)

    def test_descendant_double_registration_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);reg=root/'registry';first=self.trial('holdout');second=copy.deepcopy(first)
            second['trial_id']='second';second['config']['research_question']='another'
            registry=create_registry({'name':'family','alpha':.05,'trials':[first,second]},reg)
            for i,trial in enumerate(registry['plan']['trials']):
                path,r=self.artifact(root,trial);r['run_id']=f'parent{i}';path.write_text(encode(r));bind_result(reg,trial['trial_id'],path)
            with self.assertRaisesRegex(ValueError,'descendant'):report_registry(reg,root/'bad')

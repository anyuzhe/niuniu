"""No network/model: exact source binding, no substitutions, component and data diagnostics."""
import copy,json,tempfile,unittest
from datetime import date,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import polars as pl
from quantlab.agent.research_specs import ResearchSpecStore,GROUPS,pair_audit
from quantlab.agent.research_spec_tools import ResearchSpecAPI
from quantlab.agent.spec_test_service import SpecTestService
from quantlab.trading import qm50_contract as q

CONFIG = {'model_id': 'QM50-SCLA', 'schema_version': '0.2', 'weights': {'S': {'S01': 0.55, 'S02': 0.25, 'S03': 0.2}, 'A_auction': {'A01': 1.0}, 'A_intraday': {'A01': 0.2, 'A02': 0.25, 'A03': 0.15, 'A04': 0.15, 'A05': 0.15, 'A06': 0.1}, 'Lpre': {'LP01': 0.3, 'LP02': 0.25, 'LP03': 0.2, 'LP04': 0.15, 'LP05': 0.1}, 'Lreal': {'LR01': 0.25, 'LR02': 0.25, 'LR03': 0.25, 'LR04': 0.25}, 'C': {'C01': 0.4, 'C02': 0.3, 'C03': 0.3}, 'Tbase': {'T02': 0.25, 'T03': 0.25, 'T04': 0.25, 'T05': 0.25}, 'N': {'N01': 0.2, 'N02': 0.2, 'N03_reversed': 0.2, 'N04_reversed': 0.2, 'N05_reversed': 0.2}, 'D': {'D01_reversed': 0.3, 'D02_reversed': 0.25, 'D04': 0.2, 'D05': 0.25}}, 'research_thresholds': {'q_min': 75, 'top1_gap_min': 8, 'market_N_min': 40, 'stronger_prev_strength_min': 70, 'stronger_S_min': 65, 'stronger_A_min': 70, 'weak_to_strong_prev_strength_max': 50, 'weak_to_strong_S_min': 80, 'weak_to_strong_A_min': 70, 'reseal_D_min': 70, 'reseal_seconds_max': 300, 'reseal_drawdown_max': 0.03, 'reseal_amount_ratio_min': 0.5, 'buy_trigger_distance_ticks': 1, 'hold_continue_min': 70, 'hold_exit_below': 50, 'hold_exit_confirmations': 2, 'hold_exit_snapshot_spacing_seconds': 60, 'order_participation_max': 0.01, 'max_concurrent_positions': 1, 'max_new_position_entries_per_day': 1, 'entry_notional_budget': None, 'cost_budget_bps': None, 'candidate_critical_coverage_required': 1.0}, 'factors': [{'id': 'P01'}, {'id': 'P02'}, {'id': 'P03'}, {'id': 'P04'}, {'id': 'P05'}, {'id': 'P06'}, {'id': 'P07'}, {'id': 'P08'}, {'id': 'P09'}, {'id': 'S01'}, {'id': 'S02'}, {'id': 'S03'}, {'id': 'S04'}, {'id': 'S05'}, {'id': 'A01'}, {'id': 'A02'}, {'id': 'A03'}, {'id': 'A04'}, {'id': 'A05'}, {'id': 'A06'}, {'id': 'LP01'}, {'id': 'LP02'}, {'id': 'LP03'}, {'id': 'LP04'}, {'id': 'LP05'}, {'id': 'LR01'}, {'id': 'LR02'}, {'id': 'LR03'}, {'id': 'LR04'}, {'id': 'C01'}, {'id': 'C02'}, {'id': 'C03'}, {'id': 'C04'}, {'id': 'T01'}, {'id': 'T02'}, {'id': 'T03'}, {'id': 'T04'}, {'id': 'T05'}, {'id': 'T06'}, {'id': 'N01'}, {'id': 'N02'}, {'id': 'N03'}, {'id': 'N04'}, {'id': 'N05'}, {'id': 'N06'}, {'id': 'E01'}, {'id': 'E02'}, {'id': 'E03'}, {'id': 'E04'}, {'id': 'E05'}, {'id': 'E06'}, {'id': 'D01'}, {'id': 'D02'}, {'id': 'D03'}, {'id': 'D04'}, {'id': 'D05'}, {'id': 'H01'}, {'id': 'H02'}, {'id': 'H03'}, {'id': 'H04'}]}

def synthetic_pair(folder):
    spec=copy.deepcopy(CONFIG);factors=[];sections=[]
    for group,count in GROUPS.items():
        for i in range(1,count+1):
            fid=f'{group}{i:02d}';f={'id':fid,'key':fid.lower(),'name':'fixture '+fid,'group':group,
                'definition':'fixture definition','earliest_available':'after input','proposed_direction':'none',
                'baseline_use':'fixture','implementation_notes':'not a live factor','required_data':['daily_bars'],'score_transform':'fixture'}
            factors.append(f)
            sections.append(f"#### {fid} · {f['name']}\n字段：`{f['key']}`\n定义：{f['definition']}\n最早可用：{f['earliest_available']}\n拟定方向：{f['proposed_direction']}\n用途：{f['baseline_use']}\n数据：`daily_bars`\n注意：{f['implementation_notes']}\n")
    spec['factors']=factors;spec['group_counts']=GROUPS
    md=folder/'source.md';js=folder/'source.json'
    md.write_text('# Fixture\n## 3. Fields\n'+'\n'.join(sections)+'\n## 4. Rules\nSynthetic only.\n')
    js.write_text(json.dumps(spec,ensure_ascii=False));return md,js

class ResearchSpecTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.output=self.root/'out';self.output.mkdir()
        self.md,self.js=synthetic_pair(self.root);self.store=ResearchSpecStore(self.output)
        self.manifest=self.store.import_pair(self.md,self.js,confirmed=True);self.sid=self.manifest['spec_id']
    def test_pair_covers_all60_and_original_bytes_immutable(self):
        self.assertEqual(len(self.manifest['consistency']['factors']),60)
        self.assertTrue(self.manifest['consistency']['matched'])
        self.assertEqual((self.store.folder(self.sid)/'spec.md').read_bytes(),self.md.read_bytes())
        self.assertEqual(self.store.import_pair(self.md,self.js,confirmed=True)['spec_id'],self.sid)
    def test_pair_different_definition_and_duplicate_id_rejected(self):
        spec=json.loads(self.js.read_text());spec['factors'][0]['definition']='changed'
        self.assertFalse(pair_audit(self.md.read_text(),spec)['matched'])
        spec['factors'][1]['id']=spec['factors'][0]['id']
        self.assertFalse(pair_audit(self.md.read_text(),spec)['matched'])
    def test_source_tamper_and_symlink_rejected(self):
        path=self.store.folder(self.sid)/'dictionary.json';path.write_text('{}')
        with self.assertRaises(ValueError):self.store.get(self.sid)
        link=self.root/'link.md';link.symlink_to(self.md)
        with self.assertRaises(ValueError):self.store.import_pair(link,self.js,confirmed=True)
    def test_import_requires_host_confirmation_and_no_path_tool(self):
        with self.assertRaises(ValueError):self.store.import_pair(self.md,self.js)
        api=ResearchSpecAPI(SimpleNamespace(schemas=lambda:[]),self.output,active_spec=self.sid)
        names={t['name'] for t in api.schemas()}
        self.assertNotIn('run_research_spec_test',names);self.assertNotIn('import_research_spec',names)
        result=api.call('read_research_spec',{'spec_id':self.sid,'section':'../../secret'})
        self.assertFalse(result['ok'])
    def test_exact_revision_required_despite_matching_model_id(self):
        service=SpecTestService(self.output)
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED_SPEC_REVISION'):
            service.run(self.sid,{'spec_id':self.sid,'kind':'CONTRACT_GUARDS','symbols':'','start':'','end':''})
    def test_all_11_groups_read_without_truncation(self):
        ids=[]
        for group in GROUPS:
            packet,refs=self.store.read(self.sid,group)
            ids.extend(f['id'] for f in packet['factors']);self.assertEqual(len(refs),2)
            self.assertTrue(all(c['start_line']<=c['end_line'] for c in packet['source_chunks']))
        self.assertEqual(len(set(ids)),60)
        global_packet,_=self.store.read(self.sid,'global');self.assertEqual(len(global_packet['source_chunks']),2)
    def test_strict_task_blocks_generic_substitutions_and_wrong_spec(self):
        inner=SimpleNamespace(schemas=lambda:[{'name':'submit_granted_experiment'},{'name':'search_factors'}],call=lambda *a:self.fail('forbidden dispatch'))
        api=ResearchSpecAPI(inner,self.output,active_spec=self.sid,allow_tests=True)
        self.assertNotIn('submit_granted_experiment',{t['name'] for t in api.schemas()})
        self.assertEqual(api.call('submit_granted_experiment',{})['error']['code'],'SPEC_SUBSTITUTION_REJECTED')
        self.assertFalse(api.call('read_research_spec',{'spec_id':'0'*64,'section':'global'})['ok'])
    def test_fixed_test_budget_has_no_arbitrary_shell(self):
        api=ResearchSpecAPI(SimpleNamespace(schemas=lambda:[]),self.output,active_spec=self.sid,allow_tests=True)
        args={'spec_id':self.sid,'kind':'CONTRACT_GUARDS','symbols':'','start':'','end':''}
        with patch.object(SpecTestService,'run',return_value={'status':'fixture'}):
            for _ in range(3):self.assertTrue(api.call('run_research_spec_test',args)['ok'])
            self.assertEqual(api.call('run_research_spec_test',args)['error']['code'],'SPEC_TEST_BUDGET')
    def test_audit_preserves_all60_blocked_without_strategy_claim(self):
        result=SpecTestService(self.output).audit(self.sid)
        self.assertEqual(len(result['factors']),60);self.assertIsNone(result['core_score_Q']);self.assertFalse(result['alpha_verified'])
        self.assertEqual(result['full_backtest_status'],'BLOCKED')
    def test_34_component_cases_and_mutated_threshold_caught(self):
        result=q.contract_checks(CONFIG)
        self.assertEqual(result['failed'],0,result)
        self.assertGreaterEqual(result['passed'],34)
        bad=copy.deepcopy(CONFIG);bad['research_thresholds']['reseal_seconds_max']=299
        self.assertGreater(q.contract_checks(bad)['failed'],0)
    def test_p07_off_by_one_and_no_imputation(self):
        self.assertEqual(q.previous_relative_amount(420.,list(range(1,21)))['value'],40.)
        self.assertIsNone(q.previous_relative_amount(420.,[None]+[1.]*19)['value'])
        self.assertEqual(q.previous_relative_amount(420.,[1.]*19)['status'],'INSUFFICIENT_HISTORY')
    def test_lookahead_missing_and_tied_leader_fail_closed(self):
        at=lambda x:'2024-01-02T'+x+'+08:00'
        self.assertFalse(q.observable(at('10:00:00'),at('09:59:59'),at('10:01:00')))
        self.assertEqual(q.known_lead(None,None,at('10:00:00'),feed_complete=False)['status'],'MISSING_SOURCE')
        self.assertEqual(q.choose_target({'a':80.,'b':80.},complete=True,thresholds=CONFIG['research_thresholds'])['reason'],'NO_UNIQUE_LEADER')
        with self.assertRaises(ValueError):q.timestamp('2024-01-02T09:30:00')
    def test_missing_score_propagates_without_reweighting(self):
        scores={f['id']:80. for f in CONFIG['factors']};scores['A04']=None
        full=q.components(CONFIG,scores,'INTRADAY',3)
        self.assertIsNone(full['A']);self.assertIsNone(full['B']);self.assertIsNone(full['Q'])
        self.assertEqual(q.components(CONFIG,scores,'INTRADAY',1)['A'],80.)
    def test_raw_diagnostic_correct_calendar_formula_and_no_backtest(self):
        from quantlab.agent.spec_p07_diagnostic import diagnose
        data=self.root/'data';folder=data/'lake/bronze/provider=baostock'
        (folder/'trade_calendar').mkdir(parents=True);(folder/'stock_kline_daily').mkdir()
        days=[date(2024,1,1)+timedelta(days=i) for i in range(40)]
        pl.DataFrame({'calendar_date':[d.isoformat() for d in days],'is_trading_day':['1']*40}).write_parquet(folder/'trade_calendar/calendar.parquet')
        raw=pl.DataFrame({'date':days,'code':['sh.600000']*40,'volume':[100]*40,'amount':[float(i+1) for i in range(40)],'fetch_ts':['2026-01-01T00:00:00']*40})
        path=folder/'stock_kline_daily/sh_600000.parquet';raw.write_parquet(path);before=path.read_bytes()
        frame,meta=diagnose(data,'sh.600000',days[21].isoformat(),days[22].isoformat())
        self.assertAlmostEqual(frame['raw_formula_value'][0],21/10.5)
        self.assertIsNone(frame['historical_decision_value'][0]);self.assertFalse(meta['core_Q_generated'])
        self.assertEqual(path.read_bytes(),before)
        raw.with_columns(pl.when(pl.col('date')==days[5]).then(None).otherwise(pl.col('amount')).alias('amount')).write_parquet(path)
        frame,_=diagnose(data,'sh.600000',days[21].isoformat(),days[21].isoformat())
        self.assertIsNone(frame['raw_formula_value'][0])
        with self.assertRaises(ValueError):diagnose(data,'sh.688001',days[21].isoformat(),days[22].isoformat())

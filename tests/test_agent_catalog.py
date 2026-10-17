import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
import numpy as np
from test_context_experiments import ContextProvider, context_config, runner
from quantlab.agent.catalog import ReadOnlyResearchAPI, compact
from quantlab.dipbuy import tracker
from quantlab.dipbuy.engine import DipConfig, latest_signal


EXPECTED_TOOLS = {'get_capabilities','search_factors','describe_factor','list_research_templates',
    'get_research_template','get_strategy_package_contract','preview_strategy_package',
    'list_strategy_runs','get_strategy_run','compare_strategy_runs','list_experiments',
    'get_experiment','get_job','get_proposal_progress','get_run_research_links','compare_factor_candidates',
    'audit_factor_risk',
    'list_forward_records','get_forward_record','get_forward_summary','preview_backtest','preview_factor_combination','get_full_evidence','list_research_specs','read_research_spec'}


class AgentCatalogTests(unittest.TestCase):
    def source(self, root):
        result = runner(ContextProvider(), root).run(replace(context_config(), context=None, replay=True))
        return result, ReadOnlyResearchAPI(root)

    def test_real_registry_and_typed_read_only_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = ReadOnlyResearchAPI(tmp)
            self.assertEqual({t['name'] for t in api.schemas()}, EXPECTED_TOOLS)
            self.assertEqual(len(api.schemas()),len(EXPECTED_TOOLS))
            caps = api.call('get_capabilities', {})
            self.assertEqual(caps['data']['access'], 'read_only')
            self.assertFalse(caps['data']['model_connected'])
            found = api.call('search_factors', {'query':'MOMENTUM','offset':0,'limit':5})
            self.assertTrue(found['ok']); self.assertGreater(found['data']['total'], 0)
            item = api.call('describe_factor', {'factor_id':'BASE.MOMENTUM','version':'1.0.0'})
            self.assertTrue(item['ok']); self.assertIn('lookback', item['data']['defaults'])
            self.assertEqual(list(Path(tmp).iterdir()), [])
            schemas = api.schemas(); schemas.clear(); self.assertEqual(len(api.schemas()), len(EXPECTED_TOOLS))

    def test_rejects_writes_invalid_fields_and_oversized_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = ReadOnlyResearchAPI(tmp)
            bad = [('submit_experiment', {}), ('approve', {}), ('get_capabilities', {'extra':1}),
                   ('search_factors', {'query':'','offset':False,'limit':5}),
                   ('search_factors', {'query':'','offset':0,'limit':1000}),
                   ('get_experiment', {'run_id':'../../elsewhere'}), ('get_job', {'job_id':'../../elsewhere'})]
            for name, arguments in bad:
                with self.subTest(name=name, args=arguments):
                    result = api.call(name, arguments); self.assertFalse(result['ok']); self.assertEqual(result['evidence'], [])
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_saved_results_are_referenced_and_remain_unchanged(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); result, api = self.source(root)
            def hashes():
                return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
            before = hashes()
            found = api.call('list_experiments', {'query':'','status':'','kind':'','offset':0,'limit':20})
            self.assertTrue(found['ok']); self.assertEqual(found['data']['total'], 1)
            self.assertEqual(found['data']['runs'][0]['symbol_count'], 3)
            detail = api.call('get_experiment', {'run_id':result.run_id})
            self.assertTrue(detail['ok']); self.assertEqual(detail['data']['status'], 'completed')
            self.assertEqual(detail['data']['metrics'], compact(json.loads((result.artifact_path/'experiment.json').read_text())['metrics']))
            self.assertEqual(detail['evidence'][0]['run_id'], result.run_id)
            self.assertEqual(before, hashes())

    def test_jobs_and_symlink_boundary(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp); _, api = self.source(root); job = str(uuid4()); folder = root/'_jobs'; folder.mkdir()
            path = folder/(job+'.json'); path.write_text(json.dumps({'job_id':job,'status':'cancelled','attempt':2}))
            value = api.call('get_job', {'job_id':job})
            self.assertTrue(value['ok']); self.assertEqual(value['data']['status'], 'cancelled')
            self.assertEqual(value['data']['attempt'], 2)
            other = Path(outside)/'job.json'; other.write_text(path.read_text()); path.unlink(); path.symlink_to(other)
            self.assertFalse(api.call('get_job', {'job_id':job})['ok'])

    def test_cli_json_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = [sys.executable, '-m', 'quantlab.agent', '--output', tmp]
            value = subprocess.run(command+['--schemas'], capture_output=True, text=True, timeout=30)
            self.assertEqual(value.returncode, 0, value.stderr)
            self.assertEqual({t['name'] for t in json.loads(value.stdout)['tools']}, EXPECTED_TOOLS)
            value = subprocess.run(command+['--call','submit_experiment'], capture_output=True, text=True, timeout=30)
            self.assertEqual(value.returncode, 2); self.assertFalse(json.loads(value.stdout)['ok'])
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_capabilities_lists_forward_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = ReadOnlyResearchAPI(tmp)
            caps = api.call('get_capabilities', {})
            self.assertTrue(caps['ok']); self.assertTrue(caps['data']['forward_records_available'])
            names = caps['data']['tools']
            for tool in ('list_forward_records','get_forward_record','get_forward_summary'):
                self.assertIn(tool, names)

    def test_forward_records_unknown_kind_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = ReadOnlyResearchAPI(tmp)
            for name in ('list_forward_records','get_forward_summary'):
                result = api.call(name, {'kind':'forex','offset':0,'limit':5})
                self.assertFalse(result['ok']); self.assertEqual(result['error']['code'],'INVALID_ARGUMENT')
            result = api.call('get_forward_record', {'kind':'forex','record_id':'abc'})
            self.assertFalse(result['ok']); self.assertEqual(result['error']['code'],'INVALID_ARGUMENT')

    def _seed_forward(self, tmp, kind='market'):
        from test_dipbuy import make_panel, scripted
        panel = make_panel(np.full((340, 30), 10.0))
        market, cand = scripted(340, 30, 339, {339: [0,1,2]}, ret20=np.full((340,30), 0.03, np.float32))
        signal = latest_signal(panel, market, cand, DipConfig(positions=2, hold_days=5))
        if not signal.get('gate_open') or not signal.get('picks'):
            self.skipTest('seeded signal not gate_open')
        record = tracker.record_signal(tmp, signal, DipConfig(positions=2, hold_days=5), kind=kind)
        self._panel = panel
        return record['id'], signal['date']

    def test_forward_kind_accepts_strategy_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            record_id, date = self._seed_forward(tmp, kind='fusion4')
            api = ReadOnlyResearchAPI(tmp)
            for alias in ('D4', 'd4', 'fusion4'):
                result = api.call('list_forward_records', {'kind':alias,'offset':0,'limit':5})
                self.assertTrue(result['ok'], result)
                self.assertEqual(result['data']['kind'], 'fusion4')
                self.assertEqual(result['data']['strategy'], '策略 D4')
                self.assertEqual(result['data']['records'][0]['id'], record_id)
            summary = api.call('get_forward_summary', {'kind':'D4'})
            self.assertTrue(summary['ok']); self.assertEqual(summary['data']['strategy'], '策略 D4')
            bad = api.call('list_forward_records', {'kind':'D9','offset':0,'limit':5})
            self.assertFalse(bad['ok']); self.assertIn('D4 = fusion4', bad['error']['message'])

    def test_get_forward_record_marks_read_only_from_cached_panel(self):
        from quantlab.dipbuy.panel import cache_dir
        with tempfile.TemporaryDirectory() as tmp:
            record_id, date = self._seed_forward(tmp, kind='fusion4')
            api = ReadOnlyResearchAPI(tmp)
            plain = api.call('get_forward_record', {'kind':'D4','record_id':record_id})
            self.assertTrue(plain['ok'])
            self.assertEqual(plain['data']['record']['result_source'], 'ledger')
            self.assertTrue(plain['data']['warnings'])
            self.assertIn('backtest_reference', plain['data'])
            self.assertEqual(plain['data']['ledger_config']['hold_days'], 5)
            self._panel.save(cache_dir(tmp))
            ledger = tracker._path(tmp, 'fusion4'); before = ledger.read_bytes()
            marked = api.call('get_forward_record', {'kind':'D4','record_id':record_id})
            self.assertTrue(marked['ok'], marked)
            record = marked['data']['record']
            self.assertEqual(record['result_source'], 'read_only_mark')
            self.assertEqual(record['mark_data_date'], str(self._panel.dates[-1]))
            self.assertIn('rows', record['result'])
            self.assertEqual(ledger.read_bytes(), before)

    def test_factor_combination_weights_follow_aliases(self):
        spec = {'inputs': {'zeta': {'factor_id':'BASE.MOMENTUM'}, 'alpha': {'factor_id':'BASE.MOMENTUM','parameters':{'lookback':5}}},
                'weights': {'zeta': 0.3, 'alpha': 0.7}}
        with tempfile.TemporaryDirectory() as tmp:
            result = ReadOnlyResearchAPI(tmp).call('preview_factor_combination', {'inputs':json.dumps(spec),'mode':'weights'})
        self.assertTrue(result['ok'], result)
        self.assertIn('0.7*alpha', result['data']['expression']); self.assertIn('0.3*zeta', result['data']['expression'])

    def test_preview_backtest_rejects_non_market_engines(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = ReadOnlyResearchAPI(tmp)
            schema = next(t for t in api.schemas() if t['name'] == 'preview_backtest')
            self.assertEqual(set(schema['parameters']['properties']), {'kind'})   # 不接受改参数
            result = api.call('preview_backtest', {'kind':'D4'})
            self.assertFalse(result['ok']); self.assertEqual(result['error']['code'],'INVALID_ARGUMENT')
            self.assertIn('策略 D4', result['error']['message'])
            empty = api.call('preview_backtest', {'kind':'A'})
            self.assertFalse(empty['ok']); self.assertIn('冻结参数', empty['error']['message'])

    def test_full_evidence_is_capped(self):
        from unittest.mock import patch
        run_id = str(uuid4())
        record = {'run_id': run_id, 'metrics': {'blob': 'x' * 30000}, 'summary': {'n': 1}}
        with tempfile.TemporaryDirectory() as tmp, \
                patch('quantlab.workbench.server.ArtifactCatalog.file', return_value=Path(tmp) / 'experiment.json'), \
                patch('quantlab.agent.catalog.load_record_fields', return_value=record):
            api = ReadOnlyResearchAPI(tmp)
            small = api.call('get_full_evidence', {'run_id': run_id, 'pointer': 'summary'})
            self.assertTrue(small['ok'], small); self.assertEqual(small['data']['value'], {'n': 1})
            big = api.call('get_full_evidence', {'run_id': run_id, 'pointer': 'metrics'})
            self.assertFalse(big['ok']); self.assertIn('超过单次上限', big['error']['message'])

    def test_list_forward_records_read_only_and_paginates(self):
        with tempfile.TemporaryDirectory() as tmp:
            record_id, date = self._seed_forward(tmp)
            api = ReadOnlyResearchAPI(tmp)
            before = {str(p.relative_to(tmp)):p.read_bytes() for p in Path(tmp).rglob('*') if p.is_file()}
            result = api.call('list_forward_records', {'kind':'market','offset':0,'limit':5})
            self.assertTrue(result['ok'])
            self.assertEqual(result['data']['total'], 1)
            self.assertEqual(len(result['data']['records']), 1)
            self.assertEqual(result['data']['records'][0]['signal_date'], date)
            self.assertEqual(result['data']['records'][0]['status'], 'waiting')
            self.assertEqual({str(p.relative_to(tmp)):p.read_bytes() for p in Path(tmp).rglob('*') if p.is_file()}, before)
            page2 = api.call('list_forward_records', {'kind':'market','offset':1,'limit':5})
            self.assertTrue(page2['ok']); self.assertEqual(page2['data']['records'], [])

    def test_get_forward_record_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            record_id, date = self._seed_forward(tmp)
            api = ReadOnlyResearchAPI(tmp)
            result = api.call('get_forward_record', {'kind':'market','record_id':record_id})
            self.assertTrue(result['ok'])
            record = result['data']['record']
            self.assertEqual(record['id'], record_id)
            self.assertEqual(record['signal_date'], date)
            self.assertEqual(record['status'], 'waiting')
            self.assertGreater(record['n_picks'], 0)
            self.assertEqual(result['data']['kind'], 'market')
            self.assertEqual(result['evidence'][0]['record_id'], record_id)

    def test_get_forward_record_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = ReadOnlyResearchAPI(tmp)
            result = api.call('get_forward_record', {'kind':'market','record_id':'no-such-record'})
            self.assertFalse(result['ok']); self.assertEqual(result['error']['code'],'INVALID_ARTIFACT')

    def test_get_forward_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._seed_forward(tmp)
            api = ReadOnlyResearchAPI(tmp)
            result = api.call('get_forward_summary', {'kind':'market'})
            self.assertTrue(result['ok'])
            self.assertEqual(result['data']['kind'], 'market')
            self.assertEqual(result['data']['n_records'], 1)
            self.assertEqual(result['data']['n_closed'], 0)
            self.assertFalse(result['data']['enough'])
            self.assertIn('只当记录看', result['data']['note'])

    def test_summary_preserves_numbers_and_exposes_omissions(self):
        self.assertEqual(compact({'v':None,'zero':0.,'x':-1.234}), {'v':None,'zero':0.,'x':-1.234})
        self.assertEqual(compact(list(range(40)))[-1], {'omitted_items':10})

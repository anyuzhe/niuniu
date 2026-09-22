import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
from test_context_experiments import ContextProvider, context_config, runner
from quantlab.agent.catalog import ReadOnlyResearchAPI, compact


EXPECTED_TOOLS = {'get_capabilities','search_factors','describe_factor','list_research_templates',
    'get_research_template','get_strategy_package_contract','preview_strategy_package',
    'list_strategy_runs','get_strategy_run','compare_strategy_runs','list_experiments',
    'get_experiment','get_job','get_proposal_progress'}


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

    def test_summary_preserves_numbers_and_exposes_omissions(self):
        self.assertEqual(compact({'v':None,'zero':0.,'x':-1.234}), {'v':None,'zero':0.,'x':-1.234})
        self.assertEqual(compact(list(range(40)))[-1], {'omitted_items':10})

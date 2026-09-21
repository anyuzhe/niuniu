"""Real host/provider/approval/reproduction wiring using isolated synthetic archives only."""
import contextlib
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from test_retro_daily import FakeSDK, bar
from test_strategy_package_cli import package_fixture
from quantlab.data.retro_daily import RetroDailyStore
from quantlab.data.archived_daily_dataset import (
    MARKER, ArchivedDailyDatasetProvider, preview_archived_daily_dataset,
    export_archived_daily_dataset, inspect_archived_daily_dataset,
)
from quantlab.data.provider import local_data_provider
from quantlab.workbench.jobs import prepare, JobQueue
from quantlab.agent.archived_daily_dataset_cli import main as cli_main


def files(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


class ArchivedDatasetLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / 'source'; self.source.mkdir()
        self.output = self.root / 'runs'; self.output.mkdir()
        self.destination = self.root / 'dataset'
        self.symbols = ['sh.600000', 'sh.600519', 'sz.000001']
        days = [date(2026, 7, 1) + timedelta(days=i) for i in range(45)]
        self.sessions = [day for day in days if day.weekday() < 5]
        self.start, self.end = days[0].isoformat(), days[-1].isoformat()
        calendar = [(day.isoformat(), '1' if day.weekday() < 5 else '0') for day in days]
        basic = [(symbol, 'synthetic', '2000-01-01', '', '1', '1') for symbol in self.symbols]
        values = {symbol: [bar(day.isoformat(), symbol,
                    10 + n * 2 + i * (0.05 + n * 0.02),
                    10 + n * 2 + max(0, i-1) * (0.05 + n * 0.02),
                    st='1' if n == 2 and i == 3 else '0')
                  for i, day in enumerate(self.sessions)] for n, symbol in enumerate(self.symbols)}
        sdk = FakeSDK(basic=basic, calendar=calendar, bars=values)
        self.store = RetroDailyStore(self.source, today_fn=lambda: date(2026, 9, 21),
                                    now_fn=lambda: datetime(2026, 9, 21, tzinfo=timezone.utc))
        self.capture = self.store.create_plan(self.start, self.end, sdk=sdk)['capture_id']
        self.store.fetch(self.capture, sdk=sdk)
        self.selected = (self.source, self.capture, ' '.join(self.symbols), self.start, self.end)
        self.spec = {'question': 'synthetic archived input wiring', 'symbols': self.symbols,
                     'start': self.start, 'end': self.end, 'timeframe': '1d', 'adjustment': 'raw',
                     'factor': 'BASE.MOMENTUM', 'version': '1.0.0', 'parameters': {'lookback': 2},
                     'horizons': [1], 'quantiles': 3, 'replay': True, 'mode': 'single',
                     'qualification': 'research_only'}
        self.queue = None
        self.addCleanup(lambda: self.queue.close() if self.queue else None)

    def export(self):
        preview = preview_archived_daily_dataset(*self.selected)
        return export_archived_daily_dataset(*self.selected, self.destination,
                   expected_preview_hash=preview['preview_hash'], confirmed=True)

    def cli(self, *args):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = cli_main(list(args))
        return code, json.loads(stream.getvalue())

    def common_args(self):
        return ('--source-workspace', str(self.source), '--capture-id', self.capture,
                '--symbols', *self.symbols, '--start', self.start, '--end', self.end)

    def settled(self, job_id):
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            job = next(j for j in self.queue.list() if j['job_id'] == job_id)
            if job['status'] not in ('queued', 'running'):
                return job
            time.sleep(.02)
        self.fail('isolated JobQueue did not settle')

    def test_cli_preview_export_and_new_process_inspect_do_not_run_research(self):
        before = files(self.source)
        code, preview = self.cli('preview', *self.common_args())
        self.assertEqual(code, 0, preview); self.assertFalse(self.destination.exists())
        args = ('export', *self.common_args(), '--destination', str(self.destination),
                '--expected-preview-hash', preview['data']['preview_hash'])
        code, denied = self.cli(*args)
        self.assertEqual(code, 2); self.assertFalse(self.destination.exists())
        code, result = self.cli(*args, '--confirm-create')
        self.assertEqual(code, 0, result); self.assertFalse(result['research_approved'])
        self.assertFalse(result['research_executed']); self.assertEqual(before, files(self.source))
        child = subprocess.run([sys.executable, '-B', '-m', 'quantlab.agent.archived_daily_dataset_cli',
                    'inspect', '--data-root', str(self.destination)], capture_output=True, text=True, timeout=30)
        self.assertEqual(child.returncode, 0, child.stderr + child.stdout)
        self.assertEqual(json.loads(child.stdout)['data']['dataset_id'], result['data']['dataset_id'])
        self.assertFalse((self.output / '_jobs').exists())
        original = files(self.destination)
        self.assertEqual(self.cli(*args, '--confirm-create')[0], 2)
        self.assertEqual(original, files(self.destination))

    def test_provider_route_keeps_features_and_never_uses_mqc_fallback(self):
        exported = self.export(); before = files(self.destination)
        with patch('quantlab.data.mqc.MQCParquetProvider.load', side_effect=AssertionError('wrong provider')):
            provider = local_data_provider(self.destination, 'raw')
            self.assertIsInstance(provider, ArchivedDailyDatasetProvider)
            batch = provider.load(prepare(self.spec).config.data)
        self.assertEqual(batch.snapshot.source, 'archived_retro_daily_dataset')
        self.assertEqual(batch.snapshot.adjustment, 'raw')
        self.assertEqual(batch.bars.height, len(self.sessions) * len(self.symbols))
        self.assertTrue({'vendor_previous_close', 'bs_turn_pct', 'bs_trade_status', 'bs_is_st'} <= set(batch.bars.columns))
        self.assertTrue(all(item.get('historical_available_at_verified') is not True for item in batch.snapshot.files))
        self.assertIn(exported['dataset_id'], json.dumps(batch.snapshot.files))
        self.assertEqual(before, files(self.destination))
        from quantlab.agent.local_data_tools import LocalMarketDataTools
        rejected = LocalMarketDataTools(self.destination).call('list_local_market_data',
                     {'timeframe': '1d', 'adjustment': 'raw', 'offset': 0, 'limit': 1})
        self.assertFalse(rejected['ok']); self.assertIn('MANAGED_DISCOVERY_UNSUPPORTED', rejected['error']['message'])

    def test_invalid_and_conflicting_markers_never_fall_back(self):
        self.export(); request = prepare(self.spec).config.data
        marker = self.destination / MARKER; payload = marker.read_bytes()
        with patch('quantlab.data.mqc.MQCParquetProvider.load', side_effect=AssertionError('fallback')):
            marker.write_text('{invalid')
            with self.assertRaises((ValueError, KeyError)):
                local_data_provider(self.destination, 'raw').load(request)
            marker.write_bytes(payload)
            for name in ('manifest.json', 'baostock-series.json', 'baostock-dataset.json'):
                conflict = self.destination / name; conflict.write_text('{}')
                with self.assertRaisesRegex(ValueError, 'Conflicting'):
                    local_data_provider(self.destination, 'raw')
                conflict.unlink()
            with self.assertRaises(ValueError):
                local_data_provider(self.destination, 'qfq').load(request)

    def test_strict_qualification_stays_blocked_and_raw_research_is_allowed(self):
        from quantlab.data.qualification import qualify_research
        self.export()
        self.assertTrue(qualify_research(self.destination, self.spec)['qualified'])
        for level in ('strict_pit', 'official_rule_covered'):
            result = qualify_research(self.destination, {**self.spec, 'qualification': level})
            self.assertFalse(result['qualified'], result)
            self.assertIn('historical_bar_vintage_not_certified', result['blockers'])

    def test_approval_freezes_input_then_source_and_dataset_can_go_offline(self):
        from quantlab.agent.planning import ResearchBudget
        from quantlab.agent.proposals import ProposalService
        self.export()
        service = ProposalService(self.output, self.destination,
                                  budget=replace(ResearchBudget(), max_active_jobs=1))
        proposal = service.propose(str(uuid4()), self.spec)
        full = SimpleNamespace(root=self.output, data_root=self.destination,
                               list=lambda: [{'job_id': str(uuid4()), 'status': 'running'}])
        with self.assertRaises(Exception):
            service.approve_and_submit(proposal['proposal_id'], proposal['proposal_digest'], lambda: full)
        self.assertEqual(service.store.get(proposal['proposal_id'])['status'], 'approved')
        self.source.rename(self.root / 'source-offline')
        self.destination.rename(self.root / 'dataset-offline'); self.destination.mkdir()
        self.queue = JobQueue(self.output, self.destination)
        with patch.object(ArchivedDailyDatasetProvider, 'load', side_effect=AssertionError('must use approval freeze')):
            submitted = service.approve_and_submit(proposal['proposal_id'], proposal['proposal_digest'], lambda: self.queue)
            job = self.settled(submitted['job']['job_id'])
        self.assertEqual(job['status'], 'completed', job)
        record = json.loads((self.output / job['run_id'] / 'experiment.json').read_text())
        snapshot = record['manifest']['data_snapshot']
        self.assertEqual(snapshot['source'], 'archived_retro_daily_dataset')
        self.assertTrue(snapshot['files'][0]['approval_time_frozen'])
        repeated = service.approve_and_submit(proposal['proposal_id'], proposal['proposal_digest'], lambda: self.queue)
        self.assertEqual(repeated['job']['job_id'], job['job_id']); self.assertEqual(len(self.queue.list()), 1)

    def test_strategy_execution_and_reproduction_use_same_source_identity(self):
        from quantlab.agent.proposals import ProposalService
        from quantlab.trading.strategy_package import compile_strategy
        from quantlab.storage.bundle import reproduce_artifact
        self.export(); package = package_fixture()
        package['spec'].update(symbols=self.symbols, start=self.start, end=self.end, adjustment='raw')
        compiled = compile_strategy(package)
        service = ProposalService(self.output, self.destination)
        proposal = service.propose(str(uuid4()), compiled['spec'])
        self.queue = JobQueue(self.output, self.destination)
        submitted = service.approve_and_submit(proposal['proposal_id'], proposal['proposal_digest'], lambda: self.queue)
        job = self.settled(submitted['job']['job_id']); self.assertEqual(job['status'], 'completed', job)
        original = self.output / job['run_id']
        record = json.loads((original / 'experiment.json').read_text())
        self.assertEqual(record['manifest']['signal_data_snapshot']['source'], 'archived_retro_daily_dataset')
        self.source.rename(self.root / 'source-offline')
        self.destination.rename(self.root / 'dataset-offline')
        with patch.object(ArchivedDailyDatasetProvider, 'load', side_effect=AssertionError('external data read')):
            replay = reproduce_artifact(original, self.root / 'replayed')
        self.assertEqual(replay['status'], 'numerically_matched', replay)
        actual = json.loads((Path(replay['artifact_path']) / 'experiment.json').read_text())
        self.assertEqual(record['manifest']['strategy_package'], actual['manifest']['strategy_package'])

    def test_chat_and_mcp_inspect_dataset_without_creation_or_execution_permissions(self):
        from quantlab.agent.chat_runtime import ChatRuntime
        from quantlab.agent.mcp_server import build_mcp_api
        from quantlab.agent.peer_review import ReviewReadOnlyAPI
        exported = self.export(); before = files(self.destination)
        for api in (ChatRuntime(self.output, self.destination, local_data_only=True).api,
                    build_mcp_api(self.output, self.destination)):
            names = [tool['name'] for tool in api.schemas()]
            self.assertEqual(len(names), len(set(names)))
            self.assertIn('get_archived_daily_dataset', names)
            value = api.call('get_archived_daily_dataset', {})
            self.assertTrue(value['ok'], value); self.assertEqual(value['data']['dataset_id'], exported['dataset_id'])
            self.assertFalse(api.call('get_archived_daily_dataset', {'path': str(self.source)})['ok'])
            for forbidden in ('export_archived_daily_dataset', 'approve_proposal', 'download_baostock'):
                self.assertNotIn(forbidden, names)
        self.assertEqual(before, files(self.destination)); self.assertFalse((self.output / '_jobs').exists())
        reviewer = ReviewReadOnlyAPI(self.output, self.destination)
        self.assertNotIn('get_archived_daily_dataset', {t['name'] for t in reviewer.schemas()})

    def test_failed_competing_export_does_not_remove_another_owners_lock(self):
        preview = preview_archived_daily_dataset(*self.selected)
        lock = self.destination.parent / ('.' + self.destination.name + '.archived-dataset-export.lock')
        lock.write_text('another-export-owner')
        with self.assertRaises(ValueError):
            export_archived_daily_dataset(*self.selected, self.destination,
                expected_preview_hash=preview['preview_hash'], confirmed=True)
        self.assertTrue(lock.exists(), 'failed acquisition must not unlink someone else\'s lock')
        self.assertEqual(lock.read_text(), 'another-export-owner')
        self.assertFalse(self.destination.exists())

    def test_provider_rejects_redirected_root_ancestor(self):
        self.export()
        alias = self.root / 'alias'; alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            local_data_provider(alias / self.destination.name, 'raw').load(prepare(self.spec).config.data)
        with self.assertRaises(ValueError):
            inspect_archived_daily_dataset(alias / self.destination.name)
        with self.assertRaises(ValueError):
            preview_archived_daily_dataset(alias / self.source.name, *self.selected[1:])

    def test_marker_last_fallback_publishes_only_after_all_payloads_exist(self):
        from quantlab.data import archived_daily_dataset as backend
        original_replace = backend.os.replace
        observations = []
        def checked_replace(source, destination):
            if Path(destination) == self.destination / MARKER:
                with self.assertRaises(ValueError):
                    inspect_archived_daily_dataset(self.destination)
                self.assertTrue((self.destination / 'normalized/bars.parquet').is_file())
                self.assertTrue((self.destination / 'source/plan.json').is_file())
                observations.append('incomplete_until_marker')
            return original_replace(source, destination)
        with patch.object(backend, '_rename_noreplace', side_effect=backend._publish_marker_last), \
                patch.object(backend.os, 'replace', side_effect=checked_replace):
            exported = self.export()
        self.assertEqual(observations, ['incomplete_until_marker'])
        self.assertEqual(inspect_archived_daily_dataset(self.destination)['dataset_id'], exported['dataset_id'])
        self.assertEqual(list(self.root.glob('.dataset.stage-*')), [])

    def test_marker_last_failure_keeps_incomplete_target_and_never_reuses_it(self):
        from quantlab.data import archived_daily_dataset as backend
        original_rename = backend.os.rename; before = files(self.source)
        def interrupted(source, destination):
            if Path(destination) == self.destination / 'normalized':
                raise OSError('synthetic publication interruption')
            return original_rename(source, destination)
        with patch.object(backend, '_rename_noreplace', side_effect=backend._publish_marker_last), \
                patch.object(backend.os, 'rename', side_effect=interrupted), self.assertRaises(OSError):
            self.export()
        self.assertEqual(json.loads((self.destination / MARKER).read_text())['publication_state'], 'INCOMPLETE')
        with self.assertRaises(ValueError):
            local_data_provider(self.destination, 'raw').load(prepare(self.spec).config.data)
        retained = files(self.destination)
        with self.assertRaises(ValueError):
            self.export()
        self.assertEqual(files(self.destination), retained)
        self.assertEqual(files(self.source), before)
        self.assertEqual(list(self.root.glob('.dataset.stage-*')), [])
        self.assertFalse((self.root / '.dataset.archived-dataset-export.lock').exists())

    def test_host_input_export_does_not_expand_original_spec_session(self):
        from test_research_spec_fidelity import synthetic_pair
        from quantlab.agent.research_specs import ResearchSpecStore
        from quantlab.agent.chat_runtime import ChatRuntime
        self.export(); md, js = synthetic_pair(self.root)
        saved = ResearchSpecStore(self.output).import_pair(md, js, confirmed=True)
        runtime = ChatRuntime(self.output, self.destination, local_data_only=True, research_spec=saved['spec_id'])
        self.assertNotIn('get_archived_daily_dataset', {t['name'] for t in runtime.api.schemas()})
        self.assertEqual(runtime.api.call('get_archived_daily_dataset', {})['error']['code'], 'SPEC_SUBSTITUTION_REJECTED')


if __name__ == '__main__':
    unittest.main()

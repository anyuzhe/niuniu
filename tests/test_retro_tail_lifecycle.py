"""Real synthetic retro-tail → approval freeze → execution lifecycle regressions."""
import json
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from test_retro_daily import FakeSDK, bar
from test_retro_tail_fallback import _baostock_daily
from quantlab.agent.planning import ResearchBudget
from quantlab.agent.proposals import ProposalService
from quantlab.data.base import DataRequest
from quantlab.data.provider import local_data_provider
from quantlab.data.retro_daily import RetroDailyStore
from quantlab.domain import Timeframe
from quantlab.storage.approval_inputs import ApprovalInputFreezeStore
from quantlab.workbench.jobs import JobQueue


class RetroTailLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.data = self.root / 'data'; self.data.mkdir()
        self.output = self.root / 'runs'; self.output.mkdir()
        self.source = self.root / 'source'; self.source.mkdir()
        self.symbols = ('sh.600000', 'sz.000001', 'sh.600519')
        days = [date(2026, 9, 1) + timedelta(days=i) for i in range(15)]
        calendar = [(d.isoformat(), '1' if d.weekday() < 5 else '0') for d in days]
        self.sessions = [d for d in days if d.weekday() < 5]
        data = {s: [bar(d.isoformat(), s, 12 + j + i * (j + 1) / 10,
                       11.9 + j + i * (j + 1) / 10) for i, d in enumerate(self.sessions)]
                for j, s in enumerate(self.symbols)}
        sdk = FakeSDK(basic=[(s, 'fixture', '2000-01-01', '', '1', '1') for s in self.symbols],
                      calendar=calendar, bars=data)
        store = RetroDailyStore(self.source, today_fn=lambda: date(2026, 9, 21),
                               now_fn=lambda: datetime(2026, 9, 21, tzinfo=timezone.utc))
        capture = store.create_plan('2026-09-01', '2026-09-15', sdk=sdk)['capture_id']
        store.fetch(capture, sdk=sdk); store.consolidate(capture, confirmed=True, remove_originals=True)
        folder = self.source / '_market_data/retro_daily' / capture
        index = json.loads((folder / 'packs/index.json').read_text())
        for s in self.symbols:
            _baostock_daily(self.data / 'lake/bronze/provider=baostock/stock_kline_daily' /
                            (s.replace('.', '_') + '.parquet'), s, days[:4])
        self.pointer = self.data / 'catalog/retro_daily_tail.json'; self.pointer.parent.mkdir()
        self.pointer_value = {'format': 'retro-daily-tail-pointer-v1', 'capture_path': str(folder),
                              'coverage_end': '2026-09-15', 'digest': index['checksum'],
                              'scope': 'raw daily tail; research_only; not Strict PIT',
                              'written_by': 'synthetic lifecycle fixture'}
        self.pointer.write_text(json.dumps(self.pointer_value))
        self.spec = {'question': 'Synthetic tail lifecycle only, not an investment claim',
                     'symbols': list(self.symbols), 'start': '2026-09-01', 'end': '2026-09-15',
                     'timeframe': '1d', 'adjustment': 'raw', 'factor': 'BASE.MOMENTUM',
                     'parameters': {'lookback': 2}, 'mode': 'single', 'horizons': [1],
                     'quantiles': 2, 'replay': True, 'qualification': 'research_only'}
        self.queue = None
        self.addCleanup(lambda: self.queue.close() if self.queue else None)

    def get_queue(self):
        if self.queue is None:
            self.queue = JobQueue(self.output, self.data)
        return self.queue

    def test_tail_only_request_with_real_packed_sources_and_observation_evidence(self):
        req = DataRequest(self.symbols, Timeframe.DAILY, date(2026, 9, 7), date(2026, 9, 15))
        batch = local_data_provider(self.data, 'raw').load(req)
        self.assertEqual(batch.bars.height, 21)
        self.assertEqual(batch.bars['datetime'].min().date(), date(2026, 9, 7))
        self.assertTrue(any(f.get('role') == 'raw_daily_tail' for f in batch.snapshot.files))
        self.assertTrue(any(f.get('sha256') for f in batch.snapshot.files if f.get('role') == 'raw_daily_tail'))
        self.assertNotIn(True, [f.get('historical_available_at_verified') for f in batch.snapshot.files])

    def test_original_source_and_pointer_can_go_offline_after_approval_freeze(self):
        service = ProposalService(self.output, self.data, budget=replace(ResearchBudget(), max_active_jobs=1))
        proposal = service.propose(str(uuid4()), self.spec)
        full = SimpleNamespace(root=self.output, data_root=self.data,
                               list=lambda: [{'job_id': str(uuid4()), 'status': 'running'}])
        with self.assertRaises(Exception):
            service.approve_and_submit(proposal['proposal_id'], proposal['proposal_digest'], lambda: full)
        self.assertEqual(service.store.get(proposal['proposal_id'])['status'], 'approved')
        folder = ApprovalInputFreezeStore(self.output, self.data).path(proposal['proposal_id'])
        manifest = json.loads((folder / 'manifest.json').read_text())['manifest']
        self.assertEqual(manifest['data_entries'][0]['rows'], 33)
        self.assertTrue(any(f.get('role') == 'raw_daily_tail'
                            for f in manifest['data_entries'][0]['source_snapshot']['files']))
        self.source.rename(self.root / 'source-offline')
        self.pointer.write_text('broken after approval')
        with patch('quantlab.data.retro_tail.RetroTail.tail_bars', side_effect=AssertionError('live tail read after approval')):
            result = service.approve_and_submit(proposal['proposal_id'], proposal['proposal_digest'], self.get_queue)
            end = time.monotonic() + 25
            while time.monotonic() < end:
                job = next(r for r in self.queue.list() if r['job_id'] == result['job']['job_id'])
                if job['status'] not in ('queued', 'running'):
                    break
                time.sleep(.02)
            self.assertEqual(job['status'], 'completed', job)
        record = json.loads((self.output / job['run_id'] / 'experiment.json').read_text())
        self.assertTrue(record['manifest']['data_snapshot']['files'][0]['approval_time_frozen'])
        again = service.approve_and_submit(proposal['proposal_id'], proposal['proposal_digest'], self.get_queue)
        self.assertEqual(again['job']['job_id'], result['job']['job_id'])
        self.assertEqual(len(self.queue.list()), 1)

    def test_wrong_pointer_identity_blocks_approval_without_creating_queue(self):
        service = ProposalService(self.output, self.data)
        proposal = service.propose(str(uuid4()), self.spec)
        self.pointer.write_text(json.dumps({**self.pointer_value, 'digest': '0' * 64}))
        with self.assertRaises(Exception):
            service.approve_and_submit(proposal['proposal_id'], proposal['proposal_digest'], self.get_queue)
        self.assertEqual(service.store.get(proposal['proposal_id'])['status'], 'pending')
        self.assertIsNone(self.queue)
        self.assertFalse((self.output / '_jobs').exists())

    def test_qfq_does_not_load_or_depend_on_the_raw_tail_pointer(self):
        from quantlab.data.retro_tail import load_pointer
        for symbol in self.symbols:
            _baostock_daily(self.data / 'lake/silver/qfq_kline_daily' /
                            (symbol.replace('.', '_') + '.parquet'), symbol, self.sessions[:4])
        self.source.rename(self.root / 'source-offline')
        self.pointer.write_text('invalid but irrelevant to qfq')
        with patch('quantlab.data.retro_tail.load_pointer', side_effect=AssertionError('qfq consulted raw tail')):
            batch = local_data_provider(self.data, 'qfq').load(DataRequest(
                self.symbols, Timeframe.DAILY, date(2026, 9, 1), date(2026, 9, 4)))
        self.assertEqual(batch.bars.height, 12)
        self.assertEqual(batch.snapshot.adjustment, 'qfq')

    def test_raw_minute_does_not_open_daily_capture(self):
        import polars as pl
        for symbol in self.symbols:
            path = self.data / 'lake/bronze/provider=baostock/stock_kline_min5' / (symbol.replace('.', '_') + '.parquet')
            _baostock_daily(path, symbol, [date(2026, 9, 4)])
            frame = pl.read_parquet(path).with_columns(pl.lit('20260904093500000').alias('time'))
            frame.write_parquet(path)
        self.source.rename(self.root / 'source-offline')
        with patch('quantlab.data.retro_daily.RetroDailyStore', side_effect=AssertionError('minute opened daily archive')):
            batch = local_data_provider(self.data, 'raw').load(DataRequest(
                self.symbols, Timeframe.MIN5, date(2026, 9, 4), date(2026, 9, 4)))
        self.assertEqual(batch.bars.height, 3)
        self.assertFalse(any(str(f.get('role', '')).startswith('raw_daily_tail') for f in batch.snapshot.files))

    def test_weekend_after_trunk_is_not_misreported_as_a_missing_tail(self):
        batch = local_data_provider(self.data, 'raw').load(DataRequest(
            self.symbols, Timeframe.DAILY, date(2026, 9, 1), date(2026, 9, 6)))
        self.assertEqual(batch.bars.height, 12)
        self.assertEqual(batch.bars['datetime'].max().date(), date(2026, 9, 4))

    def test_redirected_data_root_is_not_resolved_away_before_pointer_check(self):
        alias = self.root / 'data-link'; alias.symlink_to(self.data, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            local_data_provider(alias, 'raw').load(DataRequest(
                self.symbols, Timeframe.DAILY, date(2026, 9, 7), date(2026, 9, 15)))

    def test_pointer_duplicate_fields_are_rejected_not_last_value_wins(self):
        self.pointer.write_text('{"digest":"' + '0' * 64 + '",' + json.dumps(self.pointer_value)[1:])
        with self.assertRaises(ValueError):
            local_data_provider(self.data, 'raw').load(DataRequest(
                self.symbols, Timeframe.DAILY, date(2026, 9, 7), date(2026, 9, 15)))

    def test_strict_request_does_not_inherit_qualification_from_a_tail_pointer(self):
        from quantlab.data.qualification import qualify_research
        value = qualify_research(self.data, {**self.spec, 'qualification': 'strict_pit'})
        self.assertFalse(value['qualified'])
        self.assertIn('historical_bar_vintage_not_certified', value['blockers'])


if __name__ == '__main__':
    unittest.main()

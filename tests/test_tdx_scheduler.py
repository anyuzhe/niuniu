"""Scheduler review/apply safety; provider evidence here is synthetic."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from quantlab.data.tdx_lake import TdxLake, digest, write_json
from quantlab.agent.tdx_collection_cli import (
    POLICY_FORMAT, DEDICATED, Runner, build_scheduler_policy,
    validate_scheduler_policy, preview_scheduler_policy,
    apply_scheduler_policy_to_pending, recover_for_resume,
    _verify_auction_retention_evidence,
)


class SchedulerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        disk = patch('quantlab.data.tdx_lake.shutil.disk_usage', return_value=SimpleNamespace(free=200*1024**3))
        disk.start()
        self.addCleanup(disk.stop)
        self.lake = TdxLake(self.root, create=True)
        self.body = {'symbols': ['sh.600000', 'bj.920010'],
                     'trading_days': ['2025-07-21', '2025-07-22', '2025-07-23', '2026-09-17'],
                     'max_offset': 1000000, 'personal_research_only': True}
        self.pid = self.lake.add_plan(self.body)
        self.policy = self.seal({'format': POLICY_FORMAT, 'plan_id': self.pid,
            'lifecycle_bounds': {'sh.600000': {'listed': '2025-07-21', 'delisted': '2025-07-23'}},
            'family_market_history_floors': {'auction': {'sh': '2025-07-22', 'sz': '2025-07-22'}},
            'request_interval_seconds': .35})

    @staticmethod
    def seal(core):
        core = {k: v for k, v in core.items() if k != 'policy_id'}
        return {**core, 'policy_id': digest(core)}

    def jobs(self):
        with self.lake.db(readonly=True) as con:
            return [dict(r) for r in con.execute('SELECT * FROM jobs ORDER BY job_id')]

    def seed(self, family='trades', symbol='sh.600000', day='2026-09-17', offset=0):
        jid = self.lake.enqueue(self.pid, family, symbol, day, offset)
        return {'job_id': jid, 'plan_id': self.pid, 'family': family, 'symbol': symbol, 'day': day, 'offset': offset}

    def test_build_is_pure_and_default_is_three_node_safe_interval(self):
        before = self.jobs()
        value = build_scheduler_policy(self.lake, self.pid)
        self.assertEqual(value['request_interval_seconds'], .35)
        self.assertEqual(value['lifecycle_unknown'], self.body['symbols'])
        self.assertEqual(value['request_estimate']['lifecycle_bounded_symbol_days_per_family'], 8)
        self.assertFalse((self.lake.base/'scheduler-policy.json').exists())
        self.assertEqual(self.jobs(), before)

    def test_preview_does_not_mutate_queue_or_policy(self):
        self.seed()
        before = self.jobs()
        preview = preview_scheduler_policy(self.lake, self.pid, self.policy)
        self.assertTrue(preview['dry_run'])
        self.assertEqual(preview['pending_pruned'], 1)
        self.assertEqual(preview['pending_retargeted'], 1)
        self.assertEqual(self.jobs(), before)
        self.assertFalse((self.lake.base/'scheduler-policy.json').exists())

    def test_apply_rejects_stale_preview_without_changes(self):
        self.seed()
        preview = preview_scheduler_policy(self.lake, self.pid, self.policy)
        self.seed(symbol='bj.920010')
        before = self.jobs()
        with self.assertRaisesRegex(ValueError, 'stale'):
            apply_scheduler_policy_to_pending(self.lake, self.pid, self.policy, expected_snapshot=preview['snapshot_id'])
        self.assertEqual(self.jobs(), before)

    def test_apply_preserves_error_and_inflight_page_evidence(self):
        error = self.seed()
        self.lake.mark(error, 'ERROR', error='ProtocolError: invalid historical ticks payload')
        pending = self.seed(family='auction')
        stored = self.seed(family='trades', offset=1800)
        self.lake.mark(stored, 'PENDING', chunk='previous-checkpoint')
        before_error = next(r for r in self.jobs() if r['job_id'] == error['job_id'])
        snapshot = preview_scheduler_policy(self.lake, self.pid, self.policy)
        self.assertEqual(snapshot['pending_pruned'], 1)
        apply_scheduler_policy_to_pending(self.lake, self.pid, self.policy, expected_snapshot=snapshot['snapshot_id'])
        actual = {r['job_id']: r for r in self.jobs()}
        self.assertEqual(actual[error['job_id']], before_error)
        self.assertEqual(actual[pending['job_id']]['state'], 'SKIPPED_POLICY')
        self.assertEqual(actual[stored['job_id']]['chunk'], 'previous-checkpoint')
        with self.lake.db(readonly=True) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM scheduler_policy_audit').fetchone()[0], 1)

    def test_revised_policy_can_restore_old_skips_without_deleting_audit(self):
        job = self.seed()
        apply_scheduler_policy_to_pending(self.lake, self.pid, self.policy)
        revised = self.seal({**self.policy, 'lifecycle_bounds': {}})
        apply_scheduler_policy_to_pending(self.lake, self.pid, revised)
        self.assertEqual(next(r for r in self.jobs() if r['job_id'] == job['job_id'])['state'], 'PENDING')
        with self.lake.db(readonly=True) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM scheduler_policy_audit').fetchone()[0], 2)

    def test_policy_rejects_reverse_dates_and_unverified_bse_floor(self):
        for changes in (
            {'lifecycle_bounds': {'sh.600000': {'listed': '2026-01-01', 'delisted': '2025-01-01'}}},
            {'family_market_history_floors': {'auction': {'bj': '2025-07-22'}}},
            {'family_market_history_floors': {'trades': {'sh': '2025-07-22'}}},
            {'lifecycle_bounds': {'sh.600000': {'listed': '20250721'}}},
            {'request_interval_seconds': float('inf')},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_scheduler_policy(self.seal({**self.policy, **changes}), self.pid)

    def test_unknown_lifecycle_does_not_trim_bse_or_trade_years(self):
        write_json(self.lake.base/'scheduler-policy.json', self.policy)
        runner = Runner(self.lake, self.pid)
        self.assertEqual(runner._previous_history_day('auction', 'bj.920010', '2025-07-22'), '2025-07-21')
        self.assertEqual(runner._previous_history_day('trades', 'bj.920010', '2025-07-22'), '2025-07-21')
        self.assertIsNone(runner._previous_history_day('auction', 'sh.600000', '2025-07-22'))

    def test_resume_only_retries_transport_errors(self):
        permanent = self.seed()
        transient = self.seed(symbol='bj.920010')
        self.lake.mark(permanent, 'ERROR', error='ProtocolError: invalid historical ticks payload')
        self.lake.mark(transient, 'ERROR', error='ConnectionClosedError: closed')
        recover_for_resume(self.lake, self.pid, 12)
        actual = {r['job_id']: r for r in self.jobs()}
        self.assertEqual(actual[permanent['job_id']]['state'], 'ERROR')
        self.assertEqual(actual[transient['job_id']]['state'], 'PENDING')

    def evidence(self):
        directory = self.root/'evidence'
        directory.mkdir()
        symbols = ['sh.600000', 'sh.600004', 'sz.000001', 'sz.000002']
        rows = [{'symbol': s, 'day': d, 'rows': n, 'error': None}
                for d, n in [('2025-07-21', 0), ('2025-07-22', 5)] for s in symbols]
        cross = [{**r, 'dedicated_host': h} for h in DEDICATED for r in rows]
        cross += [{'symbol': s, 'day': d, 'rows': 3, 'error': None, 'dedicated_host': h}
                  for h in DEDICATED for s in ['bj.920010', 'bj.920011'] for d in ['2025-07-21', '2025-07-22']]
        write_json(directory/'auction-boundary.json', {'symbols': symbols, 'records': rows})
        write_json(directory/'auction-host-crosscheck.json', {'records': cross})
        return directory, cross

    def test_retention_dual_host_market_evidence(self):
        directory, _ = self.evidence()
        result = _verify_auction_retention_evidence(directory, self.body['trading_days'])
        self.assertEqual(result['market_floors'], {'sh': '2025-07-22', 'sz': '2025-07-22'})
        self.assertEqual(result['markets_without_floor'], ['bj'])

    def test_duplicate_anchor_does_not_count_as_complete_crosscheck(self):
        directory, cross = self.evidence()
        cross[1] = dict(cross[0])
        write_json(directory/'auction-host-crosscheck.json', {'records': cross})
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            _verify_auction_retention_evidence(directory, self.body['trading_days'])

    def test_writer_body_oserror_is_not_misreported_as_lock_contention(self):
        from quantlab.agent.tdx_collection_cli import writer_lease
        with self.assertRaisesRegex(OSError, 'body-error'):
            with writer_lease(self.lake):
                raise OSError('body-error')

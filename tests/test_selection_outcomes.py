from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from multiprocessing import get_context
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from zoneinfo import ZoneInfo
import io
import json
import unittest

from limit_research_fixtures import FakeSDK, Resp, T
from quantlab.agent.peer_review import ReviewReadOnlyAPI
from quantlab.agent.playbook_tools import PlaybookResearchAPI, SELECTION_OUTCOME_TOOLS
from quantlab.agent.selection_outcomes_cli import main as selection_cli
from quantlab.data.daily_market_archive import EXPECTED_FIELDS, DailyMarketArchive
from quantlab.data.forward_daily import ForwardReferenceArchive
from quantlab.experiments.campaign_state import read_checked, write_checked
from quantlab.storage.codec import digest
from quantlab.trading.playbook_store import PlaybookStore
from quantlab.trading.selection_outcomes import SelectionOutcomeError, SelectionOutcomeService

TZ = ZoneInfo('Asia/Shanghai')
A, B, C, D, BJ = 'sh.600001', 'sz.000001', 'sz.000002', 'sh.600002', 'bj.830001'
# (close, preclose) per trading day; None marks a suspended session. D splits 2:1 on day 4 (preclose adjusted).
PRICES = {
    1: {A: (10, 10), B: (10, 10), C: (10, 10), D: (20, 20)},
    2: {A: (11, 10), B: (9, 10), C: (10, 10), D: (20, 20)},
    3: {A: (11, 11), B: (9.9, 9), C: None, D: (22, 20)},
    4: {A: (12.1, 11), B: (9.9, 9.9), C: (11, 10), D: (12.1, 11)},
    5: {A: (12.1, 12.1), B: (9.9, 9.9), C: (11, 11), D: (12.1, 12.1)},
}


def local(i, hh, mm):
    return datetime.combine(T(i), datetime.min.time(), TZ).replace(hour=hh, minute=mm)


def daily_row(day, code, price):
    row = {key: '' for key in EXPECTED_FIELDS}
    row.update(date=day.isoformat(), code=code, adjustflag='3', isST='0')
    if price is None:
        row.update(tradestatus='0', preclose='10')
        return row
    close, preclose = price
    row.update(open=str(close), high=str(close), low=str(close), close=str(close), preclose=str(preclose),
               volume='1000', amount=str(1000 * close), turn='1.0', tradestatus='1',
               pctChg=str(round((close / preclose - 1) * 100, 4)))
    return row


class MarketSDK(FakeSDK):
    """Controlled full-market daily rows on top of the shared calendar / stock_basic fixture."""
    def __init__(self, prices=PRICES, closed_days=()):
        super().__init__(); self.prices = prices; self.closed_days = {day.isoformat() for day in closed_days}
    def query_daily_history_k_AStock(self, date=''):
        index = next(i for i in self.prices if T(i).isoformat() == date)
        rows = [daily_row(T(index), code, price) for code, price in sorted(self.prices[index].items())]
        return Resp(EXPECTED_FIELDS, [[row[name] for name in EXPECTED_FIELDS] for row in rows])
    def query_trade_dates(self, start_date, end_date):
        result = super().query_trade_dates(start_date, end_date)
        return Resp(result.fields, [[day, '0' if day in self.closed_days else flag] for day, flag in result.rows])


def freeze_worker(output, selection_id, core, start, queue):
    """Separate-process writer used to exercise the POSIX publication lock."""
    start.wait(10)
    try:
        service = SelectionOutcomeService(output, now_fn=lambda: datetime(2026, 9, 30, tzinfo=timezone.utc))
        value, created = service._freeze(service._folder(selection_id), core)
        queue.put({'ok': True, 'created': created, 'review_hash': value['review_hash']})
    except Exception as error:  # child result must be returned to the parent for an assertion
        queue.put({'ok': False, 'code': getattr(error, 'code', type(error).__name__), 'message': str(error)})


class SelectionOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)
        self.clock = [local(1, 19, 0)]
        self.daily = DailyMarketArchive(self.output, now_fn=lambda: self.clock[0])
        self.store = PlaybookStore(self.output)
        self.source = self.store.create_source(str(uuid4()), {
            'expert_key': 'selection-test', 'title': '测试来源', 'source_type': 'PUBLIC_POST',
            'locator': 'https://example.invalid/x', 'available_at': '2026-01-01T09:00:00+08:00',
            'content_hash': 'b' * 64, 'completeness': 'VERIFIED'})
        self.definition = self.store.create_definition(str(uuid4()), {
            'playbook_key': 'selection_test', 'name': '选择对照测试', 'version': 'draft-1', 'state': 'DRAFT',
            'source_ids': [], 'market_context': {}, 'eligibility': {}, 'selection': {}, 'veto': {}, 'entry': {},
            'confirm': {}, 'invalidation': {}, 'hold': {}, 'add': {}, 'reduce': {}, 'exit': {}, 'notes': ''})

    def capture_days(self, days, prices=PRICES):
        for i in days:
            self.clock[0] = local(i, 19, 0)
            self.daily.capture(T(i), sdk=MarketSDK(prices))

    def capture_reference(self, i, *, closed_days=()):
        self.clock[0] = local(i, 19, 30)
        return ForwardReferenceArchive(self.output, now_fn=lambda: self.clock[0]).capture(
            sdk=MarketSDK(closed_days=closed_days))

    def selection(self, frame='PREP', day=2, selected=(A, B), kind='OBSERVED_EXPERT'):
        trading_day = T(day) if isinstance(day, int) else day
        opening = datetime.combine(trading_day, datetime.min.time(), TZ)
        as_of = opening.replace(hour=8, minute=50) if frame == 'PREP' else opening.replace(hour=9, minute=35)
        case = self.store.create_case(str(uuid4()), {
            'definition_id': self.definition['definition_id'], 'trading_day': trading_day.isoformat(), 'frame': frame,
            'as_of': as_of.isoformat(), 'source_ids': [self.source['source_id']], 'summary': '选择结果对照测试', 'notes': ''})
        members = [{'symbol': symbol, 'eligibility_reasons': ['满足冻结条件'], 'features': {}, 'evidence_ids': []}
                   for symbol in (A, B, C, D, BJ)]
        candidates = self.store.create_candidate_set(str(uuid4()), {
            'case_id': case['case_id'], 'definition_id': self.definition['definition_id'],
            'trading_day': trading_day.isoformat(), 'frame': frame, 'as_of': as_of.isoformat(), 'completeness': 'FULL',
            'pit_status': 'RETROSPECTIVE_REFERENCE', 'universe_source': '测试全集', 'generation_method': '测试规则',
            'candidates': members, 'evidence_ids': []})
        return self.store.create_selection(str(uuid4()), {
            'candidate_set_id': candidates['candidate_set_id'], 'kind': kind, 'selected_symbols': list(selected),
            'ranked_symbols': [], 'reasons': {}, 'evidence_ids': [], 'as_of': as_of.isoformat(), 'notes': ''})

    def service(self):
        return SelectionOutcomeService(self.output, now_fn=lambda: datetime(2026, 9, 30, tzinfo=timezone.utc))

    def core(self, selection_id, window=1):
        service = self.service()
        selection, candidates, case = service._selection_bundle(selection_id)
        sessions = service._sessions(candidates['trading_day'], window, candidates['frame'])
        core, blocked = service._measure(selection, candidates, case, window, sessions)
        self.assertIsNone(blocked)
        return core

    def race_freeze(self, selection_id, cores):
        context = get_context('spawn')
        start, queue = context.Event(), context.Queue()
        processes = [context.Process(target=freeze_worker, args=(str(self.output), selection_id, core, start, queue))
                     for core in cores]
        for process in processes:
            process.start()
        start.set()
        results = [queue.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(15)
            if process.is_alive():
                process.terminate(); process.join(5)
            self.assertEqual(process.exitcode, 0)
        queue.close(); queue.join_thread()
        return results

    @staticmethod
    def rewrite_review(path, mutate):
        value = read_checked(path)
        mutate(value)
        core = {key: item for key, item in value.items() if key not in ('review_hash', 'created_at')}
        value['review_hash'] = digest(core)
        write_checked(path, value)

    def test_both_sides_are_measured_the_same_way_from_the_selection_close(self):
        self.capture_days(range(1, 6)); self.capture_reference(5)
        selection = self.selection()
        result = self.service().build(selection['selection_id'], [0, 1, 2, 5])
        by_window = {row['window_label']: row for row in result['records']}
        self.assertEqual(sorted(by_window), ['D0', 'D1', 'D2'])
        symbols = {row['symbol']: row for row in by_window['D2']['symbols']}
        self.assertAlmostEqual(symbols[A]['return'], 0.10); self.assertAlmostEqual(symbols[B]['return'], 0.10)
        self.assertAlmostEqual(symbols[C]['return'], 0.10); self.assertEqual(symbols[C]['suspended_sessions'], 1)
        # The 2:1 split on day 4 is carried by the adjusted preclose, so it is not mistaken for a -50% day.
        self.assertAlmostEqual(symbols[D]['return'], 0.21)
        self.assertEqual((symbols[BJ]['status'], symbols[BJ]['return']), ('NO_DAILY_ROW', None))
        groups = by_window['D2']['groups']
        self.assertEqual((groups['SELECTED']['measured'], groups['UNSELECTED']['total'], groups['UNSELECTED']['measured']), (2, 3, 2))
        self.assertAlmostEqual(by_window['D2']['spread_selected_minus_unselected'], 0.10 - 0.155)
        self.assertEqual([row['symbol'] for row in by_window['D2']['unselected_above_selected_mean']], [D])
        self.assertEqual({row['symbol'] for row in by_window['D2']['selected_below_unselected_mean']}, {A, B})
        self.assertEqual(by_window['D2']['reference'], 'SELECTION_DAY_CLOSE')
        self.assertEqual(by_window['D2']['sessions'], [T(3).isoformat(), T(4).isoformat()])
        # D0 uses the previous close, which was known before a PREP selection.
        day0 = {row['symbol']: row['return'] for row in by_window['D0']['symbols']}
        self.assertAlmostEqual(day0[A], 0.10); self.assertAlmostEqual(day0[B], -0.10)
        self.assertEqual(by_window['D0']['reference'], 'SELECTION_DAY_PRECLOSE')
        self.assertEqual(result['pending'], [{'window': 'D5', 'status': 'NOT_YET_OBSERVED',
                                              'reason': result['pending'][0]['reason']}])
        for row in result['records']:
            self.assertEqual(row['semantics'], 'SIGNAL_CLOSE_TO_CLOSE_RETURN_NOT_EXECUTABLE')
            self.assertFalse(row['future_data_used']); self.assertFalse(row['policy']['automatic_reweighting'])
        self.assertFalse(result['strategy_intent_mutated']); self.assertFalse(result['weights_mutated'])
        self.assertEqual(sorted(p.name for p in (self.output / '_trading').iterdir()), ['selection_outcomes'])

    def test_day0_is_not_produced_for_intraday_frames(self):
        self.capture_days(range(1, 6)); self.capture_reference(5)
        selection = self.selection(frame='R1')
        result = self.service().build(selection['selection_id'], [0, 1])
        self.assertEqual([row['window_label'] for row in result['records']], ['D1'])
        self.assertEqual(result['pending'][0]['window'], 'D0')
        self.assertEqual(result['pending'][0]['status'], 'NOT_APPLICABLE')

    def test_frozen_windows_are_idempotent_and_a_missing_day_blocks_instead_of_skipping(self):
        self.capture_days([1, 2, 3, 5]); self.capture_reference(5)
        selection = self.selection()
        service = self.service()
        first = service.build(selection['selection_id'], [1, 2])
        self.assertEqual([row['window_label'] for row in first['records']], ['D1'])
        self.assertEqual(first['pending'], [{'window': 'D2', 'status': 'DATA_MISSING', 'missing_days': [T(4).isoformat()]}])
        again = service.build(selection['selection_id'], [1, 2])
        self.assertEqual(again['created'], 0)
        self.assertEqual(again['records'][0]['review_hash'], first['records'][0]['review_hash'])
        self.capture_days([4])
        # Reusing the same service must re-observe a day that was previously cached as missing.
        later = service.build(selection['selection_id'], [1, 2])
        self.assertEqual([row['window_label'] for row in later['records']], ['D1', 'D2']); self.assertEqual(later['created'], 1)

    def test_new_reference_snapshot_is_idempotent_for_legacy_v1_but_material_calendar_change_conflicts(self):
        self.capture_days(range(1, 6)); first_reference = self.capture_reference(5)
        selection = self.selection()
        service = self.service()
        first = service.build(selection['selection_id'], [1])['records'][0]
        original_bytes = (self.output / '_trading' / 'selection_outcomes' / selection['selection_id'] / 'D1.json').read_bytes()
        self.assertEqual(first['format'], 'selection-outcome-review-v1')
        self.assertEqual(first['calendar_reference_snapshot_id'], first_reference['snapshot_id'])

        second_reference = self.capture_reference(6)
        self.assertNotEqual(second_reference['snapshot_id'], first_reference['snapshot_id'])
        rebuilt = service.build(selection['selection_id'], [1, 2])
        old = next(row for row in rebuilt['records'] if row['window'] == 1)
        self.assertEqual((old['review_hash'], old['created_at']), (first['review_hash'], first['created_at']))
        self.assertEqual((self.output / '_trading' / 'selection_outcomes' / selection['selection_id'] / 'D1.json').read_bytes(), original_bytes)
        self.assertEqual(rebuilt['created'], 1)

        self.capture_reference(7, closed_days=(T(3),))
        with self.assertRaises(SelectionOutcomeError) as changed:
            service.build(selection['selection_id'], [1])
        self.assertEqual(changed.exception.code, 'REVIEW_CONFLICT')

    def test_accepted_market_revision_conflicts_with_a_frozen_review(self):
        self.capture_days(range(1, 6)); self.capture_reference(5)
        selection = self.selection()
        service = self.service()
        service.build(selection['selection_id'], [1])
        revised = {**PRICES, 3: {**PRICES[3], A: (11.5, 11)}}
        self.clock[0] = local(5, 20, 0)
        revision = self.daily.capture(T(3), sdk=MarketSDK(revised))
        self.assertTrue(revision['revision_detected'])
        self.daily.accept_revision(T(3), revision['snapshot_id'], confirmed=True)
        # Reusing the same service must not hide an accepted revision behind its frame cache.
        with self.assertRaises(SelectionOutcomeError) as error:
            service.build(selection['selection_id'], [1])
        self.assertEqual(error.exception.code, 'REVIEW_CONFLICT')

    def test_concurrent_freeze_is_single_creator_and_never_overwrites_a_different_request(self):
        self.capture_days(range(1, 6)); self.capture_reference(5)
        same, different = self.selection(), self.selection()
        same_core = self.core(same['selection_id'])
        old_core = self.core(different['selection_id'])
        revised = {**PRICES, 3: {**PRICES[3], A: (11.5, 11)}}
        self.clock[0] = local(5, 20, 0)
        revision = self.daily.capture(T(3), sdk=MarketSDK(revised))
        self.daily.accept_revision(T(3), revision['snapshot_id'], confirmed=True)
        new_core = self.core(different['selection_id'])

        same_results = self.race_freeze(same['selection_id'], [same_core, same_core])
        self.assertEqual(sorted(result.get('created') for result in same_results), [False, True])
        self.assertTrue(all(result['ok'] for result in same_results))

        different_results = self.race_freeze(different['selection_id'], [old_core, new_core])
        self.assertEqual(sum(result['ok'] and result.get('created', False) for result in different_results), 1)
        self.assertEqual([result.get('code') for result in different_results if not result['ok']], ['REVIEW_CONFLICT'])
        saved = self.service().get(different['selection_id'])['records'][0]
        self.assertIn(saved['review_hash'], {digest(old_core), digest(new_core)})

    def test_summary_keeps_kinds_frames_and_windows_apart_and_flags_small_samples(self):
        self.capture_days(range(1, 6)); self.capture_reference(5)
        self.selection(frame='PREP'); self.selection(frame='R1'); self.selection(frame='PREP', selected=())
        batch = self.service().auto_all([1, 2])
        self.assertEqual((batch['selections_checked'], batch['windows_frozen'], batch['errors']), (3, 6, []))
        rows = self.service().summary()['rows']
        keys = {(row['frame'], row['window_label']) for row in rows}
        self.assertEqual(keys, {('PREP', 'D1'), ('PREP', 'D2'), ('R1', 'D1'), ('R1', 'D2')})
        prep = next(row for row in rows if (row['frame'], row['window_label']) == ('PREP', 'D2'))
        # The NO_TRADE selection has no selected group, so it is counted but not averaged into the spread.
        self.assertEqual((prep['selections'], prep['selections_with_both_groups'], prep['no_trade_selections']), (2, 1, 1))
        self.assertEqual(prep['sample_status'], 'INSUFFICIENT_SAMPLES')
        self.assertEqual(self.service().summary(kind='SYSTEM_PREDICTION')['rows'], [])

    def test_auto_all_reports_a_selection_outside_the_calendar_without_stopping(self):
        self.capture_days(range(1, 6)); self.capture_reference(5)
        good = self.selection()
        early = self.selection(day=date(2026, 7, 31))
        with self.assertRaises(SelectionOutcomeError) as missing:
            self.service().build(str(uuid4()))
        self.assertEqual(missing.exception.code, 'NOT_FOUND')
        batch = self.service().auto_all([1])
        self.assertEqual((batch['status'], batch['windows_frozen'], batch['windows_failed']), ('PARTIAL_FAILURE', 1, 1))
        self.assertEqual([(e['selection_id'], e['window'], e['code']) for e in batch['errors']],
                         [(early['selection_id'], 'D1', 'OUTSIDE_CALENDAR')])
        self.assertEqual(self.service().get(good['selection_id'])['records'][0]['window_label'], 'D1')

    def test_auto_all_counts_successful_windows_when_another_window_conflicts(self):
        self.capture_days(range(1, 6)); self.capture_reference(5)
        selection = self.selection()
        self.service().build(selection['selection_id'], [1])
        revised = {**PRICES, 3: {**PRICES[3], A: (11.5, 11)}}
        self.clock[0] = local(5, 20, 0)
        revision = self.daily.capture(T(3), sdk=MarketSDK(revised))
        self.daily.accept_revision(T(3), revision['snapshot_id'], confirmed=True)
        batch = self.service().auto_all([1, 2])
        self.assertEqual((batch['status'], batch['windows_frozen'], batch['windows_created'], batch['windows_failed']),
                         ('PARTIAL_FAILURE', 1, 1, 1))
        self.assertEqual([(item['window'], item['code']) for item in batch['errors']], [('D1', 'REVIEW_CONFLICT')])

    def test_corrupt_reviews_are_disclosed_consistently_without_hiding_clean_summary(self):
        self.capture_days(range(1, 6)); self.capture_reference(5)
        clean = self.selection(selected=(B,))
        damaged = self.selection(selected=(A,))
        service = self.service()
        service.build(clean['selection_id'], [1])
        damaged_row = service.build(damaged['selection_id'], [1])['records'][0]
        original = damaged_row
        self.assertLess(damaged_row['spread_selected_minus_unselected'], 0)
        path = self.output / '_trading' / 'selection_outcomes' / damaged['selection_id'] / 'D1.json'
        path.write_text(path.read_text().replace('"window": 1', '"window": -1'), encoding='utf-8')

        got = service.get(damaged['selection_id'])
        listed = service.list()
        summary = service.summary()
        for result in (got, listed, summary):
            self.assertTrue(result['incomplete']); self.assertEqual(len(result['errors']), 1)
            self.assertEqual(result['errors'][0]['code'], 'CORRUPT_REVIEW')
        self.assertEqual(listed['total'], 1)
        self.assertEqual(summary['rows'][0]['selections'], 1)

        # A valid checksum cannot hide an invalid review_hash, format, path identity, or negative shape value.
        checks = [
            lambda value: value.__setitem__('review_hash', '0' * 64),
            lambda value: value.__setitem__('format', 'selection-outcome-review-v0'),
            lambda value: value.__setitem__('selection_id', clean['selection_id']),
            lambda value: value['groups']['SELECTED'].__setitem__('total', -1),
            lambda value: value['symbols'][-1].__setitem__('symbol', 'sh.699999'),
        ]
        for mutate in checks:
            write_checked(path, original)
            if mutate is checks[0]:
                value = read_checked(path); mutate(value); write_checked(path, value)
            else:
                self.rewrite_review(path, mutate)
            current = service.get(damaged['selection_id'])
            self.assertTrue(current['incomplete']); self.assertEqual(current['records'], [])

        write_checked(path, original)
        moved = path.with_name('D2.json'); path.replace(moved)
        wrong_window = service.get(damaged['selection_id'])
        self.assertTrue(wrong_window['incomplete']); self.assertEqual(wrong_window['records'], [])
        moved.replace(path)
        target = path.with_name('stored-review.json'); path.replace(target); path.symlink_to(target.name)
        symlinked = service.get(damaged['selection_id'])
        self.assertTrue(symlinked['incomplete']); self.assertEqual(symlinked['records'], [])

    def test_agent_tools_are_read_only_compact_and_kept_out_of_first_round_review(self):
        self.capture_days(range(1, 6)); self.capture_reference(5)
        selection = self.selection()
        self.service().build(selection['selection_id'], [1, 2])
        api = PlaybookResearchAPI(self.output); names = {tool['name'] for tool in api.schemas()}
        self.assertTrue(set(SELECTION_OUTCOME_TOOLS) <= names)
        self.assertFalse(any('selection_outcome' in name and not name.startswith(('get_', 'list_')) for name in names))
        got = api.call('get_selection_outcome_review', {'selection_id': selection['selection_id']})
        self.assertTrue(got['ok']); self.assertEqual(len(got['data']['records']), 2)
        self.assertNotIn('symbols', got['data']['records'][0])
        self.assertTrue(any('不是可成交收益' in text for text in got['warnings']))
        listed = api.call('list_selection_outcome_reviews', {'definition_id': '', 'kind': '', 'frame': 'PREP', 'offset': 0, 'limit': 20})
        self.assertEqual(listed['data']['total'], 2)
        summary = api.call('get_selection_outcome_summary', {'definition_id': '', 'kind': '', 'frame': ''})
        self.assertTrue(summary['ok']); self.assertFalse(summary['data']['policy']['automatic_reweighting'])
        capabilities = api.call('get_capabilities', {})['data']
        self.assertTrue(capabilities['selection_outcome_available']); self.assertFalse(capabilities['selection_outcome_write_model'])
        # First-round reviewers must not anchor on outcome statistics (same rule as the Scorecard).
        review_names = {tool['name'] for tool in ReviewReadOnlyAPI(self.output, self.output).schemas()}
        self.assertFalse(set(SELECTION_OUTCOME_TOOLS) & review_names)

    def test_ai_tools_preserve_archive_errors_alongside_clean_results(self):
        self.capture_days(range(1, 6)); self.capture_reference(5)
        clean, damaged = self.selection(selected=(B,)), self.selection(selected=(A,))
        service = self.service(); service.build(clean['selection_id'], [1]); service.build(damaged['selection_id'], [1])
        path = self.output / '_trading' / 'selection_outcomes' / damaged['selection_id'] / 'D1.json'
        path.write_text(path.read_text().replace('"window": 1', '"window": -1'), encoding='utf-8')
        api = PlaybookResearchAPI(self.output)
        summary = api.call('get_selection_outcome_summary', {'definition_id': '', 'kind': '', 'frame': ''})
        listed = api.call('list_selection_outcome_reviews', {'definition_id': '', 'kind': '', 'frame': '', 'offset': 0, 'limit': 20})
        got = api.call('get_selection_outcome_review', {'selection_id': damaged['selection_id']})
        for result in (summary, listed, got):
            self.assertTrue(result['ok']); self.assertTrue(result['data']['incomplete'])
            self.assertEqual(result['data']['errors'][0]['code'], 'CORRUPT_REVIEW')
            self.assertTrue(any('归档不完整' in warning for warning in result['warnings']))
        self.assertEqual(summary['data']['rows'][0]['selections'], 1)
        self.assertEqual(listed['data']['total'], 1)

    def test_cli_builds_lists_and_summarises(self):
        self.capture_days(range(1, 6)); self.capture_reference(5)
        selection = self.selection()
        def run(*args):
            stream = io.StringIO()
            with redirect_stdout(stream):
                code = selection_cli(['--output', str(self.output), *args])
            return code, json.loads(stream.getvalue())
        code, built = run('--selection-id', selection['selection_id'], '--windows', '1,2')
        self.assertEqual(code, 0); self.assertEqual(len(built['data']['records']), 2)
        self.assertNotIn('symbols', built['data']['records'][0])
        code, full = run('--get', selection['selection_id'], '--full')
        self.assertEqual(code, 0); self.assertIn('symbols', full['data']['records'][0])
        code, listed = run('--list', '--limit', '1', '--offset', '1', '--full')
        self.assertEqual(code, 0); self.assertEqual(len(listed['data']['records']), 1)
        self.assertIn('symbols', listed['data']['records'][0])
        code, summary = run('--summary')
        self.assertEqual(code, 0); self.assertEqual(len(summary['data']['rows']), 2)
        code, bad = run('--selection-id', selection['selection_id'], '--windows', '1,x')
        self.assertEqual(code, 2); self.assertFalse(bad['ok'])

    def test_cli_auto_all_distinguishes_pending_partial_failure_and_failure(self):
        self.capture_days(range(1, 6)); self.capture_reference(5)
        good = self.selection()
        early = self.selection(day=date(2026, 7, 31), kind='HUMAN_RECONSTRUCTION')
        def run(*args):
            stream = io.StringIO()
            with redirect_stdout(stream):
                code = selection_cli(['--output', str(self.output), *args])
            return code, json.loads(stream.getvalue())
        code, partial = run('--auto-all', '--windows', '1')
        self.assertEqual(code, 3); self.assertFalse(partial['ok'])
        self.assertEqual(partial['status'], 'PARTIAL_FAILURE')
        self.assertEqual((partial['data']['windows_frozen'], partial['data']['windows_failed']), (1, 1))
        self.assertEqual(partial['data']['errors'][0]['selection_id'], early['selection_id'])

        # A kind filter leaves only not-yet-observed selections; ordinary waiting is success, not failure.
        self.selection()
        code, waiting = run('--auto-all', '--kind', 'OBSERVED_EXPERT', '--windows', '10')
        self.assertEqual(code, 0); self.assertTrue(waiting['ok']); self.assertEqual(waiting['status'], 'SUCCESS')
        self.assertEqual((waiting['data']['windows_pending'], waiting['data']['windows_failed']), (2, 0))

        code, failed = run('--auto-all', '--kind', 'HUMAN_RECONSTRUCTION', '--windows', '1')
        self.assertEqual(code, 2); self.assertFalse(failed['ok']); self.assertEqual(failed['status'], 'FAILED')
        self.assertEqual((failed['data']['windows_frozen'], failed['data']['windows_failed']), (0, 1))

    def test_cli_read_commands_do_not_report_success_for_incomplete_reviews(self):
        self.capture_days(range(1, 6)); self.capture_reference(5)
        selection = self.selection()
        self.service().build(selection['selection_id'], [1, 2])
        folder = self.output / '_trading' / 'selection_outcomes' / selection['selection_id']
        (folder / 'D1.json').write_text('broken fixture', encoding='utf-8')
        for args in (('--get', selection['selection_id']), ('--list',), ('--summary',)):
            with self.subTest(args=args):
                stream = io.StringIO()
                with redirect_stdout(stream):
                    code = selection_cli(['--output', str(self.output), *args])
                reply = json.loads(stream.getvalue())
                self.assertEqual(code, 3)
                self.assertFalse(reply['ok'])
                self.assertEqual(reply['status'], 'PARTIAL_FAILURE')
                self.assertTrue(reply['data']['incomplete'])
                self.assertEqual(len(reply['data']['errors']), 1)
        (folder / 'D2.json').write_text('also broken fixture', encoding='utf-8')
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = selection_cli(['--output', str(self.output), '--summary'])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stream.getvalue())['status'], 'FAILED')


if __name__ == '__main__':
    unittest.main()

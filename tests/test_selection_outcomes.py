from contextlib import redirect_stdout
from datetime import date, datetime, timezone
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
    def __init__(self, prices=PRICES):
        super().__init__(); self.prices = prices
    def query_daily_history_k_AStock(self, date=''):
        index = next(i for i in self.prices if T(i).isoformat() == date)
        rows = [daily_row(T(index), code, price) for code, price in sorted(self.prices[index].items())]
        return Resp(EXPECTED_FIELDS, [[row[name] for name in EXPECTED_FIELDS] for row in rows])


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

    def capture_reference(self, i):
        self.clock[0] = local(i, 19, 30)
        ForwardReferenceArchive(self.output, now_fn=lambda: self.clock[0]).capture(sdk=MarketSDK())

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
        again = self.service().build(selection['selection_id'], [1, 2])
        self.assertEqual(again['created'], 0)
        self.assertEqual(again['records'][0]['review_hash'], first['records'][0]['review_hash'])
        self.capture_days([4])
        later = self.service().build(selection['selection_id'], [1, 2])
        self.assertEqual([row['window_label'] for row in later['records']], ['D1', 'D2']); self.assertEqual(later['created'], 1)

    def test_accepted_market_revision_conflicts_with_a_frozen_review(self):
        self.capture_days(range(1, 6)); self.capture_reference(5)
        selection = self.selection()
        self.service().build(selection['selection_id'], [1])
        revised = {**PRICES, 3: {**PRICES[3], A: (11.5, 11)}}
        self.clock[0] = local(5, 20, 0)
        revision = self.daily.capture(T(3), sdk=MarketSDK(revised))
        self.assertTrue(revision['revision_detected'])
        self.daily.accept_revision(T(3), revision['snapshot_id'], confirmed=True)
        with self.assertRaises(SelectionOutcomeError) as error:
            self.service().build(selection['selection_id'], [1])
        self.assertEqual(error.exception.code, 'REVIEW_CONFLICT')

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
        self.assertEqual(batch['windows_frozen'], 1)
        self.assertEqual([(e['selection_id'], e['code']) for e in batch['errors']], [(early['selection_id'], 'OUTSIDE_CALENDAR')])
        self.assertEqual(self.service().get(good['selection_id'])['records'][0]['window_label'], 'D1')

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
        code, summary = run('--summary')
        self.assertEqual(code, 0); self.assertEqual(len(summary['data']['rows']), 2)
        code, bad = run('--selection-id', selection['selection_id'], '--windows', '1,x')
        self.assertEqual(code, 2); self.assertFalse(bad['ok'])


if __name__ == '__main__':
    unittest.main()

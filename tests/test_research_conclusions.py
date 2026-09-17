from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, uuid4, uuid5
import contextlib
import io
import json
import shutil
import unittest
from unittest import mock

from limit_research_fixtures import CAL, build_research_workspace
from test_auto_research import EXECUTION, ScriptedRegistry, proposal, result, scope
from quantlab.agent.auto_research_cli import main as cli_main
from quantlab.agent.catalog import ReadOnlyResearchAPI
from quantlab.agent.limit_research_tools import TOOL_NAMES, LimitResearchAPI
from quantlab.agent.peer_review import SAFE_TOOLS
from quantlab.statistics.permutation import holm
from quantlab.storage.codec import digest
from quantlab.trading.auto_research import AutoResearch, AutoResearchError
from quantlab.trading.event_study import EventStudyError, EventStudyRegistry
from quantlab.trading.research_conclusions import ConclusionLibrary, decay_state

UTC = timezone.utc


class FakeEvents:
    def __init__(self):
        self.build_id, self.through = 'lib-1', date(2027, 12, 31)
    def latest_covering(self, day):
        return {'build_id': self.build_id} if date.fromisoformat(day) <= self.through else None


class FakeConfirmRegistry:
    """Confirmation-family registry: runs return scripted p-values; measure returns scripted monitoring windows."""

    def __init__(self, p_values):
        self.p_values, self.studies, self.results, self.measures, self.monitor = p_values, {}, {}, [], []

    def normalize_spec(self, spec):
        return spec

    def register(self, spec):
        study_id = str(uuid5(NAMESPACE_URL, 'fake:' + digest(spec)))
        self.studies[study_id] = spec
        return {'study_id': study_id, 'spec': spec, 'created': True}

    def get(self, family, study_id):
        return {'spec': self.studies[study_id], 'result': self.results.get(study_id)}

    def run(self, family, study_id):
        self.results[study_id] = result(p=self.p_values[self.studies[study_id]['condition']])
        return self.get(family, study_id)

    def family_report(self, family):
        ids = [s for s, spec in self.studies.items() if spec['family'] == family]
        p = [self.results[s]['samples']['all']['test']['p_value'] if s in self.results else None for s in ids]
        return {'studies': [{'study_id': s, 'p_value': v, 'p_holm': h, 'tested_value': self.results[s]['samples']['all']['daily_mean'] if s in self.results else None}
                            for s, v, h in zip(ids, p, holm(p))]}

    def measure(self, spec, windows, *, seed_key):
        self.measures.append((spec, windows))
        behaviour = self.monitor.pop(0)
        if isinstance(behaviour, Exception):
            raise behaviour
        days, value = behaviour
        window = lambda s, e: {'start': s, 'end': e, 'sample': {'events': days * 3, 'days': days, 'daily_mean': value, 'test': {'p_value': 0.2}},
                               'execution': None}
        return {'library_events_sha256': 'x', 'windows': {name: window(*bounds) for name, bounds in windows.items()}}


class ConclusionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = TemporaryDirectory(); cls.output = Path(cls.tmp.name)
        cls.ids = build_research_workspace(cls.output)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        for folder in ('auto_research', 'conclusions'):
            shutil.rmtree(self.output / '_limit_research' / folder, ignore_errors=True)
        self.now = [datetime(2026, 12, 1, 11, 0, tzinfo=UTC)]

    def code(self, call, *args, **kwargs):
        with self.assertRaises(AutoResearchError) as caught:
            call(*args, **kwargs)
        return caught.exception.code

    def test_measure_matches_a_registered_run(self):
        registry = EventStudyRegistry(self.output, now_fn=lambda: self.now[0])
        record = registry.register({'family': 'measure-test', 'hypothesis': '涨停收盘次日开盘买入的净收益', 'library_build_id': self.ids['events']['build_id'],
                                    'condition': 'is_limit_up_close or touched_limit_up', 'outcome': 'net_return', 'min_events': 10, 'execution': EXECUTION})
        ran = registry.run('measure-test', record['study_id'])['result']
        self.assertEqual(registry.normalize_spec(record['spec']), record['spec'])  # normalizing a frozen spec is idempotent
        with self.assertRaises(EventStudyError):
            registry.normalize_spec({**record['spec'], 'execution': {**record['spec']['execution'], 'model_version': 'limit-execution-model-v0'}})
        window = (CAL[0].isoformat(), CAL[-1].isoformat())
        measured = registry.measure(record['spec'], {'all': window, 'late': (CAL[20].isoformat(), CAL[-1].isoformat())}, seed_key=record['study_id'])
        self.assertEqual(measured['windows']['all']['sample'], ran['samples']['all'])
        self.assertEqual((measured['windows']['all']['execution'], measured['windows']['all']['by_year_tested']), (ran['execution']['all'], ran['by_year_tested']))
        self.assertLessEqual(measured['windows']['late']['sample']['events'], ran['samples']['all']['events'])
        self.assertFalse((self.output / '_limit_research' / 'event_studies' / 'measure-test' / 'late').exists())
        bounded = {**record['spec'], 'start': CAL[5].isoformat(), 'end': CAL[30].isoformat()}
        for windows in ({}, {'bad': (CAL[10].isoformat(), CAL[9].isoformat())}, {'outside': (CAL[0].isoformat(), CAL[30].isoformat())}, {'x': ('2026-13-01', '2027-01-01')}):
            with self.assertRaises(EventStudyError):
                registry.measure(bounded, windows, seed_key='k')

    def test_promotion_family_holm_monitoring_and_retirement(self):
        screening = ScriptedRegistry(self.output, lambda: self.now[0], {'touched_limit_up': 'pass', 'is_first_board': 'pass', 'is_one_word_limit_up': 'pass'})
        auto = AutoResearch(self.output, now_fn=lambda: self.now[0], registry=screening)
        plan = auto.preview_plan(scope(), expires_at=(self.now[0] + timedelta(days=20)).isoformat(), studies_per_week=10, runs_per_night=4)
        auto.authorize_plan(plan, digest(plan), confirmed=True)
        items = {}
        for condition in ('touched_limit_up', 'is_first_board', 'is_one_word_limit_up', 'is_limit_up_close'):
            self.now[0] += timedelta(seconds=1)
            items[condition] = auto.propose(str(uuid4()), proposal(condition=condition), proposer='ai:chat')['item_id']
        self.assertEqual([r['state'] for r in auto.run()['ran']], ['SCREENED_PASS', 'SCREENED_PASS', 'SCREENED_PASS', 'SCREENED_FAIL'])
        registry, events = FakeConfirmRegistry({'touched_limit_up': 0.03, 'is_first_board': 0.001, 'is_one_word_limit_up': 0.06}), FakeEvents()
        self.now[0] = datetime(2027, 3, 1, 4, 0, tzinfo=UTC)
        library = ConclusionLibrary(self.output, now_fn=lambda: self.now[0], registry=registry, auto=auto, event_library=events)
        x, a, b = items['touched_limit_up'], items['is_first_board'], items['is_one_word_limit_up']
        self.assertEqual(self.code(library.preview_promotion, items['is_limit_up_close'], '2027-02-01'), 'NOT_PROMOTABLE')
        self.assertEqual([self.code(library.preview_promotion, x, end) for end in ('2027-01-10', '2027-03-01', '2027/02/01')], ['INVALID_WINDOW'] * 3)
        self.assertEqual(self.code(library.preview_promotion, str(uuid4()), '2027-02-01'), 'NOT_FOUND')
        preview = library.preview_promotion(x, '2027-02-01')
        spec = preview['confirmation_spec']
        self.assertEqual((spec['family'], spec['start'], spec['end'], spec['split_date'], spec['library_build_id'], preview['registered_confirmations_before']),
                         ('auto-lab-confirm', plan['locked_out_of_sample_start'], '2027-02-01', None, 'lib-1', 0))
        tampered = {**preview, 'confirmation_window': {**preview['confirmation_window'], 'end': '2027-02-10'}}
        self.assertEqual([self.code(library.promote, preview, digest(preview)), self.code(library.promote, preview, '0' * 64, confirmed=True),
                          self.code(library.promote, tampered, digest(tampered), confirmed=True)],
                         ['CONFIRMATION_REQUIRED', 'DIGEST_MISMATCH', 'PROMOTION_TAMPERED'])
        self.now[0] += timedelta(minutes=31)
        self.assertEqual(self.code(library.promote, preview, digest(preview), confirmed=True), 'PREVIEW_EXPIRED')

        def promote(item_id):
            value = library.preview_promotion(item_id, '2027-02-01')
            return library.promote(value, digest(value), confirmed=True)['conclusion_id']

        cx = promote(x)
        self.assertEqual((library.get(cx)['status'], library.is_current(date(2027, 2, 20))), ('PENDING_RUN', False))
        self.assertEqual(self.code(library.preview_promotion, x, '2027-02-01'), 'ALREADY_PROMOTED')
        first = library.confirm()
        self.assertEqual((first['ran'], first['changed'][0]['outcome'], first['changed'][0]['p_holm'], library.get(cx)['status']), ([cx], 'CONFIRMED', 0.03, 'MONITORING'))
        self.assertEqual(library.get(cx)['confirmation']['checklist']['stage'], 'confirmation')
        ca, cb = promote(a), promote(b)
        library.confirm()  # the family grew to three: Holm re-judges the earlier confirmation
        judged = {cid: library.get(cid)['confirmation'] for cid in (cx, ca, cb)}
        self.assertEqual({cid: (c['outcome'], round(c['p_holm'], 6), c['family_size']) for cid, c in judged.items()},
                         {cx: ('NOT_CONFIRMED', 0.06, 3), ca: ('CONFIRMED', 0.003, 3), cb: ('NOT_CONFIRMED', 0.06, 3)})
        self.assertEqual([h['status'] for h in library.get(cx)['status_history']], ['PENDING_RUN', 'MONITORING', 'NOT_CONFIRMED'])
        self.assertEqual(library.evaluate(date(2027, 2, 1))['evaluated'], [])  # no data after the confirmation window yet
        registry.monitor = [(8, 0.02)]
        self.assertEqual(library.evaluate(date(2027, 2, 10))['evaluated'], [{'conclusion_id': ca, 'health': 'INSUFFICIENT_FORWARD_DATA', 'reasons': [], 'status': 'MONITORING'}])
        measured_spec, windows = registry.measures[-1]
        self.assertEqual((measured_spec['start'], measured_spec['end'], windows['forward'], windows['recent']),
                         ('2027-02-02', '2027-02-10', ('2027-02-02', '2027-02-10'), ('2027-02-02', '2027-02-10')))
        self.assertTrue(library.is_current(date(2027, 2, 10)))
        self.assertEqual(library.evaluate(date(2027, 2, 10))['evaluated'], [])  # already current
        events.build_id = 'lib-2'
        self.assertFalse(library.is_current(date(2027, 2, 10)))  # the event library was rebuilt: measure again
        registry.monitor = [(9, 0.02), (40, 0.012), (45, 0.004), (60, -0.01), RuntimeError('panel unavailable')]
        library.evaluate(date(2027, 2, 10))
        self.assertEqual(library.evaluate(date(2027, 8, 30))['evaluated'][0]['health'], 'HEALTHY')
        self.assertEqual(registry.measures[-1][1]['recent'], ('2027-03-04', '2027-08-30'))  # rolling 180-day window (inclusive)
        shrunk = library.evaluate(date(2027, 9, 1))['evaluated'][0]
        self.assertEqual((shrunk['health'], shrunk['reasons'], shrunk['status']), ('DECAYING', ['EFFECT_SHRUNK'], 'DECAYING'))
        reversed_ = library.evaluate(date(2027, 9, 2))['evaluated'][0]
        self.assertEqual((reversed_['reasons'], library.list(status='DECAYING')[0]['latest_monitoring']['windows']['recent']['value']), (['SIGN_REVERSED'], -0.01))
        self.assertEqual(self.code(library.evaluate, date(2027, 9, 3)), 'MONITOR_ERROR')
        self.assertEqual((library.get(ca)['status'], library.get(ca)['evaluations'][-1]['health'], library.is_current(date(2027, 9, 3))), ('DECAYING', 'ERROR', False))
        self.assertEqual(self.code(library.retire, ca, '衰减后宿主退役'), 'CONFIRMATION_REQUIRED')
        self.assertEqual(self.code(library.retire, ca, '短', confirmed=True), 'INVALID_ARGUMENT')
        retired = library.retire(ca, '前瞻效果反向，宿主退役', confirmed=True)
        self.assertEqual((retired['status'], library.is_current(date(2027, 9, 3)), library.evaluate(date(2027, 9, 3))['evaluated']), ('RETIRED', True, []))
        ledger = library.ledger()
        self.assertEqual((ledger['proposals'], ledger['proposal_states'], ledger['conclusion_statuses']),
                         (4, {'SCREENED_PASS': 3, 'SCREENED_FAIL': 1}, {'NOT_CONFIRMED': 2, 'RETIRED': 1}))
        api = LimitResearchAPI(ReadOnlyResearchAPI(self.output), now_fn=lambda: self.now[0])
        self.assertIn('list_research_conclusions', TOOL_NAMES); self.assertIn('list_research_conclusions', SAFE_TOOLS)
        listed = api.call('list_research_conclusions', {'status': ''})
        self.assertTrue(listed['ok']); self.assertEqual((listed['data']['total'], listed['data']['ledger']['conclusions']), (3, 3))
        self.assertEqual(api.call('list_research_conclusions', {'status': 'RETIRED'})['data']['conclusions'][0]['retire_reason'], '前瞻效果反向，宿主退役')
        self.assertFalse(api.call('list_research_conclusions', {'status': 'BAD'})['ok'])
        def cli(*args):
            stream = io.StringIO()
            with mock.patch('quantlab.agent.auto_research_cli.AutoResearch', lambda output: AutoResearch(output, now_fn=lambda: self.now[0])), \
                    contextlib.redirect_stdout(stream):
                code = cli_main(['--output', str(self.output), *args])
            return code, json.loads(stream.getvalue())
        code, listed = cli('--call', 'conclusions')
        self.assertEqual((code, len(listed['data']['conclusions']), listed['data']['ledger']['proposals']), (0, 3, 4))
        self.assertEqual(cli('--call', 'promote-preview', '--item-id', x)[1]['error']['code'], 'INVALID_REQUEST')
        self.assertEqual(cli('--call', 'retire', '--conclusion-id', cb, '--reason', '宿主手动退役测试')[1]['error']['code'], 'CONFIRMATION_REQUIRED')
        self.assertEqual(cli('--call', 'retire', '--conclusion-id', cb, '--reason', '宿主手动退役测试', '--confirm')[1]['data']['status'], 'RETIRED')

    def test_decay_rule_with_execution(self):
        conclusion = {'expected_sign': 'positive', 'baseline_condition': None, 'execution': EXECUTION, 'confirmation': {'tested_value': 0.01}}
        window = lambda days, value, fill, net: {'sample': {'days': days, 'daily_mean': value}, 'execution': {'fill_rate': fill, 'mean_net_return': net}}
        self.assertEqual(decay_state(conclusion, window(30, 0.011, 0.8, 0.004))[:2], ('HEALTHY', []))
        self.assertEqual(decay_state(conclusion, window(30, 0.011, 0.3, -0.001))[:2], ('DECAYING', ['FILL_RATE_LOW', 'NET_RETURN_NOT_POSITIVE']))
        self.assertEqual(decay_state({**conclusion, 'expected_sign': 'negative'}, window(30, 0.011, 0.8, 0.004))[:2], ('DECAYING', ['SIGN_REVERSED']))
        self.assertEqual(decay_state({**conclusion, 'baseline_condition': 'x'}, {'sample': {'days': 30, 'mean_daily_difference': 0.02}, 'execution': None})[:2],
                         ('HEALTHY', []))


if __name__ == '__main__':
    unittest.main()

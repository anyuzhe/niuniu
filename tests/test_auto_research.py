from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from uuid import uuid4
import contextlib
import io
import json
import shutil
import unittest

from limit_research_fixtures import T, build_research_workspace
from quantlab.agent.auto_research_cli import main as cli_main
from quantlab.agent.catalog import ReadOnlyResearchAPI
from quantlab.agent.limit_research_tools import TOOL_NAMES, WRITE_TOOL_NAMES, LimitResearchAPI
from quantlab.agent.peer_review import SAFE_TOOLS
from quantlab.storage.codec import digest
from quantlab.trading import auto_research
from quantlab.trading.auto_research import AutoResearch, AutoResearchError, embargo_days, evaluate_checklist, study_test_key
from quantlab.trading.event_study import EventStudyError, EventStudyRegistry

UTC = timezone.utc
EXECUTION = {'entry': 't1_open', 'exit': 'next_open', 'scenario': 'conservative', 'commission_bps': 2.5, 'slippage_bps': 5.0,
             'max_hold_sessions': 10}


def scope(**overrides):
    return {'family_prefix': 'auto-lab', 'start': '2019-01-02', 'in_sample_end': T(30).isoformat(),
            'outcomes': ['t1_open_ret', 't1_is_limit_up_close', 'net_return'], 'executions': [EXECUTION],
            'allow_sentiment': False, 'allow_details': False, 'min_events': 30, **overrides}


def proposal(**overrides):
    return {'family': 'auto-lab-gap', 'hypothesis': '涨停收盘后次日开盘收益为正', 'expected_sign': 'positive', 'condition': 'is_limit_up_close',
            'baseline_condition': None, 'outcome': 't1_open_ret', 'execution': None, 'group_by': None, 'use_sentiment': False, **overrides}


def years(*values, days=60):
    return [{'year': str(2019 + i), 'days': days, 'events': 100, 'value': v} for i, v in enumerate(values)]


def result(value=0.01, p=0.001, events=500, days=300, year_share=0.2, day_share=0.05, by_year=None, execution=None, difference=None):
    sample = {'events': events, 'days': days, 'daily_mean': value, 'max_year_event_share': year_share, 'top5_day_event_share': day_share,
              'test': {'status': 'computed', 'p_value': p}}
    if difference is not None:
        sample['mean_daily_difference'] = difference
    return {'samples': {'all': sample}, 'by_year_tested': years(*[value] * 5) if by_year is None else by_year,
            'execution': None if execution is None else {'all': execution}}


def spec(**overrides):
    return {'condition': 'is_limit_up_close', 'baseline_condition': None, 'outcome': 't1_open_ret', 'expected_sign': 'positive',
            'min_events': 30, 'execution': None, **overrides}


class ScriptedRegistry(EventStudyRegistry):
    """Real registry whose runs are scripted per condition: pass (synthetic result), crash, reject, or real."""

    def __init__(self, output, now_fn, script):
        super().__init__(output, now_fn=now_fn)
        self.script = script

    def register(self, spec):
        if self.script.get(spec['condition']) == 'reject':
            raise EventStudyError('INVALID_SPEC', '模拟登记被拒绝')
        return super().register(spec)

    def run(self, family, study_id):
        record = self.get(family, study_id)
        behaviour = self.script.get(record['spec']['condition'])
        if behaviour == 'crash':
            raise RuntimeError('boom')
        if behaviour == 'pass':
            return {**record, 'result': result(), 'created': True}
        return super().run(family, study_id)


class ChecklistTests(unittest.TestCase):
    def test_passing_study_and_each_skeptic_failure(self):
        passed = evaluate_checklist(spec(), result())
        self.assertTrue(passed['passed']); self.assertEqual(passed['failed'], []); self.assertTrue(passed['warnings'])
        self.assertEqual({i['key']: i['status'] for i in passed['items']}['execution_feasibility'], 'NOT_APPLICABLE')
        cases = {'sample_size': result(events=20), 'significance': result(p=0.02), 'direction': result(value=-0.01),
                 'economic_magnitude': result(value=0.001), 'year_concentration': result(year_share=0.5),
                 'day_concentration': result(day_share=0.3), 'year_stability': result(by_year=years(0.01, -0.01, -0.02)),
                 'lookahead_guard': result()}
        for key, value in cases.items():
            checked = spec(condition='close > open', execution={**EXECUTION, 'entry': 't0_limit_price'}) if key == 'lookahead_guard' else spec()
            self.assertIn(key, evaluate_checklist(checked, value)['failed'], key)
        unavailable = result(); unavailable['samples']['all']['test'] = {'status': 'unavailable', 'p_value': None}
        self.assertIn('significance', evaluate_checklist(spec(), unavailable)['failed'])
        self.assertIn('year_stability', evaluate_checklist(spec(), result(by_year=years(0.01, 0.01, 0.01, 0.01, days=4)))['failed'])
        self.assertTrue(evaluate_checklist(spec(), result(by_year=years(0.01, 0.01, -0.01, 0.01, 0.01, days=6)))['passed'])  # rare regimes still judged
        confirmed = evaluate_checklist(spec(), result(p=0.03), p_value=0.004, p_threshold=0.05)
        self.assertTrue(confirmed['passed'])

    def test_execution_baseline_and_test_identity(self):
        good = {'entered': 400, 'fill_rate': 0.8, 'unresolved_exits': 4, 'mean_net_return': 0.003}
        traded = spec(outcome='net_return', execution={**EXECUTION, 'model_version': 'limit-execution-model-v1'})
        self.assertTrue(evaluate_checklist(traded, result(execution=good))['passed'])
        self.assertIn('execution_feasibility', evaluate_checklist(traded, result(execution={**good, 'fill_rate': 0.4}))['failed'])
        self.assertIn('execution_feasibility', evaluate_checklist(traded, result(execution={**good, 'unresolved_exits': 40}))['failed'])
        self.assertIn('net_of_costs', evaluate_checklist(traded, result(execution={**good, 'mean_net_return': -0.001}))['failed'])
        avoid = evaluate_checklist({**traded, 'expected_sign': 'negative'}, result(value=-0.01, execution={**good, 'mean_net_return': -0.01}))
        self.assertTrue(avoid['passed'])  # an "avoid" hypothesis is not required to make money
        rate = spec(outcome='t1_is_limit_up_close', baseline_condition='touched_limit_up')
        self.assertIn('economic_magnitude', evaluate_checklist(rate, result(value=0.4, difference=0.01, by_year=years(*[0.01] * 5)))['failed'])
        self.assertTrue(evaluate_checklist(rate, result(value=0.4, difference=0.05, by_year=years(*[0.05] * 5)))['passed'])
        self.assertEqual((embargo_days([]), embargo_days([EXECUTION]), embargo_days([{**EXECUTION, 'max_hold_sessions': 60}])), (18, 38, 138))
        base = {**spec(), 'family': 'auto-a', 'hypothesis': 'x', 'start': '2019-01-02', 'end': '2026-01-01', 'sentiment_build_id': None,
                'library_build_id': 'a', 'group_by': None}
        same = {**base, 'family': 'auto-b', 'hypothesis': 'y', 'expected_sign': 'negative', 'condition': '(is_limit_up_close)',
                'library_build_id': 'b', 'group_by': 'board'}
        self.assertEqual(study_test_key(base), study_test_key(same))
        self.assertNotEqual(study_test_key(base), study_test_key({**base, 'outcome': 't1_close_ret'}))
        self.assertNotEqual(study_test_key(base), study_test_key({**base, 'condition': 'is_limit_up_close and is_first_board'}))


class AutoResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = TemporaryDirectory(); cls.output = Path(cls.tmp.name)
        cls.ids = build_research_workspace(cls.output)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        shutil.rmtree(self.output / '_limit_research' / 'auto_research', ignore_errors=True)
        self.now = [datetime(2026, 12, 1, 4, 0, tzinfo=UTC)]  # Tuesday 12:00 Beijing
        self.auto = AutoResearch(self.output, now_fn=lambda: self.now[0])

    def authorize(self, auto=None, days=20, **kwargs):
        auto = auto or self.auto
        plan = auto.preview_plan(kwargs.pop('scope', scope()), expires_at=(self.now[0] + timedelta(days=days)).isoformat(), **kwargs)
        return auto.authorize_plan(plan, digest(plan), confirmed=True)

    def code(self, call, *args, **kwargs):
        with self.assertRaises(AutoResearchError) as caught:
            call(*args, **kwargs)
        return caught.exception.code

    def test_plan_preview_authorize_expire_and_revoke(self):
        expires = (self.now[0] + timedelta(days=20)).isoformat()
        for bad, at in ((scope(), (self.now[0] + timedelta(days=31)).isoformat()), (scope(family_prefix='lab'), expires),
                        (scope(family_prefix='auto-lab-confirm'), expires), (scope(start='2024-01-02'), expires),
                        (scope(in_sample_end='2026-12-01'), expires), (scope(executions=[]), expires), (scope(outcomes=['t1_open_ret']), expires),
                        ({**scope(), 'extra': 1}, expires), (scope(min_events=10), expires), (scope(), '2026-12-10T00:00:00')):
            self.assertEqual(self.code(self.auto.preview_plan, bad, expires_at=at), 'INVALID_PLAN', bad)
        plan = self.auto.preview_plan(scope(), expires_at=expires, studies_per_week=5, runs_per_night=2)
        self.assertEqual((plan['embargo_days'], plan['confirmation_family'], plan['boundaries']['agent_actions']), (38, 'auto-lab-confirm', 'propose_only'))
        self.assertEqual(plan['locked_out_of_sample_start'], (T(30) + timedelta(days=39)).isoformat())
        tampered, invalid = {**plan, 'embargo_days': 0}, {**plan, 'budget': {'studies_per_week': 51, 'runs_per_night': 2}}
        self.assertEqual([self.code(self.auto.authorize_plan, plan, digest(plan)), self.code(self.auto.authorize_plan, plan, '0' * 64, confirmed=True),
                          self.code(self.auto.authorize_plan, tampered, digest(tampered), confirmed=True),
                          self.code(self.auto.authorize_plan, invalid, digest(invalid), confirmed=True)],
                         ['CONFIRMATION_REQUIRED', 'DIGEST_MISMATCH', 'PLAN_TAMPERED', 'INVALID_PLAN'])
        self.now[0] += timedelta(minutes=31)
        self.assertEqual(self.code(self.auto.authorize_plan, plan, digest(plan), confirmed=True), 'PREVIEW_EXPIRED')
        self.now[0] -= timedelta(minutes=31)
        state = self.auto.authorize_plan(plan, digest(plan), confirmed=True)
        self.assertEqual((self.auto.active_plan()['plan_id'], state['status'], state['cancelled_pending']), (state['plan_id'], 'active', 0))
        again = self.auto.preview_plan(scope(), expires_at=expires)
        self.assertEqual(self.code(self.auto.authorize_plan, again, digest(again), confirmed=True), 'PLAN_ACTIVE')
        self.assertEqual(self.auto.status()['plan']['status'], 'active')
        self.auto.propose(str(uuid4()), proposal(), proposer='ai:chat')
        self.assertEqual(self.code(self.auto.revoke_plan, state['plan_id']), 'CONFIRMATION_REQUIRED')
        self.assertEqual(self.code(self.auto.revoke_plan, str(uuid4()), confirmed=True), 'NOT_FOUND')
        revoked = self.auto.revoke_plan(state['plan_id'], confirmed=True)
        self.assertEqual((revoked['status'], revoked['cancelled_pending'], self.auto.items()[0]['state']), ('revoked', 1, 'CANCELLED'))
        self.assertIsNone(self.auto.active_plan())
        self.assertEqual(self.code(self.auto.propose, str(uuid4()), proposal(condition='touched_limit_up'), proposer='ai:chat'), 'PLAN_INACTIVE')
        second = self.authorize(days=1)
        self.assertTrue((self.output / '_limit_research' / 'auto_research' / 'plan' / 'history' / f"{state['plan_id']}.json").is_file())
        self.now[0] += timedelta(days=1, hours=1)
        self.assertIsNone(self.auto.active_plan())
        self.assertEqual((self.auto.status()['plan']['plan_id'], self.auto.status()['plan']['status']), (second['plan_id'], 'expired'))
        self.assertEqual(self.auto.run()['status'], 'PLAN_INACTIVE')
        third = self.authorize()  # an expired plan is archived as expired, not treated as active
        history = json.loads((self.output / '_limit_research' / 'auto_research' / 'plan' / 'history' / f"{second['plan_id']}.json").read_text())
        self.assertEqual((history['status'], self.auto.active_plan()['plan_id']), ('expired', third['plan_id']))

    def test_proposal_validation_duplicates_and_queue_limits(self):
        self.authorize()
        request = str(uuid4())
        item = self.auto.propose(request, proposal(), proposer='ai:chat')
        self.assertEqual((item['created'], item['state'], item['spec']['end'], item['spec']['split_date'], item['spec']['sentiment_build_id']),
                         (True, 'PENDING', T(30).isoformat(), None, None))
        self.assertEqual(item['spec']['library_build_id'], self.ids['events']['build_id'])
        self.assertFalse(self.auto.propose(request, proposal(), proposer='ai:chat')['created'])
        self.assertEqual(self.code(self.auto.propose, request, proposal(hypothesis='同一请求号的另一份提案'), proposer='ai:chat'), 'REQUEST_CONFLICT')
        duplicate = self.auto.propose(str(uuid4()), proposal(family='auto-lab-renamed', hypothesis='换个说法的同一检验', expected_sign='negative',
                                                             condition='(is_limit_up_close)', group_by='board'), proposer='ai:mcp')
        self.assertEqual((duplicate['created'], duplicate['duplicate_of']), (False, item['item_id']))
        cases = {'OUT_OF_PLAN': [proposal(family='lab-gap'), proposal(family='auto-labx'), proposal(family='auto-lab-' + 'x' * 30),
                                 proposal(family='auto-lab-confirm'), proposal(outcome='t1_close_ret'),
                                 proposal(outcome='net_return', execution={**EXECUTION, 'slippage_bps': 9.0}),
                                 proposal(condition='is_limit_up_close and mkt_limit_up_count > 10'), proposal(use_sentiment=True),
                                 proposal(group_by='mkt_phase'), proposal(condition='is_limit_up_close and em_first_seal_minute < 30')],
                 'INVALID_PROPOSAL': [proposal(expected_sign='none'), proposal(outcome='t1_is_limit_up_close'), {**proposal(), 'extra': 1},
                                      proposal(execution={'entry': 'bad'}), proposal(use_sentiment='yes')],
                 'INVALID_CONDITION': [proposal(condition='is_limit_up_close and')],
                 'LABEL_IN_CONDITION': [proposal(condition='t1_open_ret > 0')],
                 'INVALID_SPEC': [proposal(hypothesis='短'), proposal(group_by='weekday'), proposal(outcome='net_return')]}
        for expected, proposals in cases.items():
            for value in proposals:
                self.assertEqual(self.code(self.auto.propose, str(uuid4()), value, proposer='ai:chat'), expected, value)
        self.assertEqual(self.code(self.auto.propose, 'abc', proposal(), proposer='ai:chat'), 'INVALID_ARGUMENT')
        self.assertEqual(self.code(self.auto.propose, str(uuid4()).upper(), proposal(), proposer='ai:chat'), 'INVALID_ARGUMENT')
        self.assertEqual(self.code(self.auto.propose, str(uuid4()), proposal(), proposer='bot'), 'INVALID_ARGUMENT')
        traded = self.auto.propose(str(uuid4()), proposal(outcome='net_return', execution=dict(EXECUTION, slippage_bps=5)), proposer='host:manual')
        self.assertEqual(traded['spec']['execution'], EXECUTION)
        with mock.patch.object(auto_research, 'QUEUE_LIMIT', 3):
            self.auto.propose(str(uuid4()), proposal(condition='touched_limit_up'), proposer='ai:chat')
            self.assertEqual(self.code(self.auto.propose, str(uuid4()), proposal(condition='is_first_board'), proposer='ai:chat'), 'QUEUE_FULL')
        self.auto.revoke_plan(self.auto.active_plan()['plan_id'], confirmed=True)
        self.authorize(scope=scope(allow_sentiment=True))
        mood = self.auto.propose(str(uuid4()), proposal(condition='is_limit_up_close and mkt_limit_up_count >= 1', baseline_condition='is_limit_up_close',
                                                        outcome='t1_is_limit_up_close'), proposer='ai:chat')
        self.assertEqual(mood['spec']['sentiment_build_id'], self.ids['sentiment']['build_id'])
        self.auto.revoke_plan(self.auto.active_plan()['plan_id'], confirmed=True)
        self.authorize(scope=scope(in_sample_end='2026-07-31'))
        self.assertEqual(self.code(self.auto.propose, str(uuid4()), proposal(), proposer='ai:chat'), 'RESEARCH_BUILD_MISSING')
        queue_file = next((self.output / '_limit_research' / 'auto_research' / 'queue').glob('*.json'))
        queue_file.write_text(queue_file.read_text().replace('PENDING', 'SCREENED_PASS').replace('CANCELLED', 'SCREENED_PASS'))
        self.assertEqual(self.code(self.auto.status), 'CORRUPT_ARCHIVE')

    def test_nightly_budgets_screening_and_recovery(self):
        registry = ScriptedRegistry(self.output, lambda: self.now[0], {'touched_limit_up': 'pass', 'is_first_board': 'crash', 'is_broken_board': 'reject'})
        auto = AutoResearch(self.output, now_fn=lambda: self.now[0], registry=registry)
        self.now[0] = datetime(2026, 12, 1, 11, 0, tzinfo=UTC)  # Tuesday 19:00 Beijing
        self.authorize(auto, studies_per_week=3, runs_per_night=2)
        for condition in ('touched_limit_up', 'is_first_board', 'is_limit_up_close', 'is_broken_board', 'is_one_word_limit_up'):
            self.now[0] += timedelta(seconds=1)
            auto.propose(str(uuid4()), proposal(condition=condition), proposer='ai:chat')
        first = auto.run()
        self.assertEqual((first['status'], first['night'], [r['state'] for r in first['ran']]), ('NIGHTLY_BUDGET_EXHAUSTED', '2026-12-01', ['SCREENED_PASS', 'ERROR']))
        self.assertEqual(auto.run()['ran'], [])
        self.now[0] += timedelta(days=1)
        second = auto.run()
        self.assertEqual((second['status'], [r['state'] for r in second['ran']]), ('WEEKLY_BUDGET_EXHAUSTED', ['SCREENED_FAIL']))
        pending = auto.items(state='PENDING')
        self.assertEqual([p['spec']['condition'] for p in pending], ['is_broken_board', 'is_one_word_limit_up'])
        auto._save({**pending[1], 'state': 'REGISTERED', 'night': '2026-12-02', 'registered_at': self.now[0].isoformat()})  # crashed mid-study
        self.now[0] = datetime(2026, 12, 7, 11, 0, tzinfo=UTC)  # next Monday
        third = auto.run(max_runs=1)
        self.assertEqual((third['status'], third['interrupted'], [r['state'] for r in third['ran']], third['week']), ('MAX_RUNS_REACHED', 1, ['REJECTED'], '2026-W50'))
        self.assertEqual(auto.run()['status'], 'QUEUE_EMPTY')
        items = {i['spec']['condition']: i for i in auto.items()}
        self.assertEqual((items['is_one_word_limit_up']['error']['code'], items['is_first_board']['error']['code'], items['is_broken_board']['error']['code']),
                         ('INTERRUPTED', 'RuntimeError', 'INVALID_SPEC'))
        self.assertTrue(items['touched_limit_up']['screening']['passed']); self.assertEqual(items['touched_limit_up']['night'], '2026-12-01')
        failed = items['is_limit_up_close']
        self.assertIn('sample_size', failed['screening']['failed'])
        study = EventStudyRegistry(self.output).get('auto-lab-gap', failed['study_id'])
        self.assertEqual((study['spec']['end'], study['spec']['split_date']), (T(30).isoformat(), None))
        self.assertIn('by_year_tested', study['result'])
        self.assertTrue(auto.propose(str(uuid4()), proposal(condition='is_first_board'), proposer='ai:chat')['created'])  # a crashed test may be retried
        self.assertFalse(auto.propose(str(uuid4()), proposal(condition='touched_limit_up', family='auto-lab-again'), proposer='ai:chat')['created'])
        self.assertTrue(auto.night_done(date(2026, 12, 1))); self.assertFalse(auto.night_done(date(2026, 12, 3)))
        status = auto.status()
        self.assertEqual(status['queue_counts'], {'SCREENED_PASS': 1, 'ERROR': 2, 'SCREENED_FAIL': 1, 'REJECTED': 1, 'PENDING': 1})
        self.assertEqual((status['week'], status['weekly_used'], status['recent'][0]['state']), ('2026-W50', 1, 'PENDING'))
        self.assertEqual((status['recent'][-1]['state'], status['recent'][-1]['failed_checks']), ('SCREENED_PASS', []))
        with auto._flock('run.lock', blocking=False):
            self.assertEqual(self.code(auto.run), 'ALREADY_RUNNING')
        self.assertEqual(self.code(auto.run, night='2026-11-20'), 'INVALID_ARGUMENT')
        self.assertEqual(self.code(auto.run, max_runs=0), 'INVALID_ARGUMENT')

    def cli(self, *args):
        stream = io.StringIO()
        with mock.patch('quantlab.agent.auto_research_cli.AutoResearch', lambda output: AutoResearch(output, now_fn=lambda: self.now[0])), \
                contextlib.redirect_stdout(stream):
            code = cli_main(['--output', str(self.output), *args])
        return code, json.loads(stream.getvalue())

    def test_ai_tools_and_host_cli(self):
        api = LimitResearchAPI(ReadOnlyResearchAPI(self.output), now_fn=lambda: self.now[0])
        reviewer = LimitResearchAPI(ReadOnlyResearchAPI(self.output), allow_forecast_write=False)
        self.assertIn('propose_auto_study', WRITE_TOOL_NAMES); self.assertIn('get_auto_research_status', TOOL_NAMES)
        self.assertIn('get_auto_research_status', SAFE_TOOLS); self.assertNotIn('propose_auto_study', SAFE_TOOLS)
        self.assertNotIn('propose_auto_study', [tool['name'] for tool in reviewer.schemas()])
        self.assertTrue(api.call('get_capabilities', {})['data']['auto_study_proposal_tool'])
        status = api.call('get_auto_research_status', {})
        self.assertTrue(status['ok']); self.assertFalse(status['data']['active'])
        body = json.dumps(proposal(), ensure_ascii=False)
        self.assertEqual(api.call('propose_auto_study', {'request_id': str(uuid4()), 'proposal_json': body})['error']['code'], 'PLAN_INACTIVE')
        folder = self.output / 'host-files'; folder.mkdir()
        scope_file, plan_file, proposal_file = folder / 'scope.json', folder / 'plan.json', folder / 'proposal.json'
        scope_file.write_text(json.dumps(scope())); proposal_file.write_text(json.dumps(proposal(condition='touched_limit_up'), ensure_ascii=False))
        preview_args = ('--call', 'preview', '--scope-file', str(scope_file), '--expires-at', (self.now[0] + timedelta(days=10)).isoformat(),
                        '--plan-out', str(plan_file), '--studies-per-week', '4', '--runs-per-night', '2')
        code, preview = self.cli(*preview_args)
        self.assertEqual((code, preview['data']['plan']['budget']), (0, {'studies_per_week': 4, 'runs_per_night': 2}))
        self.assertEqual(self.cli(*preview_args)[0], 2)  # never overwrites a plan file
        authorize = ('--call', 'authorize', '--plan-file', str(plan_file), '--digest', preview['data']['plan_digest'])
        self.assertEqual(self.cli(*authorize)[1]['error']['code'], 'CONFIRMATION_REQUIRED')
        code, authorized = self.cli(*authorize, '--confirm')
        self.assertEqual((code, authorized['data']['status']), (0, 'active'))
        accepted = api.call('propose_auto_study', {'request_id': str(uuid4()), 'proposal_json': body})
        self.assertTrue(accepted['ok']); self.assertEqual((accepted['data']['state'], accepted['data']['proposer']), ('PENDING', 'ai:chat'))
        self.assertEqual(accepted['evidence'][0]['kind'], 'auto_research_item')
        self.assertFalse(api.call('propose_auto_study', {'request_id': str(uuid4()), 'proposal_json': '{'})['ok'])
        self.assertEqual(self.cli('--call', 'propose', '--proposal-file', str(proposal_file), '--proposer', 'ai:x')[1]['error']['code'], 'INVALID_REQUEST')
        self.assertEqual(self.cli('--call', 'propose', '--proposal-file', str(proposal_file))[0], 0)
        self.assertEqual(api.call('get_limit_research_status', {})['data']['auto_research'], {'active': True, 'plan_status': 'active', 'queue_counts': {'PENDING': 2}})
        self.assertEqual(len(self.cli('--call', 'queue', '--state', 'PENDING')[1]['data']['items']), 2)
        code, ran = self.cli('--call', 'run', '--max-runs', '1')
        self.assertEqual((code, ran['data']['status'], [r['state'] for r in ran['data']['ran']]), (0, 'MAX_RUNS_REACHED', ['SCREENED_FAIL']))
        latest = api.call('get_auto_research_status', {})['data']
        self.assertEqual((latest['weekly_used'], latest['recent'][-1]['state']), (1, 'SCREENED_FAIL'))
        code, revoked = self.cli('--call', 'revoke', '--plan-id', authorized['data']['plan_id'], '--confirm')
        self.assertEqual((code, revoked['data']['status'], revoked['data']['cancelled_pending']), (0, 'revoked', 1))
        shutil.rmtree(folder)


if __name__ == '__main__':
    unittest.main()

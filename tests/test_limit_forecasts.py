from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from zoneinfo import ZoneInfo
import io
import json
import unittest

import polars as pl

from limit_research_fixtures import T, build_research_workspace
from quantlab.agent.catalog import ReadOnlyResearchAPI
from quantlab.agent.limit_forecast_cli import main as cli_main
from quantlab.agent.limit_research_tools import LimitResearchAPI
from quantlab.agent.scorecard import AgentScorecardService
from quantlab.trading.limit_forecasts import QUESTIONS, ForecastError, LimitForecastJournal, outcomes_frame

TZ = ZoneInfo('Asia/Shanghai')


def at(day, hh, mm):
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ)


class OutcomeTests(unittest.TestCase):
    def test_question_resolution_rules(self):
        base = {'limit_up_count_non_st': 30, 'high_board_broken': None, 'broken_rate': 0.35, 'advance_rate_1to2': 0.2,
                'prev_limit_up_avg_return': -0.01, 'limit_down_count_non_st': 12}
        rows = [{'date': date(2026, 9, 14), **base},
                {'date': date(2026, 9, 15), **{**base, 'limit_up_count_non_st': 45, 'high_board_broken': False, 'broken_rate': 0.29,
                                             'advance_rate_1to2': 0.25, 'prev_limit_up_avg_return': 0.02, 'limit_down_count_non_st': 3}},
                {'date': date(2026, 9, 16), **{**base, 'limit_up_count_non_st': 45, 'high_board_broken': True, 'broken_rate': None}}]
        frame = outcomes_frame(pl.DataFrame(rows))
        first, second, third = frame.to_dicts()
        self.assertEqual([first[q] for q in QUESTIONS], [None, None, False, False, False, True])
        self.assertEqual([second[q] for q in QUESTIONS], [True, True, True, True, True, False])
        self.assertEqual((third['limit_up_count_increase'], third['high_board_continues'], third['broken_rate_below_30pct']), (False, False, None))


class JournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = TemporaryDirectory(); cls.output = Path(cls.tmp.name)
        build_research_workspace(cls.output)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def journal(self, when):
        return LimitForecastJournal(self.output, now_fn=lambda: when)

    def test_record_rules_baselines_resolution_scorecard_and_tools(self):
        target = T(28)
        evening = at(T(27), 20, 0)
        journal = self.journal(evening)
        record = dict(forecaster='ai:chat', question_id='limit_up_count_increase', target_day=target.isoformat(), probability=0.7,
                      rationale='昨日高度板加速', evidence=['market_sentiment_build'])
        request = str(uuid4())
        first = journal.record(request_id=request, **record)
        self.assertTrue(first['created']); self.assertFalse(journal.record(request_id=request, **record)['created'])
        with self.assertRaises(ForecastError) as ctx:
            journal.record(request_id=str(uuid4()), **{**record, 'probability': 0.4})
        self.assertEqual(ctx.exception.code, 'CONFLICT')
        cases = [({'target_day': target.isoformat()}, at(target, 9, 15), 'FORECAST_TOO_LATE'),
                 ({'target_day': (target + timedelta(days=14)).isoformat()}, evening, 'FORECAST_TOO_EARLY'),
                 ({'question_id': 'will_it_rain'}, evening, 'UNKNOWN_QUESTION'),
                 ({'probability': 1.2}, evening, 'INVALID_ARGUMENT'), ({'forecaster': 'robot'}, evening, 'INVALID_ARGUMENT')]
        for change, when, code in cases:
            with self.assertRaises(ForecastError) as ctx:
                self.journal(when).record(request_id=str(uuid4()), **{**record, 'question_id': 'broken_rate_below_30pct', **change})
            self.assertEqual(ctx.exception.code, code, change)
        saturday = next(T(1) + timedelta(days=i) for i in range(7) if (T(1) + timedelta(days=i)).weekday() == 5)
        with self.assertRaises(ForecastError) as ctx:
            self.journal(at(saturday - timedelta(days=1), 20, 0)).record(request_id=str(uuid4()), **{**record, 'target_day': saturday.isoformat()})
        self.assertEqual(ctx.exception.code, 'NOT_A_WEEKDAY')
        baselines = journal.generate_baselines(target)
        self.assertEqual(baselines['last_day'], T(27).isoformat())
        self.assertTrue(all(w['forecaster'] == 'baseline:climatology-250' for w in baselines['written']))  # 历史不足 60 日：无相似日基准
        climatology = {f['question_id']: f['probability'] for f in journal.forecasts(target) if f['forecaster'] == 'baseline:climatology-250'}
        self.assertIn('limit_up_count_increase', climatology)
        with self.assertRaises(ForecastError):
            self.journal(at(target, 8, 0)).resolve(T(40) + timedelta(days=30))
        resolution = self.journal(at(target, 20, 0)).resolve(target)
        self.assertTrue(resolution['trading_day'])
        ai = next(i for i in resolution['items'] if i['forecaster'] == 'ai:chat')
        expected = resolution['outcomes']['limit_up_count_increase']
        self.assertEqual(ai['status'], 'RESOLVED'); self.assertAlmostEqual(ai['brier'], (0.7 - float(expected)) ** 2)
        self.assertTrue(journal.is_resolved(target))
        card = journal.scorecard()
        ai_row = next(r for r in card['forecasters'] if r['forecaster'] == 'ai:chat')
        climate_brier = (climatology['limit_up_count_increase'] - float(expected)) ** 2
        self.assertEqual((ai_row['resolved'], ai_row['sample_status'], ai_row['matched_with_climatology']), (1, 'INSUFFICIENT_SAMPLES', 1))
        if climate_brier:
            self.assertAlmostEqual(ai_row['brier_skill_vs_climatology'], 1 - ai['brier'] / climate_brier)
        rows = AgentScorecardService(self.output).build()['rows']
        self.assertTrue(any(r['task_type'] == 'limit_forecast' and r['role_id'] == 'ai:chat' for r in rows))
        api = LimitResearchAPI(ReadOnlyResearchAPI(self.output), now_fn=lambda: at(T(29), 8, 0))
        payload = {'question_id': 'high_board_continues', 'target_day': T(29).isoformat(), 'probability': 0.55, 'rationale': '工具记录', 'evidence': []}
        recorded = api.call('record_limit_forecast', {'request_id': str(uuid4()), 'forecast_json': json.dumps(payload, ensure_ascii=False)})
        self.assertTrue(recorded['ok']); self.assertEqual(recorded['data']['forecaster'], 'ai:chat')
        late = LimitResearchAPI(ReadOnlyResearchAPI(self.output), now_fn=lambda: at(T(29), 9, 30)).call(
            'record_limit_forecast', {'request_id': str(uuid4()), 'forecast_json': json.dumps({**payload, 'question_id': 'broken_rate_below_30pct'})})
        self.assertEqual(late['error']['code'], 'FORECAST_TOO_LATE')
        questions = api.call('list_limit_forecast_questions', {'target_day': target.isoformat()})
        self.assertEqual(len(questions['data']['questions']), len(QUESTIONS)); self.assertIsNotNone(questions['data']['resolution'])
        self.assertTrue(api.call('get_limit_forecast_scorecard', {})['ok'])
        reviewer = LimitResearchAPI(ReadOnlyResearchAPI(self.output), allow_forecast_write=False)
        self.assertNotIn('record_limit_forecast', [t['name'] for t in reviewer.schemas()])
        stream = io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(cli_main(['--output', str(self.output), '--call', 'questions']), 0)
        self.assertEqual(json.loads(stream.getvalue())['data']['questions'][0]['question_id'], 'limit_up_count_increase')


if __name__ == '__main__':
    unittest.main()

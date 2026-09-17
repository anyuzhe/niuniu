from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import contextlib
import io
import json
import shutil
import unittest

from limit_research_fixtures import T, build_research_workspace
from test_auto_research import EXECUTION
from quantlab.agent.catalog import ReadOnlyResearchAPI
from quantlab.agent.limit_research_tools import TOOL_NAMES, LimitResearchAPI
from quantlab.agent.peer_review import SAFE_TOOLS
from quantlab.agent.premarket_brief_cli import main as cli_main
from quantlab.trading.auto_research import _write
from quantlab.trading.daily_review import DailyReviewLibrary
from quantlab.trading.event_study import EventStudyRegistry
from quantlab.trading.limit_forecasts import LimitForecastJournal
from quantlab.trading.mobile import MobileBriefService
from quantlab.trading.premarket_brief import PremarketBriefError, PremarketBriefLibrary, render_markdown
from quantlab.trading.research_conclusions import CONCLUSION_FORMAT

UTC = timezone.utc


def conclusion(output, build_id, *, status, condition, execution=None, reasons=(), hypothesis='涨停收盘后次日开盘收益为正'):
    cid = str(uuid4())
    spec = {'family': 'auto-lab-confirm', 'hypothesis': hypothesis, 'expected_sign': 'positive', 'library_build_id': build_id, 'sentiment_build_id': None,
            'condition': condition, 'baseline_condition': None, 'outcome': 'net_return' if execution else 't1_open_ret', 'start': '2026-08-03',
            'end': '2026-08-31', 'split_date': None, 'group_by': None, 'min_events': 30, 'execution': execution}
    evaluation = {'as_of_day': T(27).isoformat(), 'library_build_id': build_id, 'health': 'DECAYING' if status == 'DECAYING' else 'HEALTHY',
                  'reasons': list(reasons), 'windows': {'recent': {'start': '2026-09-01', 'end': T(27).isoformat(), 'events': 60, 'days': 25, 'value': 0.004}}}
    value = {'format': CONCLUSION_FORMAT, 'conclusion_id': cid, 'item_id': str(uuid4()), 'plan_id': str(uuid4()), 'promoted_at': '2026-09-01T00:00:00+00:00',
             'promotion_digest': 'x', 'hypothesis': hypothesis, 'expected_sign': 'positive', 'condition': condition, 'baseline_condition': None,
             'outcome': spec['outcome'], 'execution': execution, 'group_by': None, 'screening_study': {'family': 'auto-lab', 'study_id': str(uuid4())},
             'confirmation': {'family': 'auto-lab-confirm', 'study_id': str(uuid4()), 'window': {'start': '2026-08-03', 'end': '2026-08-31'}, 'spec': spec,
                              'outcome': 'CONFIRMED', 'p_value': 0.001, 'p_holm': 0.002, 'family_size': 2, 'tested_value': 0.01,
                              'checklist': {'failed': []}, 'evaluated_at': None},
             'status': status, 'status_history': [], 'evaluations': [evaluation], 'retired_at': None, 'retire_reason': None}
    _write(output / '_limit_research' / 'conclusions' / f'{cid}.json', value)
    return cid


class PremarketBriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = TemporaryDirectory(); cls.output = Path(cls.tmp.name)
        cls.ids = build_research_workspace(cls.output)
        DailyReviewLibrary(cls.output, now_fn=lambda: datetime(2026, 9, 8, 11, 0, tzinfo=UTC)).build(T(27))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def cli(self, *args):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = cli_main(['--output', str(self.output), *args])
        return code, stream.getvalue()

    def test_brief_sections_rebuild_tools_mobile_and_integrity(self):
        clock = [datetime(2026, 9, 8, 12, 0, tzinfo=UTC)]  # 20:00 Beijing, after the T(27) close
        library = PremarketBriefLibrary(self.output, now_fn=lambda: clock[0])
        with self.assertRaises(PremarketBriefError) as caught:
            library.build(T(2))
        self.assertEqual(caught.exception.code, 'REVIEW_MISSING')
        build_id = self.ids['events']['build_id']
        valid = conclusion(self.output, build_id, status='MONITORING', condition='is_limit_up_close')
        intraday = conclusion(self.output, build_id, status='MONITORING', condition='prev_is_limit_up_close and touched_limit_up',
                              execution={**EXECUTION, 'entry': 't0_limit_price'}, hypothesis='昨日涨停今日触板以涨停价打板的净收益为正')
        decaying = conclusion(self.output, build_id, status='DECAYING', condition='touched_limit_up', reasons=['EFFECT_SHRUNK'], hypothesis='触板股次日开盘收益为正')
        conclusion(self.output, build_id, status='NOT_CONFIRMED', condition='is_first_board', hypothesis='首板次日开盘收益为正')
        self.assertFalse(library.is_current(T(28)))
        brief = library.build(T(28))
        self.assertEqual((brief['created'], brief['target_day'], brief['basis_day'], brief['sentiment']['limit']['limit_up_count']),
                         (True, T(28).isoformat(), T(27).isoformat(), 1))
        monitoring = {c['conclusion_id']: c for c in brief['conclusions']['monitoring']}
        self.assertEqual(set(monitoring), {valid, intraday})
        first = monitoring[valid]['candidates'][0]
        self.assertEqual((monitoring[valid]['candidate_count'], first['code'], first['name']), (1, 'sh.600001', 'A股'))
        self.assertEqual(set(first), {'code', 'name', 'board', 'limit_up_streak', 'close', 'day_ret', 'is_st'})
        self.assertIsNone(monitoring[intraday]['candidates']); self.assertIn('盘中', monitoring[intraday]['candidate_note'])
        self.assertEqual([c['conclusion_id'] for c in brief['conclusions']['decaying']], [decaying])
        self.assertEqual(brief['gaps'], ['billboard', 'baseline_forecasts'])
        later = library.build(T(30))  # the newest review is still T(27): the brief says the basis is older than the previous weekday
        self.assertEqual((later['basis_day'], later['gaps'][-1]), (T(27).isoformat(), 'review_before_previous_weekday'))
        shutil.rmtree(self.output / '_limit_research' / 'premarket_brief' / T(30).isoformat())
        self.assertTrue({'DECAYING_CONCLUSIONS', 'DATA_GAPS'} <= {r['code'] for r in brief['risks']})
        self.assertTrue(library.is_current(T(28))); self.assertFalse(library.build(T(28))['created'])
        LimitForecastJournal(self.output, now_fn=lambda: clock[0]).record(request_id=str(uuid4()), forecaster='host:manual', question_id='limit_up_count_increase',
                                                                          target_day=T(28).isoformat(), probability=0.4, rationale='测试')
        self.assertFalse(library.is_current(T(28)))  # a forecast recorded later changes the inputs
        clock[0] += timedelta(minutes=5)
        rebuilt = library.build(T(28))
        self.assertTrue(rebuilt['created']); self.assertNotEqual(rebuilt['brief_id'], brief['brief_id'])
        question = next(q for q in rebuilt['forecasts']['questions'] if q['question_id'] == 'limit_up_count_increase')
        self.assertEqual(question['forecasts'], [{'forecaster': 'host:manual', 'probability': 0.4}])
        self.assertEqual(library.get(T(28))['brief_id'], rebuilt['brief_id'])
        text = render_markdown(rebuilt)
        self.assertEqual(rebuilt['pool_industries'][0]['limit_up_count'], 1)
        for piece in ('盘前简报', '仍有效的已确认规律：2 条', '观察名单', '盘前无法列出', '衰减中', '风险提示', '已记录预测'):
            self.assertIn(piece, text)
        frame = EventStudyRegistry(self.output).matching_events(library.conclusions().get(valid)['confirmation']['spec'], T(27))
        self.assertEqual([c for c in frame.columns if c.startswith(('t1_', 't2_', 'ret_close', 'ret_t1'))], [])
        api = LimitResearchAPI(ReadOnlyResearchAPI(self.output), now_fn=lambda: clock[0])
        self.assertIn('get_premarket_brief', TOOL_NAMES); self.assertIn('get_premarket_brief', SAFE_TOOLS)
        latest = api.call('get_premarket_brief', {'target_day': ''})
        self.assertTrue(latest['ok']); self.assertEqual(latest['data']['brief_id'], rebuilt['brief_id']); self.assertIn('盘前简报', latest['data']['markdown'])
        self.assertEqual(api.call('get_premarket_brief', {'target_day': T(30).isoformat()})['error']['code'], 'NOT_FOUND')
        mobile = MobileBriefService(self.output).limit_premarket(T(27).isoformat())  # after the close the next session's brief is shown
        self.assertEqual((mobile['available'], mobile['target_day'], mobile['valid_conclusions'], mobile['decaying_conclusions']), (True, T(28).isoformat(), 2, 1))
        self.assertFalse(MobileBriefService(self.output).limit_premarket(T(35).isoformat())['available'])
        code, out = self.cli('--call', 'get', '--date', T(28).isoformat())
        self.assertEqual((code, json.loads(out)['data']['brief_id']), (0, rebuilt['brief_id']))
        self.assertIn('盘前简报', self.cli('--call', 'markdown', '--date', T(28).isoformat())[1])
        self.assertEqual(self.cli('--call', 'get', '--date', T(30).isoformat())[0], 2)
        path = self.output / '_limit_research' / 'premarket_brief' / T(28).isoformat() / f"{rebuilt['brief_id']}.json"
        path.write_text(path.read_text().replace('"research_only"', '"tradable"'))
        with self.assertRaises(PremarketBriefError) as caught:
            library.get(T(28))
        self.assertEqual(caught.exception.code, 'CORRUPT_ARCHIVE')


if __name__ == '__main__':
    unittest.main()

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import io
import json
import unittest

from limit_research_fixtures import T, build_research_workspace
from quantlab.agent.catalog import ReadOnlyResearchAPI
from quantlab.agent.daily_review_cli import main as cli_main
from quantlab.agent.limit_research_tools import LimitResearchAPI
from quantlab.trading.daily_review import DailyReviewError, DailyReviewLibrary, render_markdown
from quantlab.trading.mobile import MobileBriefService


class DailyReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = TemporaryDirectory(); cls.output = Path(cls.tmp.name)
        cls.ids = build_research_workspace(cls.output)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def library(self):
        clock = [datetime(2026, 12, 2, tzinfo=timezone.utc)]
        def now():
            clock[0] += timedelta(seconds=1); return clock[0]
        return DailyReviewLibrary(self.output, now_fn=now)

    def test_layers_markdown_commentary_and_idempotency(self):
        library = self.library()
        self.assertFalse(library.is_current(T(27)))
        review = library.build(T(27))
        self.assertTrue(review['created']); self.assertTrue(library.is_current(T(27))); self.assertFalse(library.build(T(27))['created'])
        facts, state = review['facts'], review['machine_state']
        self.assertEqual((facts['limit']['limit_up_count'], facts['previous_day']['limit_up_count'], facts['previous_day']['date']), (1, 1, T(26).isoformat()))
        level = facts['ladder']['levels'][0]
        self.assertEqual((level['streak'], level['stocks'][0]['name'], level['stocks'][0]['first_seal_time'], level['stocks'][0]['seal_fund_yi']),
                         (2, 'A股', '09:25:00', 0.8))
        self.assertEqual(facts['details']['reconciliation'], 'CONSISTENT'); self.assertEqual(facts['details']['first_seal_distribution'], [{'bucket': '集合竞价', 'count': 1}])
        self.assertEqual(facts['themes']['concept'][0]['board_name'], '板块1')
        self.assertEqual(facts['coverage'], {'theme_facts': True, 'event_details': True, 'billboard': False})
        self.assertEqual(state['rules_version'], 'sentiment-cycle-rules-v1'); self.assertIn('error', state['similar_days'])
        self.assertEqual(review['inputs']['limit_event_build_id'], self.ids['events']['build_id'])
        text = render_markdown(library.get(T(27)))
        self.assertIn('涨停 1（非ST 1，前一日 1）', text); self.assertIn('2板：A股', text); self.assertIn('数据缺口：billboard', text)
        note = library.annotate(T(27), review['review_id'], text='高度板一字加速，次日注意分歧。', author='chief_researcher', kind='ai')
        self.assertEqual(note['layer'], 'judgment_not_fact')
        again = library.get(T(27))
        self.assertEqual(len(again['commentary']), 1); self.assertEqual(again['facts'], facts)  # 评论不改事实
        self.assertIn('AI评论（chief_researcher，判断不是事实）', render_markdown(again))
        for bad in ({'text': '', 'author': 'x', 'kind': 'ai'}, {'text': 'ok', 'author': 'x', 'kind': 'robot'}):
            with self.assertRaises(DailyReviewError):
                library.annotate(T(27), review['review_id'], **bad)
        with self.assertRaises(DailyReviewError) as ctx:
            library.build(T(40) + timedelta(days=5))
        self.assertEqual(ctx.exception.code, 'RESEARCH_BUILD_MISSING')
        path = self.output / '_limit_research' / 'daily_review' / T(27).isoformat() / review['review_id'] / 'review.json'
        original = path.read_bytes()
        path.write_bytes(original.replace(b'"limit_up_count": 1', b'"limit_up_count": 9', 1))
        with self.assertRaises(DailyReviewError):
            library.get(T(27))
        path.write_bytes(original)

    def test_tool_mobile_and_cli(self):
        self.library().build(T(27))
        api = LimitResearchAPI(ReadOnlyResearchAPI(self.output))
        result = api.call('get_daily_review', {'trading_day': ''})
        self.assertTrue(result['ok']); self.assertEqual(result['data']['trading_day'], T(27).isoformat())
        self.assertIn('打板情绪复盘', result['data']['markdown'])
        brief = MobileBriefService(self.output).limit_review(T(30).isoformat())
        self.assertEqual((brief['available'], brief['trading_day'], brief['limit_up_count']), (True, T(27).isoformat(), 1))
        self.assertFalse(MobileBriefService(self.output).limit_review(T(20).isoformat())['available'])
        stream = io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(cli_main(['--output', str(self.output), '--call', 'markdown', '--date', T(27).isoformat()]), 0)
        self.assertIn('情绪周期', json.loads(stream.getvalue())['data']['markdown'])


if __name__ == '__main__':
    unittest.main()

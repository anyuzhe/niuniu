from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo
import unittest

from limit_research_fixtures import CAL, FakeSDK, T
from test_eastmoney_snapshots import Http as BoardHttp, member
from test_public_evidence import pool_body, zt_item
from quantlab.agent.catalog import ReadOnlyResearchAPI
from quantlab.agent.limit_research_tools import TOOL_NAMES, LimitResearchAPI
from quantlab.agent.peer_review import SAFE_TOOLS
from quantlab.data.eastmoney_sources import EastmoneyBoardMembersSource, pool_sources
from quantlab.data.public_evidence import PublicEvidenceArchive
from quantlab.data.retro_daily import RetroDailyStore
from quantlab.trading.event_details import EventDetailLibrary
from quantlab.trading.event_study import EventStudyRegistry
from quantlab.trading.limit_events import LimitEventLibrary
from quantlab.trading.market_sentiment import MarketSentimentLibrary
from quantlab.trading.theme_engine import ThemeFactsLibrary

TZ = ZoneInfo('Asia/Shanghai')


class PoolHttp:
    def __call__(self, spec):
        if 'getTopicZTPool' in spec.url:
            return 200, spec.url, 'application/json', pool_body([zt_item('600001', 1, 'A股', 12100, lbc=2, fbt=92500, lbt=92500, fund=8.0e7, zbc=0)])
        return 200, spec.url, 'application/json', pool_body([])


class LimitResearchToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = TemporaryDirectory(); output = cls.output = Path(cls.tmp.name)
        clock = lambda: datetime(2026, 12, 1, tzinfo=timezone.utc)
        store = RetroDailyStore(output, now_fn=clock, today_fn=lambda: CAL[-1] + timedelta(days=30))
        plan = store.create_plan(CAL[0], CAL[-1], sdk=FakeSDK()); store.fetch(plan['capture_id'], sdk=FakeSDK())
        cls.events = LimitEventLibrary(output, now_fn=clock).build([plan['capture_id']])
        cls.sentiment = MarketSentimentLibrary(output, now_fn=clock).build([plan['capture_id']])
        day = T(27)
        when = datetime.combine(day, time(16, 30), TZ)
        pools = PublicEvidenceArchive(output, sources=pool_sources(), now_fn=lambda: when, http=PoolHttp(), sleep=lambda s: None)
        for source in ('em_limit_up_pool', 'em_broken_board_pool', 'em_limit_down_pool'):
            pools.capture(source, day)
        boards = PublicEvidenceArchive(output, sources=[EastmoneyBoardMembersSource('concept')], now_fn=lambda: when,
                                       http=BoardHttp({'BK1001': [member(1)], 'BK1002': [member(2)]}), sleep=lambda s: None)
        boards.capture('em_concept_board_members', day)
        cls.details = EventDetailLibrary(output, now_fn=clock).build(day)
        cls.theme = ThemeFactsLibrary(output, now_fn=clock).build(day)
        registry = EventStudyRegistry(output, now_fn=clock)
        study = registry.register({'family': 'tool-test', 'hypothesis': '涨停次日开盘收益为正', 'library_build_id': cls.events['build_id'],
                                   'condition': 'is_limit_up_close', 'outcome': 't1_open_ret', 'min_events': 10})
        registry.run('tool-test', study['study_id'])
        cls.study_id = study['study_id']
        cls.api = LimitResearchAPI(ReadOnlyResearchAPI(output))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def call(self, name, **arguments):
        return self.api.call(name, arguments)

    def test_capabilities_status_and_wiring(self):
        caps = self.call('get_capabilities')
        self.assertTrue(caps['data']['limit_research_tools_available']); self.assertFalse(caps['data']['limit_research_write_tool'])
        self.assertTrue(set(TOOL_NAMES) <= set(caps['data']['tools'])); self.assertTrue(set(TOOL_NAMES) <= SAFE_TOOLS)
        status = self.call('get_limit_research_status')
        self.assertTrue(status['ok']); data = status['data']
        self.assertEqual(data['limit_event_builds'][0]['build_id'], self.events['build_id'])
        self.assertEqual(data['public_evidence']['em_limit_up_pool']['accepted_days'], 1)
        self.assertEqual(data['event_study_families'], {'tool-test': 1}); self.assertFalse(data['public_evidence_verified'])
        self.assertFalse(self.call('get_market_sentiment', trading_day='2026/09/01', days=3)['ok'])
        self.assertFalse(self.api.call('get_market_sentiment', {'trading_day': ''})['ok'])

    def test_sentiment_ladder_and_events(self):
        sentiment = self.call('get_market_sentiment', trading_day=T(27).isoformat(), days=5)
        self.assertTrue(sentiment['ok']); rows = sentiment['data']['rows']
        self.assertEqual((len(rows), rows[-1]['date'], rows[-1]['limit_up_count']), (5, T(27).isoformat(), 1))
        self.assertIn('phase', rows[-1]); self.assertEqual(sentiment['evidence'][0]['build_id'], self.sentiment['build_id'])
        similar = self.call('find_similar_sentiment_days', trading_day=T(27).isoformat(), k=3)
        self.assertFalse(similar['ok'])  # 40 个交易日不足 60 日历史，诚实报错
        ladder = self.call('get_limit_ladder', trading_day=T(27).isoformat(), limit=5)
        self.assertTrue(ladder['ok']); data = ladder['data']
        self.assertEqual((data['limit_up_close'], data['ladder'][0]['streak']), (1, 2))
        stock = data['ladder'][0]['stocks'][0]
        self.assertEqual((stock['code'], stock['name'], stock['em_first_seal_time'], stock['em_seal_fund_yi']), ('sh.600001', 'A股', '09:25:00', 0.8))
        self.assertIn('核对一致', data['details'])
        events = self.call('query_limit_events', start=T(20).isoformat(), end=T(30).isoformat(), condition='is_limit_up_close and limit_up_streak >= 1',
                           offset=0, limit=20)
        self.assertTrue(events['ok']); self.assertEqual(events['data']['total'], 2)  # sz.000002 临近退市不入事件
        self.assertEqual([(r['code'], r['date']) for r in events['data']['rows']][-1], ('sh.600001', T(27).isoformat()))
        detail = self.call('query_limit_events', start=T(27).isoformat(), end=T(27).isoformat(), condition='em_in_limit_up_pool and em_first_seal_minute == 0',
                           offset=0, limit=20)
        self.assertEqual((detail['data']['total'], detail['data']['rows'][0]['em_first_seal_minute']), (1, 0))
        self.assertTrue(any(ref['kind'] == 'event_details' for ref in detail['evidence']))
        leak = self.call('query_limit_events', start='', end='', condition='t1_open_ret > 0', offset=0, limit=5)
        self.assertFalse(leak['ok']); self.assertEqual(leak['error']['code'], 'LABEL_IN_CONDITION')

    def test_themes_billboard_and_studies(self):
        themes = self.call('get_theme_facts', trading_day='', family='concept', limit=5)
        self.assertTrue(themes['ok']); self.assertEqual(themes['data']['rows'][0]['board_code'], 'BK1001')
        self.assertEqual(themes['data']['machine_state'], 'UNKNOWN')
        self.assertFalse(self.call('get_theme_facts', trading_day='', family='style', limit=5)['ok'])
        missing = self.call('get_billboard', trading_day='', symbol='', limit=5)
        self.assertFalse(missing['ok']); self.assertEqual(missing['error']['code'], 'NOT_FOUND')
        families = self.call('list_event_studies', family='')
        self.assertEqual(families['data']['families'], [{'family': 'tool-test', 'studies': 1}])
        report = self.call('list_event_studies', family='tool-test')
        self.assertEqual(report['data']['studies'][0]['study_id'], self.study_id); self.assertIn('conclusion', report['data']['studies'][0])
        study = self.call('get_event_study', family='tool-test', study_id=self.study_id)
        self.assertTrue(study['ok']); self.assertEqual(study['data']['spec']['condition'], 'is_limit_up_close')


if __name__ == '__main__':
    unittest.main()

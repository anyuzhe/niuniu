from contextlib import redirect_stdout, redirect_stderr
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo
import io
import json
import unittest

from quantlab.agent.evidence_scheduler import SCHEDULE, EvidenceScheduler, SchedulerError
from quantlab.agent.evidence_scheduler_cli import main as cli_main
from quantlab.agent.system_health import SystemHealthService
from quantlab.data.public_evidence import PublicEvidenceError
from quantlab.trading.auto_research import AutoResearchError

TZ = ZoneInfo('Asia/Shanghai')


def at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


class FakeArchive:
    def __init__(self):
        self.accepted = set(); self.calls = []; self.not_ready_until = {}; self.fail = set(); self.calendar_days = None
        self.staged_rounds = {}
        self.clock = None
    def get(self, task, day):
        if (task, day.isoformat()) not in self.accepted:
            raise PublicEvidenceError('NOT_FOUND', 'missing')
        return {'capture_id': 'x'}
    def capture(self, task, day, max_seconds=None):
        self.calls.append((task, day.isoformat()))
        if max_seconds is not None and task in self.staged_rounds and self.staged_rounds[task] > 0:
            self.staged_rounds[task] -= 1
            return {'state': 'IN_PROGRESS', 'fetched': 100, 'queued': 50}
        if task in self.fail:
            raise PublicEvidenceError('PROVIDER_ERROR', 'boom')
        until = self.not_ready_until.get(task)
        if until is not None and self.clock() < until:
            raise PublicEvidenceError('NOT_READY', 'not published')
        self.accepted.add((task, day.isoformat()))
        return {'rows': 3, 'created': True, 'capture_timing': 'SAME_DAY_AFTER_CLOSE', 'warnings': []}
    def list_days(self, task, limit=10):
        days = sorted((d for t, d in self.accepted if t == task), reverse=True)
        return [{'trading_day': d} for d in days[:limit]]


class FakeThemes:
    def __init__(self, archive):
        self.archive = archive; self.builds = []; self.current = set()
    RELEVANT = {'em_limit_up_pool', 'em_broken_board_pool', 'em_limit_down_pool', 'em_concept_boards', 'em_industry_boards',
                'em_concept_board_members', 'em_industry_board_members'}
    def _inputs(self, day):
        return tuple(sorted(t for t, d in self.archive.accepted if d == day.isoformat() and t in self.RELEVANT))
    def is_current(self, day):
        return (day.isoformat(), self._inputs(day)) in self.current
    def build(self, day):
        pools = {'em_limit_up_pool', 'em_broken_board_pool', 'em_limit_down_pool'}
        if not pools <= set(self._inputs(day)):
            raise ValueError('POOLS_MISSING')
        key = (day.isoformat(), self._inputs(day)); created = key not in self.current
        self.current.add(key); self.builds.append(key)
        return {'build_id': str(len(self.builds)), 'created': created, 'families': ['concept'], 'skipped_families': {}}


class FakeDetails(FakeThemes):
    RELEVANT = {'em_limit_up_pool', 'em_broken_board_pool', 'em_limit_down_pool', 'em_billboard_daily', 'em_billboard_buy_seats',
                'em_billboard_sell_seats', 'em_popularity_rank', 'em_strong_pool'}
    def __init__(self, archive, research):
        super().__init__(archive); self.research = research
    def _inputs(self, day):
        return super()._inputs(day) + (('research',) if day.isoformat() in self.research else ())
    def build(self, day):
        result = super().build(day)
        return {**result, 'rows': 10, 'reconciliation': 'CONSISTENT' if day.isoformat() in self.research else 'UNCHECKED'}


class FakeReviews:
    def __init__(self, research):
        self.research = research; self.built = set()
    def is_current(self, day):
        return day.isoformat() in self.built
    def build(self, day):
        if day.isoformat() not in self.research:
            raise ValueError('RESEARCH_BUILD_MISSING')
        self.built.add(day.isoformat()); return {'review_id': 'r', 'created': True, 'machine_state': {'phase': 'ICE'}}


class FakeForecasts:
    def __init__(self):
        self.records = {}; self.resolved = set()
    def forecasts(self, day):
        return self.records.get(day.isoformat(), [])
    def is_resolved(self, day):
        return day.isoformat() in self.resolved
    def resolve(self, day):
        self.resolved.add(day.isoformat()); return {'items': self.forecasts(day), 'trading_day': True}
    def generate_baselines(self, target):
        self.records.setdefault(target.isoformat(), []).append({'forecaster': 'baseline:climatology-250'})
        return {'target_day': target.isoformat(), 'written': [1], 'last_day': 'x'}


class FakeAuto:
    def __init__(self):
        self.active = False; self.nights = []; self.error = None
    def active_plan(self):
        return {'plan_id': 'p'} if self.active else None
    def night_done(self, day):
        return day.isoformat() in self.nights
    def run(self, *, night):
        if self.error is not None:
            raise self.error
        self.nights.append(night.isoformat())
        return {'status': 'QUEUE_EMPTY', 'night': night.isoformat(), 'ran': [{'state': 'SCREENED_PASS'}, {'state': 'SCREENED_FAIL'}], 'interrupted': 0}


class FakeConclusions:
    def __init__(self):
        self.current = True; self.days = []; self.error = None
    def is_current(self, day):
        return self.current
    def evaluate(self, day):
        if self.error is not None:
            raise self.error
        self.days.append(day.isoformat()); self.current = True
        return {'evaluated': [{'status': 'DECAYING'}, {'status': 'MONITORING'}], 'confirmations': {'ran': ['c'], 'changed': []}}


class FakePremarket:
    def __init__(self):
        self.current = True; self.targets = []
    def is_current(self, target):
        return self.current
    def build(self, target):
        self.targets.append(target.isoformat()); self.current = True
        return {'target_day': target.isoformat(), 'brief_id': 'b', 'created': True, 'conclusions': {'monitoring': [1]}, 'risks': [1, 2]}


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.output = Path(self.tmp.name)
        self.now = [at(2026, 9, 16, 15, 30)]; self.archive = FakeArchive(); self.archive.clock = lambda: self.now[0]
        self.holidays = set(); self.daily = []
        def daily_market(day):
            self.daily.append(day.isoformat()); return {'rows': 5000, 'created': True}
        self.references = []
        def reference(day):
            self.references.append(day.isoformat()); return {'snapshot_id': 'x', 'as_of': day.isoformat(), 'created': True}
        self.themes = FakeThemes(self.archive)
        self.research = []
        def research(action, day):
            if action == 'current':
                return day.isoformat() in self.research
            self.research.append(day.isoformat()); return {'event_build_id': 'e', 'events': 1, 'sentiment_build_id': 's', 'created': True}
        self.details = FakeDetails(self.archive, self.research)
        self.reviews = FakeReviews(self.research)
        self.forecasts = FakeForecasts()
        self.auto = FakeAuto()
        self.conclusions = FakeConclusions()
        self.premarket = FakePremarket()
        self.scheduler = EvidenceScheduler(self.output, now_fn=lambda: self.now[0], archive=self.archive,
                                           calendar_fn=lambda day: day not in self.holidays, daily_market_fn=daily_market,
                                           reference_fn=reference, theme_library=self.themes, research_fn=research,
                                           detail_library=self.details, review_library=self.reviews, forecast_journal=self.forecasts,
                                           auto_research=self.auto, conclusion_library=self.conclusions,
                                           premarket_library=self.premarket)
    def tearDown(self):
        self.tmp.cleanup()
    def tasks(self, result):
        return sorted(a['task'] for a in result['actions'] if a['ok'])

    def test_disabled_and_enable_requires_confirmation(self):
        self.assertEqual(self.scheduler.tick(), {'status': 'DISABLED', 'actions': []})
        with self.assertRaises(SchedulerError):
            self.scheduler.enable(authorization='用户授权')
        with self.assertRaises(SchedulerError):
            self.scheduler.enable(confirmed=True)
        control = self.scheduler.enable(confirmed=True, authorization='用户在对话中授权收盘后低频归档')
        self.assertTrue(control['enabled'])
        self.scheduler.pause(); self.assertEqual(self.scheduler.tick()['status'], 'DISABLED')

    def test_after_close_windows_retries_and_next_morning(self):
        self.scheduler.enable(confirmed=True, authorization='ok')
        self.assertEqual(self.scheduler.tick()['actions'], [])
        self.now[0] = at(2026, 9, 16, 15, 45)
        first = self.scheduler.tick()
        self.assertEqual(self.tasks(first), sorted(['em_limit_up_pool', 'em_prev_limit_up_pool', 'em_broken_board_pool', 'em_limit_down_pool',
                                                    'em_strong_pool', 'em_popularity_rank', 'em_concept_boards', 'em_industry_boards']))
        self.archive.not_ready_until = {'em_billboard_daily': at(2026, 9, 16, 17, 50)}
        self.now[0] = at(2026, 9, 16, 17, 35)
        second = self.scheduler.tick()
        failed = [a for a in second['actions'] if not a['ok']]
        self.assertEqual([a['task'] for a in failed], ['em_billboard_daily'])
        self.assertIn('em_concept_board_members', self.tasks(second))
        self.now[0] = at(2026, 9, 16, 17, 40)
        self.assertEqual(self.scheduler.tick()['actions'], [])
        self.now[0] = at(2026, 9, 16, 17, 55)
        self.assertEqual(self.tasks(self.scheduler.tick()), ['em_billboard_daily'])
        # 15:45 股池已就绪但未到 16:10 不建；17:35 同一 tick 内成分先抓完，题材事实只建一次；龙虎榜不是输入，不触发重建。
        self.assertEqual(len(self.themes.builds), 1)
        self.now[0] = at(2026, 9, 17, 8, 0)
        morning = self.scheduler.tick()
        self.assertEqual(morning['candidates'], ['2026-09-16'])
        self.assertEqual(self.tasks(morning), ['daily_market', 'daily_review', 'event_details', 'forecast_baselines', 'forward_reference', 'limit_research'])
        self.assertEqual(self.forecasts.records, {'2026-09-17': [{'forecaster': 'baseline:climatology-250'}]})  # 为下一个工作日生成机器基准
        details = next(a for a in morning['actions'] if a['task'] == 'event_details')
        self.assertEqual(details['reconciliation'], 'CONSISTENT')  # 日线研究库先于明细构建，明细可核对
        self.assertEqual((self.daily, self.references), (['2026-09-16'], ['2026-09-16']))
        self.now[0] = at(2026, 9, 17, 9, 20)
        self.assertEqual(self.scheduler.tick()['candidates'], [])
        status = self.scheduler.status()['recent_days']['2026-09-16']
        self.assertEqual(status['em_billboard_daily']['attempts'], 2); self.assertEqual(status['em_billboard_daily']['status'], 'ACCEPTED')

    def test_holiday_weekly_and_give_up(self):
        self.scheduler.enable(confirmed=True, authorization='ok')
        self.holidays.add(date(2026, 10, 1)); self.now[0] = at(2026, 10, 1, 16, 0)
        self.assertEqual(self.scheduler.tick()['actions'], [])
        self.assertFalse(self.scheduler.status()['recent_days'])
        self.now[0] = at(2026, 9, 18, 16, 40)
        self.assertIn('em_industry_board_members', self.tasks(self.scheduler.tick()))
        self.now[0] = at(2026, 9, 21, 16, 40)
        monday = self.scheduler.tick()
        self.assertNotIn('em_concept_board_members', self.tasks(monday))
        self.assertEqual(self.scheduler.status()['recent_days']['2026-09-21']['em_concept_board_members']['status'], 'SKIPPED_NOT_DUE')
        self.archive.fail.add('em_limit_up_pool'); self.now[0] = at(2026, 9, 22, 15, 41)
        for minute in range(0, 8 * 16, 16):
            self.now[0] = at(2026, 9, 22, 15 + (41 + minute) // 60, (41 + minute) % 60)
            self.scheduler.tick()
        entry = self.scheduler.status()['recent_days']['2026-09-22']['em_limit_up_pool']
        self.assertEqual((entry['attempts'], entry['status']), (8, 'GAVE_UP'))
        health = SystemHealthService(self.output, now_fn=lambda: self.now[0]).build()['components']['public_evidence']
        self.assertEqual(health['status'], 'WARN'); self.assertIn('evidence_capture_gave_up', health['warnings'])

    def test_theme_facts_rebuild_when_inputs_change(self):
        self.scheduler.enable(confirmed=True, authorization='ok')
        self.archive.staged_rounds = {'em_concept_board_members': 1}
        self.now[0] = at(2026, 9, 18, 16, 15)
        self.scheduler.tick()  # 股池/板块就绪，成分进行中 → 先用已有输入构建
        self.assertEqual(len(self.themes.builds), 1)
        self.now[0] = at(2026, 9, 18, 16, 25)
        self.scheduler.tick()  # 概念成分完成 → 输入变化 → 重建
        self.assertEqual(len(self.themes.builds), 2)
        self.now[0] = at(2026, 9, 18, 16, 35)
        self.scheduler.tick()
        self.assertIn('em_industry_board_members', dict(self.themes.builds[-1:])['2026-09-18'])
        self.now[0] = at(2026, 9, 18, 16, 45)
        before = len(self.themes.builds); self.scheduler.tick()
        self.assertEqual(len(self.themes.builds), before)
        self.assertEqual(self.scheduler.status()['recent_days']['2026-09-18']['theme_facts']['status'], 'ACCEPTED')

    def test_auto_research_runs_once_per_night_only_with_an_active_plan(self):
        self.scheduler.enable(confirmed=True, authorization='ok')
        self.now[0] = at(2026, 9, 16, 19, 5)
        self.assertNotIn('auto_research', self.tasks(self.scheduler.tick()))  # 没有有效计划：视为无事可做
        self.assertEqual(self.scheduler.status()['recent_days']['2026-09-16']['auto_research']['status'], 'ACCEPTED')
        self.auto.active = True
        self.now[0] = at(2026, 9, 17, 18, 55)
        self.assertNotIn('auto_research', [a['task'] for a in self.scheduler.tick()['actions']])  # 19:00 前不运行
        self.auto.error = AutoResearchError('ALREADY_RUNNING', '另一个自主研究夜间任务正在运行。')
        self.now[0] = at(2026, 9, 17, 19, 5)
        failed = [a for a in self.scheduler.tick()['actions'] if a['task'] == 'auto_research']
        self.assertEqual((len(failed), failed[0]['ok']), (1, False)); self.assertIn('ALREADY_RUNNING', failed[0]['error'])
        self.auto.error = None
        self.now[0] = at(2026, 9, 17, 19, 25)
        action = next(a for a in self.scheduler.tick()['actions'] if a['task'] == 'auto_research')
        self.assertEqual((action['status'], action['ran'], action['passed'], action['interrupted']), ('QUEUE_EMPTY', 2, 1, 0))
        self.now[0] = at(2026, 9, 17, 21, 0)
        self.assertNotIn('auto_research', [a['task'] for a in self.scheduler.tick()['actions']])
        self.assertEqual(self.auto.nights, ['2026-09-17'])

    def test_conclusion_monitor_refreshes_when_not_current(self):
        self.scheduler.enable(confirmed=True, authorization='ok')
        self.conclusions.current = False
        self.now[0] = at(2026, 9, 17, 19, 25)
        self.assertNotIn('conclusion_monitor', [a['task'] for a in self.scheduler.tick()['actions']])  # 19:30 前不运行
        self.now[0] = at(2026, 9, 17, 19, 35)
        action = next(a for a in self.scheduler.tick()['actions'] if a['task'] == 'conclusion_monitor')
        self.assertEqual((action['evaluated'], action['decaying'], action['confirmations_run']), (2, 1, 1))
        self.now[0] = at(2026, 9, 17, 19, 40)
        self.assertNotIn('conclusion_monitor', [a['task'] for a in self.scheduler.tick()['actions']])
        self.conclusions.current = False  # 事件库重建或新晋级：刷新
        self.conclusions.error = AutoResearchError('MONITOR_ERROR', '1 项确认或监控失败')
        self.now[0] = at(2026, 9, 17, 19, 45)
        failed = next(a for a in self.scheduler.tick()['actions'] if a['task'] == 'conclusion_monitor')
        self.assertIn('MONITOR_ERROR', failed['error'])
        self.conclusions.error = None
        self.now[0] = at(2026, 9, 17, 20, 5)
        self.assertIn('conclusion_monitor', self.tasks(self.scheduler.tick()))
        self.assertEqual(self.conclusions.days, ['2026-09-17', '2026-09-17'])

    def test_premarket_brief_for_next_weekday_refreshes_on_new_inputs(self):
        self.scheduler.enable(confirmed=True, authorization='ok')
        self.premarket.current = False
        self.now[0] = at(2026, 9, 18, 19, 35)
        self.assertNotIn('premarket_brief', [a['task'] for a in self.scheduler.tick()['actions']])  # 19:40 前不生成
        self.now[0] = at(2026, 9, 18, 19, 45)
        action = next(a for a in self.scheduler.tick()['actions'] if a['task'] == 'premarket_brief')
        self.assertEqual((action['target_day'], action['valid_conclusions'], action['risks']), ('2026-09-21', 1, 2))  # 周五收盘后为下周一生成
        self.premarket.current = False  # 早盘前新记录的预测改变输入：09:15 前重建
        self.now[0] = at(2026, 9, 21, 8, 30)
        self.assertIn('premarket_brief', self.tasks(self.scheduler.tick()))
        self.assertEqual(self.premarket.targets, ['2026-09-21', '2026-09-21'])

    def test_staged_member_capture_continues_next_tick_without_using_attempts(self):
        self.scheduler.enable(confirmed=True, authorization='ok')
        self.archive.staged_rounds = {'em_concept_board_members': 2}
        self.now[0] = at(2026, 9, 18, 16, 5)
        first = self.scheduler.tick()
        progress = next(a for a in first['actions'] if a['task'] == 'em_concept_board_members')
        self.assertTrue(progress['ok']); self.assertTrue(progress['in_progress'])
        entry = self.scheduler.status()['recent_days']['2026-09-18']['em_concept_board_members']
        self.assertEqual((entry['status'], entry['attempts'], entry['last_attempt_at']), ('IN_PROGRESS', 0, None))
        self.now[0] = at(2026, 9, 18, 16, 6)  # 冷却期内也继续
        self.scheduler.tick()
        self.now[0] = at(2026, 9, 18, 16, 7)
        self.scheduler.tick()
        entry = self.scheduler.status()['recent_days']['2026-09-18']['em_concept_board_members']
        self.assertEqual((entry['status'], entry['attempts']), ('ACCEPTED', 1))
        self.assertEqual([c for c in self.archive.calls if c[0] == 'em_concept_board_members'], [('em_concept_board_members', '2026-09-18')] * 3)

    def test_lock_and_cli(self):
        self.scheduler.enable(confirmed=True, authorization='ok'); self.now[0] = at(2026, 9, 16, 15, 45)
        with self.scheduler._lock():
            with self.assertRaises(SchedulerError) as ctx:
                self.scheduler.tick()
        self.assertEqual(ctx.exception.code, 'ALREADY_RUNNING')
        stream = io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(cli_main(['--output', str(self.output), '--status']), 0)
        self.assertTrue(json.loads(stream.getvalue())['enabled']); self.assertEqual(len(json.loads(stream.getvalue())['schedule']), len(SCHEDULE))
        with redirect_stderr(io.StringIO()):
            self.assertEqual(cli_main(['--output', str(self.output), '--enable']), 1)
        fresh = TemporaryDirectory()
        try:
            self.assertEqual(SystemHealthService(Path(fresh.name)).build()['components']['public_evidence']['status'], 'NOT_CONFIGURED')
        finally:
            fresh.cleanup()


if __name__ == '__main__':
    unittest.main()

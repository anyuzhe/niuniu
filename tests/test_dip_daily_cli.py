"""不开牛牛也自动跑的每日流水线：数据任务在跑时等、做完才记、情绪库更新后补推、文件锁、.env、LaunchAgent 配置。"""
import fcntl
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from quantlab.agent import dip_daily_cli as cli
from quantlab.dipbuy import autorecord, panel as dpanel


class FakeJobs:
    def __init__(self, live=None):
        self.live = live

    def _running(self, ids):
        return self.live if self.live and self.live['job_id'] in ids else None


OK = dict(checked_at='2026-10-12T18:00:00', data_date='2026-10-12', results={'market': dict(status='recorded', n_picks=3)})
BAD = dict(OK, results={'market': dict(status='error', message='x')})


class Rec:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, output, catalog=None, **kw):
        self.calls.append(kw)
        return self.answers.pop(0) if self.answers else None


class TickTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = self.tmp.name

    def test_waits_while_a_close_job_is_running_and_does_not_touch_signals(self):
        rec = Rec(OK)
        for job in ('daily_close_early', 'daily_close_update'):
            r = cli.tick(self.out, jobs=FakeJobs(dict(job_id=job, run_id='r1')), record=rec, token='2026-10-12')
            self.assertEqual(r['status'], 'waiting')
        self.assertEqual(rec.calls, [])

    def test_update_stops_blocking_once_the_panel_inputs_are_done(self):
        for step, blocks in (('日状态、日K、5 分钟', True), ('前复权重建', True), ('全市场情绪序列', False), ('基本面与估值历史', False),
                             ('封存', False), (None, True)):
            busy = cli.data_busy(FakeJobs(dict(job_id='daily_close_update', run_id='r', step=step)))
            self.assertEqual(busy is not None, blocks, step)
        early = dict(job_id='daily_close_early', run_id='r', step='全市场情绪序列')
        self.assertIsNotNone(cli.data_busy(FakeJobs(early)))          # 快速更新要整个跑完

    def test_other_jobs_do_not_block(self):
        rec = Rec(OK)
        r = cli.tick(self.out, jobs=FakeJobs(dict(job_id='sector_recorder_start', run_id='r1')), record=rec, token='t1')
        self.assertEqual(r['status'], 'done')

    def test_done_remembers_sentiment_token_only_when_clean(self):
        cli.tick(self.out, jobs=FakeJobs(), record=Rec(BAD), token='t1')
        self.assertNotIn('token', cli.load_mine(self.out))
        cli.tick(self.out, jobs=FakeJobs(), record=Rec(OK), token='t1')
        self.assertEqual(cli.load_mine(self.out)['token'], 't1')

    def test_mobile_error_is_not_clean(self):
        cli.tick(self.out, jobs=FakeJobs(), record=Rec(dict(OK, mobile=dict(status='error', message='net'))), token='t1')
        self.assertNotIn('token', cli.load_mine(self.out))

    def test_idle_when_nothing_changed(self):
        cli.save_mine(self.out, token='t1')
        rec = Rec()
        self.assertEqual(cli.tick(self.out, jobs=FakeJobs(), record=rec, token='t1')['status'], 'idle')
        self.assertEqual(len(rec.calls), 1)

    def test_republishes_once_when_sentiment_library_moves_on(self):
        autorecord.save_state(self.out, dict(autorecord.load_state(self.out), last_signature='sig'))
        cli.save_mine(self.out, token='old')
        rec = Rec(None, OK)
        r = cli.tick(self.out, jobs=FakeJobs(), record=rec, token='new')
        self.assertEqual(r['status'], 'republished')
        self.assertEqual(rec.calls, [{}, {'force': True}])
        self.assertEqual(cli.load_mine(self.out)['token'], 'new')
        rec2 = Rec()
        self.assertEqual(cli.tick(self.out, jobs=FakeJobs(), record=rec2, token='new')['status'], 'idle')
        self.assertEqual(rec2.calls, [{}])             # 同一个情绪库不再补推

    def test_no_republish_before_the_first_record(self):
        cli.save_mine(self.out, token='old')
        rec = Rec()
        self.assertEqual(cli.tick(self.out, jobs=FakeJobs(), record=rec, token='new')['status'], 'idle')
        self.assertEqual(len(rec.calls), 1)

    def test_disabled_switch_is_respected(self):
        autorecord.set_enabled(self.out, False)
        rec = Rec(OK)
        self.assertEqual(cli.tick(self.out, jobs=FakeJobs(), record=rec, token='t')['status'], 'disabled')
        self.assertEqual(rec.calls, [])


class LockTests(unittest.TestCase):
    def test_second_process_is_turned_away_not_blocked(self):
        with tempfile.TemporaryDirectory() as out:
            path = Path(out) / '_home' / 'dip_autorecord.lock'
            path.parent.mkdir(parents=True)
            with open(path, 'a') as held:
                fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with mock.patch.object(dpanel, 'current_sources', side_effect=AssertionError('不该读面板')):
                    self.assertIsNone(autorecord.run_if_new(out, None, force=True))
            with mock.patch.object(dpanel, 'current_sources', side_effect=dpanel.DipDataError('尚未交付')):
                self.assertIsNone(autorecord.run_if_new(out, None, force=True))     # 锁放开后能进到里面（这里数据没开放）

    def test_lock_is_released_after_an_exception(self):
        with tempfile.TemporaryDirectory() as out:
            with mock.patch.object(dpanel, 'current_sources', side_effect=RuntimeError('boom')):
                with self.assertRaises(RuntimeError):
                    autorecord.run_if_new(out, None, force=True)
            with autorecord._exclusive(out) as got:
                self.assertTrue(got)


class HelperTests(unittest.TestCase):
    def test_env_file_does_not_override_or_choke(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / '.env'
            p.write_text('# c\n\nA=1\nB="two"\nC = x y \nbad line\nKEEP=new\n', encoding='utf-8')
            env = {'KEEP': 'old'}
            self.assertEqual(cli.load_env_file(p, env), 3)
            self.assertEqual(env, {'KEEP': 'old', 'A': '1', 'B': 'two', 'C': 'x y'})
            self.assertEqual(cli.load_env_file(Path(d) / 'nope', {}), 0)

    def test_agent_configs(self):
        cfg = cli.agent_configs('/tmp/out')
        self.assertEqual(set(cfg), {cli.DUTY_LABEL, cli.DAILY_LABEL})
        for label, c in cfg.items():
            self.assertEqual(c['Label'], label)
            self.assertEqual(c['StartInterval'], cli.INTERVAL)
            self.assertIn('--output', c['ProgramArguments'])
            self.assertTrue(c['StandardOutPath'].endswith('.log'))
        self.assertIn('--run-duty', cfg[cli.DUTY_LABEL]['ProgramArguments'])
        self.assertIn('--tick', cfg[cli.DAILY_LABEL]['ProgramArguments'])

    def test_sentiment_token_survives_a_missing_library(self):
        with tempfile.TemporaryDirectory() as out:
            self.assertIsNone(cli.sentiment_token(out))


if __name__ == '__main__':
    unittest.main()

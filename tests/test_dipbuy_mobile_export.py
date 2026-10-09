"""手机版快照：加密往返、口令与配置校验、快照拼装、前向/持仓视图、推送参数检查。全部用合成数据，不连服务器。"""
import json
import os
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np

from quantlab.dipbuy import engine, fusion, mobile_export as me, portfolio, tracker
from test_dipbuy import cfg, make_panel
from test_dipbuy_fusion import scripted
from test_dipbuy_portfolio import day, fixture

SH = timezone(timedelta(hours=8))
PASS = 'abcd-efgh-jkmn-pqrs'


class CryptoTests(unittest.TestCase):
    snap = dict(format=me.SNAPSHOT_FORMAT, generated_at='2026-10-09T20:00:00+08:00', data_date='2026-10-09', note='持仓 600000 × 1000')

    def test_roundtrip_and_nothing_readable_in_envelope(self):
        env = me.encrypt_snapshot(self.snap, PASS, iterations=1000)
        self.assertEqual(env['format'], me.ENVELOPE_FORMAT)
        self.assertEqual(me.decrypt_envelope(env, PASS), self.snap)
        text = json.dumps(env)
        self.assertNotIn('600000', text)
        self.assertNotIn('持仓', text)
        self.assertEqual(env['data_date'], '2026-10-09')          # 只有日期明文，页面用它显示“数据截至”

    def test_wrong_passphrase_and_tampering_fail(self):
        env = me.encrypt_snapshot(self.snap, PASS, iterations=1000)
        with self.assertRaisesRegex(ValueError, '口令不对'):
            me.decrypt_envelope(env, PASS + 'x')
        bad = dict(env, ct=env['ct'][:-6] + ('AAAAAA' if not env['ct'].endswith('AAAAAA') else 'BBBBBB'))
        with self.assertRaises(ValueError):
            me.decrypt_envelope(bad, PASS)
        with self.assertRaises(ValueError):
            me.decrypt_envelope(dict(env, format='other'), PASS)

    def test_each_encryption_uses_fresh_salt_and_iv(self):
        a, b = me.encrypt_snapshot(self.snap, PASS, iterations=1000), me.encrypt_snapshot(self.snap, PASS, iterations=1000)
        self.assertNotEqual((a['salt'], a['iv'], a['ct']), (b['salt'], b['iv'], b['ct']))

    def test_short_passphrase_refused(self):
        with self.assertRaises(ValueError):
            me.encrypt_snapshot(self.snap, 'short')


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_config_roundtrip_and_validation(self):
        self.assertIsNone(me.load_config(self.out))
        me.save_config(self.out, host='root@1.2.3.4', remote_dir='/www/wwwroot/x.example.com/', url='https://x.example.com')
        cfg_ = me.load_config(self.out)
        self.assertEqual((cfg_['host'], cfg_['remote_dir'], cfg_['enabled']), ('root@1.2.3.4', '/www/wwwroot/x.example.com', True))
        for kw in (dict(host='a b', remote_dir='/x'), dict(host='h;rm', remote_dir='/x'), dict(host='h', remote_dir='x'),
                   dict(host='h', remote_dir='/a b'), dict(host='h', remote_dir='/a/../b'), dict(host='h', remote_dir="/a'b")):
            with self.assertRaises(ValueError):
                me.save_config(self.out, **kw)

    def test_passphrase_is_private_and_generated_when_missing(self):
        self.assertIsNone(me.load_passphrase(self.out))
        generated = me.set_passphrase(self.out)
        self.assertEqual(me.load_passphrase(self.out), generated)
        self.assertGreaterEqual(len(generated), me.MIN_PASSPHRASE)
        mode = stat.S_IMODE(os.stat(self.out / '_home' / 'mobile_passphrase').st_mode)
        self.assertEqual(mode, 0o600)
        self.assertNotEqual(me.set_passphrase(self.out), generated)
        with self.assertRaises(ValueError):
            me.set_passphrase(self.out, 'short')

    def test_environment_passphrase_wins(self):
        me.set_passphrase(self.out, PASS)
        with mock.patch.dict(os.environ, {'NIUNIU_MOBILE_PASSPHRASE': 'from-the-environment'}):
            self.assertEqual(me.load_passphrase(self.out), 'from-the-environment')


class CleanTests(unittest.TestCase):
    def test_clean_makes_plain_json(self):
        raw = {'a': np.float32(1.5), 'b': np.int64(3), 'c': np.bool_(True), 'd': float('nan'), 'e': [np.float64('inf'), (1, 2)],
               'f': np.array([1.0, np.nan]), 'g': None}
        out = me._clean(raw)
        self.assertEqual(out, {'a': 1.5, 'b': 3, 'c': True, 'd': None, 'e': [None, [1, 2]], 'f': [1.0, None], 'g': None})
        json.dumps(out, allow_nan=False)

    def test_trim_keeps_head_and_total(self):
        out = me._trim({'picks': list(range(100)), 'small': [1, 2], 'x': 1})
        self.assertEqual(len(out['picks']), me.MAX_LIST)
        self.assertEqual(out['picks_total'], 100)
        self.assertNotIn('small_total', out)

    def test_curve_downsamples_and_keeps_last_point(self):
        dates = [f'd{i}' for i in range(1000)]
        eq = [1 + i / 1000 for i in range(1000)]
        c = me._curve(dates, eq)
        self.assertLessEqual(len(c['dates']), me.MAX_CURVE + 1)
        self.assertEqual(c['dates'][-1], 'd999')
        self.assertEqual(len(c['dates']), len(c['equity']))
        short = me._curve(['a', 'b'], [1.0, None])
        self.assertEqual(short, dict(dates=['a', 'b'], equity=[1.0, None]))


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_holdings_view_has_a_plan_per_variant(self):
        panel, inp = fixture()
        names = {str(c): f'股{i}' for i, c in enumerate(panel.codes)}
        portfolio.add_holding(self.out, code='600000', shares=1000, entry_date=day(panel, 3), cost=9.5, sleeve='A')
        portfolio.set_equity(self.out, 50.0)
        with mock.patch.object(fusion, 'build_inputs', lambda p, c, cls: inp):
            view = me._holdings_view(self.out, panel, None, names, datetime.fromisoformat(panel.last_date).date())
        json.dumps(view, allow_nan=False)
        self.assertEqual(view['equity_wan'], 50.0)
        self.assertEqual(view['n_holdings'], 1)
        self.assertEqual(list(view['plans']), ['D', 'D1', 'D2', 'D3', 'D4'])
        self.assertEqual(view['holdings'][0]['code'], 'sh.600000')
        d = view['plans']['D']
        self.assertTrue(d['gate_open'])
        self.assertTrue(d['buys'])
        self.assertIn('plan_day', d)
        self.assertFalse(d['stale'])
        self.assertNotIn('holdings', d)               # 持仓明细只放一份，不重复五遍

    def test_holdings_view_survives_one_variant_failing(self):
        panel, inp = fixture()
        calls = []

        def build(p, c, cls):
            calls.append(c.variant)
            if c.variant == 'D2':
                raise ValueError('boom')
            return inp
        with mock.patch.object(fusion, 'build_inputs', build):
            view = me._holdings_view(self.out, panel, None, {}, datetime.now(SH).date())
        self.assertIn('boom', view['plans']['D2']['error'])
        self.assertNotIn('error', view['plans']['D'])

    def test_market_signal_view_and_fusion_error_isolated(self):
        panel = make_panel(np.full((60, 8), 10.0))
        sig = me._signal_view('market', panel, None, {}, 400000.0)
        self.assertEqual(sig['date'], str(panel.dates[-1]))
        self.assertFalse(sig['gate_open'])
        err = me._signal_view('fusion', panel, None, {}, 400000.0)          # 没有行业分类，只这一本出错
        self.assertIn('error', err)
        json.dumps(sig, allow_nan=False)

    def test_forward_view_with_records_and_curve(self):
        panel = make_panel(np.full((60, 8), 10.0))
        c = cfg(positions=3)
        market, cand = engine.compute_features(panel)
        market.z[:] = -2.0
        cand.e6[:] = False
        cand.e6[-1, :6] = True
        cand.ret20[-1, :6] = np.linspace(-0.3, -0.1, 6)
        sig = engine.latest_signal(panel, market, cand, c)
        tracker.record_signal(self.out, sig, c)
        first = me._forward_view(self.out, panel, None, 'market')
        self.assertEqual(len(first['records']), 1)
        self.assertEqual(first['records'][0]['signal_date'], str(panel.dates[-1]))
        self.assertNotIn('portfolio', first)                                   # 记录日就是最新一天
        longer = make_panel(np.vstack([np.full((60, 8), 10.0), np.full((30, 8), 10.0)]))
        view = me._forward_view(self.out, longer, None, 'market')
        json.dumps(view, allow_nan=False)
        self.assertEqual(len(view['portfolio']['curve']['dates']), 31)
        self.assertEqual(view['start_date'], str(panel.dates[-1]))
        self.assertIn('summary', view)

    def test_forward_view_error_is_contained(self):
        with mock.patch.object(tracker, 'settle_ledger', side_effect=RuntimeError('x')):
            self.assertEqual(me._forward_view(self.out, None, None, 'market'), {'error': 'RuntimeError: x'})


class SnapshotAndPublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.panel = make_panel(np.full((60, 8), 10.0))
        self.now = datetime.fromisoformat(self.panel.last_date).replace(hour=20, tzinfo=SH)

    def tearDown(self):
        self.tmp.cleanup()

    def patched(self):
        return mock.patch.multiple(me, _signal_view=lambda k, *a: {'kind': k}, _forward_view=lambda o, p, c, k: {'kind': k},
                                   _holdings_view=lambda *a: {'plans': {}})

    def test_snapshot_shape_and_freshness(self):
        with self.patched():
            snap = me.build_snapshot(self.out, self.panel, None, {}, now=self.now)
            stale = me.build_snapshot(self.out, self.panel, None, {}, now=self.now + timedelta(days=3))
        self.assertEqual(snap['format'], me.SNAPSHOT_FORMAT)
        self.assertEqual(snap['data_date'], self.panel.last_date)
        self.assertTrue(snap['fresh'])
        self.assertFalse(stale['fresh'])
        self.assertEqual(snap['kinds'], list(me.autorecord.KINDS))
        self.assertEqual(set(snap['signals']), set(snap['forward']))
        json.dumps(snap, allow_nan=False)

    def test_publish_skips_without_config_or_passphrase_and_never_raises(self):
        self.assertEqual(me.publish(self.out, self.panel, None, {})['status'], 'skipped')
        me.save_config(self.out, host='root@h', remote_dir='/srv/x')
        self.assertEqual(me.publish(self.out, self.panel, None, {})['status'], 'skipped')
        me.set_passphrase(self.out, PASS)
        with self.patched(), mock.patch.object(me, 'push_bytes', side_effect=RuntimeError('network down')):
            res = me.publish(self.out, self.panel, None, {}, now=self.now)
        self.assertEqual(res['status'], 'error')
        self.assertIn('network down', res['message'])

    def test_publish_pushes_encrypted_data_json(self):
        me.save_config(self.out, host='root@h', remote_dir='/srv/x')
        me.set_passphrase(self.out, PASS)
        sent = {}
        with self.patched(), mock.patch.object(me, 'push_bytes', lambda host, path, data, **kw: sent.update(host=host, path=path, data=data)):
            res = me.publish(self.out, self.panel, None, {}, now=self.now)
        self.assertEqual(res['status'], 'pushed')
        self.assertEqual((sent['host'], sent['path']), ('root@h', '/srv/x/data.json'))
        env = json.loads(sent['data'])
        self.assertEqual(me.decrypt_envelope(env, PASS)['data_date'], self.panel.last_date)

    def test_disabled_config_is_skipped(self):
        me.save_config(self.out, host='root@h', remote_dir='/srv/x', enabled=False)
        me.set_passphrase(self.out, PASS)
        with mock.patch.object(me, 'push_bytes') as push:
            self.assertEqual(me.publish(self.out, self.panel, None, {})['status'], 'skipped')
        push.assert_not_called()

    def test_push_bytes_uses_batchmode_and_atomic_move(self):
        with mock.patch.object(me.subprocess, 'run') as run:
            run.return_value = mock.Mock(returncode=0, stderr=b'')
            me.push_bytes('root@h', '/srv/x/data.json', b'abc')
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[:3], ['ssh', '-o', 'BatchMode=yes'])
        self.assertIn('mv /srv/x/data.json.tmp /srv/x/data.json', cmd[-1])
        self.assertEqual(run.call_args.kwargs['input'], b'abc')
        for bad in ('relative/x', '/srv/a b', '/srv/x;rm -rf'):
            with self.assertRaises(ValueError):
                me.push_bytes('root@h', bad, b'')
        with mock.patch.object(me.subprocess, 'run', return_value=mock.Mock(returncode=255, stderr='denied'.encode())):
            with self.assertRaisesRegex(RuntimeError, 'denied'):
                me.push_bytes('root@h', '/srv/x/data.json', b'')


if __name__ == '__main__':
    unittest.main()

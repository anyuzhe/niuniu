"""日内做T: engine (fills, limits, T+1, fees, force close, unfinished), the three article strategies,
the read-only gst_intraday reader over a small temporary DuckDB, and the backtest runner."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np

from quantlab.intraday import backtest
from quantlab.intraday.gst import Day, GstIntraday, IntradayDataError
from quantlab.intraday.strategies import (STRATEGIES, CloseScore, LateMomentum, OpeningBreakout, Strategy, VwapReversion,
                                          WeakClose)
from quantlab.intraday.t0 import Costs, T0Config, run_day, summarize, verdict


def session_minutes():
    out = ['09:25']
    for h, a, b in ((9, 31, 59), (10, 0, 59), (11, 0, 30), (13, 1, 59), (14, 0, 57)):
        out += [f'{h:02d}:{m:02d}' for m in range(a, b + 1)]
    return out + ['15:00']


MINUTES = session_minutes()


def make_day(prices, *, prev_close=10.0, volume=100_000.0, day=date(2024, 3, 1), up=11.0, down=9.0,
             highs=None, lows=None, opens=None, symbol='sh.600000', market=None):
    """One synthetic day. `prices` gives the close of each minute (a callable of the minute or a list)."""
    closes = np.array([prices(m) for m in MINUTES] if callable(prices) else prices, dtype=float)
    n = len(closes)
    opens = np.array(opens if opens is not None else closes, dtype=float)
    highs = np.array(highs if highs is not None else np.maximum(opens, closes), dtype=float)
    lows = np.array(lows if lows is not None else np.minimum(opens, closes), dtype=float)
    vol = np.full(n, float(volume)) if np.isscalar(volume) else np.array(volume, dtype=float)
    bars = {'minute': np.array(MINUTES[:n]), 'open': opens, 'high': highs, 'low': lows, 'close': closes,
            'volume': vol, 'amount': vol * closes, 'vwap': closes, 'ticks': np.full(n, 20.0),
            'buy_volume': vol / 2, 'sell_volume': vol / 2}
    if market is not None:
        market = np.array([market(m) for m in MINUTES] if callable(market) else market, dtype=float)[:n]
    return Day(symbol, '测试', day, prev_close, up, down, '主板 ±10%', bars, market)


class Scripted(Strategy):
    """Enter `side` at `enter_at`, exit at `exit_at` (both are decision minutes)."""
    key = 'scripted'
    name = '脚本'

    def __init__(self, side, enter_at, exit_at=None, repeat=False):
        self.side, self.enter_at, self.exit_at, self.repeat = side, enter_at, exit_at, repeat

    def prepare(self, day, params):
        return {'done': False, 'p': {}}

    def entry(self, i, ctx, day):
        if day.bars['minute'][i] == self.enter_at and (self.repeat or not ctx['done']):
            ctx['done'] = True
            return self.side
        return 0

    def entry_reason(self, i, ctx, day, side):
        return '脚本'

    def exit(self, i, ctx, day, trip):
        return '脚本平仓' if self.exit_at and day.bars['minute'][i] >= self.exit_at else None


NO_COST = Costs(commission=0, commission_min=0, stamp_before=0, stamp_after=0, transfer=0, slippage=0)


def idx(minute):
    return MINUTES.index(minute)


class EngineTests(unittest.TestCase):
    def test_sell_first_fills_next_open_and_profits_from_a_drop(self):
        prices = [10.0] * len(MINUTES)
        for i in range(idx('10:01'), len(MINUTES)):
            prices[i] = 9.8
        opens = list(prices)
        day = make_day(prices, opens=opens)
        record, trips = run_day(day, Scripted(-1, '09:59', '10:05'), {}, T0Config(costs=NO_COST))
        self.assertEqual(record['base_shares'], 10_000)
        self.assertEqual(len(trips), 1)
        trip = trips[0]
        self.assertEqual(trip['direction'], '先卖后买')
        self.assertEqual(trip['entry_minute'], '10:00')  # decided on 09:59, filled on the next bar
        self.assertEqual(trip['entry_price'], 10.0)
        self.assertEqual(trip['exit_minute'], '10:06')
        self.assertEqual(trip['qty'], 5_000)  # half of the base
        self.assertAlmostEqual(trip['gross'], 0.2 * 5_000)
        self.assertAlmostEqual(record['bps'], 1000 / 100_000 * 1e4)
        self.assertEqual(record['unfinished'], 0)

    def test_fees_slippage_and_stamp_duty_change(self):
        day = make_day(lambda m: 10.0, day=date(2023, 3, 1))
        costs = Costs(slippage=0.001)
        _, trips = run_day(day, Scripted(1, '10:00', '10:10'), {}, T0Config(costs=costs))
        trip = trips[0]
        self.assertAlmostEqual(trip['entry_price'], 10.01)  # buy pays up
        self.assertAlmostEqual(trip['exit_price'], 9.99)  # sell gives up
        buy, sell = 10.01 * 5000, 9.99 * 5000
        fees = max(5, buy * 0.00025) + buy * 0.00001 + max(5, sell * 0.00025) + sell * 0.00001 + sell * 0.001
        self.assertAlmostEqual(trip['fees'], round(fees, 2), places=2)
        self.assertAlmostEqual(trip['gross'], round(-0.02 * 5000, 2))
        self.assertEqual(trip['raw_bps'], 0.0)  # the signal itself earned nothing; slippage and fees did the damage
        later = make_day(lambda m: 10.0, day=date(2023, 9, 1))
        _, trips_later = run_day(later, Scripted(1, '10:00', '10:10'), {}, T0Config(costs=costs))
        self.assertAlmostEqual(trips[0]['fees'] - trips_later[0]['fees'], sell * 0.0005, places=1)

    def test_minimum_commission_applies_to_small_orders(self):
        day = make_day(lambda m: 10.0)
        costs = Costs(slippage=0, stamp_before=0, stamp_after=0, transfer=0)
        _, trips = run_day(day, Scripted(1, '10:00', '10:10'), {}, T0Config(base_value=10_000, costs=costs))
        self.assertEqual(trips[0]['qty'], 500)
        self.assertAlmostEqual(trips[0]['fees'], 10.0)

    def test_participation_caps_fill_and_partial_entry_is_kept(self):
        day = make_day(lambda m: 10.0, volume=1_000)  # 20 % of 1000 = 200 shares per bar
        _, trips = run_day(day, Scripted(-1, '10:00', '10:10'), {}, T0Config(costs=NO_COST))
        self.assertEqual(trips[0]['qty'], 200)  # the entry takes what one bar allows; the rest is cancelled

    def test_buy_blocked_at_limit_up_and_entry_gives_up(self):
        prices = [10.0] * len(MINUTES)
        for i in range(idx('10:01'), len(MINUTES)):
            prices[i] = 11.0
        day = make_day(prices)
        record, trips = run_day(day, Scripted(1, '10:00', '10:30'), {}, T0Config(costs=NO_COST))
        self.assertEqual(trips, [])
        self.assertEqual(record['trips'], 0)

    def test_buyback_blocked_at_limit_up_is_unfinished(self):
        prices = [10.0] * len(MINUTES)
        for i in range(idx('10:05'), len(MINUTES)):
            prices[i] = 11.0
        day = make_day(prices)
        record, trips = run_day(day, Scripted(-1, '10:00', '10:10'), {}, T0Config(costs=NO_COST))
        self.assertEqual(record['unfinished'], 1)
        self.assertEqual(len(trips), 1)
        self.assertIn('未能回补', trips[0]['reason'])
        self.assertAlmostEqual(trips[0]['gross'], -1.0 * 5000)  # sold at 10, marked at 11

    def test_sell_blocked_at_limit_down(self):
        prices = [10.0] * len(MINUTES)
        for i in range(idx('10:01'), len(MINUTES)):
            prices[i] = 9.0
        day = make_day(prices)
        _, trips = run_day(day, Scripted(-1, '10:00', '10:30'), {}, T0Config(costs=NO_COST))
        self.assertEqual(trips, [])

    def test_force_close_and_closing_auction(self):
        day = make_day(lambda m: 10.0)
        _, trips = run_day(day, Scripted(1, '14:00'), {}, T0Config(costs=NO_COST))
        self.assertEqual(trips[0]['reason'], '收盘前平仓')
        self.assertEqual(trips[0]['exit_minute'], '14:51')
        config = T0Config(costs=NO_COST, force_close='14:57', windows=(('09:35', '14:57'),))
        prices = [10.0] * len(MINUTES)
        prices[-1] = 10.3
        _, trips = run_day(make_day(prices), Scripted(1, '14:00'), {}, config)
        self.assertEqual(trips[0]['exit_minute'], '15:00')
        self.assertAlmostEqual(trips[0]['exit_price'], 10.3)  # filled in the closing auction at the close

    def test_windows_skip_open_lunch_and_auction(self):
        seen = []

        class Spy(Strategy):
            def prepare(self, day, params):
                return {}

            def entry(self, i, ctx, day):
                seen.append(day.bars['minute'][i])
                return 0

        run_day(make_day(lambda m: 10.0), Spy(), {}, T0Config())
        self.assertEqual(seen[0], '09:35')
        self.assertNotIn('09:25', seen)
        self.assertNotIn('11:30', seen)
        self.assertNotIn('13:15', seen)
        self.assertEqual(seen[-1], '14:49')

    def test_daily_loss_limit_stops_trading(self):
        prices = [10.0] * len(MINUTES)
        for i in range(idx('10:02'), len(MINUTES)):
            prices[i] = 10.5
        day = make_day(prices, up=None, down=None)
        record, trips = run_day(day, Scripted(-1, '10:00', '10:03', repeat=True), {}, T0Config(costs=NO_COST))
        self.assertTrue(record['stopped'])
        self.assertEqual(len(trips), 1)

    def test_max_trips_and_t_plus_one(self):
        class Every(Strategy):
            def prepare(self, day, params):
                return {}

            def entry(self, i, ctx, day):
                return 1

            def exit(self, i, ctx, day, trip):
                return '下一分钟卖'

        record, trips = run_day(make_day(lambda m: 10.0), Every(), {}, T0Config(costs=NO_COST, max_trips=4))
        self.assertEqual(len(trips), 4)
        # every trip sells no more than the base (T+1: today's buys are never needed for the sell)
        self.assertTrue(all(t['qty'] <= record['base_shares'] for t in trips))

    def test_skips_day_without_enough_base(self):
        record, trips = run_day(make_day(lambda m: 10.0, prev_close=2000), Scripted(1, '10:00'), {}, T0Config())
        self.assertIn('底仓不足', record['skipped'])
        self.assertEqual(trips, [])


class StrategyTests(unittest.TestCase):
    def test_opening_breakout_up_and_stop_at_mid(self):
        def price(m):
            if m <= '10:00':
                return 10.0 + (0.1 if m == '09:45' else 0) - (0.1 if m == '09:50' else 0)
            if m <= '10:20':
                return 10.2
            return 9.95  # below the midpoint 10.0 → stop
        day = make_day(price)
        _, trips = run_day(day, OpeningBreakout(), {}, T0Config(costs=NO_COST))
        self.assertEqual(trips[0]['direction'], '先买后卖')
        self.assertEqual(trips[0]['entry_minute'], '10:02')
        self.assertIn('止损', trips[0]['reason'])
        # one entry per direction: the later drop below the range low opens one sell-first trip at most
        self.assertLessEqual(len(trips), 2)

    def test_vwap_reversion_buys_below_band_and_exits_at_vwap(self):
        rng = np.random.default_rng(1)
        base = 10 + rng.normal(0, 0.01, len(MINUTES))
        base[idx('10:40')] = 9.7
        base[idx('10:41'):idx('10:44')] = 9.75
        base[idx('10:44'):] = 10.02
        day = make_day(list(base), up=None, down=None)
        _, trips = run_day(day, VwapReversion(), {'stop_atr': 0}, T0Config(costs=NO_COST))
        first = trips[0]
        self.assertEqual(first['direction'], '先买后卖')
        self.assertEqual(first['entry_minute'], '10:41')
        self.assertEqual(first['reason'], '回到 VWAP')

    def test_late_momentum_follows_afternoon_move_with_volume(self):
        def price(m):
            if m < '13:01':
                return 10.0
            return 10.0 + 0.2 * min(1, (int(m[:2]) * 60 + int(m[3:]) - 781) / 89)
        volume = [200_000.0 if '14:00' < m <= '14:30' else 100_000.0 for m in MINUTES]
        day = make_day(price, volume=volume)
        config = backtest.config_for('late_momentum', T0Config(costs=NO_COST))
        _, trips = run_day(day, LateMomentum(), {}, config)
        self.assertEqual(trips[0]['direction'], '先买后卖')
        self.assertEqual(trips[0]['entry_minute'], '14:31')
        self.assertEqual(trips[0]['reason'], '收盘前平仓')
        quiet = make_day(price)  # no volume expansion → no trade
        self.assertEqual(run_day(quiet, LateMomentum(), {}, config)[1], [])

    def test_strategies_only_look_backwards(self):
        """Changing bars after minute i must not change the decision at i."""
        rng = np.random.default_rng(7)
        walk = list(10 + np.cumsum(rng.normal(0, 0.02, len(MINUTES))))
        for key, strategy in STRATEGIES.items():
            if key == 'opening_breakout':
                continue  # its range is fixed at 10:00 and it only acts after that
            a = make_day(walk, up=None, down=None)
            cut = idx('14:00')
            b = make_day(walk[:cut + 1] + [w * 1.05 for w in walk[cut + 1:]], up=None, down=None)
            ca, cb = strategy.prepare(a, {}), strategy.prepare(b, {})
            if key == 'late_momentum':
                continue  # decides at 14:30 on purpose; its inputs end at 14:30
            decisions_a = [strategy.entry(i, ca, a) for i in range(cut + 1)]
            decisions_b = [strategy.entry(i, cb, b) for i in range(cut + 1)]
            self.assertEqual(decisions_a, decisions_b, key)


class ResearchStrategyTests(unittest.TestCase):
    """尾盘弱势 / 尾盘打分: sell at 14:01, buy back in the closing auction, 1-tick slippage."""

    @staticmethod
    def weak_prices(m):
        return 10.0 if m < '13:00' else (9.6 if m < '15:00' else 9.5)

    def config(self, key):
        return backtest.config_for(key, T0Config(costs=Costs(commission=0, commission_min=0, stamp_before=0,
                                                             stamp_after=0, transfer=0, slippage_ticks=1)))

    def test_weak_close_sells_at_1401_and_buys_back_in_the_auction(self):
        day = make_day(self.weak_prices, market=lambda m: -0.012 if m >= '13:00' else 0.0)
        _, trips = run_day(day, WeakClose(), {}, self.config('weak_close'))
        self.assertEqual(len(trips), 1)
        trip = trips[0]
        self.assertEqual((trip['direction'], trip['entry_minute'], trip['exit_minute']), ('先卖后买', '14:01', '15:00'))
        self.assertAlmostEqual(trip['entry_price'], 9.59)  # one tick below the 14:01 open
        self.assertAlmostEqual(trip['exit_price'], 9.5)  # the closing auction price, no spread
        self.assertEqual(trip['reason'], '收盘集合竞价平仓')
        self.assertIn('16 只平均 -1.20%', WeakClose().entry_reason(0, {'why': (-0.04, -0.012)}, day, -1))

    def test_weak_close_needs_market_weakness_price_and_data(self):
        config = self.config('weak_close')
        calm = make_day(self.weak_prices, market=lambda m: -0.005)
        self.assertEqual(run_day(calm, WeakClose(), {}, config)[1], [])
        unknown = make_day(self.weak_prices)  # no market context
        self.assertEqual(run_day(unknown, WeakClose(), {}, config)[1], [])
        cheap = make_day(lambda m: self.weak_prices(m) / 2, prev_close=5.0, up=5.5, down=4.5, market=lambda m: -0.02)
        self.assertEqual(run_day(cheap, WeakClose(), {}, config)[1], [])
        self.assertEqual(len(run_day(cheap, WeakClose(), {'min_price': 0}, config)[1]), 1)

    def test_auction_buyback_blocked_at_limit_up_is_unfinished(self):
        prices = [self.weak_prices(m) for m in MINUTES]
        prices[-1] = 11.0  # closes at the limit up: the buy-back in the auction cannot be filled
        day = make_day(prices, market=lambda m: -0.02)
        record, trips = run_day(day, WeakClose(), {}, self.config('weak_close'))
        self.assertEqual(record['unfinished'], 1)
        self.assertIn('未能回补', trips[0]['reason'])

    def test_close_score_uses_fixed_training_coefficients(self):
        strategy = CloseScore()
        day = make_day(self.weak_prices, market=lambda m: -0.015 if m >= '13:00' else 0.0)
        i = MINUTES.index('14:00')
        score = strategy.score(day, i)
        # by hand: close 9.6, open 10, VWAP (09:31..14:00) = mean price, no imbalance, at the day's low, no gap
        closes = day.bars['close'][1:i + 1]
        vwap = closes.mean()
        values = (-0.04, -0.04, 9.6 / vwap - 1, 0.0, 0.0, -0.015, 0.0)
        expected = strategy.BIAS + sum(w * (v - m) / d for v, m, d, w in
                                       zip(values, strategy.MEAN, strategy.STD, strategy.WEIGHT))
        self.assertAlmostEqual(score, expected)
        _, trips = run_day(day, strategy, {}, self.config('close_score'))
        self.assertEqual(len(trips), 1 if expected <= -20 else 0)
        self.assertIsNone(strategy.score(make_day(self.weak_prices), i))

    def test_tick_slippage(self):
        day = make_day(lambda m: 10.0)
        config = T0Config(costs=Costs(commission=0, commission_min=0, stamp_before=0, stamp_after=0, transfer=0,
                                      slippage_ticks=2))
        _, trips = run_day(day, Scripted(1, '10:00', '10:10'), {}, config)
        self.assertAlmostEqual(trips[0]['entry_price'], 10.02)
        self.assertAlmostEqual(trips[0]['exit_price'], 9.98)

    def test_gap_rebound_decides_on_the_auction_and_buys_the_first_trade(self):
        prices = [9.75] + [9.8] * (len(MINUTES) - 2) + [9.9]  # 09:25 auction 9.75 (−2.5%)
        opens = list(prices)
        opens[1] = 9.76  # first continuous trade
        day = make_day(prices, opens=opens)
        _, trips = run_day(day, STRATEGIES['gap_rebound'], {}, self.config('gap_rebound'))
        self.assertEqual(len(trips), 1)
        trip = trips[0]
        self.assertEqual((trip['direction'], trip['entry_minute'], trip['exit_minute']), ('先买后卖', '09:31', '15:00'))
        self.assertAlmostEqual(trip['entry_price'], 9.77)  # first trade + 1 tick
        self.assertAlmostEqual(trip['exit_price'], 9.9)  # base shares sold in the closing auction
        small = make_day([9.9] + [9.9] * (len(MINUTES) - 1))  # −1% gap: below the 2% threshold
        self.assertEqual(run_day(small, STRATEGIES['gap_rebound'], {}, self.config('gap_rebound'))[1], [])
        no_auction = make_day(prices[1:])
        no_auction.bars['minute'] = np.array(MINUTES[1:])
        self.assertEqual(run_day(no_auction, STRATEGIES['gap_rebound'], {}, self.config('gap_rebound'))[1], [])

    def test_morning_score_uses_only_models_fitted_before_the_trade_year(self):
        from quantlab.intraday.morning_models import MODELS
        strategy = STRATEGIES['morning_score']
        self.assertIsNone(strategy.models_for(make_day(lambda m: 10.0, day=date(2020, 6, 1))))
        self.assertIs(strategy.models_for(make_day(lambda m: 10.0, day=date(2023, 6, 1))), MODELS['2023'])
        self.assertIs(strategy.models_for(make_day(lambda m: 10.0, day=date(2031, 6, 1))), MODELS[max(MODELS)])
        self.assertEqual(sorted(MODELS['2024']), ['10:00', '10:30'])
        context = {'minutes': np.array(MINUTES[1:]), 'ret_pc': np.full(len(MINUTES) - 1, -0.01),
                   'ret_open': np.full(len(MINUTES) - 1, -0.01), 'count': np.full(len(MINUTES) - 1, 16), 'gap': 0.0}
        for year, expected in ((2024, 1), (2020, 0)):
            day = make_day(lambda m: 10.0, day=date(year, 3, 1))
            day.context = context
            _, trips = run_day(day, strategy, {'threshold_bp': -1000}, self.config('morning_score'))
            self.assertEqual(len(trips), expected, year)
            if expected:
                self.assertEqual((trips[0]['entry_minute'], trips[0]['exit_minute']), ('10:01', '15:00'))
        # the 2023 coefficients are the ones the full-day model was fitted with (training period only)
        self.assertEqual(MODELS['2023']['10:00'], STRATEGIES['intraday_score'].MODELS['10:00'])

    def test_range_breakout_filters_and_first_break_only(self):
        strategy = STRATEGIES['range_breakout']
        config = self.config('range_breakout')

        def path(m):  # range 9.9–10.1 until 10:00, breaks down at 10:20, recovers, breaks again at 11:00
            if m <= '10:00':
                return 10.1 if m == '09:40' else (9.9 if m == '09:50' else 10.0)
            if '10:20' <= m < '10:40' or m >= '11:00':
                return 9.8
            return 10.0
        volume = [300_000.0 if m in ('10:20', '11:00') else 100_000.0 for m in MINUTES]
        market = lambda m: -0.015
        day = make_day(path, volume=volume, market=market)
        day.prev_volume = 100_000.0 * 240
        _, trips = run_day(day, strategy, {}, config)
        self.assertEqual(len(trips), 1)  # only the first breakdown is traded
        self.assertEqual((trips[0]['direction'], trips[0]['entry_minute'], trips[0]['exit_minute']),
                         ('先卖后买', '10:21', '15:00'))
        self.assertIn('跌破开盘 30 分钟区间 9.90', strategy.entry_reason(
            0, {'p': {'range_minutes': 30}, 'why': (-1, 9.9)}, day, -1))
        calm = make_day(path, volume=volume, market=lambda m: -0.005)  # market not down enough
        calm.prev_volume = 100_000.0 * 240
        self.assertEqual(run_day(calm, strategy, {}, config)[1], [])
        quiet = make_day(path, market=market)  # no volume surge
        quiet.prev_volume = 100_000.0 * 240
        self.assertEqual(run_day(quiet, strategy, {}, config)[1], [])
        self.assertEqual(len(run_day(quiet, strategy, {'volume_x': 0}, config)[1]), 1)
        up = make_day(lambda m: 10.3 if m >= '10:30' else 10.0, market=lambda m: 0.02)
        up.prev_volume = 100_000.0 * 240
        _, trips = run_day(up, strategy, {'direction': 1, 'volume_x': 0}, config)
        self.assertEqual((len(trips), trips[0]['direction']), (1, '先买后卖'))
        self.assertEqual(run_day(up, strategy, {'direction': -1, 'volume_x': 0}, config)[1], [])

    def test_slot_grid_carries_prices_and_starts_from_the_first_price(self):
        from quantlab.intraday.strategies import SLOTS, slot_grid
        prices = [10.0 if m < '10:00' else 10.5 for m in MINUTES]
        day = make_day(prices)
        keep = [k for k, m in enumerate(MINUTES) if m not in ('09:31', '10:30')]  # two minutes without trades
        for key in day.bars:
            day.bars[key] = day.bars[key][keep]
        grid = slot_grid(day)
        self.assertEqual(len(grid['close']), len(SLOTS))
        self.assertEqual(grid['close'][0], 10.0)  # 09:31 missing → the 09:25 price
        self.assertEqual(grid['close'][SLOTS.index('10:30')], 10.5)  # carried from 10:29
        self.assertEqual(grid['cum_buy'][0], 0.0)
        self.assertAlmostEqual(grid['vwap'][SLOTS.index('09:59')], 10.0)

    def test_intraday_score_sells_on_the_first_bearish_decision_only(self):
        strategy = STRATEGIES['intraday_score']
        rising = lambda m: 10.0 + (0.3 if m >= '09:40' else 0.0) - (0.6 if m >= '10:05' else 0.0)
        context = {'minutes': np.array(MINUTES[1:]), 'ret_pc': np.full(len(MINUTES) - 1, -0.02),
                   'ret_open': np.full(len(MINUTES) - 1, -0.02), 'count': np.full(len(MINUTES) - 1, 16), 'gap': 0.0}
        day = make_day(rising)
        day.context = context
        grid = strategy.prepare(day, {})['grid']
        # hand-check one score against the fixed 10:00 coefficients
        values = strategy.features(day, grid, '10:00')
        m = strategy.MODELS['10:00']
        expected = m['b'] + sum(w * (v - mu) / sd for v, mu, sd, w in zip(values, m['mu'], m['sd'], m['w']))
        self.assertAlmostEqual(strategy.score(day, grid, '10:00'), expected)
        self.assertAlmostEqual(values[0], 0.03)  # 10.3 vs prev close 10
        self.assertAlmostEqual(values[6], -0.02)
        _, trips = run_day(day, strategy, {'threshold_bp': -1000}, self.config('intraday_score'))
        self.assertEqual(len(trips), 1)  # one trip a day, at the first decision time
        self.assertEqual((trips[0]['direction'], trips[0]['entry_minute']), ('先卖后买', '10:01'))
        self.assertEqual(trips[0]['exit_minute'], '15:00')
        day.context = None  # no market context → no trade
        self.assertEqual(run_day(day, strategy, {'threshold_bp': -1000}, self.config('intraday_score'))[1], [])


class SummaryTests(unittest.TestCase):
    def test_summary_and_verdict(self):
        days = [{'symbol': s, 'date': f'2024-01-0{d}', 'bps': b, 'pnl': b * 10, 'trips': 1, 'unfinished': 0}
                for s, d, b in (('a', 1, 5), ('b', 1, 1), ('a', 2, -2), ('b', 2, 0))]
        trips = [{'pnl': 10, 'gross': 20, 'fees': 10, 'bps': 5}, {'pnl': -5, 'gross': 0, 'fees': 5, 'bps': -2}]
        stats = summarize(days, trips)
        self.assertEqual(stats['dates'], 2)
        self.assertAlmostEqual(stats['portfolio_mean_bps'], 1.0)
        self.assertEqual(stats['max_drawdown_bps'], 1.0)
        self.assertEqual(stats['win_rate'], 0.5)
        self.assertEqual(stats['payoff'], 2.0)
        self.assertIn('太少', verdict(stats))
        self.assertEqual(summarize([], [])['days'], 0)


# ---------------------------------------------------------------------- reader over a temporary DuckDB

def build_db(root: Path) -> Path:
    import duckdb
    path = root / 'gst_intraday.duckdb'
    conn = duckdb.connect(str(path))
    conn.execute('create table stocks (symbol varchar, name varchar, tick_days bigint, tick_from date, tick_to date,'
                 ' quote_days bigint, quote_from date, quote_to date)')
    conn.execute("insert into stocks values ('sz.300033','同花顺',3,'2020-08-21','2020-08-25',0,null,null),"
                 "('sh.601777','力帆',1,'2020-08-25','2020-08-25',0,null,null)")
    conn.execute('create table stock_days (symbol varchar, date date, prev_close double, close double, volume hugeint,'
                 ' amount double, ref_close double, usable_ticks boolean, usable_quotes boolean)')
    conn.execute("insert into stock_days values ('sz.300033','2020-08-21',100,101,1,1,100,true,false),"
                 "('sz.300033','2020-08-24',101,102,1,1,101,true,false),"
                 "('sz.300033','2020-08-25',102,103,1,1,102,false,false),"
                 "('sh.601777','2020-08-25',2.0,2.0,1,1,2.0,true,false)")
    conn.execute('create table bars_1m (symbol varchar, date date, minute varchar, open double, high double,'
                 ' low double, close double, volume hugeint, amount double, vwap double, ticks bigint,'
                 ' buy_volume hugeint, sell_volume hugeint)')
    for symbol, day, px in (('sz.300033', '2020-08-21', 100.5), ('sz.300033', '2020-08-24', 101.5),
                            ('sz.300033', '2020-08-25', 102.5), ('sh.601777', '2020-08-25', 2.0)):
        for m in ('09:25', '09:31', '09:32', '15:00'):
            conn.execute('insert into bars_1m values (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         [symbol, day, m, px, px, px, px, 1000, px * 1000, px, 3,
                          None if m == '09:32' else 500, 500])
    conn.execute('create table ticks (symbol varchar, date date, seq bigint, time varchar, price double,'
                 ' volume bigint, amount double, side varchar)')
    conn.execute("insert into ticks values ('sz.300033','2020-08-24',2,'09:30:03',101.5,100,10150,'B'),"
                 "('sz.300033','2020-08-24',1,'09:25:00',101.4,200,20280,'N')")
    conn.close()
    return path


class ReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.db = build_db(root)
        status = root / 'status'
        status.mkdir()
        import polars as pl
        pl.DataFrame({'date': ['2020-08-24', '2020-08-25'], 'isST': ['0', '1']}).write_parquet(
            status / 'sh_601777.parquet')
        pl.DataFrame({'date': ['2020-08-24'], 'isST': ['0']}).write_parquet(status / 'sz_300033.parquet')
        cls.reader = GstIntraday(path=cls.db, status_dir=status)

    @classmethod
    def tearDownClass(cls):
        cls.reader.close()
        cls.temp.cleanup()

    def test_opens_read_only(self):
        with self.assertRaises(Exception):
            self.reader._query('create table x (a int)')

    def test_usable_days_and_bars(self):
        self.assertEqual([d.isoformat() for d in self.reader.usable_days('sz.300033')], ['2020-08-21', '2020-08-24'])
        days = list(self.reader.days('sz.300033'))
        self.assertEqual([d.date.isoformat() for d in days], ['2020-08-21', '2020-08-24'])
        first = days[0]
        self.assertEqual(first.name, '同花顺')
        self.assertEqual(list(first.minutes), ['09:25', '09:31', '09:32', '15:00'])
        self.assertTrue(np.isnan(first.bars['buy_volume'][2]))  # NULL stays missing, not zero
        self.assertEqual((days[0].prev_volume, days[1].prev_volume), (None, 1.0))  # previous usable day

    def test_chinext_limit_changes_on_2020_08_24_and_st(self):
        before, after = self.reader.days('sz.300033')
        self.assertAlmostEqual(before.limit_up, 110.0)
        self.assertAlmostEqual(after.limit_up, 121.2)
        st = self.reader.day('sh.601777', date(2020, 8, 25))
        self.assertAlmostEqual(st.limit_up, 2.1)
        self.assertAlmostEqual(st.limit_down, 1.9)
        self.assertEqual(st.limit_reason, 'ST ±5%')
        self.assertEqual(after.limit_reason, '创业板 ±20%')

    def test_market_context_uses_prices_known_at_each_minute(self):
        from quantlab.intraday import gst
        old = gst.MARKET_MIN_STOCKS
        gst.MARKET_MIN_STOCKS = 1
        try:
            reader = GstIntraday(path=self.db, status_dir=Path(self.temp.name) / 'status')
            table = reader.market()
            # 2020-08-25: only 601777 is usable (300033 is not) → its own return 2.0/2.0-1 = 0
            item = table[date(2020, 8, 25)]
            self.assertEqual(list(item['minutes']), ['09:31', '09:32', '15:00'])
            self.assertEqual(list(item['count']), [1, 1, 1])
            self.assertEqual((item['ret_pc'][0], item['ret_open'][0], item['gap']), (0.0, 0.0, 0.0))
            day = next(reader.days('sz.300033', '2020-08-24', '2020-08-24'))
            self.assertTrue(np.isnan(day.market[0]))  # 09:25 auction bar has no market value
            self.assertAlmostEqual(day.market[1], 101.5 / 101 - 1)
            self.assertAlmostEqual(day.context['gap'], 101.5 / 101 - 1)  # first price is the 09:25 auction
            reader.close()
        finally:
            gst.MARKET_MIN_STOCKS = old
        day = next(self.reader.days('sz.300033', '2020-08-24', '2020-08-24'))
        self.assertTrue(np.isnan(day.market).all())  # fewer than 8 stocks → unknown
        self.assertIsNone(day.context['gap'])

    def test_market_asof_carries_the_last_value(self):
        from quantlab.intraday.gst import market_asof
        context = {'minutes': np.array(['09:31', '09:33', '13:01']), 'ret_pc': np.array([0.01, 0.02, 0.03]),
                   'ret_open': np.array([0.0, 0.0, 0.0])}
        self.assertTrue(np.allclose(market_asof(context, ['09:25', '09:31', '09:32', '11:30', '14:00'])[1:],
                                    [0.01, 0.01, 0.02, 0.03]))
        self.assertTrue(np.isnan(market_asof(context, ['09:25'])[0]))

    def test_ticks_in_sequence(self):
        rows = self.reader.ticks('sz.300033', date(2020, 8, 24))
        self.assertEqual([r['time'] for r in rows], ['09:25:00', '09:30:03'])

    def test_missing_db_and_catalog_gate(self):
        with self.assertRaises(IntradayDataError):
            GstIntraday(path=Path(self.temp.name) / 'missing.duckdb')
        catalog = Path(self.temp.name) / 'catalog.md'
        catalog.write_text('# DATA → CODE 数据清单\n', encoding='utf-8')
        with self.assertRaises(IntradayDataError):
            GstIntraday(catalog)

    def test_backtest_end_to_end_and_saved_runs(self):
        result = backtest.run_backtest(self.reader, 'vwap_reversion', split='2020-08-21')
        self.assertEqual(result['symbols'], ['sh.601777', 'sz.300033'])
        self.assertEqual(result['summary']['train']['days'], 1)
        self.assertEqual(result['summary']['test']['days'], 2)
        self.assertEqual(len(result['per_symbol']), 2)
        with tempfile.TemporaryDirectory() as out:
            run_id = backtest.save_run(out, result)
            self.assertEqual(backtest.list_runs(out)[0]['run_id'], run_id)
            self.assertEqual(backtest.load_run(out, run_id)['strategy'], 'vwap_reversion')
            with self.assertRaises(ValueError):
                backtest.load_run(out, '../x')

    def test_unknown_strategy(self):
        with self.assertRaises(ValueError):
            backtest.run_backtest(self.reader, 'nope')


if __name__ == '__main__':
    unittest.main()

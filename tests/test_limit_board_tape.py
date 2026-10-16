"""Limit-board tape: the list rules, the sample rows, the minute files, the seed and the run loop."""
import json
import tempfile
import threading
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import pandas as pd

from quantlab.data import limit_board_tape as lbt
from quantlab.data.market_breadth_live import LiveBreadth

TZ = ZoneInfo("Asia/Shanghai")
TODAY = date(2026, 10, 19)


def at(clock):
    return datetime.fromisoformat(f"2026-10-19T{clock}+08:00")


def quote(code, market=1, price=10.0, last_close=10.0, high=None, low=None, vol=1000, bid_vol1=500):
    q = {"market": market, "code": code, "price": price, "last_close": last_close, "open": last_close,
         "high": price if high is None else high, "low": price if low is None else low, "vol": vol, "cur_vol": 5,
         "amount": vol * 100 * price, "servertime": "10:00:03.123", "b_vol": vol // 4, "s_vol": vol - vol // 4,
         "active1": 4553, "reversed_bytes0": 15298851, "reversed_bytes4": (5078,)}
    for level in range(1, 6):
        q[f"bid{level}"] = round(price - 0.01 * level, 2)
        q[f"ask{level}"] = round(price + 0.01 * level, 2)
        q[f"bid_vol{level}"] = bid_vol1 if level == 1 else 10 * level
        q[f"ask_vol{level}"] = 7 * level
    return q


class FakeAPI:
    book: dict = {}
    fail = 0
    calls: list = []

    def __init__(self, raise_exception=True):
        pass

    def connect(self, host, port, time_out=5):
        return True

    def disconnect(self):
        pass

    def get_security_quotes(self, chunk):
        FakeAPI.calls.append(list(chunk))
        if FakeAPI.fail > 0:
            FakeAPI.fail -= 1
            raise OSError("boom")
        return [dict(FakeAPI.book[k]) for k in chunk if k in FakeAPI.book]


class FakeBreadth:
    def __init__(self, rates, calendar=("2026-10-15", "2026-10-16")):
        self.API, self.hosts, self.today = FakeAPI, [("h1", 1), ("h2", 2)], TODAY
        self.calendar, self._rates = sorted(calendar), rates

    def _rule(self, symbol):
        return self._rates.get(symbol)


RATES = {"sh.600000": 0.10, "sz.000001": 0.10, "sz.300001": 0.20, "sz.300002": 0.20, "bj.920001": 0.30,
         "sh.600001": 0.10, "sh.688001": None}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        FakeAPI.book, FakeAPI.fail, FakeAPI.calls = {}, 0, []

    def tape(self, rates=None, **kw):
        return lbt.LimitBoardTape(self.root, FakeBreadth(RATES if rates is None else rates), **kw)

    def put(self, *quotes):
        for q in quotes:
            FakeAPI.book[(q["market"], q["code"])] = q


class RuleTests(unittest.TestCase):
    def test_a_move_of_seventy_percent_of_the_rate_qualifies(self):
        cases = [(0.10, 10.70, [("up", "涨幅")]), (0.10, 10.69, []), (0.20, 11.40, [("up", "涨幅")]),
                 (0.20, 11.39, []), (0.30, 12.10, [("up", "涨幅")]), (0.30, 12.09, []),
                 (0.10, 9.30, [("down", "涨幅")]), (0.10, 9.31, [])]
        for rate, price, expected in cases:
            self.assertEqual(lbt.qualify(quote("x", price=price), rate), expected, (rate, price))

    def test_touching_the_limit_qualifies_even_when_the_price_fell_back(self):
        self.assertEqual(lbt.qualify(quote("x", price=10.5, high=11.0), 0.10), [("up", "触板")])
        self.assertEqual(lbt.qualify(quote("x", price=11.0), 0.10), [("up", "触板")])   # one-word board
        self.assertEqual(lbt.qualify(quote("x", price=9.5, low=9.0), 0.10), [("down", "触板")])
        self.assertEqual(lbt.qualify(quote("x", price=9.0, high=11.0, low=9.0), 0.10),
                         [("up", "触板"), ("down", "触板")])

    def test_quotes_without_a_price_or_previous_close_never_qualify(self):
        self.assertEqual(lbt.qualify(quote("x", price=0.0), 0.10), [])
        self.assertEqual(lbt.qualify(quote("x", last_close=0.0), 0.10), [])

    def test_windows(self):
        cases = [("09:14:59", "before"), ("09:15:00", "auction"), ("09:29:59", "auction"),
                 ("09:30:00", "continuous"), ("11:30:30", "continuous"), ("11:30:31", "lunch"),
                 ("12:59:59", "lunch"), ("13:00:00", "continuous"), ("15:00:30", "continuous"), ("15:00:31", "after")]
        for clock, expected in cases:
            self.assertEqual(lbt.window(clock), expected, clock)


class WatchTests(Base):
    def test_the_minute_pass_puts_movers_and_touchers_on_the_list_once(self):
        tape = self.tape()
        quotes = [quote("600000", 1, price=10.8), quote("000001", 0, price=10.3),
                  quote("300001", 0, price=11.0), quote("300002", 0, price=11.45),
                  quote("920001", 2, price=12.2), quote("688001", 1, price=15.0),
                  quote("600001", 1, price=0.0)]
        self.assertEqual(tape.update_from_quotes(at("09:25:03"), quotes), 3)
        self.assertEqual(set(tape.watch), {("sh.600000", "up"), ("sz.300002", "up"), ("bj.920001", "up")})
        self.assertEqual(tape.watch[("sh.600000", "up")]["reason"], "涨幅")
        self.assertEqual(tape.watch[("sh.600000", "up")]["entered_at"], "2026-10-19T09:25:03+08:00")
        self.assertEqual(tape.update_from_quotes(at("09:26:03"), quotes), 0)
        self.assertEqual(tape.update_from_quotes(at("09:27:03"), [quote("300001", 0, price=11.5, high=12.0)]), 1)
        self.assertEqual(tape.watch[("sz.300001", "up")]["reason"], "触板")
        self.assertEqual(tape.receipt["list_max"], 4)
        self.assertEqual(tape.receipt["entered"], {"涨幅": 3, "触板": 1})

    def test_a_full_list_drops_newcomers_and_says_so(self):
        tape = self.tape()
        with mock.patch.object(lbt, "MAX_WATCH", 2):
            tape.update_from_quotes(at("10:00:03"), [quote("600000", 1, price=10.8), quote("000001", 0, price=10.8),
                                                     quote("600001", 1, price=10.8)])
        self.assertEqual(len(tape.watch), 2)
        self.assertEqual(tape.receipt["dropped"], 1)


class SampleTests(Base):
    def add(self, tape, *symbols, side="up"):
        for s in symbols:
            tape._add(s, side, "涨幅", at("09:31:00"))

    def test_rows_carry_shares_not_lots_and_the_limit_prices(self):
        tape = self.tape()
        self.put(quote("600000", 1, price=11.0, vol=1000, bid_vol1=500), quote("300002", 0, price=11.4, last_close=10.0))
        self.add(tape, "sh.600000", "sz.300002", "sh.600001")        # 600001 has no quote
        self.assertEqual(tape.sample(at("10:00:03"), "continuous"), 2)
        rows = {r["symbol"]: r for r in tape.buffer}
        r = rows["sh.600000"]
        self.assertEqual((r["volume"], r["bid_vol1"], r["bid_vol2"], r["ask_vol1"], r["cur_volume"]),
                         (100000.0, 50000.0, 2000.0, 700.0, 500.0))
        self.assertEqual((r["limit_up_price"], r["limit_down_price"]), (11.0, 9.0))
        self.assertEqual(rows["sz.300002"]["limit_up_price"], 12.0)
        self.assertEqual((r["outer_volume"], r["inner_volume"]), (25000.0, 75000.0))      # 250 and 750 lots
        self.assertEqual(r["raw_extra"], "")                  # raw fields are only kept for the auction
        self.assertEqual((r["captured_at"], r["servertime"], r["phase"], r["side"], r["provider"]),
                         ("2026-10-19T10:00:03.000+08:00", "10:00:03.123", "continuous", "up", "tdx"))
        self.assertEqual(len(FakeAPI.calls), 1)

    def test_auction_rows_keep_the_raw_unnamed_fields(self):
        tape = self.tape()
        self.put(quote("600000", 1, price=11.0))
        self.add(tape, "sh.600000")
        tape.sample(at("09:20:03"), "auction")
        extra = json.loads(tape.buffer[0]["raw_extra"])
        self.assertEqual((extra["active1"], extra["reversed_bytes0"], extra["reversed_bytes4"]), (4553, 15298851, [5078]))

    def test_requests_go_out_in_batches_of_eighty(self):
        tape = self.tape()
        self.add(tape, *[f"sh.6{n:05d}" for n in range(170)])
        tape.sample(at("10:00:03"), "continuous")
        self.assertEqual([len(c) for c in FakeAPI.calls], [80, 80, 10])

    def test_a_failed_request_is_retried_on_another_host_and_then_given_up(self):
        tape = self.tape()
        self.put(quote("600000", 1, price=11.0))
        self.add(tape, "sh.600000")
        FakeAPI.fail = 1
        self.assertEqual(tape.sample(at("10:00:03"), "continuous"), 1)
        self.assertEqual(tape.host_index, 2)
        FakeAPI.fail = 3
        with self.assertRaises(OSError):
            tape.sample(at("10:00:06"), "continuous")


class FileTests(Base):
    def setUp(self):
        super().setUp()
        self.put(quote("600000", 1, price=11.0))

    def started(self):
        tape = self.tape()
        tape._add("sh.600000", "up", "涨幅", at("09:31:00"))
        return tape

    def test_rows_are_written_one_file_per_minute_and_counted_in_the_receipt(self):
        tape = self.started()
        for clock in ("10:00:03", "10:00:57", "10:01:03"):
            tape.sample(at(clock), "continuous")
        self.assertEqual(tape.flush(before="1001"), 2)
        day = self.root / lbt.OUT / "date=2026-10-19"
        self.assertEqual(sorted(p.name for p in day.glob("*.parquet")), ["1000.parquet"])
        self.assertEqual(tape.flush(), 1)
        frame = pd.read_parquet(day / "1001.parquet")
        spec = ["captured_at", "servertime", "symbol", "price", "last_close", "open", "high", "low", "volume", "amount",
                "bid1", "bid5", "bid_vol1", "bid_vol5", "ask1", "ask5", "ask_vol1", "ask_vol5", "limit_up_price",
                "limit_down_price", "enter_reason", "provider", "side", "phase", "entered_at"]
        self.assertTrue(set(spec) <= set(frame.columns))
        self.assertNotIn("_minute", frame.columns)
        receipt = json.loads((self.root / lbt.OUT / "_receipts/2026-10-19.json").read_text())
        self.assertEqual((receipt["rows"], receipt["list_max"], receipt["version"]), (3, 1, lbt.VERSION))

    def test_a_restart_rebuilds_the_list_keeps_the_counts_and_does_not_double_a_minute(self):
        tape = self.started()
        tape.sample(at("10:00:03"), "continuous")
        tape.flush()
        again = self.tape()
        self.assertEqual(again.receipt["restarts"], 1)
        self.assertEqual(again.restore(), 1)
        self.assertEqual(again.watch[("sh.600000", "up")]["entered_at"], "2026-10-19T09:31:00+08:00")
        again.sample(at("10:00:03"), "continuous")       # same instant again
        again.sample(at("10:00:30"), "continuous")
        again.flush()
        frame = pd.read_parquet(self.root / lbt.OUT / "date=2026-10-19/1000.parquet")
        self.assertEqual(len(frame), 2)

    def test_rows_that_cannot_be_written_stay_in_the_buffer(self):
        tape = self.started()
        tape.sample(at("10:00:03"), "continuous")
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            self.assertEqual(tape.flush(), 0)
        self.assertEqual(len(tape.buffer), 1)
        self.assertIn("写回执失败", tape.receipt["last_error"])     # the receipt could not be written either
        self.assertEqual(tape.flush(), 1)
        self.assertEqual(len(pd.read_parquet(self.root / lbt.OUT / "date=2026-10-19/1000.parquet")), 1)


class SeedTests(Base):
    def bars(self, code, closes, dates):
        path = self.root / "lake/bronze/provider=baostock/stock_kline_daily" / f"{code.replace('.', '_')}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"date": pd.to_datetime(dates).date, "code": code, "close": closes}).to_parquet(path, index=False)

    def test_yesterdays_limit_ups_and_big_movers_are_on_the_list_before_the_open(self):
        d = ["2026-10-15", "2026-10-16"]
        self.bars("sh.600000", [10.0, 11.0], d)        # limit-up
        self.bars("sz.000001", [10.0, 10.8], d)        # +8 %
        self.bars("sz.000002", [10.0, 10.3], d)        # +3 %
        self.bars("sz.300001", [10.0, 11.5], d)        # +15 % at 20 cm
        self.bars("sh.600001", [10.0, 11.0], ["2026-10-14", "2026-10-15"])   # bars end a day early
        self.bars("sh.688001", [10.0, 15.0], d)        # no limit
        tape = self.tape(now_fn=lambda: at("09:10:00"))
        info = tape.seed()
        self.assertEqual({k: v["reason"] for k, v in tape.watch.items()},
                         {("sh.600000", "up"): "昨日涨停", ("sz.000001", "up"): "昨日涨幅",
                          ("sz.300001", "up"): "昨日涨幅"})
        self.assertEqual((info["limit_up"], info["big_move"], info["note"]), (1, 2, None))
        self.assertEqual(info["bars_through"], "2026-10-16")

    def test_stale_bars_are_noted_in_the_receipt(self):
        self.bars("sh.600000", [10.0, 11.0], ["2026-10-14", "2026-10-15"])
        info = self.tape(now_fn=lambda: at("09:10:00")).seed()
        self.assertIn("2026-10-15", info["note"])


class RunTests(Base):
    def run_tape(self, clocks, tape=None):
        tape = tape or self.tape()
        times = iter(at(c) for c in clocks)
        tape.now_fn = lambda: next(times)
        tape.wait = lambda stop, seconds: None
        tape.seed = lambda: {}
        tape.run(threading.Event())
        return tape

    def test_a_day_is_sampled_by_phase_and_closed_with_a_receipt(self):
        self.put(quote("600000", 1, price=11.0))
        tape = self.tape()
        tape._add("sh.600000", "up", "涨幅", at("09:05:00"))
        self.run_tape(["09:10:00", "09:15:10", "09:25:30", "09:30:03", "11:31:00", "13:00:01", "15:01:00"], tape)
        day = self.root / lbt.OUT / "date=2026-10-19"
        self.assertEqual(sorted(p.name for p in day.glob("*.parquet")), ["0915.parquet", "0925.parquet", "0930.parquet", "1300.parquet"])
        phases = pd.concat([pd.read_parquet(p) for p in sorted(day.glob("*.parquet"))])["phase"].tolist()
        self.assertEqual(phases, ["auction", "auction", "continuous", "continuous"])
        receipt = json.loads((self.root / lbt.OUT / "_receipts/2026-10-19.json").read_text())
        self.assertEqual((receipt["ok"], receipt["failed"], receipt["rows"], receipt["list_max"]), (4, 0, 4, 1))

    def test_a_failed_pass_is_counted_and_the_loop_goes_on(self):
        self.put(quote("600000", 1, price=11.0))
        tape = self.tape()
        tape._add("sh.600000", "up", "涨幅", at("09:05:00"))
        FakeAPI.fail = 3
        self.run_tape(["09:30:03", "09:30:06", "15:01:00"], tape)
        self.assertEqual((tape.receipt["ok"], tape.receipt["failed"], tape.receipt["rows"]), (1, 1, 1))
        self.assertIn("boom", tape.receipt["last_error"])

    def test_a_sealed_day_is_not_written(self):
        with mock.patch("quantlab.data.day_seals.is_sealed", return_value=True):
            tape = self.run_tape(["09:30:03", "15:01:00"])
        self.assertFalse((self.root / lbt.OUT).exists())
        self.assertEqual(tape.receipt["ok"], 0)


class HookTests(unittest.TestCase):
    def test_a_failing_consumer_never_costs_the_breadth_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = LiveBreadth.__new__(LiveBreadth)
            live.data_root, live.today, live.on_quotes = Path(tmp), TODAY, None
            seen = []
            live.quotes = lambda: [quote("600000")]
            live.compute = lambda quotes, started: {"date": TODAY, "time": "10:00", "n_stocks": len(quotes)}
            live.on_quotes = lambda started, quotes: seen.append(len(quotes)) or 1 / 0
            row = live.record()
            self.assertEqual((seen, row["n_stocks"]), ([1], 1))


if __name__ == "__main__":
    unittest.main()

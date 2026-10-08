import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect import tdx_minute as t  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")


SESSION = [f"{m // 60:02d}:{m % 60:02d}" for m in list(range(9 * 60 + 31, 11 * 60 + 31)) + list(range(13 * 60 + 1, 15 * 60 + 1))]


def bars(day, n, start_minute=0):
    out = []
    for i in range(n):
        out.append({"datetime": f"{day} {SESSION[start_minute + i]}", "open": 1, "high": 1, "low": 1, "close": 1,
                    "vol": 100.0, "amount": 100.0, "up_count": 5, "down_count": 3})
    return out


class FakeAPI:
    history = {}
    calls = []

    def __init__(self, raise_exception=True):
        pass

    def connect(self, host, port, time_out=8):
        return True

    def disconnect(self):
        pass

    def _get(self, category, market, code, offset, count):
        FakeAPI.calls.append((code, offset))
        data = FakeAPI.history.get(code, [])
        end = len(data) - offset
        return data[max(0, end - count):max(0, end)]

    get_security_bars = get_index_bars = _get


class TdxMinuteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        t.PACE = 0
        FakeAPI.calls = []
        FakeAPI.history = {"600000": bars("2026-09-23", 240) + bars("2026-09-24", 240) * 1,
                           "000001": bars("2026-09-24", 5)}
        # make the second day distinct
        FakeAPI.history["600000"][240:] = bars("2026-09-24", 240)
        self.targets = [{"symbol": "sh.600000", "kind": "stock", "period": "min1", "dir": "kline_min1"},
                        {"symbol": "sh.000001", "kind": "index", "period": "min1", "dir": "index_kline_min1"}]

    def tearDown(self):
        self.tmp.cleanup()

    def write_plan(self, mode="backfill"):
        body = {"kind": "tdx_minute", "mode": mode, "data_root": str(self.root), "workers": 2, "targets": self.targets}
        data = json.dumps(body).encode()
        path = self.root / "plan.json"
        path.write_bytes(data)
        import hashlib
        return path, hashlib.sha256(data).hexdigest()

    def test_phantom_open_labels_are_dropped(self):
        rows = t._to_rows([{"datetime": "2026-09-28 13:00", "open": 1, "high": 1, "low": 1, "close": 1, "vol": 1, "amount": 1},
                           {"datetime": "2026-09-28 09:30", "open": 1, "high": 1, "low": 1, "close": 1, "vol": 1, "amount": 1},
                           {"datetime": "2026-09-28 13:01", "open": 1, "high": 1, "low": 1, "close": 1, "vol": 1, "amount": 1}],
                          {"symbol": "sh.600000", "kind": "stock"}, "x")
        self.assertEqual([r["time"][8:12] for r in rows], ["1301"])

    def test_backfill_then_resume_and_daily(self):
        import pandas as pd
        path, sha = self.write_plan()
        night = lambda: datetime(2026, 9, 25, 20, 0, tzinfo=TZ)
        with self.assertRaises(SystemExit):
            t.apply(path, "bad", max_seconds=60, API=FakeAPI, now_fn=night, log=lambda *_: None)
        with self.assertRaises(SystemExit):
            t.apply(path, sha, max_seconds=60, API=FakeAPI, now_fn=lambda: datetime(2026, 9, 24, 10, 0, tzinfo=TZ),
                    log=lambda *_: None)
        summary = t.apply(path, sha, max_seconds=60, API=FakeAPI, now_fn=night, log=lambda *_: None)
        self.assertEqual(summary["done"], 2)
        stock = pd.read_parquet(self.root / "lake/bronze/provider=tdx/kline_min1/sh_600000.parquet")
        self.assertEqual(len(stock), 480)
        self.assertEqual(stock["time"].iloc[0], "20260923093100000")
        index = pd.read_parquet(self.root / "lake/bronze/provider=tdx/index_kline_min1/sh_000001.parquet")
        self.assertEqual(int(index["up_count"].iloc[0]), 5)
        calls = len(FakeAPI.calls)
        t.apply(path, sha, max_seconds=60, API=FakeAPI, now_fn=night, log=lambda *_: None)
        self.assertEqual(len(FakeAPI.calls), calls)        # resumed: nothing refetched
        # next day arrives; daily mode fetches only the newest page and merges
        FakeAPI.history["600000"] = FakeAPI.history["600000"] + bars("2026-09-28", 240)
        daily, dsha = self.write_plan("daily")
        t.apply(daily, dsha, max_seconds=60, API=FakeAPI, now_fn=night, log=lambda *_: None)
        stock = pd.read_parquet(self.root / "lake/bronze/provider=tdx/kline_min1/sh_600000.parquet")
        self.assertEqual(len(stock), 720)
        self.assertEqual(str(stock["date"].iloc[-1]), "2026-09-28")


if __name__ == "__main__":
    unittest.main()

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import polars as pl

REPO = Path(__file__).resolve().parents[1]
SESSION = [f"{m // 60:02d}{m % 60:02d}" for m in list(range(9 * 60 + 31, 11 * 60 + 31)) + list(range(13 * 60 + 1, 15 * 60 + 1))]


def min1(day, extra=(), drop=0, volume=100):
    times = list(SESSION[: len(SESSION) - drop]) + list(extra)
    stamp = day.replace("-", "")
    n = len(times)
    return pl.DataFrame({
        "date": [date.fromisoformat(day)] * n, "time": [f"{stamp}{t}00000" for t in times], "code": ["sh.600000"] * n,
        "open": [10.0 + i * 0.001 for i in range(n)], "high": [10.5 + i * 0.001 for i in range(n)],
        "low": [9.5] * n, "close": [10.0 + i * 0.002 for i in range(n)], "volume": [volume] * n, "amount": [1000.0] * n,
        "fetch_ts": ["x"] * n, "provider": ["tdx"] * n})


def daily(rows):
    return pl.DataFrame({"date": [date.fromisoformat(d) for d in rows], "code": ["sh.600000"] * len(rows),
                         "open": [1.0] * len(rows), "high": [2.0] * len(rows), "low": [0.5] * len(rows),
                         "close": [1.5] * len(rows), "volume": [10] * len(rows), "amount": [15.0] * len(rows),
                         "adjustflag": ["3"] * len(rows), "fetch_ts": ["old"] * len(rows)})


class DailyFromMin1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.daily, self.min1, self.log = root / "daily", root / "min1", root / "log"
        for d in (self.daily, self.min1):
            d.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *extra):
        out = subprocess.run([sys.executable, str(REPO / "scripts/collect/daily_from_min1.py"), "apply", "--day", "2026-09-30",
                              "--daily-dir", str(self.daily), "--min1-dir", str(self.min1), "--log-dir", str(self.log), *extra],
                             capture_output=True, text=True, check=True)
        return json.loads(out.stdout.strip().splitlines()[-1])

    def test_derive_and_filter_phantom_bar(self):
        daily(["2026-09-29"]).write_parquet(self.daily / "sh_600000.parquet")
        min1("2026-09-30", extra=("1300",)).write_parquet(self.min1 / "sh_600000.parquet")   # 假的 13:00 线要被过滤
        info = self.run_cli()
        self.assertEqual(info["derived"], 1)
        row = pl.read_parquet(self.daily / "sh_600000.parquet").filter(pl.col("date") == date(2026, 9, 30)).row(0, named=True)
        self.assertEqual(row["volume"], 240 * 100)
        self.assertEqual(row["amount"], 240000.0)
        self.assertEqual(row["open"], 10.0)
        self.assertAlmostEqual(row["close"], 10.0 + 239 * 0.002)
        self.assertEqual(row["adjustflag"], "3")
        self.assertEqual(pl.read_parquet(self.log / "date=2026-09-30.parquet").height, 1)
        again = self.run_cli()
        self.assertEqual(again["status"].get("already_present"), 1)   # 重跑不重复写

    def test_skips_incomplete_suspended_and_gap(self):
        daily(["2026-09-29"]).write_parquet(self.daily / "sh_600000.parquet")
        min1("2026-09-30", drop=1).write_parquet(self.min1 / "sh_600000.parquet")           # 239 根
        daily(["2026-09-29"]).write_parquet(self.daily / "sh_600001.parquet")
        min1("2026-09-30", volume=0).write_parquet(self.min1 / "sh_600001.parquet")          # 停牌，成交量为 0
        daily(["2026-09-28"]).write_parquet(self.daily / "sh_600002.parquet")                # 前一交易日缺行
        min1("2026-09-30").write_parquet(self.min1 / "sh_600002.parquet")
        daily(["2026-09-29"]).write_parquet(self.daily / "sh_600003.parquet")                # 没有 1 分钟线文件
        info = self.run_cli()
        self.assertEqual(info["derived"], 0)
        self.assertEqual(info["status"], {"bad_row_count": 1, "no_volume": 1, "behind": 1, "no_min1_file": 1})
        self.assertEqual(pl.read_parquet(self.daily / "sh_600000.parquet").height, 1)


if __name__ == "__main__":
    unittest.main()

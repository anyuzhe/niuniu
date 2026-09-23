import json
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from derive import build_qfq as bq  # noqa: E402
from collect import registry as regcli  # noqa: E402

CODE = "sh.600000"


def bars(days, closes):
    return pd.DataFrame({"date": days, "code": CODE, "open": closes, "high": closes, "low": closes,
                         "close": closes, "volume": 100, "amount": 1000.0, "adjustflag": "3"})


class BuildQfqTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "data"
        self.lake = self.root / "lake/bronze"
        self.dirs = {
            "raw_daily": self.lake / "provider=baostock/stock_kline_daily",
            "raw_min5": self.lake / "provider=baostock/stock_kline_min5",
            "ths": self.lake / "provider=ths/corporate_actions_dividend_v2",
            "baostock": self.lake / "provider=baostock/corporate_actions_dividend_v2",
            "eastmoney": self.lake / "provider=eastmoney/corporate_actions_dividend",
            "cninfo": self.lake / "provider=cninfo/corporate_actions_allotment_v2",
        }
        for d in self.dirs.values():
            d.mkdir(parents=True)
        (self.root / "catalog").mkdir()
        f = bq.symbol_file(CODE)
        bars(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"], [10.0, 10.0, 9.0, 9.0]).to_parquet(self.dirs["raw_daily"] / f)
        m5 = pd.DataFrame({"date": ["2024-01-02", "2024-01-05"], "time": ["20240102093500000", "20240105093500000"],
                           "code": CODE, "open": [10.0, 9.0], "high": [10.0, 9.0], "low": [10.0, 9.0],
                           "close": [10.0, 9.0], "volume": 1, "amount": 1.0})
        m5.to_parquet(self.dirs["raw_min5"] / f)
        # 2024-01-04: 10派10元 (1 yuan/share) -> f = (10-1)/10 = 0.9 ; THS and Baostock agree
        pd.DataFrame({"方案进度": ["实施方案"], "A股除权除息日": ["2024-01-04"], "分红方案说明": ["10派10元(含税)"],
                      "code": [CODE]}).to_parquet(self.dirs["ths"] / f)
        pd.DataFrame({"code": [CODE, CODE], "dividOperateDate": ["2024-01-04", "2024-01-04"],
                      "dividCashPsBeforeTax": ["1.0", "1.0"], "dividStocksPs": ["", ""],
                      "dividReserveToStockPs": ["", ""]}).to_parquet(self.dirs["baostock"] / f)  # exact duplicate
        pd.DataFrame({"code": [CODE], "方案进度": ["实施分配"], "除权除息日": ["2024-01-04"],
                      "现金分红-现金分红比例": [10.0], "送转股份-送转比例": [None],
                      "送转股份-转股比例": [None]}).to_parquet(self.dirs["eastmoney"] / f)
        spec = {"format": regcli.SPEC_FORMAT, "datasets": {}}
        names = {"raw_daily": bq.SOURCES["raw_daily"], "ths": bq.SOURCES["ths"], "baostock": bq.SOURCES["baostock"],
                 "eastmoney": bq.SOURCES["eastmoney"], "cninfo": bq.SOURCES["cninfo"], "raw_min5": bq.RAW_MIN5}
        for key, name in names.items():
            spec["datasets"][name] = {"status": "legacy" if key == "eastmoney" else "current",
                                      "kind": "per_symbol_parquet", "qualification": "research_only",
                                      "producer": "test", "path": str(self.dirs[key].relative_to(self.root))}
        payload = regcli.canonical(regcli.build_draft(self.root, spec))
        import duckdb
        con = duckdb.connect(str(self.root / "catalog/mqc.duckdb"))
        con.execute("create table tdx_capital_changes (code varchar, date date, record_json varchar)")
        self.tdx_rows = []
        con.close()
        self.snapshot = Path(self.tmp.name) / "tdx.parquet"
        (self.root / "catalog/dataset_registry.json").write_bytes(payload)
        self.s1 = Path(self.tmp.name) / "s1.jsonl"
        self.s1.write_text("".join(json.dumps({"code": "sz.000%03d" % i, "ex_date": "1993-01-01"}) + "\n"
                                   for i in range(19)))

    def write_tdx(self):
        import duckdb
        con = duckdb.connect(str(self.root / "catalog/mqc.duckdb"))
        con.execute("delete from tdx_capital_changes")
        for day, c1, c2, c3, c4 in self.tdx_rows:
            con.execute("insert into tdx_capital_changes values (?, ?, ?)", [CODE, day, json.dumps(
                {"category_name": "除权除息", "c1_float": c1, "c2_float": c2, "c3_float": c3, "c4_float": c4})])
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def run_all(self):
        self.write_tdx()
        plan = bq.build_plan(self.root, self.s1, self.snapshot)
        with self.assertRaises(PermissionError):
            bq.apply_daily(plan, "0" * 64)
        self.assertTrue(bq.apply_daily(plan, plan["plan_sha256"])["complete"])
        self.assertTrue(bq.apply_min5(plan, plan["plan_sha256"])["complete"])
        return plan

    def test_two_source_dividend_factor(self):
        self.run_all()
        q = pd.read_parquet(self.root / bq.OUT["daily"] / bq.symbol_file(CODE))
        self.assertEqual(q["factor"].round(10).tolist(), [0.9, 0.9, 1.0, 1.0])
        self.assertAlmostEqual(q["close"].iloc[0], 9.0)
        self.assertEqual(q["volume"].tolist(), [100] * 4)
        m5 = pd.read_parquet(self.root / bq.OUT["min5"] / bq.symbol_file(CODE))
        self.assertAlmostEqual(m5["close"].iloc[0], 9.0)
        ev = pd.read_parquet(self.root / bq.OUT["factors"] / bq.symbol_file(CODE))
        self.assertEqual(ev["dividend_pair"].tolist(), ["baostock+eastmoney+ths"])

    def test_disagreement_blocks_and_truncates_history(self):
        f = bq.symbol_file(CODE)
        b = pd.read_parquet(self.dirs["baostock"] / f)
        b["dividCashPsBeforeTax"] = ["0.9", "0.9"]
        b.to_parquet(self.dirs["baostock"] / f)
        self.run_all()
        q = pd.read_parquet(self.root / bq.OUT["daily"] / f)
        self.assertEqual(q["date"].tolist(), ["2024-01-04", "2024-01-05"])  # nothing before the blocked ex-date
        ev = pd.read_parquet(self.root / bq.OUT["factors"] / f)
        self.assertEqual(ev["status"].tolist(), ["blocked"])
        self.assertIn("sources_disagree", ev["blockers"].iloc[0])

    def test_eastmoney_stands_in_when_baostock_missing(self):
        (self.dirs["baostock"] / bq.symbol_file(CODE)).unlink()
        self.run_all()
        ev = pd.read_parquet(self.root / bq.OUT["factors"] / bq.symbol_file(CODE))
        self.assertEqual(ev["dividend_pair"].tolist(), ["eastmoney+ths"])

    def test_tdx_is_an_independent_second_source(self):
        f = bq.symbol_file(CODE)
        for key in ("baostock", "eastmoney"):
            (self.dirs[key] / f).unlink()
        self.tdx_rows = [("2024-01-04", 10.0, 0.0, 0.0, 0.0)]
        self.run_all()
        ev = pd.read_parquet(self.root / bq.OUT["factors"] / f)
        self.assertEqual(ev["dividend_pair"].tolist(), ["tdx+ths"])

    def test_special_dividend_day_and_tdx_only(self):
        f = bq.symbol_file(CODE)
        pd.DataFrame({"方案进度": ["实施方案", "实施方案"], "A股除权除息日": ["2024-01-04", "2024-01-04"],
                      "分红方案说明": ["10派8元(含税)", "10派2元(含税)"], "code": [CODE, CODE]}).to_parquet(self.dirs["ths"] / f)
        b = pd.read_parquet(self.dirs["baostock"] / f)
        b["dividCashPsBeforeTax"] = ["0.8", "0.8"]
        b.to_parquet(self.dirs["baostock"] / f)
        (self.dirs["eastmoney"] / f).unlink()
        self.tdx_rows = [("2024-01-04", 10.0, 0.0, 0.0, 0.0), ("2024-01-03", 0.0, 0.0, 3.0, 0.0)]
        self.run_all()
        ev = pd.read_parquet(self.root / bq.OUT["factors"] / f)
        rows = {r["ex_date"]: r for r in ev.to_dict("records")}
        self.assertEqual(rows["2024-01-04"]["status"], "accepted")
        self.assertIn("missing_in:baostock", rows["2024-01-04"]["dividend_pair"])
        self.assertEqual(rows["2024-01-03"]["status"], "ignored")
        q = pd.read_parquet(self.root / bq.OUT["daily"] / f)
        self.assertEqual(len(q), 4)  # ignored event does not truncate history

    def test_nat_failure_date_is_not_a_failed_issue(self):
        f = bq.symbol_file(CODE)
        pd.DataFrame({"code": [CODE], "除权基准日": [pd.Timestamp("2024-01-04")], "配股价格": [5.0],
                      "配股比例": [3.0], "配股失败，退还申购款日期": [pd.NaT]}).to_parquet(self.dirs["cninfo"] / f)
        self.tdx_rows = [("2024-01-04", 10.0, 5.0, 0.0, 3.0)]
        self.run_all()
        ev = pd.read_parquet(self.root / bq.OUT["factors"] / f)
        self.assertEqual(ev["status"].tolist(), ["accepted"])
        # cninfo sometimes fills the refund-date column for issues that did place
        # shares; only a refund date *and* no placed shares means a failed issue.
        pd.DataFrame({"code": [CODE], "除权基准日": ["2024-01-04"], "配股价格": [5.0], "配股比例": [3.0],
                      "实际配股数量": [1000.0], "配股失败，退还申购款日期": ["2024-01-04"]}).to_parquet(self.dirs["cninfo"] / f)
        for d in (bq.OUT["daily"], bq.OUT["factors"], bq.OUT["min5"]):
            for path in (self.root / d).rglob("*"):
                if path.is_file():
                    path.unlink()
        self.run_all()
        ev = pd.read_parquet(self.root / bq.OUT["factors"] / f)
        self.assertEqual(ev["status"].tolist(), ["accepted"])

    def test_tdx_rights_without_cninfo_blocks(self):
        self.tdx_rows = [("2024-01-04", 10.0, 5.0, 0.0, 3.0)]
        self.run_all()
        ev = pd.read_parquet(self.root / bq.OUT["factors"] / bq.symbol_file(CODE))
        self.assertIn("tdx_rights_without_cninfo", ev["blockers"].iloc[0])

    def test_single_source_is_blocked(self):
        (self.dirs["baostock"] / bq.symbol_file(CODE)).unlink()
        (self.dirs["eastmoney"] / bq.symbol_file(CODE)).unlink()
        self.run_all()
        ev = pd.read_parquet(self.root / bq.OUT["factors"] / bq.symbol_file(CODE))
        self.assertIn("single_source", ev["blockers"].iloc[0])

    def test_rights_issue_and_s1_block(self):
        f = bq.symbol_file(CODE)
        for key in ("ths", "baostock", "eastmoney"):
            (self.dirs[key] / f).unlink()
        # 10配3 at 5 yuan on 2024-01-04, prev close 10: f = (10+5*0.3)/(10*1.3)
        pd.DataFrame({"code": [CODE], "除权基准日": ["2024-01-04"], "配股价格": [5.0], "配股比例": [3.0],
                      "配股失败，退还申购款日期": [None]}).to_parquet(self.dirs["cninfo"] / f)
        self.run_all()
        q = pd.read_parquet(self.root / bq.OUT["daily"] / f)
        self.assertAlmostEqual(q["factor"].iloc[0], 11.5 / 13.0)
        lines = [json.dumps({"code": CODE, "ex_date": "2024-01-04"})] + \
                [json.dumps({"code": "sz.000%03d" % i, "ex_date": "1993-01-01"}) for i in range(18)]
        self.s1.write_text("\n".join(lines) + "\n")
        for d in (bq.OUT["daily"], bq.OUT["factors"], bq.OUT["min5"]):
            for p in (self.root / d).rglob("*"):
                if p.is_file():
                    p.unlink()
        self.run_all()
        ev = pd.read_parquet(self.root / bq.OUT["factors"] / f)
        self.assertIn("s1_unresolved_rights_event", ev["blockers"].iloc[0])

    def test_input_change_after_plan_is_refused(self):
        self.write_tdx()
        plan = bq.build_plan(self.root, self.s1, self.snapshot)
        bars(["2024-01-02"], [10.0]).to_parquet(self.dirs["raw_daily"] / bq.symbol_file(CODE))
        with self.assertRaises(ValueError):
            bq.apply_daily(plan, plan["plan_sha256"])

    def test_decide_dividend_rules(self):
        d = date(2024, 1, 4)
        v = {"cash": Decimal(1), "bonus": Decimal(0), "cap": Decimal(0)}
        slot = lambda value: {d: {"value": value, "plans": 1, "blockers": []}}
        self.assertEqual(bq.decide_dividend(d, slot(v), slot(v), {})["status"], "accepted")
        w = dict(v, cash=Decimal("1.1"))
        self.assertEqual(bq.decide_dividend(d, slot(v), slot(w), slot(v))["status"], "blocked")
        self.assertEqual(bq.decide_dividend(d, {}, slot(v), slot(v))["pair"], "baostock+eastmoney")
        split = {"cash": Decimal(1), "bonus": Decimal(2), "cap": Decimal(0)}
        total = {"cash": Decimal(1), "bonus": Decimal(1), "cap": Decimal(1)}
        self.assertEqual(bq.decide_dividend(d, slot(split), slot(total), {})["status"], "accepted")


if __name__ == "__main__":
    unittest.main()

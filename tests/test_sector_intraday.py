import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from quantlab.data.research_provider import DataProviderError, InvalidRequest
from quantlab.data.sector_intraday import (SectorIntradayProvider, classify_board, limit_prices, market_status,
                                           niuniu_symbol)

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 25, 10, 0, 0, tzinfo=TZ)
TS = int(NOW.timestamp() * 1000)


class FakeClient:
    def __init__(self, fail=0):
        self.calls = []
        self.fail = fail

    def call(self, service, tool, args):
        self.calls.append(tool)
        if self.fail:
            self.fail -= 1
            raise RuntimeError("down")
        item = []
        if tool == "get_a_share_calendar_trading_days":
            item = [{"date": "20260925"}]
        elif tool == "get_a_share_index_catalog_ths_index_list":
            item = ([{"thscode": "885431.TI", "name": "新能源汽车"}, {"thscode": "885001.TI", "name": "储能"}]
                    if args["tag"] == "cn_concept" else [{"thscode": "881101.TI", "name": "银行"}])
        elif tool == "get_a_share_index_prices_snapshot":
            prices = {"885431.TI": 1.5, "885001.TI": -0.5, "881101.TI": 0.2}
            item = [{"thscode": c, "last_price": 1000, "price_change_ratio_pct": prices[c], "turnover": 5e9,
                     "volume": 1e8, "prev_price": 990, "open_price": 991, "high_price": 1001, "low_price": 989}
                    for c in args["thscodes"].split(",") if c in prices]
        elif tool == "get_a_share_index_constituents_ths_stock_list":
            item = [{"thscode": "600000.SH", "name": "浦发银行"}, {"thscode": "300750.SZ", "name": "宁德时代"},
                    {"thscode": "000016.SZ", "name": "*ST康佳A"}, {"thscode": "600001.SH", "name": "某某"}]
        elif tool == "get_a_share_prices_snapshot":
            table = {
                "600000.SH": dict(last_price=9.9, prev_price=9.0, high_price=9.9, volume=1000, turnover=9900,
                                  price_change_ratio_pct=10.0),
                "300750.SZ": dict(last_price=300.0, prev_price=290.0, high_price=348.0, volume=10, turnover=3000,
                                  price_change_ratio_pct=3.45),
                "000016.SZ": dict(last_price=None, prev_price=2.46, high_price=None, volume=0, turnover=0,
                                  price_change_ratio_pct=None),
                "600001.SH": dict(last_price=10.0, prev_price=10.0, high_price=10.2, volume=5, turnover=50,
                                  price_change_ratio_pct=0.0),
            }
            item = [{"thscode": c, "open_price": 9.0, "low_price": 8.9, **table[c]}
                    for c in args["thscodes"].split(",") if c in table]
        elif tool == "get_a_share_special_data_limit_up_pool":
            item = [{"thscode": "600000.SH"}]
        return {"data": {"item": item, "pagination": {"pages": 1}}, "response_timestamp": TS}


def public_ok(symbols):
    table = {"sh.600000": (9.9, 9.0), "sz.300750": (300.0, 290.0), "sh.600001": (11.0, 10.0)}
    return {s: {"last": table[s][0], "previous_close": table[s][1]} for s in symbols if s in table}


class Reference:
    def no_limit_new_listing(self, symbol, today):
        return False


def provider(client=None, **kw):
    p = SectorIntradayProvider(client or FakeClient(), public_loaders={"tencent": public_ok},
                               now_fn=lambda: NOW, sleep=lambda s: None, **kw)
    p.reference = Reference()
    return p


class SectorIntradayTests(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(niuniu_symbol("600519.SH"), "sh.600519")
        self.assertEqual(niuniu_symbol("885431.TI"), "")
        self.assertEqual(limit_prices("sh.600000", "浦发银行", 9.0), (9.9, 8.1))
        self.assertEqual(limit_prices("sz.300750", "宁德时代", 290.0), (348.0, 232.0))
        # main-board ST: 5 % until 2026-07-03, 10 % from 2026-07-06 (trading/price_limit_regime.py)
        self.assertEqual(limit_prices("sz.000016", "*ST康佳A", 2.46, date(2026, 7, 3)), (2.58, 2.34))
        self.assertEqual(limit_prices("sz.000016", "*ST康佳A", 2.46, date(2026, 7, 6)), (2.71, 2.21))
        self.assertEqual(limit_prices("sz.302132", "中航成飞", 50.0), (60.0, 40.0))  # ChiNext 302 is 20 %
        self.assertEqual(limit_prices("bj.920982", "锦波生物", 100.0), (130.0, 70.0))
        self.assertIsNone(limit_prices("sh.900901", "云赛B股", 1.0))  # a board the rule table does not model
        self.assertEqual(market_status(NOW, True), "TRADING")
        self.assertEqual(market_status(NOW.replace(hour=9, minute=20), True), "OPENING_AUCTION")
        self.assertEqual(market_status(NOW.replace(hour=12), True), "MIDDAY_BREAK")
        self.assertEqual(market_status(NOW, False), "NON_TRADING_DAY")

    def test_board_snapshot_sorted_units_and_cache(self):
        client = FakeClient()
        p = provider(client)
        value = p.board_snapshot(["concept", "industry"])
        self.assertEqual([b["code"] for b in value["boards"]], ["885431.TI", "881101.TI", "885001.TI"])
        self.assertEqual(value["market_status"], "TRADING")
        self.assertEqual(value["completeness"], "FULL")
        self.assertFalse(value["cache"]["hit"])
        calls = len(client.calls)
        again = p.board_snapshot(["industry", "concept"])
        self.assertTrue(again["cache"]["hit"])
        self.assertEqual(len(client.calls), calls)
        self.assertEqual(len(p.board_series("885431.TI")["points"]), 1)

    def test_invalid_types(self):
        with self.assertRaises(InvalidRequest):
            provider().board_snapshot(["region"])
        with self.assertRaises(InvalidRequest):
            provider().board_members("600000.SH")

    def test_members_limits_suspension_and_cross_check(self):
        value = provider().board_members("885431.TI")
        rows = {r["symbol"]: r for r in value["members"]}
        self.assertEqual(rows["sh.600000"]["limit_status"], "limit_up")
        self.assertEqual(rows["sh.600000"]["limit_check"], "agree")
        self.assertEqual(rows["sz.300750"]["limit_status"], "limit_break")
        self.assertEqual(rows["sz.300750"]["limit_check"], "computed_only")
        self.assertEqual(rows["sz.000016"]["status"], "no_trade_today")
        self.assertEqual(rows["sh.600001"]["status"], "withheld_source_mismatch")
        self.assertIsNone(rows["sh.600001"]["last"])
        self.assertEqual(value["completeness"], "PARTIAL")
        self.assertEqual(value["counts"]["withheld"], 1)
        self.assertTrue(value["membership_is_current_not_historical"])

    def test_members_use_the_limit_rule_of_the_session(self):
        class STUpSeven(FakeClient):
            def call(self, service, tool, args):
                value = super().call(service, tool, args)
                if tool == "get_a_share_prices_snapshot":
                    for item in value["data"]["item"]:
                        if item["thscode"] == "000016.SZ":  # main-board ST up 6.9 % on 2026-09-25
                            item.update(last_price=2.63, high_price=2.63, volume=100, turnover=263,
                                        price_change_ratio_pct=6.91)
                return value

        rows = {r["symbol"]: r for r in provider(STUpSeven()).board_members("885431.TI")["members"]}
        st = rows["sz.000016"]
        self.assertEqual((st["limit_up_price"], st["limit_down_price"]), (2.71, 2.21))
        self.assertIsNone(st["limit_status"])  # not limit-up under the 10 % rule

    def test_failure_returns_stale_cache_or_raises(self):
        client = FakeClient()
        p = provider(client, min_interval_boards=0)
        p.board_snapshot("concept")
        client.fail = 10
        stale = p.board_snapshot("concept")
        self.assertTrue(stale["stale"])
        with self.assertRaises(DataProviderError):
            provider(FakeClient(fail=10)).board_snapshot("concept")


class BoardExtrasTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify_board("林业", "industry"), ("industry", None))
        self.assertEqual(classify_board("储能", "concept"), ("theme", None))
        for name, reason in (("融资融券", "trading_access"), ("沪股通", "trading_access"),
                             ("证金持股", "holder_label"), ("同花顺漂亮100", "index_selection"),
                             ("中国AI50", "index_selection"), ("ST板块", "status_label"),
                             ("科创次新股", "listing_age"), ("2026中报预增", "earnings_label")):
            self.assertEqual(classify_board(name, "concept"), ("market_label", reason), name)

    def test_constituent_count_from_daily_file(self):
        import tempfile
        from pathlib import Path
        import pandas as pd
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "lake/bronze/provider=fuyao/sector_board_constituents"
            base.mkdir(parents=True)
            pd.DataFrame({"board_code": ["885431.TI"] * 3 + ["881101.TI"],
                          "symbol": ["sh.600000", "sz.300750", "sh.600001", "sh.600000"]}
                         ).to_parquet(base / "date=2026-09-24.parquet", index=False)
            p = SectorIntradayProvider(FakeClient(), public_loaders={}, now_fn=lambda: NOW,
                                       sleep=lambda s: None, data_root=tmp)
            value = p.board_snapshot(["concept", "industry"])
            by = {b["code"]: b for b in value["boards"]}
            self.assertEqual(by["885431.TI"]["constituent_count"], 3)
            self.assertEqual(by["881101.TI"]["constituent_count"], 1)
            self.assertIsNone(by["885001.TI"]["constituent_count"])
            self.assertEqual(by["881101.TI"]["board_class"], "industry")
            self.assertEqual(value["constituent_counts_date"], "2026-09-24")


if __name__ == "__main__":
    unittest.main()

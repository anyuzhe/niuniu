"""cninfo_history 逐日回补的超限拆分：板块超限按行业门类拆，门类超限再按分类拆（不联网，模拟巨潮分页）。"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cninfo_history", ROOT / "scripts" / "collect" / "cninfo_history.py")
C = importlib.util.module_from_spec(spec)
sys.modules["cninfo_history"] = C
spec.loader.exec_module(C)


def make_universe():
    """一天一个板块：制造业 4000 条（超限），其余门类各 10 条；制造业里分类 A 2000 条、B 1990 条、另有 10 条不属于任何分类。"""
    rows = []
    n = 0
    for tr in C.TRADES:
        k = 4000 if tr == "制造业" else 10
        for i in range(k):
            if tr == "制造业":
                cat = C.CATEGORIES[0] if i < 2000 else (C.CATEGORIES[1] if i < 3990 else "")
            else:
                cat = C.CATEGORIES[2]
            rows.append({"announcementId": str(n), "secCode": f"{n % 900000:06d}", "trade": tr, "cat": cat,
                         "announcementTime": 1745971200000, "announcementTitle": "t"})
            n += 1
    return rows


UNIVERSE = make_universe()


def fake_post(session, payload, url=None):
    sel = [r for r in UNIVERSE if (not payload["trade"] or r["trade"] == payload["trade"])
           and (not payload["category"] or r["cat"] == payload["category"])]
    page = int(payload["pageNum"])
    chunk = sel[(page - 1) * 30: page * 30]
    return {"totalAnnouncement": len(sel), "announcements": chunk, "hasMore": page * 30 < len(sel)}


def test_split_by_trade_then_category(monkeypatch):
    monkeypatch.setattr(C, "post", fake_post)
    monkeypatch.setattr(C, "PACE", 0)
    C.WARNINGS.clear()
    items = C.split_by_trade(None, "2025-04-30~2025-04-30", "", "", "shmb", len(UNIVERSE))
    # 制造业按分类拆回 3990 条（10 条无分类的取不到），其余 18 个门类各 10 条
    assert len(items) == 3990 + 18 * 10
    assert len({(x["announcementId"], x["secCode"]) for x in items}) == len(items)
    assert C.WARNINGS and "制造业" in C.WARNINGS[0]


def test_split_by_trade_exact_when_no_trade_overflows(monkeypatch):
    small = [r for r in UNIVERSE if r["trade"] != "制造业"]
    monkeypatch.setattr(C, "post", lambda s, p, url=None: fake_post_from(small, p))
    monkeypatch.setattr(C, "PACE", 0)
    C.WARNINGS.clear()
    items = C.split_by_trade(None, "2025-04-30~2025-04-30", "", "", "shmb", len(small))
    assert len(items) == len(small)
    assert not C.WARNINGS


def fake_post_from(universe, payload):
    sel = [r for r in universe if (not payload["trade"] or r["trade"] == payload["trade"])
           and (not payload["category"] or r["cat"] == payload["category"])]
    page = int(payload["pageNum"])
    return {"totalAnnouncement": len(sel), "announcements": sel[(page - 1) * 30: page * 30], "hasMore": page * 30 < len(sel)}


def test_duplicate_page_is_retried(monkeypatch):
    """第 2 页第一次返回第 1 页的内容（限流时的表现），退避重取后正常：不报错、条数完整。"""
    small = [dict(r, announcementId=f"m{i}") for i, r in enumerate(UNIVERSE[:75])]
    calls = {"p2": 0}

    def flaky(session, payload, url=None):
        page = int(payload["pageNum"])
        if page == 2 and calls["p2"] == 0:
            calls["p2"] += 1
            return {"totalAnnouncement": len(small), "announcements": small[:30], "hasMore": True}
        return {"totalAnnouncement": len(small), "announcements": small[(page - 1) * 30: page * 30], "hasMore": page * 30 < len(small)}

    monkeypatch.setattr(C, "post", flaky)
    monkeypatch.setattr(C, "PACE", 0)
    monkeypatch.setattr(C, "DUP_RETRY_SLEEP", 0)
    items = C.query_pages(None, se_date="2024-04-30~2024-04-30", plate="shmb")
    assert len(items) == 75 and calls["p2"] == 1


def test_persistent_duplicate_page_splits_by_category(monkeypatch):
    """制造业不拆时第 2 页一直重复（重取也没用）：改按分类拆，不报错；其它门类照常。"""
    small = [r for r in UNIVERSE if r["trade"] != "制造业" or r["cat"]][:2500]

    def stuck(session, payload, url=None):
        sel = [r for r in small if (not payload["trade"] or r["trade"] == payload["trade"])
               and (not payload["category"] or r["cat"] == payload["category"])]
        page = int(payload["pageNum"])
        if payload["trade"] == "制造业" and not payload["category"] and page >= 2:
            page = 1
        return {"totalAnnouncement": len(sel), "announcements": sel[(page - 1) * 30: page * 30], "hasMore": True if page * 30 < len(sel) else False}

    monkeypatch.setattr(C, "post", stuck)
    monkeypatch.setattr(C, "PACE", 0)
    monkeypatch.setattr(C, "DUP_RETRY_SLEEP", 0)
    C.WARNINGS.clear()
    items = C.split_by_trade(None, "2020-04-30~2020-04-30", "", "", "shmb", len(small))
    assert len(items) == len(small)
    assert C.WARNINGS and "翻页重复" in C.WARNINGS[0]


def test_dup_page_message_is_short():
    e = C.DupPage([{"x": 1}] * 1000, 5000, "第 3 页全是重复条目（疑似被限流）：2020-04-30~2020-04-30")
    assert str(e).startswith("第 3 页") and len(str(e)) < 80

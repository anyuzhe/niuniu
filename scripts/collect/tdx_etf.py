"""ETF universe and helpers on the TDX quote servers (personal research use only).

    python scripts/collect/tdx_etf.py universe      # list every ETF, rank by 1-year turnover, pick the set

Writes <data-root>/lake/bronze/provider=tdx/etf_universe/date=YYYY-MM-DD.parquet with
``symbol, name, market, decimal_point, first_bar, amount_1y, days_1y, rank, selected, reason``
(and ``latest.parquet``), plus ``category`` guessed from the short name (money, bond, gold,
cross_border, broad, sector).  The selection is: the 50 largest by one-year turnover, the broad
funds named in the 2026-09-28 CODE request, and by turnover the top 30 sector/theme, 10
cross-border, 10 bond and 4 gold funds (cross-border, bond, gold and money funds can be traded
back the same day, T+0).

Two pytdx quirks are handled here: security-list pages with names that do not decode as
GBK (decoded with ``errors="replace"``), and real-time quotes of 3-decimal instruments
(all ETFs) being 10x too large -- ``scale_quote`` fixes them using ``decimal_point``.
Bars (K lines) are not affected.
"""
from __future__ import annotations

import io
import json
import os
import struct
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collect import paths  # noqa: E402
from collect.tdx_minute import HOSTS, _load_pytdx  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")
BASE = "lake/bronze/provider=tdx/etf_universe"
NAMED = ["sh.510300", "sz.159919", "sh.510310", "sh.510500", "sz.159922", "sh.512100", "sz.159845", "sz.159915",
         "sz.159952", "sh.510050", "sh.588000", "sh.588080"]
MONEY_WORDS = ("日利", "添益", "货币", "快线", "现金", "理财", "保证金", "场内宝", "财富宝", "收益宝", "天天宝")
BROAD_WORDS = ("300", "500", "1000", "2000", "A500", "A50", "50ETF", "上证50", "科创50", "科创板50", "创业板", "创业ETF",
               "中证", "上证", "深证", "沪深", "红利", "双创", "MSCI", "180", "100", "综指", "A100")
T0_WORDS = ("黄金", "国债", "国开", "政金", "短融", "信用债", "公司债", "城投", "地债", "可转债", "货币", "纳指", "纳斯达克",
            "标普", "恒生", "港股", "中概", "日经", "德国", "法国", "美国", "亚太", "沙特", "东南亚", "H股", "香港")


def category(name: str) -> str:
    """Rough fund category from the exchange short name (documented as name-based)."""
    if any(w in name for w in MONEY_WORDS):
        return "money"
    if "黄金" in name or "金ETF" in name:
        return "gold"
    if "债" in name or "信用" in name or "短融" in name or "政金" in name or "国开" in name:
        return "bond"
    if any(w in name for w in T0_WORDS):
        return "cross_border"
    if any(w in name for w in BROAD_WORDS):
        return "broad"
    return "sector"


def patch_security_list():
    from pytdx.parser import get_security_list as mod
    from pytdx.helper import get_volume

    def parse(self, body_buf):
        pos = 0
        (num,) = struct.unpack("<H", body_buf[:2])
        pos += 2
        out = []
        for _ in range(num):
            code, volunit, name_bytes, _r1, decimal_point, pre_close_raw, _r2 = struct.unpack(
                "<6sH8s4sBI4s", body_buf[pos:pos + 29])
            pos += 29
            out.append(OrderedDict(code=code.decode("utf-8", "replace"), volunit=volunit, decimal_point=decimal_point,
                                   name=name_bytes.decode("gbk", "replace").rstrip("\x00"),
                                   pre_close=get_volume(pre_close_raw)))
        return out
    mod.GetSecurityList.parseResponse = parse


def scale_quote(quote: dict, decimal_point: int) -> dict:
    """pytdx scales quote prices as if every instrument had 2 decimals."""
    if decimal_point == 3:
        q = dict(quote)
        for key in ("price", "last_close", "open", "high", "low", *[f"bid{i}" for i in range(1, 6)],
                    *[f"ask{i}" for i in range(1, 6)]):
            if key in q and q[key] is not None:
                q[key] = round(float(q[key]) / 10, 4)
        return q
    return quote


def connect(API):
    for host, port in HOSTS:
        api = API(raise_exception=True)
        try:
            if api.connect(host, port, time_out=8):
                return api
        except Exception:
            continue
    raise ConnectionError("no TDX host reachable")


def list_etfs(api) -> list[dict]:
    out = []
    for market, prefix in ((1, "sh"), (0, "sz")):
        count = api.get_security_count(market)
        for start in range(0, count, 1000):
            for item in api.get_security_list(market, start) or []:
                code = item["code"]
                if (market == 1 and code[:2] in ("51", "56", "58")) or (market == 0 and code[:3] == "159"):
                    out.append({"symbol": f"{prefix}.{code}", "name": item["name"], "market": market,
                                "decimal_point": int(item["decimal_point"])})
            time.sleep(0.1)
    return out


def universe(data_root: Path, *, log=print) -> Path:
    import pandas as pd
    API = _load_pytdx()
    patch_security_list()
    api = connect(API)
    etfs = list_etfs(api)
    log(f"{len(etfs)} ETFs listed")
    for i, e in enumerate(etfs, 1):
        try:
            bars = api.get_security_bars(9, e["market"], e["symbol"][3:], 0, 250) or []
        except Exception:
            bars = []
        good = [b for b in bars if b["amount"] > 1e-6]
        e["first_bar"] = bars[0]["datetime"][:10] if bars else None
        e["amount_1y"] = float(sum(b["amount"] for b in good))
        e["days_1y"] = len(good)
        time.sleep(0.05)
        if i % 200 == 0:
            log(f"{i}/{len(etfs)}")
    frame = pd.DataFrame(etfs).sort_values("amount_1y", ascending=False).reset_index(drop=True)
    frame["rank"] = frame.index + 1
    frame["category"] = [category(n) for n in frame["name"]]
    quota = {"sector": 30, "cross_border": 10, "gold": 4, "bond": 10}
    taken = {k: 0 for k in quota}
    reasons = []
    for row in frame.itertuples():
        why = []
        if row.rank <= 50:
            why.append("top50_turnover")
        if row.symbol in NAMED:
            why.append("named_broad")
        if row.category in quota and taken[row.category] < quota[row.category] and row.days_1y >= 20:
            taken[row.category] += 1
            why.append(f"top_{row.category}")
        reasons.append(",".join(why))
    frame["reason"] = reasons
    frame["selected"] = frame["reason"] != ""
    frame["observed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    today = datetime.now(TZ).date().isoformat()
    out = data_root / BASE / f"date={today}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    for path in (out, data_root / BASE / "latest.parquet"):
        buf = io.BytesIO()
        frame.to_parquet(buf, index=False)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(buf.getvalue())
        os.replace(tmp, path)
    log(json.dumps({"etfs": len(frame), "selected": int(frame["selected"].sum()), "file": str(out)}, ensure_ascii=False))
    return out


def selected(data_root: Path) -> list[dict]:
    import pandas as pd
    path = data_root / BASE / "latest.parquet"
    frame = pd.read_parquet(path)
    return frame[frame["selected"]].to_dict(orient="records")


if __name__ == "__main__":
    if sys.argv[1:] == ["universe"]:
        universe(paths.DATA_ROOT)
    else:
        raise SystemExit(__doc__)

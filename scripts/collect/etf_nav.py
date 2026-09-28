"""Daily NAV history and basic facts for the selected ETFs (Eastmoney fund pages).

    python scripts/collect/etf_nav.py            # all selected ETFs in etf_universe/latest.parquet

For each fund one request to ``fund.eastmoney.com/pingzhongdata/<code>.js`` (the whole NAV
history) and one to ``fundf10.eastmoney.com/jbgk_<code>.html`` (tracking index, type, fees),
paced >= 1.5 s.  Writes

    <data-root>/lake/bronze/provider=eastmoney/etf_nav/<sh_510300>.parquet
        date, symbol, nav (unit NAV), acc_nav (accumulated NAV), daily_return_pct, distribution (text), fetch_ts
    <data-root>/lake/bronze/provider=eastmoney/etf_info/latest.parquet
        symbol, name, fund_type, tracking_index, benchmark, inception_date, management_fee, custody_fee, fetch_ts

The NAV is published after the close (T evening) for the day T; the date is the NAV date.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collect import paths  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")
PACE = 1.5
UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/"}


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _get(session, url: str) -> str:
    response = session.get(url, headers=UA, timeout=20)
    response.raise_for_status()
    return response.text


def parse_nav(text: str, symbol: str):
    import pandas as pd
    nav = json.loads(re.search(r"var Data_netWorthTrend = (\[.*?\]);", text, re.S).group(1))
    acc = json.loads(re.search(r"var Data_ACWorthTrend = (\[.*?\]);", text, re.S).group(1))
    acc_by = {int(x[0]): x[1] for x in acc}
    rows = [{"date": datetime.fromtimestamp(int(x["x"]) / 1000, TZ).date(), "symbol": symbol,
             "nav": float(x["y"]), "acc_nav": acc_by.get(int(x["x"])),
             "daily_return_pct": x.get("equityReturn"), "distribution": x.get("unitMoney") or None} for x in nav]
    return pd.DataFrame(rows)


def parse_info(html: str, symbol: str, name: str) -> dict:
    def cell(label):
        m = re.search(label + r"</th><td[^>]*>(.*?)</td>", html, re.S)
        return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else None
    inception = re.search(r"成立日期[：:]\s*(?:<[^>]+>\s*)*(\d{4}-\d{2}-\d{2})", html)
    return {"symbol": symbol, "name": name, "fund_type": cell("基金类型"), "tracking_index": cell("跟踪标的"),
            "benchmark": cell("业绩比较基准"), "inception_date": inception.group(1) if inception else None,
            "management_fee": cell("管理费率"), "custody_fee": cell("托管费率")}


def run(data_root: Path, log=print) -> dict:
    import pandas as pd
    import requests
    universe = pd.read_parquet(data_root / "lake/bronze/provider=tdx/etf_universe/latest.parquet")
    chosen = universe[universe["selected"]]
    session = requests.Session()
    fetch_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    infos, failed = [], {}
    for i, row in enumerate(chosen.itertuples(), 1):
        code = row.symbol[3:]
        try:
            frame = parse_nav(_get(session, f"https://fund.eastmoney.com/pingzhongdata/{code}.js"), row.symbol)
            frame["fetch_ts"] = fetch_ts
            buf = io.BytesIO()
            frame.to_parquet(buf, index=False)
            _atomic(data_root / "lake/bronze/provider=eastmoney/etf_nav" / (row.symbol.replace(".", "_") + ".parquet"),
                    buf.getvalue())
            time.sleep(PACE)
            info = parse_info(_get(session, f"https://fundf10.eastmoney.com/jbgk_{code}.html"), row.symbol, row.name)
            info["fetch_ts"] = fetch_ts
            infos.append(info)
        except Exception as error:
            failed[row.symbol] = f"{type(error).__name__}: {error}"[:200]
        time.sleep(PACE)
        if i % 20 == 0:
            log(f"{i}/{len(chosen)}")
    buf = io.BytesIO()
    pd.DataFrame(infos).to_parquet(buf, index=False)
    _atomic(data_root / "lake/bronze/provider=eastmoney/etf_info/latest.parquet", buf.getvalue())
    summary = {"funds": len(chosen), "ok": len(infos), "failed": failed}
    log(json.dumps(summary, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    run(paths.DATA_ROOT, log=lambda m: print(m, flush=True))

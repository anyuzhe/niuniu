"""Daily snapshot of THS concept / industry board constituents (Fuyao).

One file per observation day with every (board, stock) pair:

    <data-root>/lake/bronze/provider=fuyao/sector_board_constituents/date=YYYY-MM-DD.parquet

columns ``board_code, board_name, board_type, symbol, name, observed_at``, plus
``_receipts/<date>.json`` recording each board (ok / empty / failed).  Work is
resumable: partial results live in ``_partial/<date>.jsonl`` until every board has
been fetched, then the day file is written atomically.  ``SectorIntradayProvider``
reads the latest complete day file for ``constituent_count``.

Membership is the vendor's *current* membership on the observation day; it is not a
historical record.  One run fetches ~710 boards (about 0.4 s each, paced), so the
full day takes a few minutes; ``--max-seconds`` bounds one invocation.

    python scripts/collect/sector_constituents.py --max-seconds 150
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from collect import paths  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")
TAGS = {"concept": "cn_concept", "industry": "industry"}
PACE = 0.6


def _atomic(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return hashlib.sha256(data).hexdigest()


def run(data_root: Path, *, max_seconds: float, client=None, today: str | None = None) -> dict:
    import pandas as pd
    from quantlab.data.sector_intraday import niuniu_symbol
    if client is None:
        from quantlab.agent.fuyao_mcp import FuyaoMCPClient
        client = FuyaoMCPClient()
    today = today or datetime.now(TZ).date().isoformat()
    base = data_root / "lake/bronze/provider=fuyao/sector_board_constituents"
    final = base / f"date={today}.parquet"
    if final.is_file():
        return {"date": today, "status": "already_complete", "file": str(final)}
    partial = base / "_partial" / f"{today}.jsonl"
    receipt_path = base / "_receipts" / f"{today}.json"
    done: dict[str, dict] = {}
    skipped = 0
    if partial.is_file():
        text = partial.read_text(encoding="utf-8")
        for line in text.splitlines():
            try:
                row = json.loads(line)
                done[row["board_code"]] = row
            except (ValueError, KeyError, TypeError):
                skipped += 1  # cut short by a killed process or an unplugged disk: that board is fetched again
        if text and not text.endswith("\n"):
            with partial.open("a", encoding="utf-8") as sink:
                sink.write("\n")  # new rows start on their own line
    catalog = []
    for kind, tag in TAGS.items():
        call = client.call("a-share-index", "get_a_share_index_catalog_ths_index_list", {"tag": tag})
        for row in (call.get("data") or {}).get("item", []):
            code = str(row.get("thscode", "")).upper()
            if code.endswith(".TI") and all(code != c for c, _, _ in catalog):
                catalog.append((code, str(row.get("name") or ""), kind))
    if len(catalog) < 500:
        raise RuntimeError(f"board catalog looks incomplete: {len(catalog)} boards")
    start = time.monotonic()
    timed_out = False
    partial.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("a", encoding="utf-8") as sink:
        for code, name, kind in catalog:
            if code in done and done[code]["status"] in ("ok", "empty"):
                continue
            if time.monotonic() - start > max_seconds:
                timed_out = True
                break
            observed = datetime.now(timezone.utc).isoformat()
            try:
                call = client.call("a-share-index", "get_a_share_index_constituents_ths_stock_list", {"thscode": code})
                members = [{"symbol": niuniu_symbol(r.get("thscode")), "name": str(r.get("name") or "")}
                           for r in (call.get("data") or {}).get("item", [])]
                members = [m for m in members if m["symbol"]]
                row = {"board_code": code, "board_name": name, "board_type": kind, "observed_at": observed,
                       "status": "ok" if members else "empty", "members": members}
            except Exception as error:  # recorded; retried on the next invocation
                row = {"board_code": code, "board_name": name, "board_type": kind, "observed_at": observed,
                       "status": "failed", "error": f"{type(error).__name__}: {error}"[:200], "members": []}
            done[code] = row
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            sink.flush()
            time.sleep(PACE)
    counts = {}
    for row in done.values():
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    complete = all(code in done and done[code]["status"] in ("ok", "empty") for code, _, _ in catalog)
    result = {"date": today, "boards": len(catalog), **counts, "complete": complete, "timed_out": timed_out}
    if skipped:
        result["skipped_partial_lines"] = skipped
    if complete:
        records = [{"board_code": r["board_code"], "board_name": r["board_name"], "board_type": r["board_type"],
                    "symbol": m["symbol"], "name": m["name"], "observed_at": r["observed_at"]}
                   for code, _, _ in catalog for r in [done[code]] for m in r["members"]]
        buf = io.BytesIO()
        pd.DataFrame(records, columns=["board_code", "board_name", "board_type", "symbol", "name",
                                       "observed_at"]).to_parquet(buf, index=False)
        result.update(rows=len(records), sha256=_atomic(final, buf.getvalue()), file=str(final),
                      empty_boards=[r["board_code"] for r in done.values() if r["status"] == "empty"])
    _atomic(receipt_path, (json.dumps(result, ensure_ascii=False, indent=1) + "\n").encode())
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", default=str(paths.DATA_ROOT))
    parser.add_argument("--max-seconds", type=float, default=1e9)
    args = parser.parse_args(argv)
    result = run(Path(args.data_root), max_seconds=args.max_seconds)
    print(json.dumps({k: v for k, v in result.items() if k != "empty_boards"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

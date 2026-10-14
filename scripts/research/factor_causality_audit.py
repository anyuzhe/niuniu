#!/usr/bin/env python3
"""Audit every registered factor for look-ahead on real bars; read-only, writes only --out.

Each factor is recomputed with (a) all data after a cutoff removed and (b) all data after the
cutoff rescaled; values up to the cutoff must not change. Evidence, not proof.

    python scripts/research/factor_causality_audit.py --bars bars.parquet --out audit.json
"""
from __future__ import annotations
import argparse, json, sys, time
from collections import Counter
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from quantlab.app import default_registry  # noqa: E402
from quantlab.causal import audit_prefix_invariance  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bars", required=True, help="parquet in the official bar schema (symbol, datetime, available_at, timeframe, OHLCV, turnover)")
    parser.add_argument("--out", required=True, help="JSON report path")
    parser.add_argument("--symbols", type=int, default=12, help="use the first N symbols (default 12)")
    parser.add_argument("--ids", nargs="*", help="only these factor ids")
    parser.add_argument("--tail", type=int, default=0, help="keep only the last N sessions (Alpha factors cost seconds per pass; 700 is enough)")
    parser.add_argument("--cutoffs", type=float, nargs="+", default=[0.5, 0.75, 0.9], help="cutoff positions as fractions of the sessions")
    args = parser.parse_args()
    bars = pl.read_parquet(args.bars)
    keep = sorted(bars["symbol"].unique().to_list())[:args.symbols]
    bars = bars.filter(pl.col("symbol").is_in(keep))
    if args.tail:
        bars = bars.filter(pl.col("datetime").is_in(sorted(bars["datetime"].unique().to_list())[-args.tail:]))
    reports, started = [], time.time()
    for factor_id, _version, factor in default_registry().factors():
        if args.ids and factor_id not in args.ids:
            continue
        begin = time.time()
        report = audit_prefix_invariance(factor, bars, cutoff_fractions=tuple(args.cutoffs))
        report["seconds"] = round(time.time() - begin, 2)
        reports.append(report)
        if report["status"] in ("FAIL", "ERROR"):
            print(report["status"], factor_id, report["reason"][:100], flush=True)
    Path(args.out).write_text(json.dumps(reports, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(dict(Counter(r["status"] for r in reports)), "seconds", round(time.time() - started))
    return 1 if any(r["status"] == "FAIL" for r in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())

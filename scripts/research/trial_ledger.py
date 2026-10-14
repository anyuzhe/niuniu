#!/usr/bin/env python3
"""Record every configuration you try, then ask what the best one is worth after selection.

    python scripts/research/trial_ledger.py add     --ledger artifacts/_ledger --family quad-factor --config '{"hold":40}' --curve curve.parquet --initial-cash 1e8
    python scripts/research/trial_ledger.py add     --ledger L --family F --config '{...}' --returns returns.csv     # columns: date,return
    python scripts/research/trial_ledger.py add     --ledger L --family F --config '{...}'                           # count only (no series)
    python scripts/research/trial_ledger.py summary --ledger L --family F [--assumed-trials 500]
    python scripts/research/trial_ledger.py verify  --ledger L

Record the trial when it is run, before you look at which one is best. A trial left out makes N too small.
"""
from __future__ import annotations
import argparse, csv, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from quantlab.statistics import trial_ledger as tl  # noqa: E402


def _series(args):
    if args.returns:
        with open(args.returns, newline="") as stream:
            rows = list(csv.DictReader(stream))
        return [float(r["return"]) for r in rows], [r["date"] for r in rows]
    if args.curve:
        import polars as pl
        from quantlab.statistics.equity_inference import daily_returns
        curve = pl.read_parquet(args.curve)
        daily = curve.sort("datetime").with_columns(pl.col("datetime").dt.date().alias("date")).group_by("date", maintain_order=True).agg(pl.col("equity").last())
        return list(daily_returns(curve, args.initial_cash)), [str(d) for d in daily["date"]]
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("add", "summary", "verify"))
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--family")
    parser.add_argument("--config", help="JSON describing this configuration")
    parser.add_argument("--returns")
    parser.add_argument("--curve")
    parser.add_argument("--initial-cash", type=float)
    parser.add_argument("--note", default="")
    parser.add_argument("--assumed-trials", type=int)
    args = parser.parse_args()
    if args.action == "verify":
        out = tl.verify_ledger(args.ledger)
    elif args.action == "summary":
        out = tl.summarize(args.ledger, args.family, assumed_trials=args.assumed_trials)
    else:
        if not args.family or args.config is None:
            parser.error("add needs --family and --config")
        if args.curve and not args.initial_cash:
            parser.error("--curve needs --initial-cash")
        returns, dates = _series(args)
        out = tl.record_trial(args.ledger, args.family, json.loads(args.config), returns, dates=dates, note=args.note)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())

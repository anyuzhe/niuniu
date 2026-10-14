#!/usr/bin/env python3
"""Pre-registered IC scan of the whole GTJA191 pack as ONE fixed family, corrected with Holm.

The design below is fixed BEFORE any result is looked at; change it only by starting a new output folder.

    universe  main-board stocks (sh 600/601/603/605, sz 000/001/002/003) in the local baostock daily bars whose
              bars in the window have >= 700 rows and no nulls; every 10th by code, then every k-th so that 100 remain.
              Survivors only (they have complete data to the end of the window): NOT a point-in-time universe.
    window    2023-01-03 .. 2025-12-31  (2026 is left untouched as a reserve for anything that survives)
    test      horizon 5 days, daily mean IC and mean rank-IC, sign-flip date-block permutation (5-day blocks, 19999 draws)
    family    every offered GTJA191 factor x {IC, rank-IC}; Holm over the whole family at alpha 0.05
    failures  a factor that errors keeps its slot (reported as not run); nothing is retried silently

Resumable: run again with the same --output to continue. Stops starting new factors after --max-seconds.

    python scripts/research/gtja191_ic_scan.py --data-root /Volumes/Lexar/niuniu-data --output artifacts/_gtja191_ic_2026-10-15
"""
from __future__ import annotations
import argparse, json, sys, time
from datetime import date
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from quantlab.experiments.trial_registry import bind_result, create_registry, report_registry  # noqa: E402
from quantlab.factors.gtja import gtja_pack  # noqa: E402
from quantlab.workbench.jobs import execute, prepare  # noqa: E402
from quantlab.workbench.trial_submission import load_submissions, planned_trial, save_submissions  # noqa: E402

START, END = "2023-01-03", "2025-12-31"
BOARDS = ("sh_600", "sh_601", "sh_603", "sh_605", "sz_000", "sz_001", "sz_002", "sz_003")
PERMUTATION = {"resamples": 19999, "block_days": 5, "alpha": 0.05}
ALPHA = 0.05
TARGET = 100


def choose_universe(data_root: Path) -> dict:
    folder = data_root / "lake/bronze/provider=baostock/stock_kline_daily"
    start, end = date.fromisoformat(START), date.fromisoformat(END)
    candidates = [p.stem for p in sorted(folder.glob("*.parquet")) if p.stem[:6] in BOARDS][::10]
    clean = []
    for code in candidates:
        bars = pl.read_parquet(folder / f"{code}.parquet")
        column = bars["date"]
        days = column.str.to_date() if column.dtype == pl.Utf8 else column.cast(pl.Date)
        window = bars.filter(days.is_between(start, end))
        fields = [c for c in ("open", "high", "low", "close", "volume", "amount") if c in window.columns]
        if window.height >= 700 and not window.select(pl.any_horizontal(pl.col(fields).is_null())).to_series().any():
            clean.append(code.replace("_", "."))
    step = max(1, len(clean) // TARGET)
    return {"rule": __doc__.split("universe")[1].split("window")[0].strip(), "candidates": len(candidates),
            "clean": len(clean), "step": step, "symbols": clean[::step][:TARGET], "window": [START, END], "survivors_only": True}


def specs_for(universe: dict) -> list[tuple[str, dict]]:
    out = []
    for factor in sorted(f.definition.factor_id for f in gtja_pack().factors):
        trial_id = "t" + factor.rsplit("_", 1)[1]
        out.append((trial_id, {"question": f"GTJA191 IC scan · {factor}", "symbols": universe["symbols"], "start": START, "end": END,
                               "factor": factor, "horizons": [5], "replay": True, "permutation": PERMUTATION, "adjustment": "raw"}))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-seconds", type=float, default=1e9)
    args = parser.parse_args()
    out, family, runs = args.output, args.output / "family", args.output / "runs"
    out.mkdir(parents=True, exist_ok=True); runs.mkdir(exist_ok=True)
    marker = out / "universe.json"
    if marker.exists():
        universe = json.loads(marker.read_text())
    else:
        universe = choose_universe(args.data_root)
        marker.write_text(json.dumps(universe, ensure_ascii=False, indent=1))
    print(f"universe: {len(universe['symbols'])} symbols from {universe['clean']} clean of {universe['candidates']} candidates", flush=True)
    specs = specs_for(universe)
    if not family.exists():
        plan = {"name": "GTJA191 IC scan 2023-2025 (fixed family)", "alpha": ALPHA, "trials": [planned_trial(spec, tid) for tid, spec in specs]}
        create_registry(plan, family)
        save_submissions(family, [spec for _, spec in specs])
        print(f"registered {len(specs)} trials", flush=True)
    jobs = load_submissions(family)
    ids = [tid for tid, _ in specs]
    failures_path = out / "failures.jsonl"
    failed = {json.loads(line)["trial_id"] for line in failures_path.read_text().splitlines()} if failures_path.exists() else set()
    started, done_now = time.time(), 0
    for tid, (_, spec) in zip(ids, jobs):
        if (family / "results" / f"{tid}.json").exists() or tid in failed:
            continue
        if time.time() - started > args.max_seconds:
            break
        try:
            result = execute(prepare(spec), args.data_root, runs)
            bind_result(family, tid, runs / result.run_id)
        except Exception as error:  # keep the slot, record why, do not retry
            with failures_path.open("a") as stream:
                stream.write(json.dumps({"trial_id": tid, "error": f"{type(error).__name__}: {str(error)[:300]}"}, ensure_ascii=False) + "\n")
            failed.add(tid)
            print(f"FAILED {tid}: {type(error).__name__}: {str(error)[:120]}", flush=True)
        done_now += 1
    bound = sum((family / "results" / f"{tid}.json").exists() for tid in ids)
    print(f"bound {bound}/{len(ids)}, failed {len(failed)}, this call {done_now}, {time.time() - started:.0f}s", flush=True)
    if bound + len(failed) == len(ids) and not (out / "report").exists():
        report = report_registry(family, out / "report")
        rejected = [t for t in report["tests"] if t.get("reject_holm")]
        print(f"REPORT: planned {report['planned_tests']}, available {report['available_tests']}, Holm rejections {len(rejected)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

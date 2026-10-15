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

On a machine where the output volume shows new files late (a mounted external disk in a sandbox) run with a local --output
and --archive-to on the big disk, then copy the output folder over at the end.
"""
from __future__ import annotations
import argparse, json, shutil, sys, time
from datetime import date
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from quantlab.experiments.trial_layout import hypotheses  # noqa: E402
from quantlab.experiments.trial_registry import _load_registry, _validate_binding, bind_result, create_registry, report_registry  # noqa: E402
from quantlab.statistics.multiple_testing import benjamini_hochberg  # noqa: E402
from quantlab.statistics.permutation import holm  # noqa: E402
from quantlab.factors.gtja import gtja_pack  # noqa: E402
from quantlab.workbench.jobs import execute, prepare  # noqa: E402
from quantlab.workbench.trial_submission import load_submissions, planned_trial, save_submissions  # noqa: E402

START, END = "2023-01-03", "2025-12-31"
BOARDS = ("sh_600", "sh_601", "sh_603", "sh_605", "sz_000", "sz_001", "sz_002", "sz_003")
PERMUTATION = {"resamples": 19999, "block_days": 5, "alpha": 0.05}
ALPHA = 0.05
TARGET = 100


def settle(action, tries: int = 8):
    """The external volume sometimes shows a just-written file late; retry only that specific failure."""
    for attempt in range(tries):
        try:
            return action()
        except FileNotFoundError:
            if attempt == tries - 1:
                raise
            time.sleep(3)


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


def restrict_to_window(data_root: Path, universe: dict, start: str, end: str) -> dict:
    """Confirmation window: keep only the already-chosen symbols whose bars are complete (full row count, no nulls) in it."""
    folder = data_root / "lake/bronze/provider=baostock/stock_kline_daily"
    lo, hi = date.fromisoformat(start), date.fromisoformat(end)
    rows = {}
    for symbol in universe["symbols"]:
        bars = pl.read_parquet(folder / f"{symbol.replace('.', '_')}.parquet")
        column = bars["date"]
        days = column.str.to_date() if column.dtype == pl.Utf8 else column.cast(pl.Date)
        window = bars.filter(days.is_between(lo, hi))
        fields = [c for c in ("open", "high", "low", "close", "volume", "amount") if c in window.columns]
        rows[symbol] = (window.height, bool(window.select(pl.any_horizontal(pl.col(fields).is_null())).to_series().any()))
    full = max(count for count, _ in rows.values())
    kept = [s for s in universe["symbols"] if rows[s] == (full, False)]
    return {**universe, "symbols": kept, "window": [start, end], "restricted_from": len(universe["symbols"]),
            "restriction_rule": "kept symbols with the full row count and no null in the new window"}


def specs_for(universe: dict) -> list[tuple[str, dict]]:
    out = []
    for factor in sorted(f.definition.factor_id for f in gtja_pack().factors):
        trial_id = "t" + factor.rsplit("_", 1)[1]
        out.append((trial_id, {"question": f"GTJA191 IC scan · {factor}", "symbols": universe["symbols"], "start": START, "end": END,
                               "factor": factor, "horizons": [5], "replay": True, "permutation": PERMUTATION, "adjustment": "raw"}))
    return out


def compact_report(family: Path, destination: Path) -> dict:
    """Same fixed-family Holm as ``report_registry`` but streams one bound record at a time.

    Each bound record is a full experiment (tens of MB), so ``report_registry`` (which keeps every record in memory and
    writes them all into one snapshot) needs several GB; this keeps only the small raw-test blocks. The bound files stay
    in the family folder, so the official report can still be produced on a bigger machine.
    """
    registry = _load_registry(family)
    tests, trials = [], []
    for trial in registry["plan"]["trials"]:
        path = family / "results" / f"{trial['trial_id']}.json"
        if not path.exists():
            tests.extend({"trial_id": trial["trial_id"], **h, "p_value": None, "status": "not_run", "reason": "no_bound_result", "raw_test": {}} for h in hypotheses(trial))
            trials.append({"trial_id": trial["trial_id"], "factor": trial["config"]["factor_id"], "status": "not_run"})
            continue
        binding = json.loads(path.read_text())
        extracted = _validate_binding(binding, trial)
        tests.extend(extracted)
        trials.append({"trial_id": trial["trial_id"], "factor": trial["config"]["factor_id"], "status": binding["record"]["status"],
                       "run_id": binding["record"]["run_id"], "binding_id": binding["binding_id"], "source_sha256": binding["source_sha256"]})
        del binding
    adjusted = holm([t["p_value"] for t in tests])
    fdr = benjamini_hochberg([t["p_value"] for t in tests], alpha=registry["plan"]["alpha"])
    factor = {t["trial_id"]: t["factor"] for t in trials}
    rows = []
    for test, p_holm, q in zip(tests, adjusted, fdr["q_values"]):
        raw = test.get("raw_test") or {}
        rows.append({"trial_id": test["trial_id"], "factor": factor[test["trial_id"]], "horizon": test["horizon"], "metric": test["metric"],
                     "estimate": raw.get("estimate"), "p_value": test["p_value"], "p_holm": p_holm, "q_bh": q,
                     "reject_holm": None if p_holm is None else p_holm <= registry["plan"]["alpha"],
                     "valid_days": raw.get("valid_days"), "status": test["status"]})
    available = [r for r in rows if r["p_value"] is not None]
    report = {"registry_id": registry["registry_id"], "method": "holm_fwer_streaming", "alpha": registry["plan"]["alpha"],
              "planned_tests": len(rows), "available_tests": len(available), "holm_rejections": sum(bool(r["reject_holm"]) for r in rows),
              "raw_p_below_alpha": sum(r["p_value"] <= registry["plan"]["alpha"] for r in available),
              "expected_raw_below_alpha_if_all_null": round(len(available) * registry["plan"]["alpha"], 1),
              "bh_fdr_rejections": sum(bool(v) for v in fdr["reject"]), "trials": trials, "tests": rows}
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "report_compact.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    top = sorted(available, key=lambda r: r["p_value"])[:25]
    lines = ["# GTJA191 IC 扫描（固定检验族，Holm）", "",
             f"计划 {report['planned_tests']} 项检验，可检验 {report['available_tests']} 项；Holm alpha={report['alpha']}：拒绝 {report['holm_rejections']} 项；"
             f"BH-FDR 拒绝 {report['bh_fdr_rejections']} 项；未校正 p≤alpha 共 {report['raw_p_below_alpha']} 项（若全是噪声约 {report['expected_raw_below_alpha_if_all_null']} 项）。", "",
             "| 因子 | 指标 | 平均 IC | 原始 p | Holm p | BH q |", "|---|---|---:|---:|---:|---:|"]
    lines += [f"| {r['factor']} | {r['metric']} | {r['estimate']:.4f} | {r['p_value']:.5f} | {r['p_holm']:.4f} | {r['q_bh']:.4f} |" for r in top]
    (destination / "report_compact.md").write_text("\n".join(lines) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-seconds", type=float, default=1e9)
    parser.add_argument("--start", help="override the window start (confirmation runs)")
    parser.add_argument("--end", help="override the window end (confirmation runs)")
    parser.add_argument("--factors", type=Path, help="JSON list of factor ids: register only these (confirmation family)")
    parser.add_argument("--family", type=Path, help="folder for the fixed registry and its bound results (default: OUTPUT/family); each bound record is ~40 MB, so put it on the big disk")
    parser.add_argument("--official-report", action="store_true", help="also run registry.report_registry (keeps every bound record in memory; needs many GB)")
    parser.add_argument("--archive-to", type=Path, help="move each finished run folder here (keeps the working disk small); evidence snapshots stay in the family folder")
    args = parser.parse_args()
    global START, END
    START, END = args.start or START, args.end or END
    out, family, runs = args.output, args.family or args.output / "family", args.output / "runs"
    out.mkdir(parents=True, exist_ok=True); runs.mkdir(exist_ok=True)
    marker = out / "universe.json"
    if marker.exists():
        universe = json.loads(marker.read_text())
    else:
        universe = choose_universe(args.data_root)
        marker.write_text(json.dumps(universe, ensure_ascii=False, indent=1))
    if tuple(universe["window"]) != (START, END):
        universe = restrict_to_window(args.data_root, universe, START, END)
        marker.write_text(json.dumps(universe, ensure_ascii=False, indent=1))
    print(f"universe: {len(universe['symbols'])} symbols from {universe['clean']} clean of {universe['candidates']} candidates", flush=True)
    specs = specs_for(universe)
    if args.factors:
        keep = set(json.loads(args.factors.read_text()))
        specs = [(tid, spec) for tid, spec in specs if spec["factor"] in keep]
        assert len(specs) == len(keep), "some requested factors are not in the pack"
    if not family.exists():
        plan = {"name": "GTJA191 IC scan 2023-2025 (fixed family)", "alpha": ALPHA, "trials": [planned_trial(spec, tid) for tid, spec in specs]}
        create_registry(plan, family)
        print(f"registered {len(specs)} trials", flush=True)
    if not (family / "submissions.json").exists():
        settle(lambda: save_submissions(family, [spec for _, spec in specs]))
    jobs = settle(lambda: load_submissions(family))
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
            settle(lambda: bind_result(family, tid, runs / result.run_id))
            if args.archive_to:
                args.archive_to.mkdir(parents=True, exist_ok=True)
                shutil.copytree(runs / result.run_id, args.archive_to / result.run_id)
                shutil.rmtree(runs / result.run_id)
                shutil.rmtree(runs / "_factor_cache", ignore_errors=True)
        except Exception as error:  # keep the slot, record why, do not retry
            with failures_path.open("a") as stream:
                stream.write(json.dumps({"trial_id": tid, "error": f"{type(error).__name__}: {str(error)[:300]}"}, ensure_ascii=False) + "\n")
            failed.add(tid)
            print(f"FAILED {tid}: {type(error).__name__}: {str(error)[:120]}", flush=True)
        done_now += 1
    bound = sum((family / "results" / f"{tid}.json").exists() for tid in ids)
    print(f"bound {bound}/{len(ids)}, failed {len(failed)}, this call {done_now}, {time.time() - started:.0f}s", flush=True)
    if bound + len(failed) == len(ids):
        if not (out / "report_compact").exists():
            report = compact_report(family, out / "report_compact")
            print(f"REPORT: planned {report['planned_tests']}, available {report['available_tests']}, Holm rejections {report['holm_rejections']}, BH {report['bh_fdr_rejections']}", flush=True)
        if args.official_report and not (out / "report").exists():  # independent of the compact report, so it can be added on a bigger machine later
            report_registry(family, out / "report")
            print(f"official report written to {out / 'report'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

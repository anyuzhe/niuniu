#!/usr/bin/env python3
"""Host-only frozen candidate validation. No GUI, model call, downloads or orders.

capture freezes normalized local bytes and provenance; run evaluates exactly the
three original expressions; verify recomputes without creating new research.
"""
from __future__ import annotations
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import io
import json
import sys

import polars as pl
import pyarrow.parquet as pq
from quantlab.app import default_registry
from quantlab.causal import assert_prefix_invariant
from quantlab.experiments.research import FactorResearchEngine
from quantlab.experiments.runner import runtime_fingerprint
from quantlab.experiments.frozen_candidate_validation import (
    select_symbols, normalize_research_frame, load_candidates, validate_protocol,
    period_daily, infer_daily, descriptive, finalize_family)
from quantlab.factors.engine import compute_factor
from quantlab.storage.codec import digest, encode


def checked(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    checksum = value.pop("checksum", None)
    if digest(value) != checksum:
        raise ValueError("Checksum mismatch: " + str(path))
    return value


def save_new(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(encode(value))


def save_verification(path: Path, value: dict) -> None:
    """An identical re-verification succeeds without overwriting its first receipt."""
    if path.exists():
        original = json.loads(path.read_bytes())
        keys = ("status", "result_checksum", "runtime", "source_files_unchanged", "formal_registration", "model_called", "gui_loaded")
        if any(original.get(key) != value.get(key) for key in keys):
            raise ValueError("Existing verification receipt conflicts")
        return
    save_new(path, value)


def load_protocol(case: Path) -> dict:
    envelope = json.loads((case/"protocol.json").read_bytes())
    protocol = envelope["protocol"]
    if envelope.get("checksum") != digest(protocol):
        raise ValueError("Protocol checksum mismatch")
    validate_protocol(protocol)
    return protocol


def capture(case: Path, data_root: Path) -> dict:
    protocol = load_protocol(case)
    if (case/"snapshot.json").exists() or (case/"bars.parquet").exists():
        raise ValueError("Snapshot already exists; never overwrite")
    frozen = load_candidates(case/"frozen-candidates.json", protocol["source_candidates_sha256"])
    folder = data_root/"lake/silver/qfq_kline_daily"
    catalog_path = data_root/"lake/bronze/provider=baostock/stock_basic/stock_basic.parquet"
    catalog_bytes = catalog_path.read_bytes()
    catalog = pl.from_arrow(pq.read_table(io.BytesIO(catalog_bytes)))
    available = {p.stem.replace("_", ".") for p in folder.glob("*.parquet") if not p.name.startswith("._")}
    selected = select_symbols(catalog.to_dicts(), available, protocol["selection"])
    initial_selection = json.loads((case/"selected-universe.json").read_bytes())
    if (selected != initial_selection["selected"]
            or sha256(catalog_bytes).hexdigest() != initial_selection["catalog_sha256"]):
        raise ValueError("Selection changed since preregistration")
    frames, files, quality = [], [], []
    for row in selected:
        symbol = row["symbol"]
        path = folder/(symbol.replace(".", "_")+".parquet")
        if path.is_symlink() or not path.resolve().is_relative_to(data_root):
            raise ValueError("Unsafe input path")
        payload = path.read_bytes()
        original = pl.from_arrow(pq.read_table(io.BytesIO(payload)))
        original = original.filter(pl.col("date").is_between(date.fromisoformat(protocol["data_start"]), date.fromisoformat(protocol["data_end"])))
        bars = normalize_research_frame(original, symbol)
        quality.append({"symbol": symbol, "rows": bars.height,
            "first": bars["datetime"].min(), "last": bars["datetime"].max(),
            "null_volume": bars["volume"].null_count(), "null_turnover": bars["turnover"].null_count(),
            "zero_volume": int((bars["volume"] == 0).sum())})
        frames.append(bars)
        files.append({"symbol": symbol, "path": str(path), "sha256": sha256(payload).hexdigest(), "bytes": len(payload)})
    bars = pl.concat(frames).sort("symbol", "datetime")
    bars.write_parquet(case/"bars.parquet")
    body = {"created_at": datetime.now(timezone.utc).isoformat(), "protocol_checksum": digest(protocol),
        "bars_sha256": sha256((case/"bars.parquet").read_bytes()).hexdigest(), "rows": bars.height,
        "selected": selected, "source_files": files, "quality": quality,
        "catalog_sha256": sha256(catalog_bytes).hexdigest(), "candidate_count": len(frozen)}
    save_new(case/"snapshot.json", {**body, "checksum": digest(body)})
    return {"status": "captured", "rows": bars.height, "symbols": len(selected),
        "null_quantity_rows": sum(r["null_volume"] for r in quality)}


def evaluate(case: Path, *, write: bool) -> dict:
    protocol = load_protocol(case)
    snapshot = checked(case/"snapshot.json")
    if snapshot["protocol_checksum"] != digest(protocol):
        raise ValueError("Snapshot is bound to another protocol")
    payload = (case/"bars.parquet").read_bytes()
    if sha256(payload).hexdigest() != snapshot["bars_sha256"]:
        raise ValueError("Frozen bars changed")
    bars = pl.from_arrow(pq.read_table(io.BytesIO(payload)))
    if set(bars["symbol"].unique()) != {r["symbol"] for r in snapshot["selected"]}:
        raise ValueError("Snapshot universe differs")
    candidates = load_candidates(case/"frozen-candidates.json", protocol["source_candidates_sha256"])
    rows, year_results, board_results, prefix_checks, file_hashes = [], [], [], [], []
    stats = protocol["statistics"]
    mapping = {r["symbol"]: r["board"] for r in snapshot["selected"]}
    mask = bars.select("symbol", "datetime", ((pl.col("volume") > 0) & pl.col("volume").is_finite()
                      & pl.col("turnover").is_finite()).fill_null(False).alias("eligible"))
    registry = default_registry()
    factor = registry.get("DSL.RESTRICTED", "1.0.0")
    for index, frozen in enumerate(candidates, 1):
        candidate = frozen["candidate"]
        name = candidate["name"]
        params = {"ast": candidate["ast"]}
        values = compute_factor(factor, bars, params)
        cutoffs = [bars["available_at"].unique().sort()[n] for n in
                   (bars["available_at"].n_unique()//3, 2*bars["available_at"].n_unique()//3)]
        assert_prefix_invariant(factor, bars, params, cutoffs)
        prefix_checks.append({"candidate": name, "passed": True, "cutoffs": [d.isoformat() for d in cutoffs]})
        _, observations = FactorResearchEngine().evaluate(bars, values, mask, tuple(protocol["horizons"]), 5)
        folder = case/f"candidate-{index:02d}"
        if write:
            folder.mkdir(exist_ok=False)
            values.write_parquet(folder/"values.parquet")
            observations.write_parquet(folder/"observations.parquet")
            save_new(folder/"candidate.json", candidate)
        else:
            from polars.testing import assert_frame_equal
            assert_frame_equal(values, pl.read_parquet(folder/"values.parquet"), check_exact=True)
            assert_frame_equal(observations, pl.read_parquet(folder/"observations.parquet"), check_exact=True)
        for kind, frame in (("values", values), ("observations", observations)):
            file_hashes.append({"candidate": name, "kind": kind, "rows": frame.height,
                "sha256": sha256((folder/(kind+".parquet")).read_bytes()).hexdigest()})
        for period in protocol["periods"]:
            for horizon in protocol["horizons"]:
                identity = {"candidate": name, "period": period["name"], "horizon": horizon}
                daily, inventory = period_daily(observations, bars, horizon, period["start"], period["end"], stats["min_cross_section"])
                evidence = infer_daily(daily, stats, identity)
                rows.append({**identity, "expected_sign": candidate["expected_rank_ic_sign"], **inventory, **evidence})
                relative = folder/(period["name"]+f"-h{horizon}-daily.parquet")
                if write:
                    daily.write_parquet(relative)
                else:
                    from polars.testing import assert_frame_equal
                    assert_frame_equal(daily, pl.read_parquet(relative), check_exact=True)
                for year in sorted(set(daily["datetime"].dt.year().to_list())):
                    sub = daily.filter(pl.col("datetime").dt.year() == year)
                    year_results.append({**identity, "year": year, **descriptive(sub), "inference": "descriptive_only"})
                for board in protocol["selection"]["boards"]:
                    symbols = [s for s, b in mapping.items() if b == board]
                    daily_board, _ = period_daily(observations.filter(pl.col("symbol").is_in(symbols)),
                        bars.filter(pl.col("symbol").is_in(symbols)), horizon, period["start"], period["end"], stats["min_board_cross_section"])
                    board_results.append({**identity, "board": board, **descriptive(daily_board), "inference": "descriptive_only"})
                print("EVALUATED", name, period["name"], horizon, "IC_DATES", evidence["ic_dates"], flush=True)
    result = finalize_family(rows, protocol)
    result.update(year_results=year_results, board_results=board_results, prefix_checks=prefix_checks,
        snapshot_checksum=digest(snapshot), source_candidates_sha256=protocol["source_candidates_sha256"],
        observation_files=file_hashes, input_rows=bars.height, symbols=len(mapping),
        source_files_unchanged=all(sha256(Path(r["path"]).read_bytes()).hexdigest() == r["sha256"] for r in snapshot["source_files"]))
    if write:
        save_new(case/"result.json", result)
        save_new(case/"runtime.json", {"runtime": runtime_fingerprint(), "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest()})
    else:
        old = json.loads((case/"result.json").read_bytes())
        if result != old:
            raise ValueError("Numerical/statistical recomputation differs")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("capture", "run", "verify"))
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args(argv)
    case = args.case_dir.resolve()
    if not case.is_dir() or case.is_symlink():
        parser.error("An existing isolated case directory is required")
    try:
        if args.phase == "capture":
            if args.data_root is None: parser.error("capture needs --data-root")
            result = capture(case, args.data_root.resolve())
        elif args.phase == "run":
            # Exclusive start marker: no silent overwrite/retry after a partial run.
            save_new(case/"run-start.json", {"started_at": datetime.now(timezone.utc).isoformat(), "runtime": runtime_fingerprint()})
            result = evaluate(case, write=True)
        else:
            result = evaluate(case, write=False)
            save_verification(case/"verification.json", {"status": "numerically_matched", "verified_at": datetime.now(timezone.utc).isoformat(),
                "result_checksum": digest(result), "runtime": runtime_fingerprint(), "source_files_unchanged": result["source_files_unchanged"],
                "formal_registration": False, "model_called": False, "gui_loaded": any(n.startswith("PyQt") for n in sys.modules)})
        print(encode({"ok": True, "phase": args.phase, "summary": {k: result.get(k) for k in
            ("status", "rows", "symbols", "input_rows", "family_size", "conclusions", "source_files_unchanged")}}))
        return 0
    except Exception as error:
        import traceback
        traceback.print_exc()
        print(encode({"ok": False, "phase": args.phase, "error": str(error)[:500]}))
        return 2

if __name__ == "__main__": raise SystemExit(main())

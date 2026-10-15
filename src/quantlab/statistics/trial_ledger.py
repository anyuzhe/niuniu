"""Append-only ledger of every configuration tried in a research family, and the selection-bias numbers it supports.

Why: ``multiple_testing.deflated_sharpe_ratio`` needs N, the number of strategies that were tried before one
was picked, and ``probability_of_backtest_overfitting`` needs the return series of ALL of them. Neither can be
reconstructed afterwards from memory. The ledger records them at run time.

Design
- One directory per ledger: ``ledger.jsonl`` (one JSON entry per line, each carrying the SHA-256 of the previous
  line, so deleting or editing an earlier entry is detectable) and ``returns/<config_id>.json`` (the daily return
  series of that trial, hashed in the entry).
- A trial is identified by ``config_id`` = digest of (family, config). Recording the same config again with the
  same returns is a no-op (it must never inflate N); with different returns it is an error.
- ``summarize`` reports N, the best trial, DSR for several N assumptions, an effective-N estimate from the
  average pairwise correlation, and PBO when the series are aligned.

Limits (also returned by ``summarize``): the ledger only knows what was recorded. Trials never recorded (other
people, earlier sessions, ideas dropped before a backtest) make N too small and the deflated numbers too
optimistic. Hash chaining detects accidental/after-the-fact edits; it is not trusted timestamping.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from quantlab.statistics.multiple_testing import (deflated_sharpe_ratio, probability_of_backtest_overfitting,
                                                   sharpe_moments)

SCHEMA = "niuniu-trial-ledger-v1"
GENESIS = "0" * 64
LIMITS = ("The ledger counts only trials that were recorded; unrecorded trials make N too small and DSR too "
          "optimistic. Hash chaining detects later edits, it is not trusted timestamping. Effective N from "
          "correlation is an approximation. PBO is noisy on one dataset (see multiple_testing).")
_FAMILY = re.compile(r"[A-Za-z0-9._-]{1,80}")


def _canon(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def config_id(family: str, config) -> str:
    return _sha(_canon({"family": family, "config": config}))[:32]


def _paths(root):
    root = Path(root)
    return root / "ledger.jsonl", root / "returns"


def _read_lines(root) -> list[str]:
    ledger, _ = _paths(root)
    if not ledger.exists():
        return []
    return [line for line in ledger.read_text(encoding="utf-8").split("\n") if line]


def verify_ledger(root) -> dict:
    """Walk the chain; report broken links, edited entries and missing/changed return files."""
    problems, prev, seen = [], GENESIS, set()
    entries = []
    for number, line in enumerate(_read_lines(root), 1):
        try:
            entry = json.loads(line)
        except ValueError:
            problems.append(f"line {number}: not JSON")
            break
        if entry.get("prev") != prev:
            problems.append(f"line {number}: chain broken (entry removed or reordered)")
        body = {k: v for k, v in entry.items() if k != "entry_hash"}
        if entry.get("entry_hash") != _sha(_canon(body)):
            problems.append(f"line {number}: entry edited")
        key = (entry.get("family"), entry.get("config_id"))
        if key in seen:
            problems.append(f"line {number}: duplicate config recorded twice")
        seen.add(key)
        if entry.get("returns_sha256"):
            path = _paths(root)[1] / f"{entry['config_id']}.json"
            if not path.exists():
                problems.append(f"line {number}: returns file missing")
            elif _sha(path.read_text(encoding="utf-8")) != entry["returns_sha256"]:
                problems.append(f"line {number}: returns file changed")
        prev = entry.get("entry_hash", "")
        entries.append(entry)
    return {"ok": not problems, "problems": problems, "entries": len(entries)}


def record_trial(root, family: str, config, returns=None, *, dates=None, note: str = "", metrics=None) -> dict:
    """Append one trial. ``returns`` (per-period, e.g. daily) is needed for DSR/PBO; ``dates`` aligns series."""
    if not _FAMILY.fullmatch(family or ""):
        raise ValueError("family must be 1-80 chars of letters, digits, . _ -")
    cid = config_id(family, config)
    series = None
    if returns is not None:
        series = [float(v) for v in returns]
        if len(series) < 3 or not all(math.isfinite(v) for v in series):
            raise ValueError("returns must be finite with at least 3 observations")
        if dates is not None:
            dates = [str(d) for d in dates]
            if len(dates) != len(series):
                raise ValueError("dates and returns differ in length")
    root = Path(root)
    ledger, returns_dir = _paths(root)
    returns_dir.mkdir(parents=True, exist_ok=True)
    payload = None if series is None else _canon({"dates": dates, "returns": series})
    with (root / "ledger.lock").open("a+b") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        try:
            lines = _read_lines(root)
            for line in lines:
                old = json.loads(line)
                if old["family"] == family and old["config_id"] == cid:
                    if payload is not None and old.get("returns_sha256") != _sha(payload):
                        raise ValueError("this configuration is already recorded with different returns")
                    return {"status": "unchanged", "config_id": cid, "n_in_family": _count(lines, family)}
            prev = json.loads(lines[-1])["entry_hash"] if lines else GENESIS
            entry = {"schema": SCHEMA, "family": family, "config_id": cid, "config": config, "note": note,
                     "recorded_at": datetime.now(timezone.utc).isoformat(), "metrics": metrics or {},
                     "returns_sha256": None if payload is None else _sha(payload),
                     "n_obs": None if series is None else len(series), "prev": prev}
            if series is not None:
                entry["sharpe_per_period"] = sharpe_moments(series)["sharpe"] if len(set(series)) > 1 else None
                target = returns_dir / f"{cid}.json"
                tmp = target.with_suffix(".tmp")
                with tmp.open("w", encoding="utf-8") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp, target)
            entry["entry_hash"] = _sha(_canon(entry))
            with ledger.open("a", encoding="utf-8") as stream:
                stream.write(_canon(entry) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return {"status": "recorded", "config_id": cid, "n_in_family": _count(lines, family) + 1}
        finally:
            fcntl.flock(guard, fcntl.LOCK_UN)


def _count(lines, family) -> int:
    return sum(json.loads(line)["family"] == family for line in lines)


def load_family(root, family: str) -> list[dict]:
    out = []
    for line in _read_lines(root):
        entry = json.loads(line)
        if entry["family"] != family:
            continue
        path = _paths(root)[1] / f"{entry['config_id']}.json"
        entry["series"] = json.loads(path.read_text(encoding="utf-8")) if entry.get("returns_sha256") and path.exists() else None
        out.append(entry)
    return out


def effective_trials(returns_matrix) -> dict:
    """Rough effective number of independent trials, N_eff = rho + (1 - rho) * N (rho = mean pairwise correlation)."""
    x = np.asarray(returns_matrix, dtype=float)
    n = x.shape[1]
    if n < 2:
        return {"n": n, "mean_correlation": None, "n_effective": float(n)}
    corr = np.corrcoef(x, rowvar=False)
    rho = float(np.nanmean(corr[np.triu_indices(n, 1)]))
    rho = min(max(rho, 0.0), 1.0)
    return {"n": n, "mean_correlation": rho, "n_effective": rho + (1.0 - rho) * n}


def summarize(root, family: str, *, assumed_trials=None, pbo_splits: int = 16) -> dict:
    """N, best trial and selection-bias numbers for a family. ``assumed_trials`` adds the N you believe in."""
    chain = verify_ledger(root)
    entries = load_family(root, family)
    if not entries:
        raise ValueError(f"no trials recorded for family {family!r}")
    with_series = [e for e in entries if e["series"] is not None]
    result = {"schema": SCHEMA, "family": family, "chain_ok": chain["ok"], "chain_problems": chain["problems"],
              "n_recorded": len(entries), "n_with_returns": len(with_series), "limits": LIMITS}
    if not with_series:
        result["note"] = "no return series recorded; only the trial count is available"
        return result
    sharpes = [sharpe_moments(e["series"]["returns"])["sharpe"] for e in with_series]
    best_index = int(np.argmax(sharpes))
    best = with_series[best_index]
    result["best"] = {"config_id": best["config_id"], "config": best["config"], "sharpe_per_period": sharpes[best_index],
                      "sharpe_annualised": sharpes[best_index] * math.sqrt(252), "n_obs": best["n_obs"]}
    returns = best["series"]["returns"]
    candidates = {"recorded": len(entries)}
    if assumed_trials:
        candidates["assumed"] = int(assumed_trials)
    aligned = _align(with_series)
    if aligned is not None:
        neff = effective_trials(aligned)
        result["effective_trials"] = neff
        candidates["effective"] = max(2, int(round(neff["n_effective"])))
        std = float(np.std(sharpes, ddof=1)) if len(sharpes) > 1 else None
        result["observed_sharpe_dispersion"] = std
    else:
        std = float(np.std(sharpes, ddof=1)) if len(sharpes) > 1 else None
        result["observed_sharpe_dispersion"] = std
        result["alignment"] = "series have different dates or lengths; PBO and effective N skipped"
    result["dsr"] = {name: deflated_sharpe_ratio(returns, n, sharpe_std=std if std and std > 0 else None)
                     for name, n in candidates.items() if n >= 2}
    if aligned is not None and aligned.shape[1] >= 2 and aligned.shape[0] >= pbo_splits * 5:  # PBO needs >= 5 periods per block
        result["pbo"] = probability_of_backtest_overfitting(aligned, n_splits=pbo_splits)
    elif aligned is not None:
        result["pbo_skipped"] = "too few aligned observations for the requested splits"
    return result


def _align(entries):
    """(periods x trials) matrix when every series has identical dates; None otherwise (no silent truncation)."""
    first = entries[0]["series"]["dates"]
    for e in entries:
        if e["series"]["dates"] is None or e["series"]["dates"] != first:
            return None
    return np.array([e["series"]["returns"] for e in entries], dtype=float).T

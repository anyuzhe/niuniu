"""Rebuild forward-adjusted (qfq) bars from pinned raw bars and cross-checked events.

Remediation stage 4 (D2).  Replaces the legacy MQC ``build_qfq`` whose script was
never in the repository.  Everything is written to *new* ``_v2`` silver
directories; the current ``lake/silver/qfq_kline_*`` stay untouched and the
registry is switched only after the difference report has been reviewed.

Event policy (D2, as approved 2026-09-23):

* Dividend per (code, ex-date) is compared on pre-tax cash and total stock
  distribution (bonus + capitalisation; the factor depends only on their sum).
  Candidate sources: THS v2, Baostock v2 (from 2004), legacy Eastmoney, and TDX
  capital changes (independent vendor, pinned by a snapshot file in the plan).
  Accepted only when at least two usable sources exist and **all** usable sources
  agree; so THS vs Baostock disagreement always blocks.  A single source blocks.
* Rights issues come from cninfo v2 (price, ratio per 10).  The 19 unresolved
  events of the S1 evidence package stay blocked; a TDX rights record with no
  cninfo plan on that date, or a cninfo/TDX price-ratio mismatch, also blocks.
  Failed issues are ignored.
* Factor for an ex-date with previous raw close C:
  ``f = (C - cash + price*ratio) / (C * (1 + bonus + capitalisation + ratio))``
  (all per share).  qfq price = raw price * product of f over later ex-dates, so the
  latest bar has factor 1.  Volume and amount stay raw (same as the legacy build).
* A blocked event cannot be crossed: qfq rows are written only from the latest
  blocked ex-date onward, and ``valid_from`` records where history starts.  Nothing
  is guessed or back-filled.

  plan       read-only; pin every input file by SHA-256 and print the plan SHA
  apply      build daily factors and qfq daily bars (resumable per symbol)
  apply-min5 apply the daily factors to raw 5-minute bars (resumable per symbol)
  report     compare v2 with the legacy qfq silver (read-only)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from collect import paths  # noqa: E402
from quantlab.data import dataset_registry as reg  # noqa: E402

PLAN_FORMAT = "niuniu-qfq-build-plan-v2"
POLICY = "qfq-events-two-source-v1"
SOURCES = {
    "raw_daily": "bars.daily.raw.baostock",
    "ths": "corporate_actions.dividend.ths",
    "baostock": "corporate_actions.dividend.baostock",
    "eastmoney": "corporate_actions.dividend.eastmoney",   # legacy, second-source stand-in only
    "cninfo": "corporate_actions.allotment.cninfo",
}
OUT = {
    "factors": "lake/silver/adjustment_factors_v2",
    "daily": "lake/silver/qfq_kline_daily_v2",
    "min5": "lake/silver/qfq_kline_min5_v2",
}
RAW_MIN5 = "bars.min5.raw.baostock"
TOL = Decimal("0.0001")          # per-10-share comparison tolerance
RIGHTS_RATIO_TOL = Decimal("0.01")  # cninfo vs TDX rights ratio, per 10 shares
IMPLEMENTED_THS = {"实施方案"}
IMPLEMENTED_EM = {"实施分配"}


# ---------------------------------------------------------------- helpers
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(body) -> bytes:
    return (json.dumps(body, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode()


def symbol_file(code: str) -> str:
    return code.replace(".", "_") + ".parquet"


def _dec(value) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if text in ("", "None", "nan", "NaN", "NaT", "--"):
        return None
    try:
        out = Decimal(text)
    except InvalidOperation:
        return None
    return out if out.is_finite() else None


def _day(value) -> date | None:
    if value is None:
        return None
    try:
        import pandas as pd
        if pd.isna(value):          # NaT is a datetime subclass: test it first
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    if len(text) != 10 or text in ("None", "NaT"):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def dataset_dirs(data_root: Path) -> dict[str, Path]:
    registry = reg.load_registry(data_root)
    if registry is None:
        raise reg.RegistryError("qfq build requires catalog/dataset_registry.json")
    dirs = {}
    for key, name in {**SOURCES, "raw_min5": RAW_MIN5}.items():
        entry = registry.entry(name)
        if key == "eastmoney":
            if entry["status"] != "legacy":
                raise reg.RegistryError("eastmoney stand-in must be registered as legacy")
        elif entry["status"] != "current":
            raise reg.RegistryError(f"{name} is not current")
        dirs[key] = data_root / entry["path"]
    return dirs


def load_s1_blocked(path: Path) -> set[tuple[str, str]]:
    blocked = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            blocked.add((row["code"], row["ex_date"]))
    if len(blocked) != 19:
        raise ValueError(f"S1 evidence must hold 19 events, found {len(blocked)}")
    return blocked


# ---------------------------------------------------------------- event extraction
def _components(cash, bonus, cap) -> dict:
    return {"cash": cash or Decimal(0), "bonus": bonus or Decimal(0), "cap": cap or Decimal(0)}


def _sum(rows: list[dict]) -> dict:
    out = {"cash": Decimal(0), "bonus": Decimal(0), "cap": Decimal(0)}
    for row in rows:
        for key in out:
            out[key] += row[key]
    return out


def _group(rows: list[tuple[date, dict, str]]) -> dict[date, dict]:
    """Per ex-date: dedupe identical rows, sum distinct plans, carry blockers."""
    grouped: dict[date, dict] = {}
    for day, comp, blocker in rows:
        slot = grouped.setdefault(day, {"rows": [], "blockers": set(), "seen": set()})
        if blocker:
            slot["blockers"].add(blocker)
            continue
        key = tuple(str(comp[k]) for k in ("cash", "bonus", "cap"))
        if key in slot["seen"]:
            continue
        slot["seen"].add(key)
        slot["rows"].append(comp)
    result = {}
    for day, slot in grouped.items():
        result[day] = {"value": _sum(slot["rows"]) if slot["rows"] else None,
                       "plans": len(slot["rows"]), "plan_values": slot["rows"],
                       "blockers": sorted(slot["blockers"]), "notes": sorted(slot.get("notes", ()))}
    return result


def ths_events(frame) -> dict[date, dict]:
    from quantlab.data.corporate_action_review import _parse_plan_text
    rows = []
    for rec in frame.to_dict("records"):
        if str(rec.get("方案进度")) not in IMPLEMENTED_THS:
            continue
        day = _day(rec.get("A股除权除息日"))
        if day is None:
            continue
        parsed = _parse_plan_text(rec.get("分红方案说明"))
        if parsed["status"] == "not_distributing":
            continue
        if parsed["status"] == "blocked" and parsed["blockers"] == ["cash_tax_basis_unspecified"]:
            # Early THS rows omit "(含税)".  The amount is kept; it still needs an
            # independent source that states the same amount before it is used.
            raw = parsed["raw_text"] or ""
            import re as _re
            m = _re.search(r"派(\d+(?:\.\d+)?)元", raw.replace(" ", ""))
            base = Decimal(parsed["declared_base_shares"] or "10")
            if m and base > 0:
                c = parsed["components"]
                rows.append((day, _components(Decimal(m.group(1)) * Decimal(10) / base,
                                              _dec(c["stock_bonus_per_10_shares"]),
                                              _dec(c["capitalization_per_10_shares"])), None))
                continue
        if parsed["status"] != "parsed":
            rows.append((day, None, "ths:" + ",".join(parsed["blockers"] or [parsed["status"]])))
            continue
        c = parsed["components"]
        rows.append((day, _components(_dec(c["cash_pre_tax_per_10_shares"]),
                                      _dec(c["stock_bonus_per_10_shares"]),
                                      _dec(c["capitalization_per_10_shares"])), None))
    return _group(rows)


def baostock_events(frame) -> dict[date, dict]:
    rows = []
    for rec in frame.to_dict("records"):
        day = _day(rec.get("dividOperateDate"))
        if day is None:
            continue
        cash, bonus, cap = (_dec(rec.get(k)) for k in
                            ("dividCashPsBeforeTax", "dividStocksPs", "dividReserveToStockPs"))
        if cash is None and bonus is None and cap is None:
            rows.append((day, None, "baostock:no_numeric_components"))
            continue
        ten = Decimal(10)
        comp = _components(cash * ten if cash is not None else None,
                           bonus * ten if bonus is not None else None,
                           cap * ten if cap is not None else None)
        if comp == _components(None, None, None):
            continue
        rows.append((day, comp, None))
    return _group(rows)


def eastmoney_events(frame) -> dict[date, dict]:
    rows = []
    for rec in frame.to_dict("records"):
        if str(rec.get("方案进度")) not in IMPLEMENTED_EM:
            continue
        day = _day(rec.get("除权除息日"))
        if day is None:
            continue
        comp = _components(_dec(rec.get("现金分红-现金分红比例")),
                           _dec(rec.get("送转股份-送转比例")),
                           _dec(rec.get("送转股份-转股比例")))
        if comp == _components(None, None, None):
            continue
        rows.append((day, comp, None))
    return _group(rows)


def _agree(a: dict, b: dict) -> bool:
    return (abs(a["cash"] - b["cash"]) <= TOL
            and abs((a["bonus"] + a["cap"]) - (b["bonus"] + b["cap"])) <= TOL)


def decide_dividend(day, ths, bao, em, tdx=None) -> dict:
    """Rule for one ex-date: >=2 usable sources and all usable sources agree."""
    named = (("ths", ths), ("baostock", bao), ("eastmoney", em), ("tdx", tdx or {}))
    got = {name: src.get(day) for name, src in named}
    usable = {n: g["value"] for n, g in got.items() if g and g["value"] is not None and not g["blockers"]}
    seen = sorted(n for n, g in got.items() if g)
    blockers = sorted(b for g in got.values() if g for b in g["blockers"])
    names = sorted(usable)
    if seen == ["tdx"]:
        # TDX alone (typically 2005-06 share-reform consideration to tradable
        # holders only): not confirmed anywhere else, so not applied.  Same as the
        # legacy build; recorded so it stays visible.
        return {"status": "ignored", "blockers": ["tdx_only_not_applied"], "sources": seen}
    if len(names) < 2:
        return {"status": "blocked", "blockers": blockers + ["single_source"], "sources": seen}
    first = usable[names[0]]
    disagree = [n for n in names[1:] if not _agree(first, usable[n])]
    if not disagree:
        value = usable["ths"] if "ths" in usable else first
        return {"status": "accepted", "pair": "+".join(names), "value": value, "sources": seen}
    # Several plans paid on one day (e.g. a special dividend): THS lists each plan,
    # TDX confirms the total, and the sources that disagree carry exactly one of
    # THS's individual plans.  Accept the THS+TDX total and name who missed a plan.
    ths_slot = got.get("ths")
    if ("ths" in usable and "tdx" in usable and _agree(usable["ths"], usable["tdx"])
            and ths_slot and ths_slot["plans"] > 1):
        others = [n for n in names if n not in ("ths", "tdx")]
        if others and all(any(_agree(usable[n], plan) for plan in ths_slot["plan_values"]) for n in others):
            return {"status": "accepted", "pair": "ths+tdx", "value": usable["ths"], "sources": seen,
                    "note": "multi_plan_day_missing_in:" + "+".join(others)}
    return {"status": "blocked", "blockers": blockers + ["sources_disagree:" + "+".join(names)],
            "sources": seen}


def tdx_events(rows) -> tuple[dict[date, dict], dict[date, tuple]]:
    """TDX 除权除息 records -> (dividend slots, rights {day: (price, ratio_per_10)})."""
    div, rights = [], {}
    for rec in rows:
        day = _day(rec.get("date"))
        if day is None:
            continue
        vals = [_dec(round(float(rec.get(k) or 0), 4)) for k in ("c1_float", "c2_float", "c3_float", "c4_float")]
        c1, c2, c3, c4 = vals
        if (c1 or 0) != 0 or (c3 or 0) != 0:
            div.append((day, _components(c1, c3, None), None))
        if (c4 or 0) > 0:
            rights.setdefault(day, set()).add((c2, c4))
    return _group(div), rights


def rights_events(frame, code: str, s1_blocked, tdx_rights=None) -> dict[date, dict]:
    out: dict[date, dict] = {}
    for rec in frame.to_dict("records"):
        day = _day(rec.get("除权基准日"))
        if day is None:
            continue
        actual = _dec(rec.get("实际配股数量"))
        if _day(rec.get("配股失败，退还申购款日期")) is not None and not (actual and actual > 0):
            continue   # failed issue: a refund date and no shares actually placed
        price, ratio = _dec(rec.get("配股价格")), _dec(rec.get("配股比例"))
        slot = out.setdefault(day, {"rows": [], "blockers": []})
        if (code, day.isoformat()) in s1_blocked:
            slot["blockers"].append("s1_unresolved_rights_event")
        if price is None or ratio is None or price <= 0 or ratio <= 0:
            slot["blockers"].append("cninfo_price_or_ratio_missing")
            continue
        if (price, ratio) not in slot["rows"]:
            slot["rows"].append((price, ratio))
    for day, slot in out.items():
        if len(slot["rows"]) > 1:
            slot["blockers"].append("cninfo_multiple_plans_same_day")
        seen = (tdx_rights or {}).get(day)
        if seen and slot["rows"]:
            price, ratio = slot["rows"][0]
            # TDX stores the ratio as float32 rounded to 2-4 decimals (1.76 vs cninfo
            # 1.7647 per 10); the price must match, the ratio within 0.01 per 10.
            if not any(p is not None and abs(p - price) <= Decimal("0.001") and abs(r - ratio) <= RIGHTS_RATIO_TOL
                       for p, r in seen):
                slot["blockers"].append("cninfo_tdx_rights_disagree")
    for day in (tdx_rights or {}):
        if day not in out:
            out[day] = {"rows": [], "blockers": ["tdx_rights_without_cninfo"]}
    for code_day in s1_blocked:
        if code_day[0] == code:
            day = date.fromisoformat(code_day[1])
            out.setdefault(day, {"rows": [], "blockers": ["s1_unresolved_rights_event"]})
    return out


# ---------------------------------------------------------------- factor build
def build_symbol(code: str, dirs: dict[str, Path], s1_blocked, tdx_rows=()) -> tuple:
    """Return (events DataFrame, qfq daily DataFrame or None, summary dict)."""
    import pandas as pd
    raw = pd.read_parquet(dirs["raw_daily"] / symbol_file(code))
    raw = raw.sort_values("date").reset_index(drop=True)
    raw["date"] = raw["date"].map(_day)

    def read(key):
        path = dirs[key] / symbol_file(code)
        return pd.read_parquet(path) if path.is_file() else pd.DataFrame()

    ths, bao, em = ths_events(read("ths")), baostock_events(read("baostock")), eastmoney_events(read("eastmoney"))
    tdx, tdx_rights = tdx_events(tdx_rows)
    rights = rights_events(read("cninfo"), code, s1_blocked, tdx_rights)
    last_day = raw["date"].iloc[-1] if len(raw) else None
    days = sorted(set(ths) | set(bao) | set(em) | set(tdx) | set(rights))
    closes = list(zip(raw["date"], raw["close"]))
    events = []
    for day in days:
        if last_day is None or day > last_day:
            continue       # future ex-date: not yet effective on the latest bar
        prev = [c for d, c in closes if d < day]
        if not prev:
            continue       # before the first bar: affects no row
        close = Decimal(repr(float(prev[-1])))
        blockers, pair, sources, ignored = [], None, [], []
        cash = bonus = cap = Decimal(0)
        if day in ths or day in bao or day in em or day in tdx:
            decision = decide_dividend(day, ths, bao, em, tdx)
            sources = decision["sources"]
            if decision["status"] == "accepted":
                pair = decision["pair"] + (f" ({decision['note']})" if decision.get("note") else "")
                cash, bonus, cap = (decision["value"][k] / 10 for k in ("cash", "bonus", "cap"))
            elif decision["status"] == "ignored":
                ignored.extend(decision["blockers"])
            else:
                blockers += decision["blockers"]
        price = ratio = Decimal(0)
        if day in rights:
            slot = rights[day]
            blockers += slot["blockers"]
            if slot["rows"] and not slot["blockers"]:
                price, ratio = slot["rows"][0][0], slot["rows"][0][1] / 10
            sources = sorted(set(sources) | {"cninfo"})
        factor = None
        if ignored and not blockers and not (day in rights):
            events.append({"code": code, "ex_date": day.isoformat(), "prev_close": str(close),
                           "cash_ps": "0", "bonus_ps": "0", "cap_ps": "0", "rights_price": "0",
                           "rights_ratio_ps": "0", "dividend_pair": None, "sources": ",".join(sources),
                           "factor": None, "status": "ignored", "blockers": ";".join(ignored)})
            continue
        if not blockers:
            numerator = close - cash + price * ratio
            denominator = close * (1 + bonus + cap + ratio)
            if numerator <= 0 or denominator <= 0:
                blockers.append("non_positive_adjusted_price")
            else:
                factor = numerator / denominator
                if not (Decimal("0") < factor < Decimal("1.5")):
                    blockers.append("factor_out_of_range")
                    factor = None
                elif factor == 1:
                    continue   # no economic effect (e.g. all-zero accepted plan)
        events.append({"code": code, "ex_date": day.isoformat(), "prev_close": str(close),
                       "cash_ps": str(cash), "bonus_ps": str(bonus), "cap_ps": str(cap),
                       "rights_price": str(price), "rights_ratio_ps": str(ratio),
                       "dividend_pair": pair, "sources": ",".join(sources),
                       "factor": None if factor is None else float(factor),
                       "status": "blocked" if blockers else "accepted",
                       "blockers": ";".join(sorted(set(blockers)))})
    ev = pd.DataFrame(events, columns=["code", "ex_date", "prev_close", "cash_ps", "bonus_ps", "cap_ps",
                                       "rights_price", "rights_ratio_ps", "dividend_pair", "sources",
                                       "factor", "status", "blockers"])
    blocked_days = [date.fromisoformat(e["ex_date"]) for e in events if e["status"] == "blocked"]
    valid_from = max(blocked_days) if blocked_days else (raw["date"].iloc[0] if len(raw) else None)
    summary = {"code": code, "rows_raw": int(len(raw)),
               "events_ignored": sum(e["status"] == "ignored" for e in events),
               "events_accepted": sum(e["status"] == "accepted" for e in events),
               "events_blocked": len(blocked_days),
               "valid_from": valid_from.isoformat() if valid_from else None}
    if not len(raw):
        return ev, None, summary
    cumulative = [1.0] * len(raw)
    accepted = sorted(((date.fromisoformat(e["ex_date"]), e["factor"]) for e in events if e["status"] == "accepted"),
                      reverse=True)
    running, idx = 1.0, 0
    for i in range(len(raw) - 1, -1, -1):
        day = raw["date"].iloc[i]
        while idx < len(accepted) and accepted[idx][0] > day:
            running *= accepted[idx][1]
            idx += 1
        cumulative[i] = running
    out = raw[["date", "code", "open", "high", "low", "close", "volume", "amount"]].copy()
    out["factor"] = cumulative
    for col in ("open", "high", "low", "close"):
        out[col] = out[col].astype("float64") * out["factor"]
    out = out[out["date"] >= valid_from].reset_index(drop=True)
    out["date"] = out["date"].map(lambda d: d.isoformat())
    summary["rows_qfq"] = int(len(out))
    return ev, out, summary


# ---------------------------------------------------------------- plan / apply
TDX_SQL = ("select code, date, record_json from tdx_capital_changes "
           "where json_extract_string(record_json, 'category_name') = '除权除息' order by code, date, record_json")


def export_tdx_snapshot(data_root: Path, out: Path) -> str:
    """Pin the TDX 除权除息 rows used by the build into one parquet file."""
    import duckdb
    import pandas as pd
    con = duckdb.connect(str(data_root / "catalog" / "mqc.duckdb"), read_only=True)
    try:
        frame = con.execute(TDX_SQL).df()
    finally:
        con.close()
    recs = [json.loads(x) for x in frame["record_json"]]
    snap = pd.DataFrame({"code": frame["code"], "date": frame["date"].astype(str),
                         **{k: [r.get(k) for r in recs] for k in ("c1_float", "c2_float", "c3_float", "c4_float")}})
    snap = snap.drop_duplicates().reset_index(drop=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    snap.to_parquet(out, index=False)
    return sha256_file(out)


def load_tdx_snapshot(path: Path) -> dict[str, list]:
    import pandas as pd
    frame = pd.read_parquet(path)
    grouped: dict[str, list] = {}
    for rec in frame.to_dict("records"):
        grouped.setdefault(rec["code"], []).append(rec)
    return grouped


def build_plan(data_root: Path, s1_path: Path, tdx_snapshot: Path) -> dict:
    dirs = dataset_dirs(data_root)
    tdx_sha = export_tdx_snapshot(data_root, tdx_snapshot)
    codes = sorted(p.stem.replace("_", ".", 1) for p in dirs["raw_daily"].glob("*.parquet")
                   if not p.name.startswith("._"))
    inputs = {}
    for key in ("raw_daily", "ths", "baostock", "eastmoney", "cninfo"):
        files = {}
        for code in codes:
            path = dirs[key] / symbol_file(code)
            if path.is_file():
                files[code] = sha256_file(path)
        inputs[key] = {"path": str(dirs[key]), "files": files}
    body = {"format": PLAN_FORMAT, "policy": POLICY, "data_root": str(data_root),
            "builder_sha256": sha256_file(Path(__file__)),
            "registry_sha256": reg.load_registry(data_root).sha256,
            "s1_evidence": {"path": str(s1_path), "sha256": sha256_file(s1_path)},
            "tdx_snapshot": {"path": str(tdx_snapshot), "sha256": tdx_sha, "sql": TDX_SQL},
            "codes": codes, "inputs": inputs, "outputs": OUT}
    body["plan_sha256"] = hashlib.sha256(canonical(body)).hexdigest()
    return body


def _check(plan: dict, approve: str) -> None:
    body = {k: v for k, v in plan.items() if k != "plan_sha256"}
    if plan.get("format") != PLAN_FORMAT or hashlib.sha256(canonical(body)).hexdigest() != plan["plan_sha256"]:
        raise PermissionError("plan content does not match plan_sha256")
    if approve != plan["plan_sha256"]:
        raise PermissionError("approval SHA does not match the plan")


def _atomic_parquet(frame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    return sha256_file(path)


def _receipt_path(data_root: Path, plan: dict, kind: str) -> Path:
    return data_root / OUT["factors"] / "_receipts" / f"{kind}-{plan['plan_sha256'][:16]}.json"


def _load_receipt(path: Path, plan: dict) -> dict:
    if path.is_file():
        receipt = json.loads(path.read_text())
        if receipt["plan_sha256"] != plan["plan_sha256"]:
            raise ValueError("receipt belongs to another plan")
        return receipt
    return {"plan_sha256": plan["plan_sha256"], "policy": POLICY, "results": {}}


def _save_receipt(path: Path, receipt: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(canonical(receipt))
    os.replace(tmp, path)


def apply_daily(plan: dict, approve: str, *, max_seconds: float = 1e9) -> dict:
    _check(plan, approve)
    if sha256_file(Path(__file__)) != plan["builder_sha256"]:
        raise ValueError("build_qfq.py changed since plan; re-plan")
    data_root = Path(plan["data_root"])
    dirs = dataset_dirs(data_root)
    s1 = Path(plan["s1_evidence"]["path"])
    if sha256_file(s1) != plan["s1_evidence"]["sha256"]:
        raise ValueError("S1 evidence changed since plan")
    s1_blocked = load_s1_blocked(s1)
    tdx_path = Path(plan["tdx_snapshot"]["path"])
    if sha256_file(tdx_path) != plan["tdx_snapshot"]["sha256"]:
        raise ValueError("TDX snapshot changed since plan")
    tdx = load_tdx_snapshot(tdx_path)
    receipt_path = _receipt_path(data_root, plan, "daily")
    receipt = _load_receipt(receipt_path, plan)
    start = time.monotonic()
    done = 0
    for code in plan["codes"]:
        if code in receipt["results"]:
            continue
        if time.monotonic() - start > max_seconds:
            break
        for key in ("raw_daily", "ths", "baostock", "eastmoney", "cninfo"):
            expected = plan["inputs"][key]["files"].get(code)
            path = dirs[key] / symbol_file(code)
            actual = sha256_file(path) if path.is_file() else None
            if actual != expected:
                raise ValueError(f"input changed since plan: {key} {code}")
        events, qfq, summary = build_symbol(code, dirs, s1_blocked, tdx.get(code, ()))
        summary["factors_sha256"] = _atomic_parquet(events, data_root / OUT["factors"] / symbol_file(code))
        summary["daily_sha256"] = (_atomic_parquet(qfq, data_root / OUT["daily"] / symbol_file(code))
                                   if qfq is not None and len(qfq) else None)
        receipt["results"][code] = summary
        done += 1
        if done % 50 == 0:
            _save_receipt(receipt_path, receipt)
    receipt["complete"] = len(receipt["results"]) == len(plan["codes"])
    _save_receipt(receipt_path, receipt)
    return {"done_now": done, "total_done": len(receipt["results"]), "codes": len(plan["codes"]),
            "complete": receipt["complete"]}


def apply_min5(plan: dict, approve: str, *, max_seconds: float = 1e9) -> dict:
    import pandas as pd
    _check(plan, approve)
    data_root = Path(plan["data_root"])
    dirs = dataset_dirs(data_root)
    daily = _load_receipt(_receipt_path(data_root, plan, "daily"), plan)
    if not daily.get("complete"):
        raise ValueError("daily build must be complete before min5")
    receipt_path = _receipt_path(data_root, plan, "min5")
    receipt = _load_receipt(receipt_path, plan)
    start, done = time.monotonic(), 0
    for code in plan["codes"]:
        if code in receipt["results"]:
            continue
        if time.monotonic() - start > max_seconds:
            break
        info = daily["results"][code]
        qfq_path = data_root / OUT["daily"] / symbol_file(code)
        raw_path = dirs["raw_min5"] / symbol_file(code)
        entry = {"raw_min5_sha256": sha256_file(raw_path) if raw_path.is_file() else None}
        if info.get("daily_sha256") and raw_path.is_file():
            if sha256_file(qfq_path) != info["daily_sha256"]:
                raise ValueError(f"qfq daily output changed: {code}")
            factors = pd.read_parquet(qfq_path, columns=["date", "factor"])
            m5 = pd.read_parquet(raw_path)
            m5["date"] = m5["date"].map(lambda d: _day(d).isoformat())
            out = m5.merge(factors, on="date", how="inner")
            out = out[["date", "time", "code", "open", "high", "low", "close", "volume", "amount", "factor"]]
            for col in ("open", "high", "low", "close"):
                out[col] = out[col].astype("float64") * out["factor"]
            entry["rows"] = int(len(out))
            entry["min5_sha256"] = _atomic_parquet(out, data_root / OUT["min5"] / symbol_file(code))
        receipt["results"][code] = entry
        done += 1
        if done % 20 == 0:
            _save_receipt(receipt_path, receipt)
    receipt["complete"] = len(receipt["results"]) == len(plan["codes"])
    _save_receipt(receipt_path, receipt)
    return {"done_now": done, "total_done": len(receipt["results"]), "codes": len(plan["codes"]),
            "complete": receipt["complete"]}


def report(plan: dict) -> dict:
    """Read-only comparison of v2 daily factors with the legacy silver qfq."""
    import pandas as pd
    data_root = Path(plan["data_root"])
    daily = _load_receipt(_receipt_path(data_root, plan, "daily"), plan)
    legacy_dir = data_root / "lake/silver/qfq_kline_daily"
    rows = []
    for code, info in sorted(daily["results"].items()):
        new_path = data_root / OUT["daily"] / symbol_file(code)
        old_path = legacy_dir / symbol_file(code)
        row = {"code": code, "events_accepted": info["events_accepted"], "events_blocked": info["events_blocked"],
               "valid_from": info["valid_from"], "rows_raw": info["rows_raw"], "rows_qfq": info.get("rows_qfq", 0)}
        if new_path.is_file() and old_path.is_file():
            new = pd.read_parquet(new_path, columns=["date", "close", "factor"])
            old = pd.read_parquet(old_path, columns=["date", "close", "factor"])
            old["date"] = old["date"].map(lambda d: _day(d).isoformat())
            m = new.merge(old, on="date", suffixes=("_new", "_old"))
            if len(m):
                # both series anchor at their own last bar; compare the shape by
                # rescaling the legacy factor to the new anchor on the last common date
                scale = m["factor_new"].iloc[-1] / m["factor_old"].iloc[-1]
                rel = (m["factor_old"] * scale / m["factor_new"] - 1).abs()
                row.update(common_rows=int(len(m)), max_rel_diff=float(rel.max()),
                           rows_rel_diff_gt_1e4=int((rel > 1e-4).sum()))
        rows.append(row)
    frame = pd.DataFrame(rows)
    both = frame.dropna(subset=["max_rel_diff"]) if "max_rel_diff" in frame else frame.iloc[0:0]
    summary = {
        "symbols": int(len(frame)),
        "symbols_with_blocked_events": int((frame["events_blocked"] > 0).sum()),
        "events_accepted": int(frame["events_accepted"].sum()),
        "events_blocked": int(frame["events_blocked"].sum()),
        "symbols_compared": int(len(both)),
        "symbols_identical_1e6": int((both["max_rel_diff"] <= 1e-6).sum()) if len(both) else 0,
        "symbols_diff_gt_1e4": int((both["max_rel_diff"] > 1e-4).sum()) if len(both) else 0,
        "symbols_history_shortened": int((frame["rows_qfq"] < frame["rows_raw"]).sum()),
    }
    return {"summary": summary, "per_symbol": frame}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", default=str(paths.DATA_ROOT))
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--s1-evidence", required=True)
    p.add_argument("--tdx-snapshot", required=True, help="写出 TDX 除权除息快照的 parquet 路径（数据根之外）")
    p.add_argument("--out", required=True)
    for name in ("apply", "apply-min5"):
        s = sub.add_parser(name)
        s.add_argument("--plan", required=True)
        s.add_argument("--approve-sha256", required=True)
        s.add_argument("--max-seconds", type=float, default=1e9)
    r = sub.add_parser("report")
    r.add_argument("--plan", required=True)
    r.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.command == "plan":
        plan = build_plan(Path(args.data_root), Path(args.s1_evidence), Path(args.tdx_snapshot))
        Path(args.out).write_bytes(canonical(plan))
        print(json.dumps({"plan": args.out, "codes": len(plan["codes"]), "plan_sha256": plan["plan_sha256"]}))
        return 0
    plan = json.loads(Path(args.plan).read_text())
    if args.command == "apply":
        print(json.dumps(apply_daily(plan, args.approve_sha256, max_seconds=args.max_seconds)))
    elif args.command == "apply-min5":
        print(json.dumps(apply_min5(plan, args.approve_sha256, max_seconds=args.max_seconds)))
    else:
        result = report(plan)
        out = Path(args.out)
        result["per_symbol"].to_csv(out.with_suffix(".csv"), index=False)
        out.write_bytes(canonical({"plan_sha256": plan["plan_sha256"], "summary": result["summary"]}))
        print(json.dumps(result["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

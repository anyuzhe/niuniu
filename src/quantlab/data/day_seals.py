"""Day seals: freeze what DATA observed on one calendar day, with a verifiable manifest.

A seal lists, for one date ``D``, every date-partitioned file DATA holds for that
day (public-source partitions, intraday sector records, board constituents,
intraday stock snapshots, the reference snapshot) with size, SHA-256, row count,
observation time and source.  After sealing, collectors refuse to write those
partitions again (``is_sealed_path``).  The data disk is exFAT, so files cannot be
made read-only; integrity is enforced by ``verify`` instead.

Items that normally arrive later (the announcement catalogue and exchange margin
data for ``D`` are published on ``D+1``; dated items can be back-filled) are listed
as ``pending`` and sealed by a later ``seal`` of the same day.  Same-day-only
observations that were never collected are listed as ``missing`` -- they cannot be
recovered.  Already sealed entries are never modified by a later seal.

``revoke`` moves the manifest *and* the sealed files to
``catalog/seals/_revoked/<D>-<timestamp>/`` (nothing is deleted) so the day can be
collected again and sealed as a new revision.

Layout under the data root::

    catalog/seals/YYYY-MM-DD.json            current manifest
    catalog/seals/_history/YYYY-MM-DD.rN.json every revision ever written
    catalog/seals/_verify/YYYY-MM-DD.json     latest verification result
    catalog/seals/_revoked/YYYY-MM-DD-<ts>/   revoked manifest + moved files
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
FORMAT = "niuniu-day-seal-v1"
SEALS = "catalog/seals"

# catalog dataset id -> (directory relative to the data root, layout, kind)
#   layout "partition": <dir>/<D>.parquet or <dir>/_empty/<D>.json (+ <dir>/_raw/<D>.*)
#   layout "day_dir":   <dir>/date=<D>/*.parquet      layout "day_file": <dir>/date=<D>.parquet
#   layout "snapshot":  <dir>/snapshot=<D>/*
#   kind "same_day": only observable on D (missing later = unrecoverable)
#   kind "next_day": published on D+1 (pending until then)
#   kind "dated":    can be back-filled later (pending while missing)
PUBLIC = {
    "sw_industry_history": ("lake/bronze/provider=swsresearch/industry_classification_history", "partition", "same_day", "申万"),
    "announcements_cninfo": ("lake/bronze/provider=cninfo/announcements", "partition", "next_day", "巨潮"),
    "limit_up_pool_ths": ("lake/bronze/provider=ths/limit_up_pool", "partition", "dated", "同花顺"),
    "monitor_pool_em": ("lake/bronze/provider=eastmoney/monitor_pool", "partition", "same_day", "东财"),
    "price_anomaly_em": ("lake/bronze/provider=eastmoney/price_anomaly_pool", "partition", "same_day", "东财"),
    "index_weights_csindex": ("lake/bronze/provider=csindex/index_weights", "partition", "same_day", "中证指数"),
    "margin_detail_exchange": ("lake/bronze/provider=exchange/margin_trading", "partition", "next_day", "沪深交易所"),
    "block_trades_em": ("lake/bronze/provider=eastmoney/block_trades", "partition", "dated", "东财"),
    "lockup_expiry_em": ("lake/bronze/provider=eastmoney/lockup_expiry", "partition", "dated", "东财"),
    "holder_count_em": ("lake/bronze/provider=eastmoney/holder_count_latest", "partition", "same_day", "东财"),
    "northbound_minute_ths": ("lake/bronze/provider=ths/northbound_minute", "partition", "same_day", "同花顺"),
    "earnings_forecast_em": ("lake/bronze/provider=eastmoney/earnings_forecast", "partition", "same_day", "东财"),
    "institution_survey_em": ("lake/bronze/provider=eastmoney/institution_survey", "partition", "dated", "东财"),
    "holder_trades_em": ("lake/bronze/provider=eastmoney/holder_trades", "partition", "dated", "东财"),
    "share_buyback_em": ("lake/bronze/provider=eastmoney/share_buyback", "partition", "same_day", "东财"),
    "equity_pledge_em": ("lake/bronze/provider=eastmoney/equity_pledge", "partition", "same_day", "东财"),
    "ipo_calendar_em": ("lake/bronze/provider=eastmoney/ipo_calendar", "partition", "same_day", "东财"),
    "hot_rank_ths": ("lake/bronze/provider=ths/hot_rank_day", "partition", "same_day", "同花顺"),
    "hot_rank_em": ("lake/bronze/provider=eastmoney/hot_rank", "partition", "same_day", "东财"),
}
OTHER = {
    "sector_board_intraday": ("lake/bronze/provider=fuyao/sector_board_intraday", "day_dir", "same_day", "扶摇"),
    "stock_intraday_snapshot": ("lake/bronze/provider=fuyao/stock_intraday_snapshot", "day_dir", "same_day", "扶摇"),
    "sector_board_constituents": ("lake/bronze/provider=fuyao/sector_board_constituents", "day_file", "same_day", "扶摇"),
    "reference_snapshot_baostock": ("lake/bronze/provider=baostock/reference_snapshots", "snapshot", "same_day", "Baostock"),
}
SEALABLE = {**PUBLIC, **OTHER}
# Datasets that exist only on trading days (a non-trading day has nothing to seal).
TRADING_ONLY = {"limit_up_pool_ths", "margin_detail_exchange", "block_trades_em", "northbound_minute_ths",
                "sector_board_intraday", "stock_intraday_snapshot"}
NOT_IN_SCOPE = ("日K、5分钟、日状态与前复权按证券存放、逐日追加，不是按日期分区的文件，不在封存范围；"
                "它们可由供应商重取并由 DATA 重建。限售解禁只封存以 D 为解禁日的分区，D 当天看到的未来预告不在内。")


class SealError(ValueError):
    pass


def _now() -> str:
    return datetime.now(TZ).replace(microsecond=0).isoformat()


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _rows(path: Path) -> int | None:
    if path.suffix != ".parquet":
        return None
    try:
        import pyarrow.parquet as pq
        return int(pq.read_metadata(path).num_rows)
    except Exception:
        return None


def _atomic_json(path: Path, body) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _check_date(value) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise SealError(f"日期格式应为 YYYY-MM-DD：{value}") from None


def day_files(data_root: Path, dataset_id: str, day: str) -> list[Path]:
    directory, layout, _kind, _src = SEALABLE[dataset_id]
    base = data_root / directory
    if layout == "partition":
        files = [base / f"{day}.parquet", base / "_empty" / f"{day}.json"]
        files += sorted((base / "_raw").glob(f"{day}.*")) if (base / "_raw").is_dir() else []
    elif layout == "day_dir":
        folder = base / f"date={day}"
        files = sorted(folder.glob("*.parquet")) if folder.is_dir() else []
    elif layout == "day_file":
        files = [base / f"date={day}.parquet"]
    else:
        folder = base / f"snapshot={day}"
        files = sorted(p for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []
    return [p for p in files if p.is_file() and not p.name.startswith("._") and not p.name.endswith(".tmp")]


def _provenance(data_root: Path, dataset_id: str, day: str) -> tuple[str | None, str | None]:
    """(observed_at, receipt path) from DATA receipts, without reading data files."""
    directory, layout, _kind, _src = SEALABLE[dataset_id]
    base = data_root / directory / "_receipts"
    if not base.is_dir():
        return None, None
    if layout == "partition":
        for receipt in sorted(base.glob("*.json"), reverse=True):
            try:
                entry = json.loads(receipt.read_text(encoding="utf-8")).get("results", {}).get(day)
            except (OSError, ValueError):
                continue
            if entry and entry.get("status") in ("ok", "empty"):
                return entry.get("observed_at"), str(receipt.relative_to(data_root))
        return None, None
    receipt = base / f"{day}.json"
    if receipt.is_file():
        try:
            body = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            body = {}
        samples = body.get("samples") or []
        observed = samples[-1].get("sampled_at") if samples else body.get("observed_at")
        return observed, str(receipt.relative_to(data_root))
    return None, None


def manifest_path(data_root: Path, day: str) -> Path:
    return data_root / SEALS / f"{day}.json"


def last_revision(data_root: Path, day: str) -> int:
    """Highest revision ever written for ``day`` (``_history`` keeps every one, revoked ones too)."""
    revisions = []
    for path in (data_root / SEALS / "_history").glob(f"{day}.r*.json"):
        suffix = path.name[len(day) + 2:-len(".json")]
        if suffix.isdigit():
            revisions.append(int(suffix))
    return max(revisions, default=0)


def load_manifest(data_root: Path, day: str) -> dict | None:
    path = manifest_path(data_root, day)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def sealed_dirs(data_root: Path, day: str) -> set[str]:
    manifest = load_manifest(data_root, day)
    return {e["dir"] for e in manifest.get("entries", [])} if manifest else set()


def is_sealed_path(data_root: Path, target: Path, day: str) -> bool:
    """True when ``target`` (a dataset directory) is sealed for ``day``."""
    try:
        rel = str(Path(target).resolve().relative_to(Path(data_root).resolve()))
    except ValueError:
        return False
    return rel in sealed_dirs(Path(data_root), day)


def is_sealed(data_root: Path, dataset_id: str, day: str) -> bool:
    return SEALABLE.get(dataset_id, (None,))[0] in sealed_dirs(data_root, day)


def plan(data_root: Path, day: str, *, trading_day: bool = True, today: str | None = None) -> dict:
    """What a seal of ``day`` would do now (read-only)."""
    day = _check_date(day)
    today = today or datetime.now(TZ).date().isoformat()
    current = load_manifest(data_root, day)
    base_revision = current["revision"] if current else last_revision(data_root, day)
    already = {e["dataset_id"] for e in current.get("entries", [])} if current else set()
    seal_now, pending, missing, sealed = [], [], [], []
    for dataset_id, (directory, _layout, kind, _src) in SEALABLE.items():
        if dataset_id in already:
            sealed.append(dataset_id)
            continue
        if not trading_day and dataset_id in TRADING_ONLY:
            continue
        files = day_files(data_root, dataset_id, day)
        if files:
            seal_now.append({"dataset_id": dataset_id, "dir": directory, "files": len(files)})
        elif kind == "same_day" and day < today:
            missing.append({"dataset_id": dataset_id, "reason": "当天没有采到，过后无法补回"})
        elif kind == "same_day":
            pending.append({"dataset_id": dataset_id, "reason": "今天还没采，采到后再封存"})
        elif kind == "next_day":
            pending.append({"dataset_id": dataset_id, "reason": "次日发布，补采后再封存"})
        else:
            pending.append({"dataset_id": dataset_id, "reason": "还没采，可补采后再封存"})
    return {"date": day, "revision": base_revision + (1 if seal_now else 0),
            "seal_now": seal_now, "already_sealed": sealed, "pending": pending, "missing": missing}


def seal(data_root: Path, day: str, *, trading_day: bool = True, log=print) -> dict:
    day = _check_date(day)
    preview = plan(data_root, day, trading_day=trading_day)
    existing = load_manifest(data_root, day)
    # after a revoke the numbering continues, so _history never overwrites an earlier revision
    current = existing or {"format": FORMAT, "date": day, "revision": last_revision(data_root, day),
                           "created_at": _now(), "entries": []}
    if not preview["seal_now"] and existing is not None:
        log(f"{day} 没有新的数据需要封存")
    stamp = _now()
    for item in preview["seal_now"]:
        dataset_id = item["dataset_id"]
        files = []
        for path in day_files(data_root, dataset_id, day):
            files.append({"path": str(path.relative_to(data_root)), "bytes": path.stat().st_size,
                          "sha256": _sha(path), "rows": _rows(path)})
        observed_at, receipt = _provenance(data_root, dataset_id, day)
        current["entries"].append({"dataset_id": dataset_id, "dir": item["dir"], "source": SEALABLE[dataset_id][3],
                                   "observed_at": observed_at, "receipt": receipt, "sealed_at": stamp,
                                   "files": files})
        log(f"封存 {dataset_id}：{len(files)} 个文件，{sum(f['rows'] or 0 for f in files)} 行")
    if preview["seal_now"] or existing is None:
        current["revision"] = current.get("revision", 0) + 1
    current.update(updated_at=stamp, pending=preview["pending"], missing=preview["missing"],
                   not_in_scope=NOT_IN_SCOPE)
    current["totals"] = {"datasets": len(current["entries"]),
                         "files": sum(len(e["files"]) for e in current["entries"]),
                         "rows": sum(f["rows"] or 0 for e in current["entries"] for f in e["files"])}
    _atomic_json(manifest_path(data_root, day), current)
    _atomic_json(data_root / SEALS / "_history" / f"{day}.r{current['revision']}.json", current)
    return current


def verify(data_root: Path, day: str, *, log=print) -> dict:
    day = _check_date(day)
    manifest = load_manifest(data_root, day)
    if manifest is None:
        raise SealError(f"{day} 没有封存记录")
    problems = []
    for entry in manifest["entries"]:
        for item in entry["files"]:
            path = data_root / item["path"]
            if not path.is_file():
                problems.append({"path": item["path"], "problem": "missing"})
            elif path.stat().st_size != item["bytes"] or _sha(path) != item["sha256"]:
                problems.append({"path": item["path"], "problem": "changed"})
        # files added to a sealed directory for this day after sealing
        known = {f["path"] for f in entry["files"]}
        for path in day_files(data_root, entry["dataset_id"], day):
            rel = str(path.relative_to(data_root))
            if rel not in known:
                problems.append({"path": rel, "problem": "added_after_seal"})
    result = {"date": day, "revision": manifest["revision"], "verified_at": _now(),
              "verify_status": "ok" if not problems else "mismatch", "problems": problems,
              "files_checked": sum(len(e["files"]) for e in manifest["entries"])}
    _atomic_json(data_root / SEALS / "_verify" / f"{day}.json", result)
    log(f"核对 {day}：{result['files_checked']} 个文件，问题 {len(problems)} 个")
    return result


def revoke(data_root: Path, day: str, reason: str, *, log=print) -> dict:
    day = _check_date(day)
    reason = str(reason or "").strip()
    if not reason:
        raise SealError("撤销封存必须写明原因")
    manifest = load_manifest(data_root, day)
    if manifest is None:
        raise SealError(f"{day} 没有封存记录")
    stamp = datetime.now(TZ).strftime("%Y%m%dT%H%M%S")
    dest = data_root / SEALS / "_revoked" / f"{day}-{stamp}"
    moved = []
    for entry in manifest["entries"]:
        for item in entry["files"]:
            source = data_root / item["path"]
            if source.is_file():
                target = dest / "files" / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                moved.append(item["path"])
    record = {"date": day, "revoked_at": _now(), "reason": reason, "revision": manifest["revision"],
              "moved_files": len(moved)}
    _atomic_json(dest / "manifest.json", manifest)
    _atomic_json(dest / "revocation.json", record)
    check = data_root / SEALS / "_verify" / f"{day}.json"
    if check.is_file():  # the result belongs to the revoked revision
        os.replace(check, dest / "verify.json")
    os.replace(manifest_path(data_root, day), dest / "manifest.current.json")
    log(f"已撤销 {day} 的封存（第 {manifest['revision']} 版），{len(moved)} 个文件移到 {dest.relative_to(data_root)}")
    return record


def recent(data_root: Path, days: int = 30) -> list[dict]:
    """Latest ``days`` seal records with their verification state (reads manifests only)."""
    base = data_root / SEALS
    if not base.is_dir():
        return []
    rows = []
    for path in sorted(base.glob("????-??-??.json"), reverse=True)[:days]:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        check_path = base / "_verify" / path.name
        check = json.loads(check_path.read_text(encoding="utf-8")) if check_path.is_file() else None
        if check and check.get("revision") != manifest.get("revision"):
            check = None
        totals = manifest.get("totals") or {}
        rows.append({"date": manifest["date"], "sealed_at": manifest.get("updated_at"),
                     "revision": manifest.get("revision"), "files": totals.get("files"), "rows": totals.get("rows"),
                     "pending": [p["dataset_id"] for p in manifest.get("pending", [])],
                     "verify_status": check["verify_status"] if check else "never",
                     "verified_at": check["verified_at"] if check else None,
                     "problems": len(check["problems"]) if check else 0})
    return rows


def sealed_through(data_root: Path, dataset_id: str) -> str | None:
    base = data_root / SEALS
    if not base.is_dir() or dataset_id not in SEALABLE:
        return None
    for path in sorted(base.glob("????-??-??.json"), reverse=True):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if any(e["dataset_id"] == dataset_id for e in manifest.get("entries", [])):
            return manifest["date"]
    return None


__all__ = ["SEALABLE", "SealError", "day_files", "is_sealed", "is_sealed_path", "last_revision", "load_manifest", "plan",
           "recent", "revoke", "seal", "sealed_through", "verify"]

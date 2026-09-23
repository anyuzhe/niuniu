"""Read-only inventory of a niuniu data root (data-remediation stage 0).

Answers, per dataset directory, *what is physically there*: file counts, bytes,
Parquet row counts, column-signature groups, date ranges from Parquet footer
statistics, empty markers, receipts, and a listing fingerprint.

It never opens a network connection and never writes inside the data root.  The
report goes to an explicit ``--out`` path that must lie outside the data root.

Fingerprints are layered and must not be confused:

* ``listing_fingerprint`` = SHA-256 over sorted ``relpath, size, mtime_ns``.  It
  detects that a directory changed; it does NOT pin file bytes.
* ``content_manifest_sha256`` (only with ``--deep-hash``) = SHA-256 over sorted
  ``relpath, sha256(file)``.  This pins bytes and is what a registry may bind.

Row counts and date ranges come from Parquet metadata only.  A date range is the
min/max over files; it says nothing about per-symbol continuity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

FORMAT = "niuniu-data-inventory-v1"
SKIP_NAMES = {".DS_Store"}
DATE_COLUMNS = ("date", "calendar_date", "trade_date", "event_date", "time",
                "dividOperateDate", "observed_at", "fetch_ts")
# Directories whose children are themselves datasets (one level deeper).
SNAPSHOT_PREFIXES = ("snapshot=",)
EXTRA_TOP_LEVEL = ("backups", "automation", "research", "research_skills",
                   "staging", "workers", "temp", "manifests", "cache",
                   "quarantine", "catalog")


def is_skipped(name: str) -> bool:
    # macOS AppleDouble sidecars ("._x") are filesystem noise on exFAT volumes.
    return name.startswith("._") or name in SKIP_NAMES


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def walk_files(root: Path):
    """Yield (relative posix path, stat) for regular files, deterministic order."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not is_skipped(d))
        for name in sorted(filenames):
            if is_skipped(name):
                continue
            path = Path(dirpath) / name
            try:
                st = path.lstat()
            except OSError:
                continue
            if not os.path.isfile(path) or path.is_symlink():
                continue
            yield path.relative_to(root).as_posix(), st


def _stat_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        try:
            value = value.decode()
        except UnicodeDecodeError:
            return None
    return None if value is None else str(value)


def parquet_facts(path: Path) -> dict:
    """Footer-only facts: rows, schema signature, date-column min/max."""
    import pyarrow.parquet as pq

    meta = pq.ParquetFile(path).metadata
    schema = meta.schema.to_arrow_schema()
    columns = [f"{field.name}:{field.type}" for field in schema]
    signature = hashlib.sha256("\n".join(columns).encode()).hexdigest()[:16]
    date_col = next((c for c in DATE_COLUMNS if c in schema.names), None)
    lo = hi = None
    stats_complete = date_col is not None
    if date_col is not None and meta.num_rows:
        index = schema.names.index(date_col)
        for rg in range(meta.num_row_groups):
            column = meta.row_group(rg).column(index)
            stats = column.statistics
            if stats is None or not stats.has_min_max:
                stats_complete = False
                continue
            mn, mx = _stat_value(stats.min), _stat_value(stats.max)
            if mn is None or mx is None:
                stats_complete = False
                continue
            lo = mn if lo is None else min(lo, mn)
            hi = mx if hi is None else max(hi, mx)
    return {"rows": meta.num_rows, "signature": signature, "columns": columns,
            "date_column": date_col, "date_min": lo, "date_max": hi,
            "date_stats_complete": stats_complete if meta.num_rows else True}


def inventory_dataset(root: Path, data_root: Path, *, deep_hash: bool, workers: int) -> dict:
    files = list(walk_files(root))
    listing = hashlib.sha256()
    content = hashlib.sha256() if deep_hash else None
    total_bytes = 0
    kinds = {"parquet": 0, "empty_markers": 0, "receipts": 0, "other": 0}
    parquet_paths = []
    for rel, st in files:
        total_bytes += st.st_size
        listing.update(f"{rel}\t{st.st_size}\t{st.st_mtime_ns}\n".encode())
        parts = rel.split("/")
        if parts[0] == "_empty":
            kinds["empty_markers"] += 1
        elif parts[0] == "_receipts":
            kinds["receipts"] += 1
        elif rel.endswith(".parquet"):
            kinds["parquet"] += 1
            parquet_paths.append(rel)
        else:
            kinds["other"] += 1

    signatures: dict[str, dict] = {}
    errors = []
    rows_total = 0
    date_min = date_max = None
    date_columns = set()
    stats_incomplete = 0

    def facts(rel):
        try:
            return rel, parquet_facts(root / rel), None
        except Exception as exc:  # unreadable parquet is a finding, not a crash
            return rel, None, f"{type(exc).__name__}: {exc}"[:300]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for rel, fact, error in pool.map(facts, parquet_paths):
            if error:
                errors.append({"path": rel, "error": error})
                continue
            rows_total += fact["rows"]
            group = signatures.setdefault(fact["signature"], {"files": 0, "rows": 0,
                                                              "columns": fact["columns"], "example": rel})
            group["files"] += 1
            group["rows"] += fact["rows"]
            if fact["date_column"]:
                date_columns.add(fact["date_column"])
            if not fact["date_stats_complete"]:
                stats_incomplete += 1
            if fact["date_min"] is not None:
                date_min = fact["date_min"] if date_min is None else min(date_min, fact["date_min"])
                date_max = fact["date_max"] if date_max is None else max(date_max, fact["date_max"])

    if deep_hash:
        def hashed(item):
            rel, _st = item
            try:
                return rel, sha256_file(root / rel), None
            except OSError as exc:
                return rel, None, str(exc)[:300]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for rel, digest, error in pool.map(hashed, files):
                if error:
                    errors.append({"path": rel, "error": f"hash: {error}"})
                    digest = "ERROR"
                content.update(f"{rel}\t{digest}\n".encode())

    top_parquet_stems = sorted({Path(p).stem for p in parquet_paths if "/" not in p})
    return {
        "path": root.relative_to(data_root).as_posix(),
        "files": len(files),
        "bytes": total_bytes,
        **kinds,
        "top_level_symbols": len(top_parquet_stems),
        "rows_total": rows_total,
        "column_signatures": dict(sorted(signatures.items())),
        "schema_is_uniform": len(signatures) <= 1,
        "date_columns": sorted(date_columns),
        "date_min": date_min,
        "date_max": date_max,
        "files_with_incomplete_date_stats": stats_incomplete,
        "errors": errors,
        "listing_fingerprint": listing.hexdigest(),
        "content_manifest_sha256": content.hexdigest() if content else None,
    }


def discover_datasets(data_root: Path) -> list[Path]:
    """lake/bronze/provider=*/<dataset>, lake/silver/<dataset>, lake/gold/<dataset>;
    snapshot=<date> children become their own datasets."""
    found = []
    lake = data_root / "lake"
    parents = []
    bronze = lake / "bronze"
    if bronze.is_dir():
        parents += [p for p in sorted(bronze.iterdir()) if p.is_dir() and not is_skipped(p.name)]
    for layer in ("silver", "gold"):
        if (lake / layer).is_dir():
            parents.append(lake / layer)
    for parent in parents:
        for child in sorted(parent.iterdir()):
            if not child.is_dir() or is_skipped(child.name) or child.is_symlink():
                continue
            snaps = [s for s in sorted(child.iterdir())
                     if s.is_dir() and s.name.startswith(SNAPSHOT_PREFIXES)]
            found.extend(snaps if snaps else [child])
    return found


def summarize_dir(root: Path, data_root: Path) -> dict:
    count = size = 0
    for _rel, st in walk_files(root):
        count += 1
        size += st.st_size
    return {"path": root.relative_to(data_root).as_posix(), "files": count, "bytes": size}


def catalog_facts(data_root: Path) -> dict:
    path = data_root / "catalog" / "mqc.duckdb"
    if not path.is_file():
        return {"available": False, "error": "missing mqc.duckdb"}
    try:
        import duckdb
        con = duckdb.connect(str(path), read_only=True)
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    try:
        views = con.execute("select view_name, sql from duckdb_views() where not internal "
                            "order by view_name").fetchall()
        tables = con.execute("select table_name, estimated_size from duckdb_tables() "
                             "order by table_name").fetchall()
    finally:
        con.close()
    return {"available": True,
            "views": [{"name": n, "sql_sha256": hashlib.sha256(s.encode()).hexdigest()} for n, s in views],
            "tables": [{"name": n, "estimated_rows": r} for n, r in tables]}


def build_report(data_root: Path, *, deep_hash=False, workers=8, captures_root=None,
                 only=None, include_catalog=True) -> dict:
    data_root = data_root.resolve()
    datasets = discover_datasets(data_root)
    if only:
        datasets = [d for d in datasets if any(o in d.relative_to(data_root).as_posix() for o in only)]
    entries = [inventory_dataset(d, data_root, deep_hash=deep_hash, workers=workers) for d in datasets]
    others = [summarize_dir(data_root / name, data_root)
              for name in EXTRA_TOP_LEVEL if (data_root / name).is_dir()] if not only else []
    captures = None
    if captures_root is not None:
        captures_root = Path(captures_root).resolve()
        captures = []
        for child in sorted(captures_root.iterdir()):
            if child.is_dir() and not is_skipped(child.name):
                item = inventory_dataset(child, captures_root, deep_hash=deep_hash, workers=workers)
                captures.append(item)
    body = {
        "format": FORMAT,
        "data_root": str(data_root),
        "deep_hash": deep_hash,
        "datasets": entries,
        "other_directories": others,
        "captures_root": str(captures_root) if captures_root else None,
        "captures": captures,
        "catalog": catalog_facts(data_root) if include_catalog else None,
        "fingerprint_semantics": {
            "listing_fingerprint": "sha256(sorted relpath,size,mtime_ns); change detection only, not byte identity",
            "content_manifest_sha256": "sha256(sorted relpath,sha256(file)); pins bytes; null unless --deep-hash",
            "date_min_max": "parquet footer statistics over all files; not per-symbol continuity",
        },
    }
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    body["report_digest"] = hashlib.sha256(canonical.encode()).hexdigest()
    body["generated_at"] = datetime.now(timezone.utc).isoformat()
    return body


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", required=True, help="显式数据根；不提供默认值")
    parser.add_argument("--out", required=True, help="报告 JSON 路径，必须在数据根之外")
    parser.add_argument("--captures-root", help="可选：同时盘点 artifacts/_market_data 捕获包")
    parser.add_argument("--only", action="append", help="只盘点路径包含该子串的数据集，可重复")
    parser.add_argument("--deep-hash", action="store_true", help="逐文件 SHA256（慢）")
    parser.add_argument("--no-catalog", action="store_true", help="不读取 mqc.duckdb")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    data_root = Path(args.data_root)
    out = Path(args.out)
    if not data_root.is_dir():
        print(f"数据根不存在：{data_root}", file=sys.stderr)
        return 2
    if _inside(out, data_root):
        print("拒绝：--out 不能位于数据根之内（盘点只读）", file=sys.stderr)
        return 2
    report = build_report(data_root, deep_hash=args.deep_hash, workers=max(1, args.workers),
                          captures_root=args.captures_root, only=args.only,
                          include_catalog=not args.no_catalog)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True))
    os.replace(tmp, out)
    errors = sum(len(d["errors"]) for d in report["datasets"])
    print(json.dumps({"out": str(out), "datasets": len(report["datasets"]), "errors": errors,
                      "report_digest": report["report_digest"]}, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

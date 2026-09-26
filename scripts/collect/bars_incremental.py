"""Apply one explicitly approved bars gap plan.

This script never discovers work at apply time. First run ``scan_gaps.py`` and
review its JSON. A real collection requires all three controls:

* ``--apply``
* ``--plan PATH``
* ``--approve-sha256`` exactly matching the reviewed plan

Without them there is no provider login, network request, backup or lake write.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import multiprocessing
import os
import shutil
import signal
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collect.scan_gaps import DATASETS, canonical_digest, file_sha256  # noqa: E402
from collect import coverage as cov  # noqa: E402
from collect import paths  # noqa: E402
from collect.daily_common import select_reference_file, select_stock_basic  # noqa: E402

FIELDS = {
    "baostock-daily": "date,code,open,high,low,close,volume,amount,adjustflag",
    "baostock-min5": "date,time,code,open,high,low,close,volume,amount,adjustflag",
}
REQUEST_FIELDS = {
    # tradestatus distinguishes suspended blank rows from malformed active rows.
    "baostock-daily": FIELDS["baostock-daily"] + ",tradestatus",
    "baostock-min5": FIELDS["baostock-min5"],
}
# daily bars with the exchange's previous close and ST flag (used for delisted stocks)
REQUEST_FIELDS["baostock-daily-ext"] = ("date,code,open,high,low,close,preclose,volume,amount,"
                                        "adjustflag,tradestatus,isST")
FREQUENCY = {"baostock-daily": "d", "baostock-min5": "5", "baostock-daily-ext": "d"}
KEYS = {"baostock-daily": ["date"], "baostock-min5": ["date", "time"]}
ADJUSTFLAG = "3"


def load_plan(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("kind") != "niuniu_bars_gap_plan" or payload.get("schema_version") != 1:
        raise ValueError("unsupported or missing plan contract")
    expected = canonical_digest(payload)
    if payload.get("plan_sha256") != expected:
        raise ValueError("plan content does not match plan_sha256")
    if payload.get("dataset") not in FIELDS:
        raise ValueError(f"unsupported dataset {payload.get('dataset')}")
    if not isinstance(payload.get("actions"), list):
        raise ValueError("plan actions must be a list")
    return payload


def require_approval(plan: dict[str, Any], approval: str | None) -> None:
    if not approval:
        raise PermissionError("real collection requires --approve-sha256")
    if not hmac.compare_digest(approval.strip(), plan["plan_sha256"]):
        raise PermissionError("approval hash does not match the reviewed plan")


def validate_plan_state(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Fail before network access if any approved input has changed."""
    dataset = plan["dataset"]
    expected_root = Path(DATASETS[dataset]["dir"]).resolve()
    plan_root = Path(plan["dataset_dir"]).resolve()
    if plan_root != expected_root:
        raise ValueError(f"plan dataset_dir is not the configured lake path: {plan_root}")
    for source in ("calendar", "universe"):
        identity = plan[source]
        path = Path(identity["path"])
        if file_sha256(path) != identity["sha256"]:
            raise ValueError(f"stale plan: {source} source changed: {path}")
        if identity.get("auto_selected") is None:
            raise ValueError(f"stale plan: {source} selection contract missing")
        if identity["auto_selected"]:
            asof = date.fromisoformat(identity["asof"])
            chosen, manifest_sha = (
                select_reference_file(asof, lake=cov.LAKE, fallback=cov.CALENDAR,
                                      name="trade_calendar") if source == "calendar"
                else select_stock_basic(asof, lake=cov.LAKE, fallback=cov.STOCK_BASIC))
            if chosen.resolve() != path.resolve() or manifest_sha != identity["reference_manifest_sha256"]:
                raise ValueError(f"stale plan: {source} newer reference selected")
    for evidence in plan.get("status_evidence", []):
        path = Path(evidence["path"]).resolve()
        if (path.parent != expected_root.parent / "daily_status_v2" or
                path.name != evidence["symbol"].replace(".", "_", 1) + ".parquet" or
                file_sha256(path) != evidence["sha256"]):
            raise ValueError(f"stale plan: suspension evidence changed: {evidence['symbol']}")
    seen: set[str] = set()
    checked: list[dict[str, Any]] = []
    for action in plan["actions"]:
        symbol = action.get("symbol")
        if symbol in seen:
            raise ValueError(f"duplicate symbol in plan: {symbol}")
        seen.add(symbol)
        path = Path(action["path"]).resolve()
        if path.parent != expected_root or path.name != symbol.replace(".", "_", 1) + ".parquet":
            raise ValueError(f"action path escapes dataset contract: {path}")
        if action["action"] == "full":
            if path.exists():
                raise ValueError(f"stale plan: full target now exists: {path}")
            if action.get("sha256_before") is not None:
                raise ValueError(f"full action unexpectedly has sha256_before: {symbol}")
        elif action["action"] in {"tail", "refresh_last"}:
            if not path.is_file():
                raise ValueError(f"stale plan: tail target disappeared: {path}")
            actual = file_sha256(path)
            if actual != action.get("sha256_before"):
                raise ValueError(f"stale plan: target changed after review: {symbol}")
        else:
            raise ValueError(f"unsupported action {action.get('action')}: {symbol}")
        checked.append({**action, "path": path})
    return checked


def _frame_from_rows(rows: list[list[str]], dataset: str, reference_schema):
    import polars as pl
    columns = REQUEST_FIELDS[dataset].split(",")
    frame = pl.DataFrame(rows, schema=columns, orient="row")
    suspended_rows = 0
    if "tradestatus" in frame.columns:
        suspended_rows = frame.filter(pl.col("tradestatus") != "1").height
        frame = frame.filter(pl.col("tradestatus") == "1").drop("tradestatus")
    expressions = [
        pl.col("date").str.to_date(),
        pl.col("open").cast(pl.Float64), pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64), pl.col("close").cast(pl.Float64),
        pl.col("volume").cast(pl.Int64), pl.col("amount").cast(pl.Float64),
        pl.col("code").cast(pl.String), pl.col("adjustflag").cast(pl.String),
        pl.lit(time.strftime("%Y-%m-%dT%H:%M:%S")).alias("fetch_ts"),
    ]
    if dataset == "baostock-min5":
        expressions.append(pl.col("time").cast(pl.String))
    frame = frame.with_columns(expressions)
    frame = frame.select(list(reference_schema))
    return frame.cast(reference_schema), suspended_rows


def merge_rows(action: dict[str, Any], rows: list[list[str]], dataset: str,
               reference_schema):
    """Replace returned days atomically in memory; no file write here."""
    import polars as pl
    new, suspended_rows = _frame_from_rows(rows, dataset, reference_schema)
    if new.is_empty():
        raise SuspendedRange(f"provider confirmed {suspended_rows} suspended rows and no tradable bars")
    requested_start = action["fetch_start"]
    requested_end = action["fetch_end"]
    returned_min = new["date"].min().isoformat()
    returned_max = new["date"].max().isoformat()
    if returned_min < requested_start or returned_max > requested_end:
        raise ValueError(f"provider returned dates outside approved range: "
                         f"{returned_min}..{returned_max}")
    keys = KEYS[dataset]
    if new.height != new.select(keys).unique().height:
        raise ValueError("provider response has duplicate primary keys")
    path = action["path"]
    if action["action"] == "full":
        merged = new.sort(keys)
        old_rows = 0
    else:
        old = pl.read_parquet(path)
        if old.schema != reference_schema:
            raise ValueError(f"existing schema differs from dataset contract: {path}")
        returned_days = new["date"].unique().to_list()
        kept = old.filter(~pl.col("date").is_in(returned_days))
        merged = pl.concat([kept, new]).sort(keys)
        old_rows = old.height
        if merged.height < old.height:
            raise ValueError(f"merged row count decreased: {old.height} -> {merged.height}")
    if merged.height != merged.select(keys).unique().height:
        raise ValueError("merged data has duplicate primary keys")
    return merged, {"old_rows": old_rows, "provider_rows": new.height,
                    "suspended_rows_ignored": suspended_rows,
                    "merged_rows": merged.height,
                    "returned_start": returned_min, "returned_end": returned_max}


def backup_existing(path: Path, backup_root: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    destination = backup_root / path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"backup already exists: {destination}")
    before = file_sha256(path)
    shutil.copy2(path, destination)
    after = file_sha256(destination)
    if before != after:
        destination.unlink(missing_ok=True)
        raise IOError(f"backup sha256 mismatch: {path}")
    return {"path": str(destination), "sha256": after}


def atomic_write(frame, path: Path) -> None:
    import polars as pl
    tmp = path.with_suffix(path.suffix + ".tmp")
    if tmp.exists():
        raise FileExistsError(f"stale temporary file: {tmp}")
    try:
        frame.write_parquet(tmp)
        reread = pl.read_parquet(tmp)
        if reread.height != frame.height or reread.schema != frame.schema:
            raise ValueError("temporary parquet failed read-back validation")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class SuspendedRange(ValueError):
    """Provider explicitly marked the whole approved range as suspended."""


def _baostock_worker(dataset: str, connection) -> None:
    """One isolated provider session. The parent may kill it on a hard stall."""
    try:
        import baostock as bs
        login = bs.login()
        if login.error_code != "0":
            connection.send(("startup_error", f"{login.error_code}: {login.error_msg}"))
            return
        connection.send(("ready", None))
        while True:
            request = connection.recv()
            if request is None:
                break
            symbol, start, end = request
            try:
                result = bs.query_history_k_data_plus(
                    symbol, REQUEST_FIELDS[dataset], start_date=start, end_date=end,
                    frequency=FREQUENCY[dataset], adjustflag=ADJUSTFLAG,
                )
                if result.error_code != "0":
                    raise RuntimeError(f"query failed {result.error_code}: {result.error_msg}")
                rows: list[list[str]] = []
                while result.error_code == "0" and result.next():
                    rows.append(result.get_row_data())
                connection.send(("ok", rows))
            except Exception as exc:
                connection.send(("error", f"{type(exc).__name__}: {exc}"))
    except EOFError:
        pass
    finally:
        try:
            bs.logout()
        except Exception:
            pass
        connection.close()


class BaostockSession:
    """Provider session isolated in a killable process with a hard timeout."""

    def __init__(self, dataset: str, request_timeout: float):
        self.dataset = dataset
        self.request_timeout = request_timeout
        self.context = multiprocessing.get_context("spawn")
        self.process = None
        self.connection = None
        self._start()

    def _start(self) -> None:
        parent, child = self.context.Pipe()
        process = self.context.Process(target=_baostock_worker,
                                       args=(self.dataset, child), daemon=True)
        process.start()
        child.close()
        self.process, self.connection = process, parent
        if not parent.poll(max(30.0, self.request_timeout)):
            self._terminate()
            raise TimeoutError("baostock worker startup timed out")
        status, detail = parent.recv()
        if status != "ready":
            self._terminate()
            raise RuntimeError(f"baostock worker startup failed: {detail}")

    def _terminate(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=5)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join(timeout=5)
            self.process = None

    def __call__(self, symbol: str, start: str, end: str) -> list[list[str]]:
        if self.connection is None:
            raise RuntimeError("baostock worker is not running")
        self.connection.send((symbol, start, end))
        if not self.connection.poll(self.request_timeout):
            self._terminate()
            raise TimeoutError(
                f"provider request exceeded {self.request_timeout:.1f}s for {symbol}")
        status, payload = self.connection.recv()
        if status == "error":
            raise RuntimeError(payload)
        if status != "ok":
            raise RuntimeError(f"unexpected worker response {status}")
        return payload

    def reset(self) -> None:
        self._terminate()
        self._start()

    def close(self) -> None:
        if self.connection is not None:
            try:
                self.connection.send(None)
            except (BrokenPipeError, EOFError, OSError):
                pass
        self._terminate()


def _provider_fetcher(dataset: str, request_timeout: float) -> tuple[BaostockSession, Callable[[], None]]:
    session = BaostockSession(dataset, request_timeout)
    return session, session.close


def call_with_timeout(fetcher: Callable[[str, str, str], list[list[str]]],
                      symbol: str, start: str, end: str, seconds: float) -> list[list[str]]:
    if seconds <= 0 or not hasattr(signal, "SIGALRM"):
        return fetcher(symbol, start, end)

    def timeout_handler(_signum, _frame):
        raise TimeoutError(f"provider request exceeded {seconds:.1f}s")

    previous = signal.signal(signal.SIGALRM, timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fetcher(symbol, start, end)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def write_receipt_checkpoint(path: Path, receipt: dict[str, Any]) -> None:
    """Persist progress after every symbol so interruption remains auditable."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def execute(plan: dict[str, Any], actions: list[dict[str, Any]], *,
            fetcher: Callable[[str, str, str], list[list[str]]],
            backup_root: Path, receipt_path: Path | None = None,
            throttle: float = 1.0, request_timeout: float = 60.0,
            retries: int = 2, keep_going: bool = False) -> dict[str, Any]:
    """Execute an already approved and state-validated plan."""
    import polars as pl
    dataset = plan["dataset"]
    root = Path(plan["dataset_dir"])
    reference_file = next(root.glob("*.parquet"), None)
    if reference_file is None:
        raise FileNotFoundError(f"dataset has no reference schema: {root}")
    reference_schema = pl.read_parquet_schema(reference_file)
    if retries < 1:
        raise ValueError("retries must be >= 1")
    receipt: dict[str, Any] = {
        "plan_sha256": plan["plan_sha256"], "dataset": dataset,
        "target_end": plan["target_end"], "symbols": [], "stopped_early": False,
        "run_status": "running",
    }
    if receipt_path:
        write_receipt_checkpoint(receipt_path, receipt)
    for index, action in enumerate(actions, 1):
        record: dict[str, Any] = {
            "symbol": action["symbol"], "action": action["action"],
            "fetch_start": action["fetch_start"], "fetch_end": action["fetch_end"],
            "sha256_before": action["sha256_before"],
        }
        try:
            rows = None
            last_fetch_error = None
            for attempt in range(1, retries + 1):
                try:
                    rows = call_with_timeout(
                        fetcher, action["symbol"], action["fetch_start"],
                        action["fetch_end"], request_timeout)
                    last_fetch_error = None
                    break
                except Exception as exc:
                    last_fetch_error = exc
                    reset = getattr(fetcher, "reset", None)
                    if callable(reset):
                        reset()
            if last_fetch_error is not None:
                raise last_fetch_error
            if not rows:
                record["status"] = "empty"
            else:
                merged, stats = merge_rows(action, rows, dataset, reference_schema)
                record["backup"] = backup_existing(action["path"], backup_root)
                atomic_write(merged, action["path"])
                record.update(status="ok", sha256_after=file_sha256(action["path"]), **stats)
        except SuspendedRange as exc:
            record.update(status="suspended", evidence=str(exc))
        except Exception as exc:  # recorded verbatim in receipt
            record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            if not keep_going:
                receipt["stopped_early"] = True
        receipt["symbols"].append(record)
        counts: dict[str, int] = {}
        for item in receipt["symbols"]:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        receipt["summary"] = counts
        if receipt_path:
            write_receipt_checkpoint(receipt_path, receipt)
        print(f"[{index}/{len(actions)}] {action['symbol']} {record['status']}")
        if receipt["stopped_early"]:
            break
        if throttle:
            time.sleep(throttle)
    counts: dict[str, int] = {}
    for record in receipt["symbols"]:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    receipt["summary"] = counts
    receipt["run_status"] = "stopped_early" if receipt["stopped_early"] else "finished"
    if receipt_path:
        write_receipt_checkpoint(receipt_path, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve-sha256")
    parser.add_argument("--receipt")
    parser.add_argument("--backup-root")
    parser.add_argument("--throttle", type=float, default=1.0)
    parser.add_argument("--request-timeout", type=float, default=60.0,
                        help="single provider request timeout in seconds")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--keep-going", action="store_true")
    args = parser.parse_args(argv)

    plan = load_plan(Path(args.plan))
    print(f"plan: {plan['plan_sha256']}")
    print(f"dataset: {plan['dataset']}; target: {plan['target_end']}; "
          f"actions: {len(plan['actions'])}")
    if not args.apply:
        print("review only: no provider login, network request, backup or lake write")
        return 0
    require_approval(plan, args.approve_sha256)
    actions = validate_plan_state(plan)
    if not actions:
        print("approved plan has no actions")
        return 0

    short = plan["plan_sha256"][:16]
    backup_root = (Path(args.backup_root) if args.backup_root else
                   paths.BACKUPS /
                   f"collection-{short}" / plan["dataset"])
    receipt_path = (Path(args.receipt) if args.receipt else
                    Path("artifacts/collection-receipts") / f"{short}.json")
    if receipt_path.exists():
        raise FileExistsError(f"receipt already exists: {receipt_path}")

    fetcher, logout = _provider_fetcher(plan["dataset"], args.request_timeout)
    try:
        receipt = execute(plan, actions, fetcher=fetcher, backup_root=backup_root,
                          receipt_path=receipt_path, throttle=args.throttle,
                          request_timeout=args.request_timeout, retries=args.retries,
                          keep_going=args.keep_going)
    finally:
        logout()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(f"receipt: {receipt_path}")
    return 1 if receipt["summary"].get("failed") else 0


def cli() -> int:
    try:
        return main()
    except (FileNotFoundError, FileExistsError, PermissionError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())

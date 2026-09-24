"""Collect full historical Baostock trading-status/ST observations for listed A-shares.

Output is an independent bronze dataset and does not alter price bars. Suspended
rows retain ``tradestatus=0``; missing values are never replaced by zero.
"""
from __future__ import annotations

import argparse
import multiprocessing
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collect import coverage  # noqa: E402
from collect.envelope import Envelope, main_guard  # noqa: E402

from collect.paths import bronze  # noqa: E402

DEFAULT_DEST = str(bronze("baostock", "daily_status_v2"))
FIELDS = "date,code,tradestatus,isST"
REQUIRED = FIELDS.split(",")


def _worker(connection) -> None:
    try:
        import baostock as bs
        login = bs.login()
        if login.error_code != "0":
            connection.send(("startup_error", f"{login.error_code}: {login.error_msg}")); return
        connection.send(("ready", None))
        while True:
            request = connection.recv()
            if request is None: break
            code, start, end = request
            try:
                response = bs.query_history_k_data_plus(
                    code, FIELDS, start_date=start, end_date=end,
                    frequency="d", adjustflag="3")
                if response.error_code != "0":
                    raise RuntimeError(f"{response.error_code}: {response.error_msg}")
                fields = list(response.fields); rows = []
                while response.error_code == "0" and response.next():
                    values = response.get_row_data()
                    if len(values) != len(fields): raise ValueError("row width differs from fields")
                    rows.append(values)
                if response.error_code != "0": raise RuntimeError(response.error_msg)
                connection.send(("ok", {"fields": fields, "rows": rows}))
            except Exception as exc:
                connection.send(("error", f"{type(exc).__name__}: {exc}"))
    except EOFError:
        pass
    finally:
        try: bs.logout()
        except Exception: pass
        connection.close()


class StatusSession:
    def __init__(self, ipo_dates: dict[str, date], end: date, timeout: float):
        self.ipo_dates, self.end, self.timeout = ipo_dates, end, timeout
        self.context = multiprocessing.get_context("spawn")
        self.process = self.connection = None
        self._start()

    def _start(self):
        parent, child = self.context.Pipe()
        proc = self.context.Process(target=_worker, args=(child,), daemon=True)
        proc.start(); child.close(); self.process, self.connection = proc, parent
        if not parent.poll(max(30.0, self.timeout)):
            self._terminate(); raise TimeoutError("status worker startup timed out")
        status, detail = parent.recv()
        if status != "ready": self._terminate(); raise RuntimeError(detail)

    def _terminate(self):
        if self.connection is not None: self.connection.close(); self.connection = None
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate(); self.process.join(timeout=5)
                if self.process.is_alive(): self.process.kill(); self.process.join(timeout=5)
            self.process = None

    def __call__(self, code: str):
        import pandas as pd
        self.connection.send((code, self.ipo_dates[code].isoformat(), self.end.isoformat()))
        if not self.connection.poll(self.timeout):
            self._terminate(); self._start()
            raise TimeoutError(f"status request exceeded {self.timeout:.1f}s for {code}")
        status, payload = self.connection.recv()
        if status != "ok": raise RuntimeError(payload)
        frame = pd.DataFrame(payload["rows"], columns=payload["fields"])
        frame["fetch_ts"] = datetime.now().astimezone().isoformat()
        return frame

    def close(self):
        if self.connection is not None:
            try: self.connection.send(None)
            except (BrokenPipeError, EOFError, OSError): pass
        self._terminate()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", default=DEFAULT_DEST)
    parser.add_argument("--receipt")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    parser.add_argument("--throttle", type=float, default=0.5)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--request-timeout", type=float, default=120.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--universe", default=None)
    args = parser.parse_args(argv)
    listed = coverage.listed_a_shares()
    if args.universe:
        codes = [x.strip() for x in Path(args.universe).read_text().splitlines()
                 if x.strip() and not x.startswith("#")]
        unknown = set(codes) - set(listed)
        if unknown: raise ValueError(f"non-listed codes: {sorted(unknown)[:5]}")
    else:
        codes = sorted(listed)
    envelope = Envelope(args, name="baostock-daily-status",
                        source="baostock.query_history_k_data_plus",
                        required_columns=REQUIRED)
    session = None
    try:
        if args.apply and not args.dry_run:
            session = StatusSession({code: listed[code] for code in codes},
                                    args.end, args.request_timeout)
            fetch = session
        else: fetch = lambda _code: None
        return envelope.run(codes, fetch)
    finally:
        if session is not None: session.close()


if __name__ == "__main__":
    raise SystemExit(main_guard(main))

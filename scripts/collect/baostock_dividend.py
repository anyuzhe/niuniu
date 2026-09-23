"""Collect full historical Baostock dividend records for currently listed A-shares.

Each symbol is queried year-by-year from IPO year through ``--end-year`` inside a
killable provider worker. Output is one full-width parquet per symbol in a new
directory; no product pointer or normalized dividend table is changed.
"""
from __future__ import annotations

import argparse
import multiprocessing
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collect import coverage  # noqa: E402
from collect.envelope import Envelope, main_guard  # noqa: E402

from collect.paths import bronze  # noqa: E402

DEFAULT_DEST = str(bronze("baostock", "corporate_actions_dividend_v2"))
REQUIRED = ["code", "dividPlanDate", "dividRegistDate", "dividOperateDate",
            "dividCashPsBeforeTax", "dividStocksPs", "dividReserveToStockPs"]


def _worker(connection) -> None:
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
            code, start_year, end_year = request
            try:
                records = []
                all_fields: list[str] = []
                for year in range(start_year, end_year + 1):
                    response = bs.query_dividend_data(code, year=year, yearType="report")
                    if response.error_code != "0":
                        raise RuntimeError(f"year {year}: {response.error_code}: {response.error_msg}")
                    fields = list(response.fields)
                    if fields:
                        all_fields = fields
                    while response.error_code == "0" and response.next():
                        values = response.get_row_data()
                        if len(values) != len(fields):
                            raise ValueError(f"year {year}: row width differs from fields")
                        row = dict(zip(fields, values))
                        row["report_year_requested"] = str(year)
                        records.append(row)
                    if response.error_code != "0":
                        raise RuntimeError(f"year {year}: pagination {response.error_msg}")
                connection.send(("ok", {"records": records, "fields": all_fields}))
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


class DividendSession:
    def __init__(self, ipo_years: dict[str, int], end_year: int, timeout: float):
        self.ipo_years = ipo_years
        self.end_year = end_year
        self.timeout = timeout
        self.context = multiprocessing.get_context("spawn")
        self.process = None
        self.connection = None
        self._start()

    def _start(self):
        parent, child = self.context.Pipe()
        process = self.context.Process(target=_worker, args=(child,), daemon=True)
        process.start(); child.close()
        self.process, self.connection = process, parent
        if not parent.poll(max(30.0, self.timeout)):
            self._terminate(); raise TimeoutError("dividend worker startup timed out")
        status, detail = parent.recv()
        if status != "ready":
            self._terminate(); raise RuntimeError(f"dividend worker startup failed: {detail}")

    def _terminate(self):
        if self.connection is not None:
            self.connection.close(); self.connection = None
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate(); self.process.join(timeout=5)
                if self.process.is_alive():
                    self.process.kill(); self.process.join(timeout=5)
            self.process = None

    def __call__(self, code: str):
        import pandas as pd
        start = max(1990, self.ipo_years[code])
        self.connection.send((code, start, self.end_year))
        if not self.connection.poll(self.timeout):
            self._terminate(); self._start()
            raise TimeoutError(f"dividend request exceeded {self.timeout:.1f}s for {code}")
        status, payload = self.connection.recv()
        if status != "ok":
            raise RuntimeError(payload)
        if payload["records"]:
            return pd.DataFrame(payload["records"])
        return pd.DataFrame(columns=payload["fields"] + ["report_year_requested"])

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
    parser.add_argument("--end-year", type=int, default=date.today().year)
    parser.add_argument("--throttle", type=float, default=0.2)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--request-timeout", type=float, default=180.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--universe", default=None)
    args = parser.parse_args(argv)
    if not 1990 <= args.end_year <= date.today().year:
        raise ValueError("end-year is outside supported range")

    listed = coverage.listed_a_shares()
    if args.universe:
        requested = [x.strip() for x in Path(args.universe).read_text().splitlines()
                     if x.strip() and not x.startswith("#")]
        unknown = set(requested) - set(listed)
        if unknown:
            raise ValueError(f"explicit universe includes non-listed codes: {sorted(unknown)[:5]}")
        codes = requested
    else:
        codes = sorted(listed)
    ipo_years = {code: listed[code].year for code in codes}
    envelope = Envelope(args, name="baostock-dividend", source="baostock.query_dividend_data",
                        required_columns=REQUIRED)
    session = None
    try:
        if args.apply and not args.dry_run:
            session = DividendSession(ipo_years, args.end_year, args.request_timeout)
            fetch = session
        else:
            fetch = lambda _code: None
        return envelope.run(codes, fetch)
    finally:
        if session is not None:
            session.close()


if __name__ == "__main__":
    raise SystemExit(main_guard(main))

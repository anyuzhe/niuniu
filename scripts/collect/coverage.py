"""Read-only coverage primitives for incremental market-data collection.

No network access and no writes.  The archived trading calendar is the market-day
contract; listed A-shares come from the archived ``stock_basic`` snapshot.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

DATA_ROOT = Path("/Volumes/Lexar/niuniu-data")
LAKE = DATA_ROOT / "lake" / "bronze"
CALENDAR = LAKE / "provider=baostock" / "trade_calendar" / "calendar.parquet"
STOCK_BASIC = LAKE / "provider=baostock" / "stock_basic" / "stock_basic.parquet"

# Confirmed vendor-side limits. Dates before a floor are not retryable gaps.
VENDOR_FLOOR = {"baostock-min5": date(2020, 1, 2)}


def to_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


class TradingCalendar:
    """Archived market calendar; never fetches or extrapolates dates."""

    def __init__(self, path: Path = CALENDAR, pandas=None):
        if pandas is None:
            import pandas as pandas
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"missing archived trading calendar: {path}")
        frame = pandas.read_parquet(path)
        required = {"calendar_date", "is_trading_day"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"calendar missing columns {sorted(missing)}: {path}")
        mask = frame["is_trading_day"].astype(str).isin({"1", "1.0", "True", "true"})
        self.days = sorted({to_date(v) for v in frame.loc[mask, "calendar_date"]})
        if not self.days:
            raise ValueError(f"calendar has no trading days: {path}")
        self._set = set(self.days)
        self.first, self.last = self.days[0], self.days[-1]
        self.path = path

    def is_trading_day(self, day: date) -> bool:
        return day in self._set

    def between(self, start: date, end: date) -> list[date]:
        if start > end:
            return []
        return [d for d in self.days if start <= d <= end]

    def latest_on_or_before(self, day: date) -> date | None:
        if day < self.first:
            return None
        bounded = min(day, self.last)
        for candidate in reversed(self.days):
            if candidate <= bounded:
                return candidate
        return None

    def first_on_or_after(self, day: date) -> date | None:
        if day > self.last:
            return None
        bounded = max(day, self.first)
        for candidate in self.days:
            if candidate >= bounded:
                return candidate
        return None


def default_target_end(calendar: TradingCalendar, now: datetime | None = None,
                       availability_cutoff: time = time(18, 0)) -> date:
    """Last trading day whose bars should be available.

    On a trading day, today's data enters the target only after the configurable
    18:00 China-time availability cutoff. Before then, use the prior trading day.
    """
    if now is None:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
    today = now.date()
    if calendar.is_trading_day(today) and now.timetz().replace(tzinfo=None) < availability_cutoff:
        cutoff = today - timedelta(days=1)
    else:
        cutoff = today
    result = calendar.latest_on_or_before(cutoff)
    if result is None:
        raise ValueError(f"calendar does not cover target day {today}")
    return result


def listed_a_shares(path: Path = STOCK_BASIC, pandas=None) -> dict[str, date]:
    """Return listed A-share code -> IPO date. Delisted rows are excluded."""
    if pandas is None:
        import pandas as pandas
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"missing stock_basic snapshot: {path}")
    frame = pandas.read_parquet(path)
    required = {"code", "ipoDate", "type", "status"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"stock_basic missing columns {sorted(missing)}: {path}")
    frame = frame[(frame["type"].astype(str) == "1") &
                  (frame["status"].astype(str) == "1")]
    result: dict[str, date] = {}
    for row in frame[["code", "ipoDate"]].itertuples(index=False):
        code = str(row.code).strip()
        raw_ipo = str(row.ipoDate).strip()
        if not code or not raw_ipo or raw_ipo.lower() == "nan":
            continue
        result[code] = to_date(raw_ipo)
    return dict(sorted(result.items()))


def symbol_filename(code: str) -> str:
    return code.replace(".", "_", 1) + ".parquet"


def symbol_coverage(path: Path, date_col: str = "date", pandas=None) -> dict[str, Any]:
    """Read one symbol's actual date coverage; missing and empty stay distinct."""
    if pandas is None:
        import pandas as pandas
    path = Path(path)
    if not path.is_file():
        return {"present": False, "rows": 0, "min_date": None,
                "max_date": None, "days": set()}
    frame = pandas.read_parquet(path, columns=[date_col])
    if frame.empty:
        return {"present": True, "rows": 0, "min_date": None,
                "max_date": None, "days": set()}
    days = {to_date(v) for v in frame[date_col]}
    return {"present": True, "rows": int(len(frame)), "min_date": min(days),
            "max_date": max(days), "days": days}


def compute_gap(coverage: dict[str, Any], calendar: TradingCalendar, *,
                target_end: date, first_start: date,
                vendor_floor: date | None = None,
                include_interior: bool = False) -> dict[str, Any]:
    """Classify a symbol as full, tail, up_to_date or ahead.

    Tail refresh deliberately starts at the existing last date so a partial final
    day is replaced as a whole. Interior holes are reported only when requested;
    they may be suspensions and are never automatically fetched.
    """
    end = calendar.latest_on_or_before(target_end)
    if end is None:
        raise ValueError(f"target {target_end} predates calendar {calendar.first}")
    start_floor = max(first_start, vendor_floor or calendar.first, calendar.first)
    full_start = calendar.first_on_or_after(start_floor)
    if full_start is None or full_start > end:
        return {"action": "not_yet_listed", "fetch_start": None,
                "fetch_end": None, "n_trading_days": 0,
                "interior_missing": [], "known_vendor_limit": False}

    if not coverage["present"] or coverage["rows"] == 0:
        return {"action": "full", "fetch_start": full_start, "fetch_end": end,
                "n_trading_days": len(calendar.between(full_start, end)),
                "interior_missing": [],
                "known_vendor_limit": bool(vendor_floor and first_start < vendor_floor)}

    have_max = coverage["max_date"]
    interior: list[str] = []
    if include_interior and coverage.get("days"):
        lo = max(coverage["min_date"], vendor_floor or calendar.first)
        interior = [d.isoformat() for d in calendar.between(lo, have_max)
                    if d not in coverage["days"]]

    if have_max >= end:
        return {"action": "up_to_date" if have_max == end else "ahead",
                "fetch_start": None, "fetch_end": None, "n_trading_days": 0,
                "interior_missing": interior, "known_vendor_limit": False}

    tail_start = max(have_max, vendor_floor or have_max)
    tail_start = calendar.first_on_or_after(tail_start)
    return {"action": "tail", "fetch_start": tail_start, "fetch_end": end,
            "n_trading_days": len(calendar.between(tail_start, end)),
            "interior_missing": interior, "known_vendor_limit": False}

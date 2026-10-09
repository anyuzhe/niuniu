"""Duty scheduler: while niuniu is open, run the daily data jobs by themselves.

Started in the background by the two launchers (``--parent-pid`` = the niuniu process);
exits when niuniu exits.  Authorised by the user on 2026-09-29 for exactly two jobs:

* ``sector_recorder_start`` every trading day from 09:10 until 15:25 (same checks as
  ``autostart``: not twice, not after a manual stop; the recorder itself exits on a
  non-trading day);
* ``daily_close_early`` (user request 2026-10-09) from 15:11 until 16:30, once per trading day: the part of the
  close update that needs only TDX data (1-minute bars → daily and 5-minute bars synthesised from them →
  qfq → breadth).  It does not seal.  The TDX 1-minute collector refuses to run until 15:10 has passed.
* ``daily_close_update`` from 16:30 for every trading day after the latest sealed day (at
  most 7 days back) that is not sealed yet, oldest first, one at a time.  For today it also waits until
  Baostock has published today's daily bars (probed every 10 minutes), because day status, valuation and
  the fundamentals come from Baostock and the run seals the day.  It never starts while the early run is going.
  A day counts as a trading day only when the TDX server
  has a daily bar of the SSE Composite for it (so holidays the local calendar does not
  know yet are never updated).  A run that failed is not retried automatically on the
  same day; it shows in the data centre with its log.

Only one scheduler runs at a time (``catalog/jobs/scheduler.lock`` holds its pid).  Every
action is one JSON line on stdout (the launchers append it to ``artifacts/scheduler.log``).

    python scripts/collect/scheduler.py --parent-pid <pid> [--once]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

TZ = ZoneInfo("Asia/Shanghai")
RECORDER_FROM, RECORDER_UNTIL = "09:10", "15:25"
EARLY_UPDATE_AT = "15:11"      # the TDX 1-minute collector refuses to run through 15:10
CLOSE_UPDATE_AT = "16:30"
BAOSTOCK_PROBE_EVERY = 600     # seconds between looks at whether Baostock has published today
LOOKBACK_DAYS = 7


def log(**fields) -> None:
    print(json.dumps({"at": datetime.now(TZ).replace(microsecond=0).isoformat(), **fields}, ensure_ascii=False),
          flush=True)


def alive(pid) -> bool:
    if not pid:
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def take_lock(base: Path) -> bool:
    lock = base / "scheduler.lock"
    base.mkdir(parents=True, exist_ok=True)
    if lock.is_file():
        try:
            other = int(lock.read_text().strip())
        except ValueError:
            other = None
        if other and other != os.getpid() and alive(other):
            return False
    lock.write_text(str(os.getpid()))
    return True


class TradingDays:
    """Recent trading days confirmed by TDX daily bars of sh.000001 (one lookup per hour)."""

    def __init__(self, fetch=None):
        self.fetch = fetch or self._fetch
        self.key, self.days = None, set()

    @staticmethod
    def _fetch() -> set:
        from collect.tdx_minute import HOSTS, _load_pytdx
        API = _load_pytdx()
        for host, port in HOSTS:
            api = API(raise_exception=True)
            try:
                if not api.connect(host, port, time_out=8):
                    continue
                bars = api.get_index_bars(9, 1, "000001", 0, 20) or []
                api.disconnect()
                return {b["datetime"][:10] for b in bars if float(b.get("amount") or 0) > 1e6}
            except Exception:
                continue
        return set()

    def recent(self, now: datetime) -> set:
        key = now.strftime("%Y-%m-%d %H")
        if key != self.key:
            days = self.fetch()
            if days:
                self.key, self.days = key, days
        return self.days


def pending_days(jobs, data_root: Path, now: datetime, trading: TradingDays) -> list:
    today = now.date().isoformat()
    start = (now.date() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    sealed = sorted(p.stem for p in (data_root / "catalog/seals").glob("????-??-??.json"))
    if sealed and sealed[-1] >= start:
        start = max(start, sealed[-1])       # never go back behind the latest sealed day
    runs = [r for r in jobs._runs() if r["job_id"] == "daily_close_update"]
    out = []
    for day in sorted(d for d in trading.recent(now) if start <= d <= today):
        if day == today and now.strftime("%H:%M") < CLOSE_UPDATE_AT:
            continue
        if (data_root / "catalog/seals" / f"{day}.json").is_file():
            continue
        mine = [r for r in runs if (r.get("params") or {}).get("date") == day]
        if any(r["state"] in ("queued", "running", "succeeded") for r in mine):
            continue
        if any(r["state"] in ("failed", "interrupted", "cancelled") and str(r.get("created_at", ""))[:10] == today
               for r in mine):
            continue      # already tried today: leave it for the user
        out.append(day)
    return out


def baostock_ready(day: str) -> bool:
    """Has Baostock published ``day``'s daily bars yet?  Asked in a child process with a timeout, so a hung
    login cannot stall the duty loop (and Baostock's chatter stays off our log)."""
    import subprocess
    code = ("import sys,io,contextlib,baostock as bs\n"
            "ok=False\n"
            "with contextlib.redirect_stdout(io.StringIO()):\n"
            "    bs.login()\n"
            "    for c in ('sh.600000','sz.000001'):\n"
            "        rs=bs.query_history_k_data_plus(c,'date',start_date=sys.argv[1],end_date=sys.argv[1],"
            "frequency='d',adjustflag='3')\n"
            "        if rs.error_code=='0' and len(rs.get_data())>0:\n"
            "            ok=True\n"
            "            break\n"
            "    bs.logout()\n"
            "print('READY' if ok else 'NO')\n")
    try:
        out = subprocess.run([sys.executable, "-c", code, day], capture_output=True, text=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return out.returncode == 0 and out.stdout.strip().endswith("READY")


def early_update(jobs, data_root: Path, now: datetime, trading: TradingDays, memo: dict) -> None:
    """Start ``daily_close_early`` once for today, between EARLY_UPDATE_AT and CLOSE_UPDATE_AT."""
    today = now.date().isoformat()
    if memo.get("early") == today or today not in trading.recent(now):
        return
    if (data_root / "catalog/seals" / f"{today}.json").is_file():
        memo["early"] = today
        return
    for run in jobs._runs():       # a run of either job today, whatever its state, means this was handled
        if str(run.get("created_at", ""))[:10] != today:
            continue
        if run["job_id"] == "daily_close_early" or (
                run["job_id"] == "daily_close_update" and (run.get("params") or {}).get("date") == today):
            memo["early"] = today
            return
    if jobs._running({"daily_close_update", "daily_close_early"}):
        return
    plan = jobs.plan("daily_close_early", {"date": today})
    if plan["blocked_reason"]:
        log(job="daily_close_early", date=today, started=False, reason=plan["blocked_reason"])
        memo["early"] = today
        return
    run = jobs.run(plan["plan_id"], trigger="scheduler")
    log(job="daily_close_early", date=today, started=True, run_id=run["run_id"])
    memo["early"] = today


def tick(jobs, data_root: Path, now: datetime, trading: TradingDays, memo: dict, probe=None) -> None:
    hm = now.strftime("%H:%M")
    today = now.date().isoformat()
    if now.weekday() < 5 and EARLY_UPDATE_AT <= hm < CLOSE_UPDATE_AT:
        early_update(jobs, data_root, now, trading, memo)
    if now.weekday() < 5 and RECORDER_FROM <= hm < RECORDER_UNTIL and memo.get("recorder") != today:
        result = jobs.autostart("sector_recorder_start")
        log(job="sector_recorder_start", **{k: v for k, v in result.items() if k != "job_id"})
        reason = str(result.get("reason") or "")
        if result.get("started") or any(w in reason for w in ("今天", "正在运行", "不是交易日")):
            memo["recorder"] = today
    if hm >= CLOSE_UPDATE_AT or hm < "08:00":
        if jobs._running({"daily_close_update", "daily_close_early"}):
            return
        hour = now.strftime("%Y-%m-%d %H")
        if memo.get("close_idle") == hour:
            return
        days = pending_days(jobs, data_root, now, trading)
        if not days:
            memo["close_idle"] = hour
            return
        if days[0] == today and not memo.get("baostock_ready") == today:
            # status, valuation and fundamentals come from Baostock and the run seals the day: wait for its data
            if time.time() < memo.get("baostock_next", 0):
                return
            if (probe or baostock_ready)(today):
                memo["baostock_ready"] = today
            else:
                memo["baostock_next"] = time.time() + BAOSTOCK_PROBE_EVERY
                if memo.get("baostock_logged") != today:
                    log(job="daily_close_update", date=today, started=False, reason="等 Baostock 发布当天数据，每 10 分钟查一次")
                    memo["baostock_logged"] = today
                return
        plan = jobs.plan("daily_close_update", {"date": days[0]})
        if plan["blocked_reason"]:
            log(job="daily_close_update", date=days[0], started=False, reason=plan["blocked_reason"])
            memo["close_idle"] = hour
            return
        run = jobs.run(plan["plan_id"], trigger="scheduler")
        log(job="daily_close_update", date=days[0], started=True, run_id=run["run_id"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--parent-pid", type=int, default=None)
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    from quantlab.data.data_services import DataUpdateJobs
    jobs = DataUpdateJobs()
    if not take_lock(jobs.base):
        log(event="exit", reason="另一个值班程序已在运行")
        return 0
    log(event="start", parent_pid=args.parent_pid, pid=os.getpid())
    trading, memo = TradingDays(), {}
    try:
        while alive(args.parent_pid):
            try:
                tick(jobs, jobs.data_root, datetime.now(TZ), trading, memo)
            except Exception as error:   # keep going; the next minute tries again
                log(event="error", error=f"{type(error).__name__}: {error}"[:300])
            if args.once:
                break
            time.sleep(args.interval)
    finally:
        try:
            lock = jobs.base / "scheduler.lock"
            if lock.read_text().strip() == str(os.getpid()):
                lock.unlink()
        except OSError:
            pass
        log(event="exit", reason="结束" if alive(args.parent_pid) else "牛牛已关闭")
    return 0


if __name__ == "__main__":
    sys.exit(main())

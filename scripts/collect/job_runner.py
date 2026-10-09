"""Execute one approved data-center run in the background (spawned by DataUpdateJobs.run).

    python scripts/collect/job_runner.py --run-dir <data-root>/catalog/jobs/runs/<run_id>

The run directory holds ``plan.json`` (the plan the user confirmed), ``state.json``
(updated as the run goes) and ``log.txt``.  Steps call the existing collectors as
child processes with the same interpreter; the confirmed job plan is the approval,
so each collector's own plan SHA is generated and passed here.  SIGTERM (cancel)
stops the current child and marks the run ``cancelled``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(REPO / "src"))

TZ = ZoneInfo("Asia/Shanghai")
S1_EVIDENCE = REPO / "artifacts/data-governance-20260922-S1-rights19/evidence/rights-19-evidence.jsonl"
PROGRESS = re.compile(r"\[(\d+)/(\d+)\]")


def now() -> str:
    return datetime.now(TZ).replace(microsecond=0).isoformat()


class Cancelled(Exception):
    pass


class Runner:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
        self.data_root = Path(self.plan["data_root"])
        self.state_path = run_dir / "state.json"
        self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.log_file = (run_dir / "log.txt").open("a", encoding="utf-8")
        self.child = None
        self.cancelled = False
        self.deferred_errors: list[str] = []   # the remaining steps still run; the run ends as failed
        self.env = {**os.environ, "NIUNIU_DATA_ROOT": str(self.data_root), "PYTHONUNBUFFERED": "1",
                    "PYTHONPATH": os.pathsep.join([str(REPO / "src"), str(HERE.parent)])}
        signal.signal(signal.SIGTERM, self._on_term)

    # ------------------------------------------------------------ bookkeeping
    def _on_term(self, *_):
        self.cancelled = True
        if self.child and self.child.poll() is None:
            try:
                self.child.terminate()
            except OSError:
                pass

    def log(self, text: str) -> None:
        for line in str(text).splitlines() or [""]:
            self.log_file.write(f"{datetime.now(TZ).strftime('%H:%M:%S')} {line}\n")
        self.log_file.flush()

    def save(self, **fields) -> None:
        self.state.update(fields)
        tmp = self.state_path.with_name("state.json.tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, self.state_path)

    def check(self) -> None:
        if self.cancelled:
            raise Cancelled()

    def sh(self, args: list[str], *, step_share: tuple[float, float] | None = None, keep_awake: bool = False) -> str:
        """Run a child process, stream its output into the log, return the output."""
        self.check()
        cmd = [sys.executable, *args]
        if keep_awake and sys.platform == "darwin" and os.path.exists("/usr/bin/caffeinate"):
            cmd = ["/usr/bin/caffeinate", "-i", *cmd]   # keep the Mac awake for long runs
        self.log("$ " + " ".join(a if len(a) < 90 else a[:40] + "…" + a[-40:] for a in args))
        self.child = subprocess.Popen(cmd, cwd=str(REPO), env=self.env, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True, bufsize=1)
        lines = []
        for line in self.child.stdout:
            line = line.rstrip("\n")
            lines.append(line)
            self.log(line)
            match = PROGRESS.search(line)
            if match and step_share:
                done, total = int(match.group(1)), int(match.group(2))
                self.save(progress=round(step_share[0] + step_share[1] * done / max(total, 1), 4))
        code = self.child.wait()
        self.child = None
        self.check()
        if code != 0:
            raise RuntimeError(f"子任务退出码 {code}：{' '.join(args[:2])}")
        return "\n".join(lines)

    @staticmethod
    def last_json(output: str) -> dict:
        for line in reversed(output.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except ValueError:
                    continue
        return {}

    def result_dataset(self, dataset_id: str, **fields) -> None:
        rows = self.state.setdefault("result", {}).setdefault("datasets", [])
        entry = next((r for r in rows if r["dataset_id"] == dataset_id), None)
        if entry is None:
            entry = {"dataset_id": dataset_id, "through": None, "rows_written": 0, "files_written": 0, "failures": []}
            rows.append(entry)
        for key, value in fields.items():
            if key in ("rows_written", "files_written"):
                entry[key] += int(value or 0)
            elif key == "failures":
                entry[key].extend(value or [])
            else:
                entry[key] = value
        self.save()

    # ------------------------------------------------------------ step kinds
    def step_reference(self, step, share):
        day = step["dates"][0]
        dest = self.data_root / f"lake/bronze/provider=baostock/reference_snapshots/snapshot={day}"
        if (dest / "manifest.json").is_file():
            self.log(f"参考快照 {day} 已存在，跳过")
            return
        out = self.run_dir / "plans"
        out.mkdir(exist_ok=True)
        self.sh(["scripts/collect/daily_plan.py", "--date", day, "--out-dir", str(out)])
        ref = json.loads((out / "reference.json").read_text(encoding="utf-8"))
        self.sh(["scripts/collect/baostock_reference_snapshot.py", "--snapshot-date", day, "--dest", str(dest),
                 "--apply", "--approve-sha256", ref["plan_sha256"]], step_share=share)
        self.result_dataset("reference_snapshot_baostock", through=day, files_written=7)

    def step_public(self, step, share):
        for name, dataset_id, start, end in step["public"]:
            self.check()
            plan_path = self.run_dir / "plans" / f"public-{name}-{start or 'snap'}.json"
            plan_path.parent.mkdir(exist_ok=True)
            args = ["scripts/collect/public_sources.py", "--data-root", str(self.data_root), "plan", "--dataset", name,
                    "--out", str(plan_path), "--today", step["dates"][0], "--calendar-snapshot", step["calendar"]]
            if start:
                args += ["--start", start, "--end", end]
            info = self.last_json(self.sh(args))
            if not info.get("partitions"):
                self.log(f"{name}：没有需要采的分区，跳过")
                continue
            try:
                result = self.last_json(self.sh(["scripts/collect/public_sources.py", "--data-root", str(self.data_root),
                                                 "apply", "--plan", str(plan_path),
                                                 "--approve-sha256", info["plan_sha256"]]))
            except RuntimeError as error:
                result = {"failed": 1, "error": str(error)}
            self.result_dataset(dataset_id, through=end or step["dates"][0], files_written=result.get("ok", 0),
                                failures=[f"{name}: {result.get('failed')} 个分区失败"] if result.get("failed") else [])

    def step_constituents(self, step, share):
        from collect.sector_constituents import run as snapshot
        for _ in range(6):
            self.check()
            try:
                result = snapshot(self.data_root, max_seconds=300)
            except Exception as error:  # boards keep yesterday's counts; bars, qfq and the seal still run
                self.log(f"成分快照失败：{type(error).__name__}: {error}")
                self.result_dataset("sector_board_constituents",
                                    failures=[f"成分快照失败：{type(error).__name__}: {error}"[:200]])
                return
            self.log(json.dumps({k: v for k, v in result.items() if k != "empty_boards"}, ensure_ascii=False))
            if result.get("complete") or result.get("status") == "already_complete":
                self.result_dataset("sector_board_constituents", through=step["dates"][0],
                                    rows_written=result.get("rows", 0), files_written=1 if result.get("rows") else 0)
                return
        self.result_dataset("sector_board_constituents", failures=["成分快照 6 轮后仍未完成"])

    def step_bars(self, step, share):
        day = step["dates"][0]
        plans = self.run_dir / "plans"
        plans.mkdir(exist_ok=True)
        receipts = REPO / "artifacts/collection-receipts"
        receipts.mkdir(parents=True, exist_ok=True)
        third = share[1] / 3
        # daily status
        # The plan is rebuilt from what is already on disk, so a retry only redoes the
        # symbols still missing. Baostock stalls now and then; retry twice after a pause.
        for attempt in range(3):
            info = self.last_json(self.sh(["scripts/collect/status_incremental.py", "--target-end", day,
                                           "--plan-output", str(plans / "status.json")]))
            if not info.get("actions"):
                break
            try:
                self.sh(["scripts/collect/status_incremental.py", "--plan", str(plans / "status.json"), "--apply",
                         "--approve-sha256", info["plan_sha256"]], step_share=(share[0], third))
                break
            except RuntimeError as exc:
                if attempt == 2:
                    raise
                self.log(f"日状态第 {attempt + 1} 次失败（{exc}），120 秒后重新规划并续跑")
                time.sleep(120)
        self.result_dataset("security_status_baostock_v2", through=day, files_written=info.get("actions", 0))
        # 日K优先由通达信 1 分钟线合成（全市场不到 1 分钟，对账与 Baostock 一致）；合成不了的（新股、停牌后复牌、
        # 1 分钟线缺根）留给下面的 Baostock 补缺，只取这些
        try:
            made = self.last_json(self.sh(["scripts/collect/daily_from_min1.py", "apply", "--day", day]))
            self.log(f"日K由 1 分钟线合成：{made.get('derived', 0)} 只；未合成 {made.get('status', {})}")
        except RuntimeError as exc:
            self.log(f"1 分钟线合成日K失败（{exc}），改由 Baostock 全部补取")
        # 5 分钟线同样由 1 分钟线合成（精度略低于日K，见 daily_from_min1.py 的说明），Baostock 只补合成不了的
        try:
            made = self.last_json(self.sh(["scripts/collect/daily_from_min1.py", "apply", "--kind", "min5", "--day", day]))
            self.log(f"5 分钟线由 1 分钟线合成：{made.get('derived', 0)} 只；未合成 {made.get('status', {})}")
        except RuntimeError as exc:
            self.log(f"1 分钟线合成 5 分钟线失败（{exc}），改由 Baostock 全部补取")
        for index, (dataset, dataset_id) in enumerate((("baostock-daily", "bars_daily_baostock_raw"),
                                                       ("baostock-min5", "bars_min5_baostock_raw")), start=1):
            path = plans / f"{dataset}.json"
            self.sh(["scripts/collect/scan_gaps.py", "--dataset", dataset, "--target-end", day, "--json", str(path),
                     "--show", "0"])
            body = json.loads(path.read_text(encoding="utf-8"))
            if body.get("actions"):
                self.sh(["scripts/collect/bars_incremental.py", "--plan", str(path), "--apply",
                         "--approve-sha256", body["plan_sha256"],
                         "--receipt", str(receipts / f"{self.state['run_id']}-{dataset}.json")],
                        step_share=(share[0] + third * index, third), keep_awake=True)
            self.result_dataset(dataset_id, through=day, files_written=len(body.get("actions", [])))

    def step_qfq(self, step, share):
        plans = self.run_dir / "plans"
        plans.mkdir(exist_ok=True)
        info = self.last_json(self.sh(["scripts/derive/build_qfq.py", "plan", "--s1-evidence", str(S1_EVIDENCE),
                                       "--tdx-snapshot", str(plans / "qfq-tdx-snapshot.parquet"),
                                       "--out", str(plans / "qfq-plan.json")]))
        sha = info["plan_sha256"]
        for mode, label in (("apply", "日线"), ("apply-min5", "5 分钟")):
            result = {}
            for _ in range(200):
                result = self.last_json(self.sh(["scripts/derive/build_qfq.py", mode, "--plan", str(plans / "qfq-plan.json"),
                                                 "--approve-sha256", sha, "--max-seconds", "600"]))
                if result.get("complete"):
                    break
            if not result.get("complete"):
                message = (f"前复权{label}没有完成：{result.get('total_done', '?')}/{result.get('codes', '?')} 只，"
                           "下次同一计划会接着做")
                self.log(message)
                self.result_dataset("qfq_published_f24", failures=[message])
                self.deferred_errors.append(message)
                return
        self.sh(["scripts/derive/build_qfq.py", "coverage", "--plan", str(plans / "qfq-plan.json")])
        self.result_dataset("qfq_published_f24", through=step["dates"][0], files_written=info.get("codes", 0))

    def step_tdx_minute(self, step, share):
        # 这一步排在日K之前（日K由它合成）：失败只记下来，日K改走 Baostock，后面的步骤照常
        try:
            plan = self.last_json(self.sh(["scripts/collect/tdx_minute.py", "plan", "--mode", "daily"]))
            output = self.sh(["scripts/collect/tdx_minute.py", "apply", "--plan", plan["plan"], "--approve", plan["sha256"],
                              "--max-seconds", "7200"], step_share=share, keep_awake=True)
            info = self.last_json(output)
        except RuntimeError as exc:
            message = f"通达信 1 分钟线更新失败：{exc}"
            self.log(message)
            self.result_dataset("tdx_kline_min1", failures=[message])
            self.deferred_errors.append(message)
            return
        for dataset_id in ("tdx_kline_min1", "tdx_index_kline_min1", "tdx_index_kline_min5"):
            self.result_dataset(dataset_id, through=step["dates"][0], files_written=info.get("done", 0) if dataset_id == "tdx_kline_min1" else 6)

    def step_bars_early(self, step, share):
        # 快速更新：只用通达信 1 分钟线合成，失败就让这次运行记为失败（不回退到 Baostock，那是完整更新的事）
        day = step["dates"][0]
        for kind, label, dataset_id in (("daily", "日K", "bars_daily_baostock_raw"),
                                        ("min5", "5 分钟线", "bars_min5_baostock_raw")):
            args = ["scripts/collect/daily_from_min1.py", "apply", "--day", day]
            if kind == "min5":
                args += ["--kind", "min5"]
            made = self.last_json(self.sh(args))
            self.log(f"{label}由 1 分钟线合成：{made.get('derived', 0)} 只；未合成 {made.get('status', {})}")
            self.result_dataset(dataset_id, through=day, files_written=made.get("derived", 0))

    def step_breadth(self, step, share):
        from datetime import date, timedelta
        start = (date.fromisoformat(step["dates"][0]) - timedelta(days=3)).isoformat()
        for source, dataset_id in (("tdx_min1", "market_intraday_breadth"), ("baostock_min5", "market_intraday_breadth_5m")):
            info = self.last_json(self.sh(["scripts/derive/market_breadth.py", "build", "--source", source, "--from", start]))
            self.result_dataset(dataset_id, through=step["dates"][0], files_written=len(info.get("files", [])) or 1)

    def step_etf_daily(self, step, share):
        self.sh(["scripts/collect/etf_nav.py"])
        self.result_dataset("etf_nav_daily", through=step["dates"][0], files_written=1)
        self.sh(["scripts/derive/event_calendar.py"])
        self.result_dataset("event_calendar", through=step["dates"][0], files_written=1)

    FUNDAMENTALS = (("pledge", "equity_pledge_history"), ("forecast", "earnings_forecast_history"),
                    ("fin_cpd", "financial_cpd"), ("fin_balance", "financial_balance"),
                    ("fin_cashflow", "financial_cashflow"), ("shares", "share_capital"),
                    ("valuation", "valuation_daily_v1"))

    def step_fundamentals(self, step, share):
        """Incremental refresh of the fundamentals history (catalog 3.9). One dataset failing does not
        stop the others; the failure is recorded and the next daily run repairs it (updates are idempotent)."""
        day = step["dates"][0]
        for name, dataset_id in self.FUNDAMENTALS:
            self.check()
            try:
                output = self.sh(["scripts/collect/fundamentals_history.py", "update", "--dataset", name,
                                  "--through", day], keep_awake=True)
                info = self.last_json(output)
                self.result_dataset(dataset_id, through=day, files_written=info.get("done", 0))
            except RuntimeError as exc:
                message = f"基本面 {dataset_id} 更新失败：{exc}"
                self.log(message)
                self.result_dataset(dataset_id, failures=[message])
                self.deferred_errors.append(message)

    MACRO = ("etf_shares_sse", "etf_shares_szse", "cn_yield_curve", "cn_repo_fixing", "cn_lpr_history",
             "cn_macro_monthly", "cn_social_financing", "index_valuation_csindex")

    def step_macro(self, step, share):
        """ETF shares, rates, macro series and index valuation (catalog 3.10).  Same contract as
        step_fundamentals: one dataset failing is recorded and the rest still run."""
        day = step["dates"][0]
        for dataset_id in self.MACRO:
            self.check()
            try:
                output = self.sh(["scripts/collect/macro_rates.py", "update", "--dataset", dataset_id,
                                  "--through", day, "--max-seconds", "900"], keep_awake=True)
                info = self.last_json(output).get("datasets", {}).get(dataset_id, {})
                self.result_dataset(dataset_id, through=day, files_written=info.get("done", 0))
            except RuntimeError as exc:
                message = f"宏观利率 {dataset_id} 更新失败：{exc}"
                self.log(message)
                self.result_dataset(dataset_id, failures=[message])
                self.deferred_errors.append(message)

    def step_seal(self, step, share):
        from quantlab.data import day_seals
        for position, day in enumerate(step["dates"]):
            self.check()
            if position < len(step["dates"]) - 1 and day_seals.load_manifest(self.data_root, day) is None:
                self.log(f"{day} 没有封存记录，不补封")
                continue
            manifest = day_seals.seal(self.data_root, day, trading_day=step.get("trading_day", True), log=self.log)
            day_seals.verify(self.data_root, day, log=self.log)
            self.state.setdefault("result", {})["seal"] = {"date": day, "manifest": f"catalog/seals/{day}.json",
                                                           "revision": manifest["revision"],
                                                           "pending": [p["dataset_id"] for p in manifest["pending"]]}
            self.save()

    def step_verify(self, step, share):
        from quantlab.data import day_seals
        checks = []
        for day in step["dates"]:
            self.check()
            result = day_seals.verify(self.data_root, day, log=self.log)
            checks.append({"date": day, "verify_status": result["verify_status"], "problems": result["problems"]})
        self.state.setdefault("result", {})["verify"] = checks
        self.save()

    def step_revoke(self, step, share):
        from quantlab.data import day_seals
        record = day_seals.revoke(self.data_root, step["dates"][0], step["note"], log=self.log)
        self.state.setdefault("result", {})["revoke"] = record
        self.save()

    def step_recorder(self, step, share):
        self.sh(["scripts/collect/sector_intraday_recorder.py", "--data-root", str(self.data_root)], keep_awake=True)

    def step_stop(self, step, share):
        from quantlab.data.data_services import runner_alive, signal_runner
        target = self.data_root / "catalog/jobs/runs" / step["target_run"] / "state.json"
        state = json.loads(target.read_text(encoding="utf-8"))
        if not signal_runner(target.parent, state):
            self.log(f"运行 {step['target_run']} 已不在，不需要停止")
            return
        for _ in range(30):
            state = json.loads(target.read_text(encoding="utf-8"))
            if state.get("state") not in ("queued", "running") or not runner_alive(target.parent, state):
                break
            time.sleep(1)
        self.log(f"已停止运行 {step['target_run']}")

    def step_status_index(self, step, share):
        from quantlab.data.data_services import refresh_status_index
        refresh_status_index(self.data_root, log=self.log)

    # ------------------------------------------------------------ main loop
    def hold_lock(self) -> None:
        """Hold runner.lock for the whole life of this process: readers take a free lock to mean the
        runner is gone, which stays true even when the system later reuses this pid."""
        from quantlab.data.data_services import RUNNER_LOCK
        self.lock_handle = (self.run_dir / RUNNER_LOCK).open("a+")
        try:
            import fcntl
        except ImportError:
            return
        fcntl.flock(self.lock_handle, fcntl.LOCK_EX)

    def run(self) -> int:
        steps = self.plan["steps"]
        weights = [max(1.0, float(s.get("weight", 1))) for s in steps]
        total = sum(weights)
        self.hold_lock()
        current = json.loads(self.state_path.read_text(encoding="utf-8"))
        if current.get("state") not in ("queued", "running"):  # cancelled before this process got going
            self.log(f"运行已是 {current.get('state')}，不再执行")
            return 1
        self.save(state="running", pid=os.getpid(), started_at=now(), progress=0.0)
        self.log(f"开始 {self.plan['job_id']}，计划 {self.plan['plan_id'][:12]}")
        done = 0.0
        try:
            for step, weight in zip(steps, weights):
                self.check()
                share = (done / total, weight / total)
                self.save(step=step["name"], progress=round(done / total, 4))
                if step["action"] == "skip_existing":
                    self.log(f"跳过：{step['name']}（{step.get('note') or '已有'}）")
                else:
                    self.log(f"== {step['name']}")
                    getattr(self, "step_" + step["kind"])(step, share)
                done += weight
            if self.deferred_errors:
                self.save(state="failed", progress=1.0, finished_at=now(), step=None,
                          error="；".join(self.deferred_errors)[:500])
                self.log("结束，但有未完成的步骤：" + "；".join(self.deferred_errors))
                return 1
            self.save(state="succeeded", progress=1.0, finished_at=now(), step=None)
            self.log("完成")
            return 0
        except Cancelled:
            self.save(state="cancelled", finished_at=now())
            self.log("已取消")
            return 1
        except Exception as error:
            self.log(traceback.format_exc())
            self.save(state="failed", finished_at=now(), error=f"{type(error).__name__}: {error}"[:500])
            return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args(argv)
    return Runner(Path(args.run_dir)).run()


if __name__ == "__main__":
    sys.exit(main())

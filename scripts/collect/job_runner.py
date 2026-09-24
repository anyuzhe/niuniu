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
            result = snapshot(self.data_root, max_seconds=300)
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
        info = self.last_json(self.sh(["scripts/collect/status_incremental.py", "--target-end", day,
                                       "--plan-output", str(plans / "status.json")]))
        if info.get("actions"):
            self.sh(["scripts/collect/status_incremental.py", "--plan", str(plans / "status.json"), "--apply",
                     "--approve-sha256", info["plan_sha256"]], step_share=(share[0], third))
        self.result_dataset("security_status_baostock_v2", through=day, files_written=info.get("actions", 0))
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
        for mode in ("apply", "apply-min5"):
            for _ in range(200):
                result = self.last_json(self.sh(["scripts/derive/build_qfq.py", mode, "--plan", str(plans / "qfq-plan.json"),
                                                 "--approve-sha256", sha, "--max-seconds", "600"]))
                if result.get("complete"):
                    break
        self.sh(["scripts/derive/build_qfq.py", "coverage", "--plan", str(plans / "qfq-plan.json")])
        self.result_dataset("qfq_published_f24", through=step["dates"][0], files_written=info.get("codes", 0))

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
        target = self.data_root / "catalog/jobs/runs" / step["target_run"] / "state.json"
        state = json.loads(target.read_text(encoding="utf-8"))
        pid = state.get("pid")
        if pid:
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            if json.loads(target.read_text(encoding="utf-8")).get("state") != "running":
                break
            time.sleep(1)
        self.log(f"已停止运行 {step['target_run']}")

    def step_status_index(self, step, share):
        from quantlab.data.data_services import refresh_status_index
        refresh_status_index(self.data_root, log=self.log)

    # ------------------------------------------------------------ main loop
    def run(self) -> int:
        steps = self.plan["steps"]
        weights = [max(1.0, float(s.get("weight", 1))) for s in steps]
        total = sum(weights)
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

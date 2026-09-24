"""Start the jobs the user authorised to run whenever niuniu opens (called by the launchers).

Returns immediately: the job itself runs in its own background process.  Prints one
JSON line (started / reason) that the launcher appends to artifacts/autostart.log.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def main() -> int:
    from quantlab.data.data_services import DataUpdateJobs
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0).isoformat()
    jobs = DataUpdateJobs()
    for job_id in jobs.AUTOSTART:
        try:
            result = jobs.autostart(job_id)
        except Exception as error:  # never block the app from opening
            result = {"started": False, "job_id": job_id, "reason": f"{type(error).__name__}: {error}"[:200]}
        print(json.dumps({"at": stamp, **result}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

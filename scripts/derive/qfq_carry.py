"""前复权沿用：把上一份已做完的前复权计划里“输入完全没变”的股票结果带进新计划的回执，新计划只重算有变化的股票。

收盘后快速更新已经用通达信 1 分钟线合成了当天日K、重建过一遍前复权；完整更新随后用 Baostock 补十几只合成不了的股票，
`build_qfq.py plan` 把每只股票每个输入文件的 SHA-256 都写进计划，于是这十几只股票一变，整份计划的 SHA 就变，
`apply` / `apply-min5` 又从头重做 5,224 只（约 2 小时），而其余 5,200 多只的输入其实一字节没变。

本脚本不改 build_qfq.py（它自己的 SHA 写在计划里，改了会让所有已有计划作废），只做一件事：在新计划批准之后、
`apply` 之前，把旧计划回执里能证明“和重算结果一定相同”的条目复制进新计划的回执。条件（任何一条不满足就一只都不沿用）：

  * 旧、新计划的 builder / registry / S1 证据 / 通达信除权快照 / 策略 / 输出目录 / 数据根完全一致；
  * 旧计划自己的 SHA 校验通过；
  * 这只股票在旧、新计划里 5 类输入文件（日K、同花顺、Baostock、东财、巨潮）的 SHA 都相同；
  * 磁盘上它的因子文件、前复权日线文件的 SHA 仍等于旧回执记下的值（没被别人改过）。

5 分钟前复权条目还要再满足：旧 5 分钟回执里有它，原始 5 分钟文件现在的 SHA 等于回执记下的 raw_min5_sha256，
前复权 5 分钟文件的 SHA 等于回执记下的 min5_sha256。

用法（和 build_qfq.py 一样要带新计划的批准 SHA）：
  python scripts/derive/qfq_carry.py --plan NEW.json --from OLD.json --approve-sha256 <NEW 的 plan_sha256>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from derive import build_qfq as bq  # noqa: E402

INPUT_KEYS = ("raw_daily", "ths", "baostock", "eastmoney", "cninfo")
SAME_FIELDS = ("format", "policy", "data_root", "builder_sha256", "registry_sha256", "outputs")


def _same_basis(old: dict, new: dict) -> str | None:
    """旧、新计划的前提不一致就返回原因，一致返回 None。"""
    for field in SAME_FIELDS:
        if old.get(field) != new.get(field):
            return f"{field} 不同"
    if old["s1_evidence"]["sha256"] != new["s1_evidence"]["sha256"]:
        return "S1 证据不同"
    if old["tdx_snapshot"]["sha256"] != new["tdx_snapshot"]["sha256"]:
        return "通达信除权快照不同"
    body = {k: v for k, v in old.items() if k != "plan_sha256"}
    if hashlib.sha256(bq.canonical(body)).hexdigest() != old["plan_sha256"]:
        return "旧计划内容与它的 SHA 不符"
    return None


def _file_sha(path: Path):
    return bq.sha256_file(path) if path.is_file() else None


def carry(new: dict, old: dict, approve: str) -> dict:
    bq._check(new, approve)
    if new["plan_sha256"] == old["plan_sha256"]:
        return {"carried_daily": 0, "carried_min5": 0, "reason": "同一份计划，不需要沿用"}
    reason = _same_basis(old, new)
    if reason:
        return {"carried_daily": 0, "carried_min5": 0, "reason": reason}
    data_root = Path(new["data_root"])
    old_daily_path = bq._receipt_path(data_root, old, "daily")
    if not old_daily_path.is_file():
        return {"carried_daily": 0, "carried_min5": 0, "reason": "旧计划没有日线回执"}
    old_daily = bq._load_receipt(old_daily_path, old)
    old_min5_path = bq._receipt_path(data_root, old, "min5")
    old_min5 = bq._load_receipt(old_min5_path, old)["results"] if old_min5_path.is_file() else {}

    new_daily_path = bq._receipt_path(data_root, new, "daily")
    new_min5_path = bq._receipt_path(data_root, new, "min5")
    new_daily = bq._load_receipt(new_daily_path, new)
    new_min5 = bq._load_receipt(new_min5_path, new)
    dirs = bq.dataset_dirs(data_root)
    carried_daily = carried_min5 = 0
    changed: list[str] = []
    for code in new["codes"]:
        if code in new_daily["results"]:
            continue                                   # 已经做过（接着上次的进度），不动
        entry = old_daily["results"].get(code)
        same = entry is not None and all(
            old["inputs"][k]["files"].get(code) == new["inputs"][k]["files"].get(code) for k in INPUT_KEYS)
        if not same:
            changed.append(code)
            continue
        name = bq.symbol_file(code)
        want_factors = entry.get("factors_sha256")
        want_daily = entry.get("daily_sha256")
        if _file_sha(data_root / bq.OUT["factors"] / name) != want_factors:
            changed.append(code)
            continue
        if _file_sha(data_root / bq.OUT["daily"] / name) != want_daily:
            changed.append(code)
            continue
        new_daily["results"][code] = entry
        carried_daily += 1
        m5 = old_min5.get(code)
        if m5 is None or code in new_min5["results"]:
            continue
        if _file_sha(dirs["raw_min5"] / name) != m5.get("raw_min5_sha256"):
            continue
        if m5.get("min5_sha256") != _file_sha(data_root / bq.OUT["min5"] / name):
            continue
        new_min5["results"][code] = m5
        carried_min5 += 1
    bq._save_receipt(new_daily_path, new_daily)
    bq._save_receipt(new_min5_path, new_min5)
    return {"carried_daily": carried_daily, "carried_min5": carried_min5, "to_rebuild": len(changed),
            "changed_sample": changed[:20], "codes": len(new["codes"]), "reason": None}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan", required=True, help="新计划")
    parser.add_argument("--from", dest="old", required=True, help="上一份已做完的计划")
    parser.add_argument("--approve-sha256", required=True)
    args = parser.parse_args(argv)
    new = json.loads(Path(args.plan).read_text())
    old = json.loads(Path(args.old).read_text())
    print(json.dumps(carry(new, old, args.approve_sha256), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

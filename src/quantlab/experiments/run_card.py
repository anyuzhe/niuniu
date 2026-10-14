"""Read-only run card: one compact, checkable summary of a saved experiment record.

Every number on the card is copied from the record and carries the path it came from, so a reader
(or ``verify_run_card``) can confirm it; nothing is recomputed or rounded. Flags are derived only from
fields that are present. A card describes what the record says, not whether the result is true.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from quantlab.storage.codec import digest, encode

SCHEMA = "niuniu-run-card-v1"
RESEARCH_METRICS = ("observations", "eligible_bars", "ic", "icir", "rank_ic", "rank_icir", "long_short_spread")
EXECUTION_METRICS = ("net_return", "max_drawdown", "final_equity", "initial_cash", "sharpe", "annualized_return",
                     "annualized_volatility", "performance_days", "fills", "rejections", "commission", "sell_tax", "slippage_cost")
SMALL_UNIVERSE = 30


def _lookup(record, path: str):
    node = record
    for part in path.split("."):
        node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            return None
    return node


def _scalar(value) -> bool:
    return value is not None and not isinstance(value, (dict, list, bool)) and isinstance(value, (int, float, str))


def _headline(record) -> list[dict]:
    rows, kind = [], record.get("kind")

    def take(path):
        value = _lookup(record, path)
        if _scalar(value):
            rows.append({"name": path, "value": value, "source": path})

    if kind is None:
        for horizon in sorted(record.get("metrics", {}), key=lambda h: int(h) if str(h).isdigit() else 10 ** 9):
            for name in RESEARCH_METRICS:
                take(f"metrics.{horizon}.{name}")
            permutation = record["metrics"][horizon].get("permutation") or {}
            for metric, test in permutation.items():
                if isinstance(test, dict) and _scalar(test.get("p_value")):
                    rows.append({"name": f"metrics.{horizon}.permutation.{metric}.p_value", "value": test["p_value"],
                                 "source": f"metrics.{horizon}.permutation.{metric}.p_value"})
    elif kind == "execution":
        for name in EXECUTION_METRICS:
            take(f"execution.{name}")
    for name in ("children", "periods", "folds", "evaluations", "comparisons"):
        if isinstance(record.get(name), list):
            rows.append({"name": f"{name}.count", "value": len(record[name]), "source": f"{name}(length)"})
    return rows


def _data(manifest) -> dict:
    snapshot = manifest.get("data_snapshot") or {}
    files = snapshot.get("files") or []
    hashes = sorted(f.get("sha256", "") for f in files if isinstance(f, dict))
    universe = manifest.get("universe") or {}
    return {"adjustment": snapshot.get("adjustment"), "file_count": len(files),
            "total_bytes": sum(f.get("bytes", 0) for f in files if isinstance(f, dict)),
            "files_digest": hashlib.sha256("\n".join(hashes).encode()).hexdigest() if hashes else None,
            "universe_id": universe.get("id"), "universe_mask_hash": universe.get("mask_hash"),
            "window": (manifest.get("config") or {}).get("data")}


def _flags(record, data) -> list[dict]:
    flags = []

    def flag(code, severity, detail, source):
        flags.append({"code": code, "severity": severity, "detail": detail, "source": source})

    kind, manifest = record.get("kind"), record.get("manifest") or {}
    if record.get("status") != "completed":
        flag("NOT_COMPLETED", "high", f"status={record.get('status')}; {record.get('error', '')}".strip("; "), "status")
    if not manifest.get("runtime"):
        flag("NO_RUNTIME_FINGERPRINT", "medium", "record has no code hash / dependency versions", "manifest.runtime")
    if str(data["universe_id"] or "").startswith("explicit_symbols"):
        flag("NON_PIT_UNIVERSE", "medium", "explicit symbol list, not a point-in-time tradable universe", "manifest.universe.id")
    if data["file_count"] and data["file_count"] < SMALL_UNIVERSE:
        flag("SMALL_UNIVERSE", "medium", f"only {data['file_count']} data files (<{SMALL_UNIVERSE})", "manifest.data_snapshot.files")
    if kind is None and record.get("status") == "completed":
        if not any((m.get("permutation") or {}) for m in (record.get("metrics") or {}).values() if isinstance(m, dict)):
            flag("NO_SIGNIFICANCE_TEST", "medium", "no permutation test was run for this experiment", "metrics.*.permutation")
    if kind == "execution" and record.get("status") == "completed":
        if _lookup(record, "execution.fills") == 0:
            flag("NO_FILLS", "high", "the simulation produced no fills; returns are not informative", "execution.fills")
        if data["adjustment"] == "raw":
            flag("RAW_PRICES", "info", "raw prices: dividends/splits are not handled", "manifest.data_snapshot.adjustment")
    return flags


def build_run_card(record: dict, *, source_sha256: str | None = None) -> dict:
    manifest = record.get("manifest") or {}
    runtime = manifest.get("runtime") or {}
    data = _data(manifest)
    card = {
        "schema": SCHEMA,
        "identity": {"run_id": record.get("run_id"), "experiment_id": record.get("experiment_id"),
                     "kind": record.get("kind") or "research", "status": record.get("status"),
                     "created_at": record.get("created_at"), "source_sha256": source_sha256},
        "code": {"code_hash": runtime.get("code_hash"), "python": runtime.get("python"), "dependencies": runtime.get("dependencies"),
                 "factor": manifest.get("factor"), "factor_code_hash": manifest.get("factor_code_hash"),
                 "backend": manifest.get("backend"), "backend_version": manifest.get("backend_version")},
        "config_digest": digest(manifest.get("config")) if manifest.get("config") is not None else None,
        "data": data,
        "headline": _headline(record),
        "flags": _flags(record, data),
        "limitations": [*record.get("limitations", []), *(record.get("cost_model_warnings") or [])],
    }
    card["card_id"] = digest(card)
    card["generated_at"] = datetime.now(timezone.utc).isoformat()
    return card


def verify_run_card(card: dict, record: dict) -> list[str]:
    """Return problems: every headline value must still equal the record at its cited path."""
    problems = []
    for row in card["headline"]:
        source = row["source"]
        if source.endswith("(length)"):
            actual = len(record.get(source[:-8], []))
        else:
            actual = _lookup(record, source)
        if actual != row["value"]:
            problems.append(f"{source}: card {row['value']!r} != record {actual!r}")
    if card["card_id"] != digest({k: v for k, v in card.items() if k not in ("card_id", "generated_at")}):
        problems.append("card_id does not match card content")
    return problems


def render_markdown(card: dict) -> str:
    ident, data, code = card["identity"], card["data"], card["code"]
    lines = [f"# Run card · {ident['kind']} · {str(ident['run_id'])[:8]}", "",
             f"- 状态：{ident['status']}；创建：{ident['created_at']}；卡片 {card['card_id'][:12]}",
             f"- 代码：{(code['code_hash'] or '无')[:12]}；Python {code['python'] or '?'}"
             + (f"；因子 {code['factor']}" if code.get("factor") else "") + (f"；后端 {code['backend']}" if code.get("backend") else ""),
             f"- 配置摘要：{(card['config_digest'] or '无')[:12]}",
             f"- 数据：复权 {data['adjustment']}；{data['file_count']} 个文件 / {data['total_bytes']} 字节；文件摘要 {(data['files_digest'] or '无')[:12]}；股票池 {data['universe_id']}", ""]
    lines += ["## 标记", ""] + ([f"- **{f['severity']}** {f['code']}：{f['detail']}（{f['source']}）" for f in card["flags"]] or ["- 无"])
    lines += ["", "## 数字（逐项引用记录中的路径）", ""] + [f"- `{h['source']}` = {h['value']}" for h in card["headline"]]
    if card["limitations"]:
        lines += ["", "## 记录自带的限制", ""] + [f"- {text}" for text in card["limitations"]]
    lines += ["", "卡片只复述记录里有的内容，不证明结果为真；不含重新计算。"]
    return "\n".join(lines) + "\n"


def write_run_card(experiment_json: str | Path, destination: str | Path) -> dict:
    """Write run_card.json / run_card.md under ``destination`` (never into the artifact folder itself)."""
    source = Path(experiment_json)
    destination = Path(destination)
    if destination.resolve() == source.resolve().parent:
        raise ValueError("write the card outside the experiment artifact folder")
    raw = source.read_bytes()
    record = json.loads(raw)
    card = build_run_card(record, source_sha256=hashlib.sha256(raw).hexdigest())
    problems = verify_run_card(card, record)
    if problems:
        raise ValueError("run card failed self-check: " + "; ".join(problems[:3]))
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "run_card.json").write_text(encode(card), encoding="utf-8")
    (destination / "run_card.md").write_text(render_markdown(card), encoding="utf-8")
    return card

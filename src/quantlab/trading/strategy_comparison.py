"""Read-only, descriptive comparison of strategy packages and execution archives.

No function in this module executes a strategy, reads a market data root, writes
an artifact, ranks alternatives, or infers Alpha.  Historical run comparison is
based only on immutable bytes inside the two requested local UUID archives.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import UUID
import math

import polars as pl

from quantlab.storage.artifact_integrity import file_hash, snapshot_tree
from quantlab.storage.codec import digest, encode
from quantlab.storage.experiments import load_record_fields
from quantlab.trading.strategy_package import compile_strategy, validate_strategy_envelope_spec


FORMAT = "niuniu-strategy-run-comparison-v1"
SCOPE = "DESCRIPTIVE_ONLY"
_IDENTITY_FIELDS = ("strategy_key", "name", "version")
_PARENT_FILES = ("experiment.json", "bars.parquet", "targets.parquet", "observations.parquet")
_CHILD_FILES = ("experiment.json", "bars.parquet", "observations.parquet")
_METRICS = (
    "initial_cash", "final_equity", "net_return", "max_drawdown", "fills", "rejections",
    "commission", "sell_tax", "transfer_fee", "slippage_cost", "sharpe",
    "annualized_volatility", "annualized_return", "performance_days",
)
_ALLOWED_EXECUTION_VARIABLES = {"top_n", "threshold", "exposure"}
_PARENT_FIELDS = {
    "run_id", "experiment_id", "status", "kind", "manifest", "children", "execution",
    "fills", "rejections",
}
_CHILD_FIELDS = {
    "run_id", "experiment_id", "status", "kind", "manifest", "children", "periods",
    "folds", "evaluations",
}


def _same(left, right):
    return encode(left) == encode(right)


def _identity(compiled):
    package = compiled["package"]
    return {
        "strategy_key": package["strategy_key"],
        "name": package["name"],
        "version": package["version"],
        "package_hash": compiled["package_hash"],
        "compiled_spec_hash": compiled["compiled_spec_hash"],
    }


def _historical_identity(envelope):
    package = envelope["package"]
    compiled_spec = {**deepcopy(package["spec"]), "strategy_package": deepcopy(envelope)}
    return {
        "strategy_key": package["strategy_key"],
        "name": package["name"],
        "version": package["version"],
        "package_hash": envelope["package_hash"],
        "compiled_spec_hash": digest(compiled_spec),
    }


def _changes(left, right):
    changes = []

    def visit(a, b, path, left_present=True, right_present=True):
        if not left_present or not right_present:
            changes.append({
                "path": path,
                "left_present": left_present,
                "right_present": right_present,
                "left": deepcopy(a) if left_present else None,
                "right": deepcopy(b) if right_present else None,
            })
            return
        if type(a) is dict and type(b) is dict:
            for key in sorted(set(a) | set(b)):
                visit(a.get(key), b.get(key), f"{path}.{key}" if path else key, key in a, key in b)
            return
        if type(a) is list and type(b) is list:
            for index in range(max(len(a), len(b))):
                visit(a[index] if index < len(a) else None, b[index] if index < len(b) else None,
                      f"{path}[{index}]", index < len(a), index < len(b))
            return
        if not _same(a, b):
            changes.append({
                "path": path,
                "left_present": True,
                "right_present": True,
                "left": deepcopy(a),
                "right": deepcopy(b),
            })

    visit(left, right, "")
    return changes


def _comparison_warnings(left_identity, right_identity, changes):
    warnings = ["仅描述配置差异；不排序、不评选赢家，也不证明 Alpha。"]
    same_named_version = (
        left_identity["version"] == right_identity["version"]
        and (left_identity["strategy_key"] == right_identity["strategy_key"]
             or left_identity["name"] == right_identity["name"])
    )
    if same_named_version and left_identity["package_hash"] != right_identity["package_hash"]:
        warnings.append("同名（或同一 strategy_key）同版本的配置内容不同：版本未更新。")
    if left_identity["strategy_key"] != right_identity["strategy_key"]:
        warnings.append("strategy_key 不同；差异不表示两个策略可互换。")
    if not changes:
        warnings.append("规范化配置内容相同。")
    return warnings


def _compare_normalized(left_package, right_package, left_identity, right_identity):
    changes = _changes(left_package, right_package)
    return {
        "left": left_identity,
        "right": right_identity,
        "same_strategy_key": left_identity["strategy_key"] == right_identity["strategy_key"],
        "same_version": left_identity["version"] == right_identity["version"],
        "changes": changes,
        "warnings": _comparison_warnings(left_identity, right_identity, changes),
    }


def compare_strategy_packages(left: dict, right: dict) -> dict:
    """Normalize two strict packages, then recursively describe every difference."""
    left_compiled = compile_strategy(left)
    right_compiled = compile_strategy(right)
    return _compare_normalized(
        left_compiled["package"], right_compiled["package"],
        _identity(left_compiled), _identity(right_compiled),
    )


def _canonical_uuid(value, label):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"{label} must be a canonical UUID") from None
    return value


def _required_receipt(folder, tree_run, name):
    expected = tree_run["files"].get(name)
    if expected is None:
        raise ValueError("Execution archive is missing required evidence file: " + name)
    actual = file_hash(folder / name)
    if actual != expected:
        raise ValueError("Execution evidence changed while being read: " + name)
    return actual


def _finite_number(value, label, *, optional=False):
    if value is None and optional:
        return None
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Invalid finite execution metric: " + label)
    return value


def _assert_metric(actual, expected, label):
    actual = _finite_number(actual, label)
    expected = _finite_number(expected, label)
    if not math.isclose(float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError("Execution summary does not match archived account curve: " + label)


def _frame(path, label):
    try:
        frame = pl.read_parquet(path)
    except Exception as error:
        raise ValueError(f"Unreadable archived {label}: {error}") from error
    if frame.is_empty():
        raise ValueError("Archived " + label + " is empty")
    return frame


def _frame_ref(folder, tree_run, spec):
    if type(spec) is not dict or type(spec.get("file")) is not str:
        raise ValueError("Invalid frozen input frame declaration")
    name = spec["file"]
    if Path(name).name != name or not name.startswith("input-") or not name.endswith(".parquet"):
        raise ValueError("Invalid frozen input path")
    receipt = _required_receipt(folder, tree_run, name)
    frame = _frame(folder / name, "frozen input")
    if digest(frame.write_json()) != spec.get("hash"):
        raise ValueError("Frozen input logical hash mismatch: " + name)
    return frame, receipt


def _universe_material(folder, tree_run, child_manifest, symbols):
    frozen = child_manifest.get("frozen_inputs")
    if type(frozen) is not dict or frozen.get("version") != 1:
        raise ValueError("Packaged execution signal archive lacks versioned frozen inputs")
    spec = frozen.get("universe")
    if type(spec) is not dict or type(spec.get("kind")) is not str:
        raise ValueError("Invalid frozen Universe declaration")
    # Decode only archived bytes through the existing frozen-input contract.
    # Historical Universe metadata participates in its stored version identity.
    from quantlab.storage.frozen_inputs import load_frozen_inputs
    _, frozen_universe = load_frozen_inputs(folder, child_manifest)
    declared_universe = child_manifest.get("universe") or {}
    if (frozen_universe.universe_id != declared_universe.get("id")
            or frozen_universe.version != declared_universe.get("version")):
        raise ValueError("Frozen Universe identity differs from signal archive")
    frame_receipts = []

    def normalize(value):
        if type(value) is dict:
            if set(value) >= {"file", "hash"}:
                _, receipt = _frame_ref(folder, tree_run, value)
                frame_receipts.append(receipt)
                return {"logical_hash": value["hash"], "bytes": receipt}
            return {key: normalize(item) for key, item in sorted(value.items())}
        if type(value) is list:
            return [normalize(item) for item in value]
        return value

    material = normalize(spec)
    if spec["kind"] == "explicit" and spec.get("symbols") != symbols:
        raise ValueError("Frozen explicit Universe differs from execution securities")
    manifest_universe = child_manifest.get("universe")
    if type(manifest_universe) is not dict or type(manifest_universe.get("mask_hash")) is not str:
        raise ValueError("Signal archive lacks actual Universe mask identity")
    return {
        "id": manifest_universe.get("id"),
        "version": manifest_universe.get("version"),
        "mask_hash": manifest_universe["mask_hash"],
        "frozen_spec": material,
        "frame_receipts": frame_receipts,
    }


def _main_frozen_signal(folder, tree_run, child_manifest, config_data, child_bars):
    frozen = child_manifest["frozen_inputs"]
    matches = []
    all_inputs = []
    for item in frozen.get("data", []):
        if type(item) is not dict:
            raise ValueError("Invalid frozen data declaration")
        frame_spec = item.get("frame")
        frame, receipt = _frame_ref(folder, tree_run, frame_spec)
        request = item.get("request")
        if type(request) is not dict or set(request) != {"symbols", "timeframe", "start", "end"}:
            raise ValueError("Frozen input lacks an exact data request")
        all_inputs.append({"request": deepcopy(request), "frame_hash": frame_spec["hash"],
                           "bytes": receipt, "adjustment": item.get("snapshot", {}).get("adjustment")})
        if _same(item.get("request"), config_data):
            matches.append((frame, receipt))
    if len(matches) != 1:
        raise ValueError("Signal archive must contain exactly one frozen main market input")
    frame, receipt = matches[0]
    if not frame.equals(child_bars):
        raise ValueError("Archived signal bars differ from their frozen market input")
    # Include background/timeframe inputs as well as main OHLCV; file names and
    # approval-freeze snapshot ids are not semantic data-comparability keys.
    return receipt, sorted(all_inputs, key=encode)


def _validate_package_binding(envelope, parent_manifest, child_manifest):
    package = envelope["package"]
    # Validate the historical envelope against its own archived ordinary spec.
    # Deliberately do not call compile_strategy: current templates are not evidence
    # for a historical run.
    checked = validate_strategy_envelope_spec({**deepcopy(package["spec"]), "strategy_package": deepcopy(envelope)})
    if not _same(checked["resolved_config"], parent_manifest.get("config")):
        raise ValueError("Archived package resolved_config differs from execution config")
    spec = package["spec"]
    config = parent_manifest["config"]
    data = config.get("data", {})
    declared_data = {key: spec.get(key) for key in ("symbols", "timeframe", "start", "end")}
    if not _same(declared_data, {key: data.get(key) for key in declared_data}):
        raise ValueError("Archived package securities/date/timeframe declaration differs")
    if "factor" in spec:
        if (spec["factor"] != config.get("factor_id") or spec["version"] != config.get("factor_version")
                or not _same(spec["parameters"], config.get("parameters"))):
            raise ValueError("Archived declared factor/parameters differ from actual parsed signal")
    else:
        origin = config.get("theory_origin") or {}
        if (spec["theory"] != origin.get("template_id") or spec["theory_version"] != origin.get("version")
                or not _same(origin.get("parameters"), config.get("parameters"))):
            raise ValueError("Archived declared template differs from actual template evidence")
    if not _same(spec.get("execution"), parent_manifest.get("execution")):
        raise ValueError("Archived package execution declaration differs")
    if not _same(spec.get("portfolio"), parent_manifest.get("portfolio")):
        raise ValueError("Archived package portfolio declaration differs")
    if spec.get("execution_backend", "open") != parent_manifest.get("backend"):
        raise ValueError("Archived package backend declaration differs")
    if not _same(spec.get("market_rules"), parent_manifest.get("market_rules")):
        raise ValueError("Archived package market-rule declaration differs")
    if spec.get("adjustment") != parent_manifest.get("signal_data_snapshot", {}).get("adjustment"):
        raise ValueError("Archived package signal price declaration differs")
    signal = checked["signal"]
    child_config = child_manifest.get("config", {})
    expected_signal = {
        "factor_id": child_config.get("factor_id"),
        "factor_version": child_config.get("factor_version"),
        "parameters": child_config.get("parameters"),
        "code_hash": child_manifest.get("factor_code_hash"),
        "template_source": child_config.get("theory_origin"),
    }
    if not _same(signal, expected_signal):
        raise ValueError("Archived package signal identity differs from stored signal parsing evidence")
    return checked


def _execution_metrics(record, curve, manifest):
    summary = record.get("execution")
    if type(summary) is not dict:
        raise ValueError("Execution archive lacks authoritative execution metrics")
    required_curve = {"datetime", "equity"}
    if not required_curve <= set(curve.columns):
        raise ValueError("Archived account curve lacks datetime/equity")
    clock_type = curve.schema["datetime"]
    if (not isinstance(clock_type, pl.Datetime) or clock_type.time_zone is None
            or curve["datetime"].null_count() or curve["datetime"].n_unique() != curve.height):
        raise ValueError("Account curve requires unique non-null timezone-aware clocks")
    curve = curve.sort("datetime")
    initial = _finite_number(manifest.get("execution", {}).get("initial_cash"), "initial_cash")
    if initial <= 0:
        raise ValueError("Archived initial cash must be positive")
    equities = [_finite_number(value, "equity") for value in curve["equity"].to_list()]
    final = equities[-1]
    peak = float(initial)
    drawdown = 0.0
    for equity in equities:
        peak = max(peak, float(equity))
        drawdown = min(drawdown, float(equity) / peak - 1)
    _assert_metric(summary.get("initial_cash"), initial, "initial_cash")
    _assert_metric(summary.get("final_equity"), final, "final_equity")
    _assert_metric(summary.get("net_return"), final / initial - 1, "net_return")
    _assert_metric(summary.get("max_drawdown"), drawdown, "max_drawdown")
    fills = record.get("fills")
    rejections = record.get("rejections")
    if type(fills) is not list or type(rejections) is not list:
        raise ValueError("Execution archive lacks fill/rejection evidence")
    if summary.get("fills") != len(fills) or summary.get("rejections") != len(rejections):
        raise ValueError("Execution summary fill/rejection counts differ from archived evidence")
    for metric, field in (("commission", "commission"), ("sell_tax", "tax"),
                          ("transfer_fee", "transfer_fee"), ("slippage_cost", "slippage_cost")):
        total = 0.0
        for fill in fills:
            if type(fill) is not dict:
                raise ValueError("Invalid archived fill evidence")
            total += float(_finite_number(fill.get(field), metric))
        _assert_metric(summary.get(metric), total, metric)
    # Check the published descriptive metrics against the saved account curve;
    # this is arithmetic validation, not signal generation or a backtest rerun.
    from quantlab.execution.performance import performance_metrics
    checked_performance = performance_metrics(curve, initial)
    for name in ("sharpe", "annualized_volatility", "annualized_return", "performance_days"):
        expected = checked_performance.get(name)
        actual = summary.get(name)
        if expected is None:
            if actual is not None:
                raise ValueError("Execution performance metric differs from saved curve: " + name)
        else:
            _assert_metric(actual, expected, name)
    result = {}
    for name in _METRICS:
        value = summary.get(name)
        result[name] = _finite_number(value, name, optional=name in {
            "sharpe", "annualized_volatility", "annualized_return",
        })
    return result, curve["datetime"].to_list()


def _load_execution(output_root, run_id, tree):
    folder = output_root / run_id
    tree_run = tree["runs"][run_id]
    for name in _PARENT_FILES:
        _required_receipt(folder, tree_run, name)
    record = load_record_fields(folder / "experiment.json", _PARENT_FIELDS)
    manifest = record.get("manifest")
    if (record.get("run_id") != run_id or record.get("experiment_id") != digest(manifest)
            or record.get("kind") != "execution"):
        raise ValueError("Execution archive identity mismatch")
    if record.get("status") != "completed":
        raise ValueError("Execution archive is not completed")
    if type(manifest) is not dict or "strategy_package" not in manifest:
        raise ValueError("Execution archive has no strategy package")
    children = record.get("children")
    if type(children) is not list or len(children) != 1 or type(children[0]) is not dict:
        raise ValueError("Execution archive must have exactly one signal child")
    child_id = _canonical_uuid(children[0].get("run_id"), "signal child run_id")
    if tree_run["children"] != [child_id] or set(tree["runs"]) != {run_id, child_id}:
        raise ValueError("Execution parent/child lineage is not the expected local pair")
    child_folder = output_root / child_id
    child_tree = tree["runs"][child_id]
    for name in _CHILD_FILES:
        _required_receipt(child_folder, child_tree, name)
    child = load_record_fields(child_folder / "experiment.json", _CHILD_FIELDS)
    child_manifest = child.get("manifest")
    if (child.get("run_id") != child_id or child.get("experiment_id") != digest(child_manifest)
            or child.get("status") != "completed" or child.get("kind", "factor") != "factor"):
        raise ValueError("Signal child archive identity mismatch")
    if child_tree["children"]:
        raise ValueError("Signal child has unexpected archive descendants")
    if manifest.get("source_experiment_id") != child["experiment_id"]:
        raise ValueError("Execution parent does not bind the signal child identity")
    if not _same(manifest.get("runtime"), child_manifest.get("runtime")):
        raise ValueError("Signal and execution runtime fingerprints differ")
    expected_child_config = deepcopy(manifest.get("config"))
    if type(expected_child_config) is not dict:
        raise ValueError("Execution archive lacks config")
    expected_child_config["replay"] = True
    if not _same(child_manifest.get("config"), expected_child_config):
        raise ValueError("Signal child config differs from execution parent")
    if (not _same(child_manifest.get("data_snapshot"), manifest.get("signal_data_snapshot"))
            or not _same(child_manifest.get("universe"), manifest.get("universe"))):
        raise ValueError("Signal child provenance differs from execution parent")
    envelope = _validate_package_binding(manifest["strategy_package"], manifest, child_manifest)

    child_bars = _frame(child_folder / "bars.parquet", "signal bars")
    execution_bars = _frame(folder / "bars.parquet", "execution bars")
    keys = ("symbol", "datetime", "available_at")
    if any(key not in child_bars.columns or key not in execution_bars.columns for key in keys):
        raise ValueError("Archived market bars lack identity columns")
    if not child_bars.select(keys).sort(keys).equals(execution_bars.select(keys).sort(keys)):
        raise ValueError("Signal and execution market clocks/securities differ within archive")
    price_mode = manifest.get("execution", {}).get("price_mode")
    if price_mode == "research" and not child_bars.equals(execution_bars):
        raise ValueError("Research-price execution bytes differ from signal market bytes")
    if price_mode == "account" and manifest.get("data_snapshot", {}).get("adjustment") != "raw":
        raise ValueError("Account-price execution archive is not raw")
    if price_mode not in ("research", "account"):
        raise ValueError("Invalid archived price_mode")

    targets = _frame(folder / "targets.parquet", "targets")
    if digest(targets.write_json()) != manifest.get("targets_hash"):
        raise ValueError("Archived targets differ from parent target identity")
    curve = _frame(folder / "observations.parquet", "account curve")
    metrics, clocks = _execution_metrics(record, curve, manifest)
    if clocks != execution_bars["datetime"].unique().sort().to_list():
        raise ValueError("Account valuation clocks do not match actual execution bars")
    config_data = manifest["config"].get("data")
    if type(config_data) is not dict:
        raise ValueError("Execution archive lacks data request")
    signal_input, all_inputs = _main_frozen_signal(child_folder, child_tree, child_manifest, config_data, child_bars)
    symbols = config_data.get("symbols")
    if type(symbols) is not list:
        raise ValueError("Execution archive has invalid securities")
    universe_material = _universe_material(child_folder, child_tree, child_manifest, symbols)
    identity = _historical_identity(envelope)
    evidence = {
        "tree_sha256": digest(tree),
        "experiment_json": tree_run["files"]["experiment.json"],
        "signal_experiment_json": child_tree["files"]["experiment.json"],
        "signal_market_bytes": child_tree["files"]["bars.parquet"],
        "frozen_signal_market_bytes": signal_input,
        "all_frozen_inputs_sha256": digest(all_inputs),
        "execution_market_bytes": tree_run["files"]["bars.parquet"],
        "targets_bytes": tree_run["files"]["targets.parquet"],
        "account_curve_bytes": tree_run["files"]["observations.parquet"],
        "universe_sha256": digest(universe_material),
    }
    return {
        "run_id": run_id,
        "package": identity,
        "execution_metrics": metrics,
        "evidence_fingerprint": evidence,
        "_package_value": envelope["package"],
        "_manifest": manifest,
        "_data": config_data,
        "_universe": universe_material,
        "_clocks": clocks,
    }


def _blockers(left, right):
    blockers = []

    def differ(code, a, b):
        if not _same(a, b):
            blockers.append(code)

    differ("securities_differ", left["_data"].get("symbols"), right["_data"].get("symbols"))
    differ("date_range_differ", [left["_data"].get("start"), left["_data"].get("end")],
           [right["_data"].get("start"), right["_data"].get("end")])
    differ("timeframe_differ", left["_data"].get("timeframe"), right["_data"].get("timeframe"))
    left_spec = left["_package_value"]["spec"]
    right_spec = right["_package_value"]["spec"]
    differ("signal_price_adjustment_differ", left_spec.get("adjustment"), right_spec.get("adjustment"))
    differ("qualification_differ", left_spec.get("qualification"), right_spec.get("qualification"))
    differ("universe_differ", left["_universe"], right["_universe"])
    differ("signal_market_bytes_differ", left["evidence_fingerprint"]["signal_market_bytes"],
           right["evidence_fingerprint"]["signal_market_bytes"])
    differ("frozen_signal_market_bytes_differ", left["evidence_fingerprint"]["frozen_signal_market_bytes"],
           right["evidence_fingerprint"]["frozen_signal_market_bytes"])
    differ("execution_market_bytes_differ", left["evidence_fingerprint"]["execution_market_bytes"],
           right["evidence_fingerprint"]["execution_market_bytes"])
    differ("additional_or_background_inputs_differ", left["evidence_fingerprint"]["all_frozen_inputs_sha256"],
           right["evidence_fingerprint"]["all_frozen_inputs_sha256"])
    differ("portfolio_industry_evidence_differ", left_spec.get("portfolio", {}).get("industry_events"),
           right_spec.get("portfolio", {}).get("industry_events"))
    differ("backend_version_differ", left["_manifest"].get("backend_version"), right["_manifest"].get("backend_version"))
    differ("runtime_differ", left["_manifest"].get("runtime"), right["_manifest"].get("runtime"))
    differ("backend_differ", left["_manifest"].get("backend"), right["_manifest"].get("backend"))
    differ("price_mode_differ", left["_manifest"].get("execution", {}).get("price_mode"),
           right["_manifest"].get("execution", {}).get("price_mode"))
    differ("market_rules_differ", left["_manifest"].get("market_rules"), right["_manifest"].get("market_rules"))
    left_execution = left["_manifest"].get("execution", {})
    right_execution = right["_manifest"].get("execution", {})
    execution_conditions = sorted((set(left_execution) | set(right_execution)) - _ALLOWED_EXECUTION_VARIABLES)
    differ("execution_assumptions_or_costs_differ",
           {key: left_execution.get(key) for key in execution_conditions},
           {key: right_execution.get(key) for key in execution_conditions})
    differ("account_valuation_clocks_differ", left["_clocks"], right["_clocks"])
    return blockers


def _public_run(value):
    return {key: value[key] for key in ("run_id", "package", "execution_metrics", "evidence_fingerprint")}


def compare_strategy_runs(output, left_run_id: str, right_run_id: str) -> dict:
    """Compare two explicit local execution UUID archives without reproducing them."""
    output_path = Path(output)
    if output_path.is_symlink() or not output_path.is_dir():
        raise ValueError("Execution artifact root must be an existing non-symlink directory")
    root = output_path.resolve()
    left_id = _canonical_uuid(left_run_id, "left_run_id")
    right_id = _canonical_uuid(right_run_id, "right_run_id")

    before_left = snapshot_tree(root, left_id)
    before_right = before_left if right_id == left_id else snapshot_tree(root, right_id)
    left = _load_execution(root, left_id, before_left)
    right = _load_execution(root, right_id, before_right)
    after_left = snapshot_tree(root, left_id)
    after_right = after_left if right_id == left_id else snapshot_tree(root, right_id)
    if before_left != after_left or before_right != after_right:
        raise ValueError("Execution evidence changed during comparison")

    config = _compare_normalized(
        left["_package_value"], right["_package_value"], left["package"], right["package"],
    )
    blockers = _blockers(left, right)
    comparable = not blockers
    metrics = []
    for metric in _METRICS:
        left_value = left["execution_metrics"].get(metric)
        right_value = right["execution_metrics"].get(metric)
        delta = None
        if comparable and left_value is not None and right_value is not None:
            delta = right_value - left_value
        metrics.append({"metric": metric, "left": left_value, "right": right_value, "delta": delta})
    warnings = [
        "仅作描述性对照；delta=right-left，不表示 Alpha、因果、优劣或赢家。",
        "结果只核对所给本地归档；未访问源 data_root，也未执行或复算策略。",
    ]
    variable_paths = [change["path"] for change in config["changes"] if (
        change["path"].startswith("spec.factor")
        or change["path"].startswith("spec.theory")
        or change["path"].startswith("spec.version")
        or change["path"].startswith("spec.parameters")
        or change["path"].startswith("spec.portfolio")
        or any(change["path"].startswith("spec.execution." + key) for key in _ALLOWED_EXECUTION_VARIABLES)
    )]
    if variable_paths:
        warnings.append("信号/仓位规则差异作为研究变量保留：" + ", ".join(variable_paths[:50]))
    if blockers:
        warnings.append("存在来源或运行条件 blocker；所有指标 delta 均留空。")
    warnings.extend(config["warnings"])
    return {
        "format": FORMAT,
        "left": _public_run(left),
        "right": _public_run(right),
        "config_changes": config["changes"],
        "comparable": comparable,
        "blockers": blockers,
        "metrics": metrics,
        "scope": SCOPE,
        "warnings": warnings,
    }


__all__ = ["compare_strategy_packages", "compare_strategy_runs"]

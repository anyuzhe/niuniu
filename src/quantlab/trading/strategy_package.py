"""Strict, versioned packaging for the existing execution research path.

This module does not run data, persist state, or add an execution engine.  The
small validation helpers are shared by ``workbench.jobs`` and the execution
archive so the declared package cannot diverge from what is actually parsed.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from uuid import UUID
import json
import math

from quantlab.storage.codec import digest, encode


FORMAT = "niuniu-strategy-package-v1"
ENVELOPE_FORMAT = "niuniu-strategy-package-envelope-v1"
REVISION_SOURCE_FORMAT = "niuniu-strategy-revision-source-v1"
_REVISION_SOURCE_FIELDS = {
    "format", "parent_run_id", "parent_strategy_key", "parent_version",
    "parent_package_hash", "parent_compiled_spec_hash", "parent_content_hash", "parent_evidence_hash",
}
QUALIFICATIONS = ("research_only",)
LIFECYCLE = {
    "rebalance": "each_completed_bar",
    "holding": "target_weight",
    "exit": "follow_target_reductions",
    "end_of_sample": "mark_to_market_without_forced_exit",
}

_PACKAGE_FIELDS = {"format", "strategy_key", "name", "version", "lifecycle", "spec"}
_ENVELOPE_FIELDS = {"format", "package", "package_hash", "resolved_config", "signal"}
_EXECUTION_REQUIRED = {
    "initial_cash", "top_n", "threshold", "exposure", "lot_size", "t_plus_one",
    "price_mode", "commission_bps", "minimum_commission", "sell_tax_bps",
    "transfer_bps", "slippage_bps", "statutory_fees",
}
_PORTFOLIO_REQUIRED = {"weighting", "max_position", "max_exposure", "max_turnover"}
_SPEC_REQUIRED = {
    "question", "symbols", "timeframe", "start", "end", "adjustment",
    "qualification", "replay", "mode", "execution", "portfolio",
}
LIMITATIONS = [
    "每根完结 bar 由现有 TargetWeightBuilder 按信号、排名和约束重算目标权重；不是固定持有期或独立止损止盈引擎。",
    "目标减少或归零驱动退出，但目标换手预算、T+1、停牌、价格限制和成交限制可能使实际持仓偏离目标。",
    "样本末持仓只按市值计价，不强制平仓；策略包不证明 Alpha、可成交性或真实市场参数适用性。",
    "v1 仅接受 research_only；尚未绑定独立资格回执，不接受以策略包声明 Strict PIT、回顾性认证或官方规则已覆盖。",
    "仅封装现有 open/vnpy_open/vnpy_rules 研究后端；策略包不批准执行或真实交易。",
]


def _json_value(value, *, depth=0, count=None):
    """Return a strict JSON clone without Python-only values or non-finite numbers."""
    if count is None:
        count = [0]
    count[0] += 1
    if depth > 16 or count[0] > 5000:
        raise ValueError("策略包嵌套或元素数量超出限制")
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("策略包数字必须有限")
        return value
    if type(value) is list:
        return [_json_value(item, depth=depth + 1, count=count) for item in value]
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError("策略包 JSON 字段名必须是字符串")
        return {key: _json_value(item, depth=depth + 1, count=count) for key, item in value.items()}
    raise ValueError("策略包只接受标准 JSON 类型")


def _same(left, right):
    return encode(left) == encode(right)


def _validate_identity(package):
    key = package["strategy_key"]
    name = package["name"]
    version = package["version"]
    if type(key) is not str or key != key.strip() or not key or len(key) > 128 or any(ord(c) < 32 for c in key):
        raise ValueError("strategy_key 必须是 1–128 位非空稳定标识且首尾无空白")
    if type(name) is not str or name != name.strip() or not name or len(name) > 200 or any(ord(c) < 32 for c in name):
        raise ValueError("name 必须是 1–200 位非空名称且首尾无空白")
    if type(version) is not str or version != version.strip() or not version or len(version) > 64 or any(ord(c) < 32 for c in version) or version.casefold() == "latest":
        raise ValueError("version 必须是 1–64 位精确版本，不能使用 latest")


def validate_revision_source(value):
    """Validate a bounded historical reference; never authenticate it or grant execution."""
    value = _json_value(value)
    if type(value) is not dict or set(value) != _REVISION_SOURCE_FIELDS or value.get('format') != REVISION_SOURCE_FORMAT:
        raise ValueError('revision_source 字段或 format 无效')
    try:
        run_id = value['parent_run_id']
        if type(run_id) is not str or str(UUID(run_id)) != run_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('revision_source parent_run_id 必须是规范 UUID') from None
    _validate_identity({'strategy_key': value['parent_strategy_key'], 'name': 'parent',
                        'version': value['parent_version']})
    for key in ('parent_package_hash', 'parent_compiled_spec_hash', 'parent_content_hash', 'parent_evidence_hash'):
        text = value[key]
        if type(text) is not str or len(text) != 64 or any(c not in '0123456789abcdef' for c in text):
            raise ValueError('revision_source ' + key + ' 必须是完整 SHA256')
    return value


def strategy_content_hash(envelope):
    """Compiled identity excluding only the immediate-parent reference, not signal code."""
    value = deepcopy(envelope)
    value['package'].pop('revision_source', None)
    value['package_hash'] = digest(value['package'])
    return digest({**deepcopy(value['package']['spec']), 'strategy_package': value})


def _validate_explicit_spec(spec):
    if type(spec) is not dict:
        raise ValueError("策略包 spec 必须是 JSON 对象")
    if "strategy_package" in spec:
        raise ValueError("完整 package 自身不得递归嵌套 strategy_package")
    missing = _SPEC_REQUIRED - set(spec)
    if missing:
        raise ValueError("策略包 spec 缺少显式字段：" + ", ".join(sorted(missing)))
    if spec["mode"] != "execution":
        raise ValueError("策略包 v1 只接受 mode='execution'")
    if spec["qualification"] not in QUALIFICATIONS:
        raise ValueError("策略包 v1 仅支持 research_only；严格资格须沿原受验证流程处理，不能自动降级")
    if spec["replay"] is not True:
        raise ValueError("策略包 v1 必须显式 replay=true")
    factor_keys = {"factor", "version", "parameters"}
    theory_keys = {"theory", "theory_version"}
    factor_present = factor_keys <= set(spec) and not (theory_keys & set(spec))
    theory_present = theory_keys <= set(spec) and not (factor_keys & set(spec))
    if not (factor_present ^ theory_present):
        raise ValueError("策略包必须恰好声明 factor+version+parameters 或 theory+theory_version")
    if factor_present and (not isinstance(spec["factor"], str) or not spec["factor"].strip()
                           or not isinstance(spec["version"], str) or not spec["version"].strip()
                           or type(spec["parameters"]) is not dict):
        raise ValueError("factor、version 和 parameters 必须显式且类型正确")
    if theory_present and (not isinstance(spec["theory"], str) or not spec["theory"].strip()
                           or not isinstance(spec["theory_version"], str) or not spec["theory_version"].strip()):
        raise ValueError("theory 和 theory_version 必须显式且非空")
    execution = spec["execution"]
    portfolio = spec["portfolio"]
    if type(execution) is not dict or not _EXECUTION_REQUIRED <= set(execution):
        raise ValueError("execution 必须显式固定资金、选股、成交与全部基础费用字段")
    if type(portfolio) is not dict or not _PORTFOLIO_REQUIRED <= set(portfolio):
        raise ValueError("portfolio 必须显式固定 weighting/max_position/max_exposure/max_turnover")


def _validate_package(package):
    package = _json_value(package)
    if type(package) is not dict or not _PACKAGE_FIELDS <= set(package) or set(package) - _PACKAGE_FIELDS - {'revision_source'}:
        raise ValueError("策略包外层字段必须含 format/strategy_key/name/version/lifecycle/spec；仅可选 revision_source")
    if 'revision_source' in package:
        package['revision_source'] = validate_revision_source(package['revision_source'])
    if package["format"] != FORMAT:
        raise ValueError("不支持的策略包 format")
    _validate_identity(package)
    if not _same(package["lifecycle"], LIFECYCLE):
        raise ValueError("unsupported lifecycle：v1 只支持现有目标权重生命周期")
    _validate_explicit_spec(package["spec"])
    return package


def _normalize_spec(spec, submission):
    """Preserve every accepted input field while freezing existing defaults."""
    value = deepcopy(spec)
    config = submission.config
    value.update(
        question=config.research_question,
        symbols=list(config.data.symbols),
        timeframe=config.data.timeframe.value,
        start=config.data.start.isoformat(),
        end=config.data.end.isoformat(),
        adjustment=submission.adjustment,
        qualification=submission.qualification,
        replay=True,
        mode="execution",
        horizons=list(config.horizons),
        quantiles=config.quantiles,
        seed=config.random_seed,
        sequence_audit=config.sequence_audit,
        incremental_test=config.incremental_test,
        universe=json.loads(encode(asdict(submission.universe))),
        execution=json.loads(encode(asdict(submission.execution))),
        portfolio=json.loads(encode(asdict(submission.portfolio))),
        execution_backend=submission.execution_backend,
    )
    if "factor" in spec:
        value["factor"] = config.factor_id
        value["version"] = config.factor_version
        value["parameters"] = deepcopy(config.parameters)
    if submission.market_rules is not None:
        from quantlab.execution.rules import MarketRules
        value["market_rules"] = json.loads(encode(MarketRules(submission.market_rules).records))
    return _json_value(value)


def _signal(config, registry):
    factor = registry.get(config.factor_id, config.factor_version)
    value = {
        "factor_id": config.factor_id,
        "factor_version": config.factor_version,
        "parameters": config.parameters,
        "code_hash": registry.code_hash(factor),
        "template_source": config.theory_origin,
    }
    return _json_value(json.loads(encode(value)))


def _resolved_config(config):
    return json.loads(encode(asdict(config)))


def _envelope(package, submission, registry):
    return {
        "format": ENVELOPE_FORMAT,
        "package": deepcopy(package),
        "package_hash": digest(package),
        "resolved_config": _resolved_config(submission.config),
        "signal": _signal(submission.config, registry),
    }


def validate_strategy_envelope_spec(spec):
    """Validate package/hash and exact ordinary-spec equality before parsing."""
    if type(spec) is not dict or "strategy_package" not in spec:
        raise ValueError("strategy_package 校验信封缺失")
    envelope = _json_value(spec["strategy_package"])
    if type(envelope) is not dict or set(envelope) != _ENVELOPE_FIELDS or envelope.get("format") != ENVELOPE_FORMAT:
        raise ValueError("strategy_package 校验信封字段或 format 无效")
    package = _validate_package(envelope["package"])
    if envelope["package_hash"] != digest(package):
        raise ValueError("strategy_package package_hash 不匹配")
    ordinary = {key: deepcopy(value) for key, value in spec.items() if key != "strategy_package"}
    if not _same(ordinary, package["spec"]):
        raise ValueError("strategy_package 声明与真正执行 spec 不一致")
    if type(envelope["resolved_config"]) is not dict or type(envelope["signal"]) is not dict:
        raise ValueError("strategy_package 解析证据无效")
    return envelope


def validate_prepared_strategy_envelope(envelope, submission, registry):
    """Bind canonical normalization and actual registry resolution to a Submission."""
    package = envelope["package"]
    normalized = _normalize_spec(package["spec"], submission)
    if not _same(package["spec"], normalized):
        raise ValueError("strategy_package package 不是完整规范化版本")
    if not _same(envelope["resolved_config"], _resolved_config(submission.config)):
        raise ValueError("strategy_package resolved_config 与实际解析配置不一致")
    if not _same(envelope["signal"], _signal(submission.config, registry)):
        raise ValueError("strategy_package 信号版本、参数、code_hash 或模板来源不一致")
    source = package.get('revision_source')
    if (source is not None and package['strategy_key'] == source['parent_strategy_key']
            and package['version'] == source['parent_version']
            and strategy_content_hash(envelope) != source['parent_content_hash']):
        raise ValueError('历史策略配置或信号已变化，请明确新的策略版本或策略标识')


def validate_runtime_strategy_source(envelope, config, execution_config, portfolio_config, backend, market_rules):
    """Recheck the values actually handed to the execution engine."""
    holder = {**deepcopy(envelope["package"]["spec"]), "strategy_package": envelope}
    # A caller may supply the envelope directly (including through reproduction).
    # Reparse the declared spec: self-consistent hashes and caller-supplied resolved
    # values alone do not prove that the claimed range/signal was actually used.
    from quantlab.workbench.jobs import prepare
    checked = prepare(holder).strategy_package
    from quantlab.app import default_registry
    if not _same(checked["resolved_config"], _resolved_config(config)):
        raise ValueError("运行时 config 与 strategy_package 声明不一致")
    if not _same(checked["signal"], _signal(config, default_registry())):
        raise ValueError("运行时信号来源与 strategy_package 声明不一致")
    declared = checked["package"]["spec"]
    if not _same(declared["execution"], asdict(execution_config)):
        raise ValueError("运行时 execution 与 strategy_package 声明不一致")
    if not _same(declared["portfolio"], asdict(portfolio_config)):
        raise ValueError("运行时 portfolio 与 strategy_package 声明不一致")
    if declared.get("execution_backend", "open") != backend:
        raise ValueError("运行时 execution_backend 与 strategy_package 声明不一致")
    actual_rules = market_rules.records if market_rules is not None else None
    declared_rules = declared.get("market_rules")
    if not _same(declared_rules, actual_rules):
        raise ValueError("运行时 market_rules 与 strategy_package 声明不一致")
    return checked


def compile_strategy(package) -> dict:
    """Compile a strict package without reading data or writing persistent state."""
    from quantlab.agent.planning import parse_spec
    from quantlab.app import default_registry
    from quantlab.workbench.jobs import prepare

    # Reuse the bounded JSON contract before the existing spec/registry validators.
    package = parse_spec(encode(_json_value(package)))
    package = _validate_package(package)
    submission = prepare(package["spec"])
    normalized_spec = _normalize_spec(package["spec"], submission)
    normalized_package = {
        "format": FORMAT,
        "strategy_key": package["strategy_key"],
        "name": package["name"],
        "version": package["version"],
        "lifecycle": deepcopy(LIFECYCLE),
        "spec": normalized_spec,
    }
    if 'revision_source' in package:
        normalized_package['revision_source'] = deepcopy(package['revision_source'])
    # Parse the expanded defaults again so the envelope records exactly what the
    # ordinary spec delivered to ProposalService/JobQueue will resolve to.
    normalized_submission = prepare(normalized_spec)
    registry = default_registry()
    envelope = _envelope(normalized_package, normalized_submission, registry)
    compiled_spec = {**deepcopy(normalized_spec), "strategy_package": envelope}
    prepare(parse_spec(encode(compiled_spec)))
    result = {
        "package": normalized_package,
        "package_hash": envelope["package_hash"],
        "compiled_spec_hash": digest(compiled_spec),
        "spec": compiled_spec,
        "limitations": list(LIMITATIONS),
        "execution_authorized": False,
    }
    if 'revision_source' in normalized_package:
        result['revision_source_verification'] = 'not_checked'
        result['limitations'].append('revision_source 仅是固定的直接父引用；纯编译不认证父来源，提案与批准前必须核验实际归档。')
    return result


__all__ = ["FORMAT", "LIFECYCLE", "compile_strategy"]

"""Explicit combinations of registered leaf factors. No string evaluation."""

import math
import re
from dataclasses import asdict

import polars as pl

from quantlab.domain import FactorType, Timeframe
from quantlab.factors.base import ComputedFactor, FactorDefinition
from quantlab.factors.engine import compute_factor
from quantlab.factors.registry import FactorPack, FactorRegistry


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Combination constants and weights must be finite numbers")
    return value


def condition(rule: dict, aliases: set[str], depth: int = 0) -> tuple[pl.Expr, set[str]]:
    if not isinstance(rule, dict) or depth > 32:
        raise ValueError("Invalid or excessively nested condition")
    if set(rule) in ({"all"}, {"any"}):
        key = next(iter(rule))
        if not isinstance(rule[key], list) or len(rule[key]) < 2:
            raise ValueError("all/any require at least two conditions")
        children = [condition(child, aliases, depth + 1) for child in rule[key]]
        expression = pl.all_horizontal([c[0] for c in children]) if key == "all" else pl.any_horizontal([c[0] for c in children])
        return expression, set().union(*(c[1] for c in children))
    if set(rule) == {"not"}:
        expression, used = condition(rule["not"], aliases, depth + 1)
        return ~expression, used
    if set(rule) != {"input", "op", "value"} or not isinstance(rule["input"], str) or rule["input"] not in aliases:
        raise ValueError("Condition must reference a declared input and contain input/op/value")
    column, value = pl.col(f"input_{rule['input']}"), pl.lit(number(rule["value"]))
    operators = {"gt": column > value, "ge": column >= value, "lt": column < value,
        "le": column <= value, "eq": column == value, "ne": column != value}
    if not isinstance(rule["op"], str) or rule["op"] not in operators:
        raise ValueError("Unsupported comparison operator")
    return operators[rule["op"]], {rule["input"]}


class CombinationFactor(ComputedFactor):
    mode: str

    def __init__(self, registry: FactorRegistry):
        self.registry = registry

    def parameters(self, supplied):
        if not supplied:
            supplied = {"inputs": {
                "momentum": {"factor_id": "BASE.MOMENTUM"},
                "efficiency": {"factor_id": "BASE.DIRECTIONAL_EFFICIENCY"}},
                self.mode: ({"all": [{"input": "momentum", "op": "gt", "value": 0},
                    {"input": "efficiency", "op": "gt", "value": 0.3}]} if self.mode == "rule" else {"momentum": 1, "efficiency": 1})}
        if set(supplied) != {"inputs", self.mode}:
            raise ValueError(f"Combination requires exactly inputs and {self.mode}")
        if not isinstance(supplied["inputs"], dict) or not supplied["inputs"]:
            raise ValueError("Combination inputs must be a nonempty object")
        inputs = {}
        for alias, spec in sorted(supplied["inputs"].items()):
            if not isinstance(alias, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", alias):
                raise ValueError("Invalid input alias")
            if not isinstance(spec, dict) or set(spec) - {"factor_id", "version", "parameters"} or "factor_id" not in spec:
                raise ValueError("Invalid input factor specification")
            if not isinstance(spec["factor_id"], str) or not isinstance(spec.get("version", "1.0.0"), str):
                raise ValueError("Input factor id/version must be strings")
            factor = self.registry.get(spec["factor_id"], spec.get("version", "1.0.0"))
            if isinstance(factor, CombinationFactor):
                raise ValueError("Combination inputs must be leaf factors, not other combinations")
            if not isinstance(spec.get("parameters", {}), dict):
                raise ValueError("Input parameters must be an object")
            inputs[alias] = {"factor_id": factor.definition.factor_id, "version": factor.definition.version,
                "parameters": factor.parameters(spec.get("parameters", {}))}
        aliases = set(inputs)
        if self.mode == "rule":
            _, used = condition(supplied["rule"], aliases)
            if used != aliases:
                raise ValueError("Every declared input must be used by the condition")
        else:
            weights = supplied["weights"]
            if not isinstance(weights, dict) or set(weights) != aliases:
                raise ValueError("Specify one weight for every input")
            for weight in weights.values():
                number(weight)
        return {"inputs": inputs, self.mode: supplied[self.mode]}

    def lineage(self, parameters):
        return [{"alias": alias, "definition": asdict(self.registry.get(spec["factor_id"], spec["version"]).definition),
            "parameters": spec["parameters"], "code_hash": self.registry.code_hash(self.registry.get(spec["factor_id"], spec["version"]))}
            for alias, spec in parameters["inputs"].items()]

    def compute(self, bars, parameters):
        parameters = self.parameters(parameters)
        frame = bars.select("symbol", "datetime", "available_at")
        time_columns = ["available_at"]
        for alias, spec in parameters["inputs"].items():
            factor = self.registry.get(spec["factor_id"], spec["version"])
            values = compute_factor(factor, bars, spec["parameters"]).rename({"value": f"input_{alias}", "available_at": f"time_{alias}"})
            frame = frame.join(values, on=["symbol", "datetime"], how="left", validate="1:1")
            time_columns.append(f"time_{alias}")
        if self.mode == "rule":
            expression, _ = condition(parameters["rule"], set(parameters["inputs"]))
        else:
            expression = sum((pl.col(f"input_{alias}") * parameters["weights"][alias] for alias in parameters["inputs"]), pl.lit(0.0))
        ready = pl.all_horizontal([pl.col(f"input_{alias}").is_not_null() for alias in parameters["inputs"]])
        return frame.select("symbol", "datetime", pl.max_horizontal(time_columns).alias("available_at"),
            pl.when(ready).then(expression).otherwise(None).alias("value"))


class ConditionCombination(CombinationFactor):
    mode = "rule"
    definition = FactorDefinition("COMB.CONDITION", "1.0.0", "嵌套条件组合", "combination", FactorType.BOOLEAN,
        (), tuple(Timeframe), "注册因子条件的 AND/OR/NOT 组合；任一输入缺失则输出 null",
        "explicit nested condition tree", available_at_rule="latest availability of all inputs")


class ScoreCombination(CombinationFactor):
    mode = "weights"
    definition = FactorDefinition("COMB.SCORE", "1.0.0", "加权因子评分", "combination", FactorType.SCALAR,
        (), tuple(Timeframe), "原始因子值乘用户权重后相加；不隐式标准化，任一输入缺失则输出 null",
        "sum(weight_i * factor_i)", available_at_rule="latest availability of all inputs")


def combination_pack(registry: FactorRegistry) -> FactorPack:
    return FactorPack("CombinationPack", "1.0.0", (ConditionCombination(registry), ScoreCombination(registry)), ("BaseQuantPack",))

"""CODE-side tools for DATA-owned on-demand research providers.

DATA owns vendor choice, credentials, throttling, field mapping and correctness.
This layer only exposes bounded product reads after the DATA catalog says READY.
"""
from __future__ import annotations

import json

from quantlab.agent.catalog import TEXT, schema
from quantlab.storage.codec import encode

MAX_RESPONSE_BYTES = 64 * 1024
WARNINGS = [
    "DATA负责供应商、字段、单位、实时性和正确性；CODE只消费DATA标记READY的统一Provider。",
    "这些查询是research_only，不是Strict PIT或正式MarketSnapshot，也不授权交易。",
    "调用失败不会自动换供应商、扫描数据湖或把错误冒充空结果。",
]

TOOLS = [
    schema("research_search", "通过DATA统一Provider做研报/新闻/公告语义搜索；channel=report/news/announcement。只读联网查询，不持久化，不fallback。",
           {"query": {"type": "string", "maxLength": 500}, "channel": TEXT,
            "size": {"type": "integer", "minimum": 1, "maximum": 20}}),
    schema("stock_research_reports", "读取DATA统一Provider返回的单股券商研报列表；只读联网查询，不持久化。",
           {"code": TEXT, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}),
    schema("stock_news", "读取DATA统一Provider返回的单股相关新闻；供应商搜索可能包含只提到代码的综合新闻，按DATA字段原样返回。",
           {"code": TEXT, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}),
    schema("stock_announcements", "读取DATA统一Provider返回的单股巨潮公告。start/end为空字符串表示不限；只读联网查询。",
           {"code": TEXT, "start": TEXT, "end": TEXT,
            "limit": {"type": "integer", "minimum": 1, "maximum": 20}}),
    schema("financial_statements", "读取DATA统一Provider返回的三大报表长表。statement=income/balance/cashflow；publish_date用于信息时点判断。",
           {"code": TEXT, "statement": TEXT,
            "periods": {"type": "integer", "minimum": 1, "maximum": 8}}),
    schema("investor_qa", "读取DATA统一Provider返回的互动易问答；当前仅深市公司。只读联网查询。",
           {"code": TEXT, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}),
]
NAMES = {tool["name"] for tool in TOOLS}


def _error(tool: str, code: str, message: str) -> dict:
    return {
        "ok": False, "tool": tool, "data": None, "evidence": [], "warnings": list(WARNINGS),
        "error": {"code": code, "message": str(message)[:600]},
    }


def _ok(tool: str, data: dict, evidence: list[dict]) -> dict:
    result = {"ok": True, "tool": tool, "data": data, "evidence": evidence,
              "warnings": list(WARNINGS), "error": None}
    size = len(encode(result).encode("utf-8"))
    if size > MAX_RESPONSE_BYTES:
        return _error(tool, "RESULT_TOO_LARGE", "响应超过64KiB；请缩小limit/size/periods后重试")
    return json.loads(encode(result))


def _validate(tool: dict, args: dict) -> None:
    props = tool["parameters"]["properties"]
    if not isinstance(args, dict) or set(args) != set(props):
        raise ValueError("工具参数与schema不一致")
    for key, rule in props.items():
        value = args[key]
        if rule["type"] == "string":
            if not isinstance(value, str) or len(value) > rule.get("maxLength", 200):
                raise ValueError("参数无效: " + key)
        elif rule["type"] == "integer":
            if type(value) is not int or not rule["minimum"] <= value <= rule["maximum"]:
                raise ValueError("参数无效: " + key)
        else:
            raise ValueError("未知参数类型: " + key)


class ResearchDataAPI:
    def __init__(self, inner, *, provider=None, data_catalog_path=None):
        self.inner = inner
        self._provider = provider
        self.data_catalog_path = data_catalog_path

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def _ready_names(self):
        try:
            from quantlab.data.dataset_catalog import read_data_catalog
            catalog = read_data_catalog(self.data_catalog_path)
            return {row["dataset_id"] for row in catalog["entries"]
                    if row["status"] == "READY" and row["delivery"] == "API" and row["dataset_id"] in NAMES}
        except Exception:
            return set()

    def schemas(self):
        original = self.inner.schemas()
        own = {tool["name"] for tool in TOOLS}
        ready = self._ready_names()
        visible = [tool for tool in TOOLS if tool["name"] in ready]
        return [tool for tool in original if tool.get("name") not in own] + json.loads(
            json.dumps(visible, ensure_ascii=False)
        )

    def _get_provider(self):
        if self._provider is None:
            from quantlab.data.research_provider import ResearchDataProvider
            self._provider = ResearchDataProvider.from_env()
        return self._provider

    def get_capabilities(self, args):
        if not isinstance(args, dict) or args:
            return _error("get_capabilities", "INVALID_ARGUMENT", "能力查询不接受参数")
        base = self.inner.call("get_capabilities", args)
        if not isinstance(base, dict) or not base.get("ok") or not isinstance(base.get("data"), dict):
            return base if isinstance(base, dict) else _error("get_capabilities", "INVALID_RESULT", "内层能力接口无效")
        ready_ids = sorted(self._ready_names())
        data = {
            **base["data"],
            "research_data_provider_available": True,
            "research_data_ready_tools": ready_ids,
            "research_data_write_authorized": False,
            "research_data_fallback_authorized": False,
            "tools": [tool["name"] for tool in self.schemas()],
        }
        return _ok("get_capabilities", data, base.get("evidence", []))

    def call(self, name, args):
        if name == "get_capabilities":
            return self.get_capabilities(args)
        tool = next((item for item in TOOLS if item["name"] == name), None)
        if tool is None:
            return self.inner.call(name, args)
        try:
            _validate(tool, args)
            from quantlab.data.dataset_catalog import get_ready_data_source
            ready = get_ready_data_source(self.data_catalog_path, dataset_id=name)
            provider = self._get_provider()
            call_args = dict(args)
            if name == "stock_announcements":
                call_args["start"] = call_args["start"] or None
                call_args["end"] = call_args["end"] or None
            result = getattr(provider, name)(**call_args)
            if not hasattr(result, "to_dict"):
                return _error(name, "INVALID_DATA_PROVIDER_RESULT", "DATA Provider返回对象缺少to_dict")
            payload = result.to_dict()
            payload.update({
                "data_authority": "DATA",
                "strict_pit": False,
                "market_snapshot": False,
                "trading_authorized": False,
                "fallback_performed": False,
                "data_correctness_revalidated_by_code": False,
            })
            evidence = [{
                "kind": "data_catalog", "authority": "DATA", "dataset_id": name,
                "status": ready["entry"]["status"], "delivery": ready["entry"]["delivery"],
            }, {
                "kind": "data_provider_observation", "dataset_id": name,
                "source": payload.get("source"), "fetched_at": payload.get("fetched_at"),
                "provider_version": payload.get("provider_version"),
            }]
            return _ok(name, payload, evidence)
        except Exception as exc:
            from quantlab.data.dataset_catalog import DataCatalogError
            if isinstance(exc, DataCatalogError):
                return _error(name, exc.code, str(exc))
            try:
                from quantlab.data.research_provider import (
                    DataProviderError, InvalidRequest, ProviderNotConfigured,
                )
            except (ImportError, ModuleNotFoundError):
                DataProviderError = ProviderNotConfigured = ()
                InvalidRequest = ValueError
            if ProviderNotConfigured and isinstance(exc, ProviderNotConfigured):
                return _error(name, "DATA_PROVIDER_NOT_CONFIGURED", str(exc))
            if DataProviderError and isinstance(exc, DataProviderError):
                return _error(name, "DATA_PROVIDER_UNAVAILABLE", str(exc))
            if isinstance(exc, (InvalidRequest, ValueError, TypeError)):
                return _error(name, "INVALID_ARGUMENT", str(exc))
            if isinstance(exc, (ImportError, ModuleNotFoundError)):
                return _error(name, "DATA_PROVIDER_NOT_INSTALLED", str(exc))
            return _error(name, "DATA_PROVIDER_FAILED", type(exc).__name__ + ": " + str(exc))


__all__ = ["ResearchDataAPI", "TOOLS", "NAMES"]

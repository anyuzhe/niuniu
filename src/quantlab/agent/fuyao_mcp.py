"""Small, allowlisted Streamable HTTP MCP client for Fuyao financial data.

The API key is loaded from the process environment or the macOS Keychain.  It is
never accepted through a model tool argument and is never included in returned
provenance or error text.
"""
from __future__ import annotations

from datetime import datetime, timezone
from getpass import getuser
from threading import RLock
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
import hashlib
import json
import os
import subprocess


BASE_URL = "https://fuyao.aicubes.cn"
ENV_KEY = "HITHINK_FINANCE_API_KEY"
KEYCHAIN_SERVICE = "cn.niuniu.fuyao.api-key"
PROTOCOL_VERSION = "2025-03-26"
MAX_BODY = 2_000_000

SERVICE_PATHS = {
    "meta": "/mcp/meta",
    "a-share": "/mcp/a-share",
    "a-share-index": "/mcp/a-share-index",
}

ALLOWED_TOOLS = {
    "meta": frozenset({"get_meta_tickers_search"}),
    "a-share": frozenset({
        "get_a_share_prices_snapshot",
        "get_a_share_prices_historical",
        "get_a_share_valuations_snapshot",
        "get_a_share_financials_indicators",
        "get_a_share_calendar_trading_days",
        "get_a_share_auction_snapshot",
        "get_a_share_auction_short_term_benchmark",
        "get_a_share_special_data_limit_up_pool",
        "get_a_share_special_data_limit_down_pool",
        "get_a_share_special_data_limit_break_pool",
        "get_a_share_special_data_limit_up_ladder",
        "get_a_share_special_data_hot_stock_rank_trend",
        "get_a_share_special_data_dragon_tiger_list",
        "get_a_share_special_data_anomaly_analysis_stock",
    }),
    "a-share-index": frozenset({
        "get_a_share_index_catalog_ths_index_list",
        "get_a_share_index_constituents_ths_stock_list",
        "get_a_share_index_prices_snapshot",
    }),
}


class FuyaoMCPError(RuntimeError):
    def __init__(self, code: str, message: str, request_id: str = ""):
        super().__init__(message)
        self.code = str(code)[:80]
        self.request_id = str(request_id)[:160]


def _valid_key(value) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or len(value) > 512 or any(ord(char) < 32 for char in value):
        return ""
    return value


def load_api_key(env=None, *, keychain_runner=None) -> str:
    """Load an API key without reading project configuration files."""
    env = os.environ if env is None else env
    value = _valid_key(env.get(ENV_KEY, ""))
    if value:
        return value
    if os.name != "posix" or not os.path.exists("/usr/bin/security"):
        return ""
    runner = keychain_runner or subprocess.run
    try:
        result = runner(["/usr/bin/security", "find-generic-password", "-a", getuser(),
            "-s", KEYCHAIN_SERVICE, "-w"], capture_output=True, text=True, timeout=3, check=False)
        return _valid_key(result.stdout) if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_post(url, headers, body, timeout):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "fuyao.aicubes.cn" or parsed.path not in SERVICE_PATHS.values():
        raise FuyaoMCPError("FUYAO_ENDPOINT_REJECTED", "扶摇 MCP 地址不在固定白名单中。")
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with build_opener(_RejectRedirects).open(request, timeout=timeout) as response:
            raw = response.read(MAX_BODY + 1)
            status = response.status
            response_headers = dict(response.headers.items())
    except HTTPError as error:
        raw = error.read(MAX_BODY + 1)
        status = error.code
        response_headers = dict(error.headers.items()) if error.headers else {}
    except (URLError, TimeoutError, OSError) as error:
        raise FuyaoMCPError("FUYAO_NETWORK_ERROR", "扶摇 MCP 网络请求失败：" + type(error).__name__) from None
    if len(raw) > MAX_BODY:
        raise FuyaoMCPError("FUYAO_RESPONSE_TOO_LARGE", "扶摇 MCP 响应超过 2MB 上限。")
    return status, response_headers, raw


def _header(headers, name):
    target = name.casefold()
    return next((str(value) for key, value in headers.items() if str(key).casefold() == target), "")


def _json_message(raw: bytes):
    text = raw.decode("utf-8", "replace").strip()
    if not text:
        return None
    if text.startswith("event:") or "\ndata:" in text:
        values = []
        for line in text.splitlines():
            if line.startswith("data:"):
                values.append(line[5:].strip())
        if not values:
            raise FuyaoMCPError("FUYAO_PROTOCOL_ERROR", "扶摇 MCP SSE 响应不含 data。")
        text = values[-1]
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        raise FuyaoMCPError("FUYAO_PROTOCOL_ERROR", "扶摇 MCP 返回了无效 JSON。") from None
    if not isinstance(value, dict):
        raise FuyaoMCPError("FUYAO_PROTOCOL_ERROR", "扶摇 MCP 响应必须是 JSON 对象。")
    return value


def _envelope(result):
    if not isinstance(result, dict):
        raise FuyaoMCPError("FUYAO_PROTOCOL_ERROR", "扶摇 MCP 工具结果结构无效。")
    if result.get("isError"):
        message = "扶摇 MCP 工具调用失败。"
        for block in result.get("content", []):
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                message = block["text"][:300]
                break
        raise FuyaoMCPError("FUYAO_TOOL_ERROR", message)
    candidates = [result.get("structuredContent")]
    for block in result.get("content", []):
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            try:
                candidates.append(json.loads(block["text"]))
            except (TypeError, ValueError):
                continue
    for value in candidates:
        if isinstance(value, dict) and "code" in value and "data" in value:
            return value
        if isinstance(value, dict):
            for nested in (value.get("result"), value.get("response")):
                if isinstance(nested, dict) and "code" in nested and "data" in nested:
                    return nested
    raise FuyaoMCPError("FUYAO_PROTOCOL_ERROR", "扶摇 MCP 工具结果不含 ApiResponse 信封。")


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]") if secret else value
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    return value


class FuyaoMCPClient:
    """MCP client limited to the data calls used by Niuniu's aggregate tools."""

    def __init__(self, api_key=None, *, http_post=None, timeout=25, now_fn=None):
        self._key = _valid_key(load_api_key() if api_key is None else api_key)
        self._post = http_post or _default_post
        self.timeout = max(1, min(int(timeout), 60))
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._sessions = {}
        self._remote_tools = {}
        self._next_id = 1
        self._lock = RLock()

    @property
    def available(self):
        return bool(self._key)

    def _request(self, service, method, params, *, notification=False):
        if not self.available:
            raise FuyaoMCPError("FUYAO_NOT_CONFIGURED", "扶摇数据源尚未配置凭证。")
        request_id = None if notification else self._next_id
        if not notification:
            self._next_id += 1
        payload = {"jsonrpc": "2.0", "method": method}
        if request_id is not None:
            payload["id"] = request_id
        if params is not None:
            payload["params"] = params
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
            "X-api-key": self._key, "MCP-Protocol-Version": PROTOCOL_VERSION}
        session = self._sessions.get(service)
        if session:
            headers["Mcp-Session-Id"] = session
        status, response_headers, raw = self._post(BASE_URL + SERVICE_PATHS[service], headers,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(), self.timeout)
        if status == 429:
            raise FuyaoMCPError("FUYAO_RATE_LIMITED", "扶摇 MCP 当前限流，请稍后再试。")
        if status < 200 or status >= 300:
            raise FuyaoMCPError("FUYAO_HTTP_" + str(status), "扶摇 MCP HTTP 请求失败（状态 " + str(status) + "）。")
        session = _header(response_headers, "Mcp-Session-Id")
        if session:
            self._sessions[service] = session[:512]
        if notification or status == 202 or not raw.strip():
            return None
        message = _json_message(raw)
        if message.get("error"):
            error = message["error"] if isinstance(message["error"], dict) else {}
            text = _redact(str(error.get("message") or "扶摇 MCP JSON-RPC 错误。"), self._key)
            raise FuyaoMCPError("FUYAO_RPC_ERROR", text[:300])
        return message.get("result")

    def _initialize(self, service):
        result = self._request(service, "initialize", {"protocolVersion": PROTOCOL_VERSION,
            "capabilities": {}, "clientInfo": {"name": "niuniu", "version": "1"}})
        if not isinstance(result, dict):
            raise FuyaoMCPError("FUYAO_PROTOCOL_ERROR", "扶摇 MCP 初始化响应无效。")
        self._request(service, "notifications/initialized", None, notification=True)
        listing = self._request(service, "tools/list", {})
        tools = listing.get("tools", []) if isinstance(listing, dict) else []
        names = {str(item.get("name")) for item in tools if isinstance(item, dict) and item.get("name")}
        if not names:
            raise FuyaoMCPError("FUYAO_PROTOCOL_ERROR", "扶摇 MCP tools/list 未返回工具目录。")
        self._remote_tools[service] = names

    def call(self, service, tool, arguments):
        if service not in SERVICE_PATHS or tool not in ALLOWED_TOOLS.get(service, ()):
            raise FuyaoMCPError("FUYAO_TOOL_REJECTED", "扶摇 MCP 工具不在牛牛固定白名单中。")
        if not isinstance(arguments, dict):
            raise FuyaoMCPError("FUYAO_INVALID_ARGUMENT", "扶摇 MCP 参数必须是对象。")
        with self._lock:
            if service not in self._sessions:
                self._initialize(service)
            if tool not in self._remote_tools.get(service, set()):
                raise FuyaoMCPError("FUYAO_TOOL_UNAVAILABLE", "扶摇 MCP 当前 tools/list 未注册该工具。")
            try:
                result = self._request(service, "tools/call", {"name": tool, "arguments": arguments})
            except FuyaoMCPError as error:
                # A stale session is safe to replace once. Rate limits and business errors are never retried.
                if error.code not in ("FUYAO_HTTP_400", "FUYAO_HTTP_404"):
                    raise
                self._sessions.pop(service, None)
                self._remote_tools.pop(service, None)
                self._initialize(service)
                if tool not in self._remote_tools.get(service, set()):
                    raise FuyaoMCPError("FUYAO_TOOL_UNAVAILABLE", "扶摇 MCP 当前 tools/list 未注册该工具。")
                result = self._request(service, "tools/call", {"name": tool, "arguments": arguments})
        try:
            envelope = _envelope(result)
        except FuyaoMCPError as error:
            raise FuyaoMCPError(error.code, _redact(str(error), self._key), error.request_id) from None
        request_id = _redact(str(envelope.get("request_id") or ""), self._key)[:160]
        code = envelope.get("code")
        if code != 0:
            if code == 4001:
                raise FuyaoMCPError("FUYAO_RATE_LIMITED", "扶摇 MCP 当前限流，请稍后再试。", request_id)
            raise FuyaoMCPError("FUYAO_BUSINESS_ERROR_" + str(code),
                _redact(str(envelope.get("message") or "扶摇数据请求失败。"), self._key)[:300], request_id)
        data = _redact(envelope.get("data"), self._key)
        if not isinstance(data, dict):
            raise FuyaoMCPError("FUYAO_PROTOCOL_ERROR", "扶摇 ApiResponse data 结构无效。", request_id)
        captured = self.now_fn()
        if not isinstance(captured, datetime) or captured.tzinfo is None:
            captured = datetime.now(timezone.utc)
        canonical = json.dumps({"service": service, "tool": tool, "arguments": arguments,
            "response": envelope}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return {"service": service, "tool": tool, "request_id": request_id, "data": data,
            "response_timestamp": data.get("timestamp"), "captured_at": captured.astimezone(timezone.utc).isoformat(),
            "source_hash": hashlib.sha256(canonical).hexdigest()}


__all__ = ["ALLOWED_TOOLS", "ENV_KEY", "FuyaoMCPClient", "FuyaoMCPError", "KEYCHAIN_SERVICE", "load_api_key"]

import json

import pytest

from quantlab.data import research_provider as rp


class FakeResponse:
    def __init__(self, status=200, body=None, text=None):
        self.status_code = status
        self._body = body
        self.text = text if text is not None else json.dumps(body, ensure_ascii=False)

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make(*responses, key="k"):
    return rp.ResearchDataProvider(iwencai_key=key, session=FakeSession(*responses),
                                   intervals={"eastmoney": 0, "cninfo": 0, "sina": 0, "iwencai": 0})


def test_parse_security_forms():
    assert rp.parse_security("300750") == rp.Security("300750", "SZ")
    assert rp.parse_security("sh600519") == rp.Security("600519", "SH")
    assert rp.parse_security("600519.SH") == rp.Security("600519", "SH")
    assert rp.parse_security("920982") == rp.Security("920982", "BJ")
    with pytest.raises(rp.InvalidRequest):
        rp.parse_security("SH600519.SZ")
    with pytest.raises(rp.InvalidRequest):
        rp.parse_security("AAPL")


def test_research_search_requires_key():
    with pytest.raises(rp.ProviderNotConfigured):
        make(key="").research_search("x")


def test_research_search_normalises_and_sends_headers():
    body = {"status_code": 0, "status_msg": "OK", "total": 10, "data": [
        {"channel": "report", "uid": "u1", "title": "<em>标题</em>", "summary": "s", "url": "https://a",
         "score": 0.5, "extra": {"organization": "平安证券", "author": "李", "rating": "强烈推荐"}},
        {"channel": "news", "id": "n1", "title": "t", "publish_time": 1789976280,
         "extra": {"real_publish_source": "科创板日报"}}]}
    provider = make(FakeResponse(body=body))
    result = provider.research_search("宁德时代 储能", channel="report", size=2)
    assert result.status == "ok" and result.total == 10
    assert result.rows[0]["title"] == "标题" and result.rows[0]["source"] == "平安证券"
    assert result.rows[1]["publish_time"] == "2026-09-21 15:38:00"
    method, url, kwargs = provider.session.calls[0]
    assert method == "POST" and url.endswith("/v1/comprehensive/search")
    assert kwargs["headers"]["Authorization"] == "Bearer k"
    assert kwargs["headers"]["X-Claw-Skill-Id"] == "report-search"
    assert kwargs["json"]["channels"] == ["report"]


def test_vendor_error_is_not_empty():
    with pytest.raises(rp.DataProviderError):
        make(FakeResponse(body={"status_code": 1, "status_msg": "bad key"})).research_search("x")
    with pytest.raises(rp.DataProviderError):
        make(FakeResponse(status=502, body={})).stock_fund_flow_daily("300750")
    with pytest.raises(rp.DataProviderError):
        make(FakeResponse(body=None, text="<html>")).stock_research_reports("300750")
    with pytest.raises(rp.DataProviderError):
        make(ConnectionError("down")).financial_statements("300750")


def test_empty_is_explicit():
    result = make(FakeResponse(body={"status_code": 0, "data": []})).research_search("x", channel="news")
    assert result.status == "empty" and result.rows == ()


def test_fund_flow_parse_and_unknown_code():
    line = "2026-09-23,161505200.0,80050336.0,-241555536.0,248378624.0,-86873424.0,2.17,1.08,-3.25,3.34,-1.17,301.00,-1.19,0.00,0.00"
    result = make(FakeResponse(body={"rc": 0, "data": {"klines": [line]}})).stock_fund_flow_daily("300750", days=1)
    row = result.rows[0]
    assert row["date"] == "2026-09-23" and row["main_net"] == 161505200.0 and row["close"] == 301.0
    with pytest.raises(rp.InvalidRequest):
        make(FakeResponse(body={"rc": 100, "data": None})).stock_fund_flow_daily("399999.SZ")


def test_financial_statements_long_format():
    body = {"result": {"status": {"code": 0}, "data": {"report_count": "30", "report_list": {
        "20260630": {"rType": "合并期末", "rCurrency": "CNY", "is_audit": "未审计", "publish_date": "20260725",
                     "data": [{"item_field": "BIZTOTINCO", "item_title": "营业总收入",
                               "item_value": "276916580000.000000", "item_tongbi": 0.548},
                              {"item_field": "INTEINCO", "item_title": "利息收入", "item_value": None}]}}}}}
    result = make(FakeResponse(body=body)).financial_statements("300750", statement="income", periods=1)
    assert len(result.rows) == 1 and result.truncated and result.total == 30
    row = result.rows[0]
    assert row["report_date"] == "2026-06-30" and row["publish_date"] == "2026-07-25"
    assert row["value"] == 276916580000.0 and row["yoy"] == 0.548


def test_announcements_uses_org_map_and_beijing_time():
    stocks = {"stockList": [{"code": f"{i:06d}", "orgId": f"o{i}"} for i in range(1200)]
              + [{"code": "300750", "orgId": "GD165627"}]}
    page = {"totalAnnouncement": 1, "hasMore": False, "announcements": [
        {"announcementTitle": "公告", "announcementTime": 1790160369000, "announcementId": "1",
         "adjunctUrl": "finalpage/2026-09-23/1.PDF"}]}
    provider = make(FakeResponse(body=stocks), FakeResponse(body=page))
    result = provider.stock_announcements("300750", start="2026-09-01", end="2026-09-23")
    assert result.rows[0]["publish_date"] == "2026-09-23"
    assert result.rows[0]["pdf_url"] == "https://static.cninfo.com.cn/finalpage/2026-09-23/1.PDF"
    assert provider.session.calls[1][2]["data"]["stock"] == "300750,GD165627"
    assert provider.session.calls[1][2]["data"]["seDate"] == "2026-09-01~2026-09-23"


def test_investor_qa_rejects_shanghai():
    with pytest.raises(rp.InvalidRequest):
        make().investor_qa("600519")


def test_from_env_reads_dotenv(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("export IWENCAI_API_KEY='abc'\nIWENCAI_BASE_URL=https://x.example/\n", encoding="utf-8")
    provider = rp.ResearchDataProvider.from_env(env={}, dotenv=env_file, session=FakeSession())
    assert provider.iwencai_key == "abc" and provider.iwencai_base == "https://x.example"

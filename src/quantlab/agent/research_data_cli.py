"""CLI for DATA-owned on-demand research APIs.

Read-only network queries only. Vendor selection and correctness belong to DATA.
"""
from __future__ import annotations

import argparse

from quantlab.agent.research_data_tools import ResearchDataAPI
from quantlab.storage.codec import encode


class _NoOtherTools:
    def schemas(self):
        return []

    def call(self, name, args):
        raise ValueError("unsupported tool")


def main(argv=None):
    parser = argparse.ArgumentParser(description="牛牛DATA研究查询接口；只读、不落盘、不换源")
    parser.add_argument("--catalog")
    commands = parser.add_subparsers(dest="command", required=True)

    search = commands.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--channel", choices=("report", "news", "announcement"), default="report")
    search.add_argument("--size", type=int, default=10)

    reports = commands.add_parser("reports")
    reports.add_argument("--code", required=True)
    reports.add_argument("--limit", type=int, default=20)

    news = commands.add_parser("news")
    news.add_argument("--code", required=True)
    news.add_argument("--limit", type=int, default=20)

    announcements = commands.add_parser("announcements")
    announcements.add_argument("--code", required=True)
    announcements.add_argument("--start", default="")
    announcements.add_argument("--end", default="")
    announcements.add_argument("--limit", type=int, default=20)

    financials = commands.add_parser("financials")
    financials.add_argument("--code", required=True)
    financials.add_argument("--statement", choices=("income", "balance", "cashflow"), default="income")
    financials.add_argument("--periods", type=int, default=4)

    qa = commands.add_parser("investor-qa")
    qa.add_argument("--code", required=True)
    qa.add_argument("--limit", type=int, default=20)

    parsed = parser.parse_args(argv)
    api = ResearchDataAPI(_NoOtherTools(), data_catalog_path=parsed.catalog)
    if parsed.command == "search":
        name, args = "research_search", {"query": parsed.query, "channel": parsed.channel, "size": parsed.size}
    elif parsed.command == "reports":
        name, args = "stock_research_reports", {"code": parsed.code, "limit": parsed.limit}
    elif parsed.command == "news":
        name, args = "stock_news", {"code": parsed.code, "limit": parsed.limit}
    elif parsed.command == "announcements":
        name, args = "stock_announcements", {
            "code": parsed.code, "start": parsed.start, "end": parsed.end, "limit": parsed.limit}
    elif parsed.command == "financials":
        name, args = "financial_statements", {
            "code": parsed.code, "statement": parsed.statement, "periods": parsed.periods}
    else:
        name, args = "investor_qa", {"code": parsed.code, "limit": parsed.limit}
    result = api.call(name, args)
    print(encode(result))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())

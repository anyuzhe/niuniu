"""Export an auditable daily-factor context dataset on existing 5m bars."""

import argparse
from datetime import date
from pathlib import Path
from uuid import uuid4

from quantlab.app import default_registry
from quantlab.data.base import DataRequest
from quantlab.data.mqc import MQCParquetProvider
from quantlab.domain import Timeframe
from quantlab.multitimeframe.engine import MultiTimeframeEngine
from quantlab.storage.codec import encode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--daily-start", type=date.fromisoformat, required=True)
    parser.add_argument("--lookback", type=int, default=20)
    args = parser.parse_args()
    symbols = tuple(args.symbols)
    result = MultiTimeframeEngine(MQCParquetProvider(args.data_root), default_registry()).load(
        DataRequest(symbols, Timeframe.MIN5, args.start, args.end),
        DataRequest(symbols, Timeframe.DAILY, args.daily_start, args.end),
        "BASE.MOMENTUM", parameters={"lookback": args.lookback})
    destination = args.output.resolve() / f"context-{uuid4()}"
    destination.mkdir(parents=True, exist_ok=False)
    result.frame.write_parquet(destination / "context.parquet")
    (destination / "manifest.json").write_text(encode({"context_id": result.context_id, **result.manifest}), encoding="utf-8")
    available = result.frame["context_available_at"].count()
    valid = result.frame["context_value"].count()
    (destination / "report.md").write_text(
        f"# 日线因子 → 5 分钟线背景\n\n数据集：`{result.context_id}`\n\n"
        f"- 5 分钟线行数：{result.frame.height}\n- 匹配到已可用日线：{available}\n- 日线因子非空：{valid}\n\n"
        "按标的和 available_at 向后匹配，允许信息时间相等。日线背景可跨交易日沿用，无自动过期规则；最新行为空时不回退到旧值。\n\n"
        "context_datetime / context_available_at 保留日线来源及可用时刻；未匹配时为空。\n\n"
        "这是对齐数据集，不是收益回测；未生成交易信号，未接入实验筛选条件或 DuckDB 实验索引。"
        "当前只支持已有日线和 5 分钟线，不重采样其他周期。复权与历史股票池限制仍适用。\n",
        encoding="utf-8")
    print(encode({"context_id": result.context_id, "artifact_path": destination, "rows": result.frame.height}))


if __name__ == "__main__":
    main()

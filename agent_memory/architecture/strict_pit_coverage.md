# Strict PIT Coverage

Strict PIT Coverage 是证据缺口地图，不是数据集证书，也禁止生成误导性的“整体完成百分比”。

## 固定语义

- `strict_evidence` 只统计通过 PIT Evidence Archive 深度校验的 receipt；官方原文或 receipt 被篡改后不得计入。
- 四类维度固定为 `universe_eligibility / security_status / industry_membership / daily_market_cap`。
- 可以按年份、证券、日期范围查询 evidence presence；presence 不证明该时间段没有遗漏其他历史变更。
- `overall_strict_pit_coverage_ratio` 必须保持 `None`，除非未来定义了可证明完整的外部基准全集和分母合同。
- `dataset_strict_pit_certified=false`；只有具体研究请求经过 `qualify_research_data` 全时点检查后才能叫 `strict_pit qualified`。
- 回顾性 `stock_basic`、单快照 industry、历史 bars 与 `fetch_ts` 只能进入 inventory，不得计入 strict evidence。

## 性能与权限

- 真实 MQC 默认优先使用只读 `catalog/mqc.duckdb` 做历史 bar inventory；没有 catalog 时才回退 Parquet metadata，不扫描数值列做统计结论。
- System Health 不在页面刷新时深扫 5215 个 Parquet；PIT statement 只展示轻量 receipt 数量/工具入口。Official MarketRules v2 可深验其受控 receipt/官方文档小库，但必须明确这是全局 archive inventory，规模增长后需保持有界。
- `niuniu-pit-coverage`、AI/MCP `get_strict_pit_coverage` 和桌面 Coverage 均只读；模型无 archive/download/certify 权限。
- 当前 `/Volumes/Lexar/niuniu-data` 已有 `security_status=14` verified receipts（7只股票），其它三类仍为 0；历史 bars 很多不改变覆盖不完整这一事实。

当前真实 inventory 基线：Baostock 日线 5215 个证券文件、17075243 行、1990-12-19～2026-09-04；bar lake 无 `tradestatus/isST`；`stock_basic` 8940 行；industry 5546 行且只有 2026-08-31 单一快照。上述均是候选/回顾性资料，不是 strict PIT coverage。

任何后续 Strict PIT 数据收集任务先读取本文件与 `strict_pit_evidence.md`，按 Coverage gap 排序，不得因为数据量大就降低 publication evidence 门槛。

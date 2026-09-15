# 牛牛 AI 交易工作台：Strict PIT Coverage v1 验收说明

- 日期：2026-09-15
- 范围：Strict PIT evidence presence / retrospective inventory / gap diagnostics
- 基线：Strict PIT Evidence Archive v1 已完成；真实 MQC receipt 仍为 0
- 本阶段不下载、推断或补造任何历史官方资料

## 1. 目标

Strict PIT Evidence Archive 已解决“严格证据怎么归档和验证”，但仍缺一张能回答以下问题的缺口地图：

1. 哪一类 strict receipt 已经存在；
2. 哪些年份、哪些证券有 evidence presence；
3. 当前数据湖里有哪些只能回顾性使用的候选资料；
4. 真正缺的是 K 线，还是资格/ST/停牌、行业历史、每日市值；
5. 后续官方资料收集应该先补哪一块。

Coverage v1 只做诊断，不认证整个数据湖，也不生成误导性的“Strict PIT 总完成率”。
## 2. 新增能力

新增 `strict_pit_coverage()`：

- 深度验证 PIT Evidence receipt 和官方原文字节；篡改记录不计入严格证据；
- 固定统计 `universe_eligibility / industry_membership / daily_market_cap` 三类 evidence；
- 支持按 `symbols / start / end` 过滤；
- 每类输出 verified statements、unique symbols、effective/publication 日期范围；
- 按年份输出 statement 数、证券数和有限证券样例；
- 对显式查询证券列出有证据与缺证据证券；
- 同时读取回顾性 `stock_basic / industry / bar lake / silver table` inventory；
- 输出结构化 gap code，供后续数据采集排优先级。

固定边界：`overall_strict_pit_coverage_ratio=None`，`dataset_strict_pit_certified=false`。具体研究只有通过 `qualify_research_data` 才能声称 `strict_pit qualified`。

新增 `niuniu-pit-coverage` CLI、AI/MCP 只读工具 `get_strict_pit_coverage`，以及桌面“Baostock 历史资料 → 查看当前 Strict PIT Coverage”。
## 3. 真实 MQC Coverage 基线

对 `/Volumes/Lexar/MQC-DATA` 只读检查：

- Strict receipts：universe=0、industry=0、daily market cap=0；
- Baostock 日线：5215 个证券文件、17,075,243 行；
- 日线日期范围：1990-12-19 ～ 2026-09-04；
- 日线文件 `tradestatus`：0 / 5215；`isST`：0 / 5215；
- 全部日线带 `fetch_ts`，但它是 2026 年采集时间，不是历史 publication time；
- `stock_basic.parquet`：8940 行/代码，IPO 范围 1990-12-10 ～ 2026-09-04，仍是回顾性资料；
- `industry.parquet`：5546 行，其中 5212 行行业非空；只有 2026-08-31 一个 snapshot；
- `lake/silver/security_status / industry_membership / index_membership / security_master / market_rule_history / trading_calendar` 当前均无 Parquet。

因此当前真正缺口不是历史 OHLCV 数量，而是可证明 publication time 的资格/ST/停牌事件链、行业历史变更链与每日市值链。
## 4. 性能与权限

真实 MQC Coverage 优先读取只读 `catalog/mqc.duckdb`；一次完整真实查询约 2.8 秒。没有 catalog 时才回退逐 Parquet metadata 扫描。

System Health 只展示 receipt 数量、按类计数和 Coverage 工具入口，不在每次健康刷新时深扫数据湖。

AI/MCP 只能调用 `get_strict_pit_coverage`；没有 archive、download、certify、write 等 Coverage/PIT 权限。桌面 Coverage 同样只读。

真实 smoke 指定 `sh.600000 / sz.000001`、2025-01-01～2026-09-15：三类 strict evidence 均缺，明确返回两只证券的 missing evidence；查询前后 `artifacts` 文件数 `77006 → 77006`。

## 5. 测试

- Coverage + Evidence + Qualification：18/18；
- Coverage + System Health/UI：19/19；
- Baostock/Series/MarketSnapshot/Session Coverage/Candidate Review：43/43；
- 完整仓库：**956 tests / 0 failed / 0 skipped**，412.711 秒。

下一阶段不再继续扩 Coverage 框架，直接按 gap 开始真实官方资料采集与 receipt coverage 提升；优先顺序为历史资格/ST/停牌 → 行业历史变更 → 每日真实市值 → 逐日特殊交易制度。

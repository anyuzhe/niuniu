# DATA → CODE 数据清单

[文档导航](../README.md) · [数据与证据](../guide/data-and-evidence.md) · [当前状态](../project/status.md)

本文件是 **DATA → CODE 的唯一日常数据交接入口**。DATA 负责数据本身；CODE 只负责使用 DATA 已交付的数据。

最近一次 DATA 审查：2026-09-23（数据侧整改分支 `data-remediation`）。机器可读的同源清单是数据根里的 `catalog/dataset_registry.json`（注册表，见[数据与证据 §14](../guide/data-and-evidence.md)）；本表与注册表由 DATA 同步维护，二者不一致时以 DATA 更正为准，CODE 不自行取舍。

## 1. 责任边界

**DATA 全责：** 数据采集、来源选择、版本/修订选择、公司行动裁决、去重/规范化、单位和精度、完整性、覆盖范围、Strict PIT 资格、factor/qfq 重建、影响审计、发布与回滚。DATA 只有在确认某项数据可以给产品使用后，才把状态改为 `READY`。

**CODE 不负责：** 判断哪家供应商正确、重新裁决公司行动、比较多个来源选赢家、重算 factor/qfq 验证 DATA、重新认证 PIT、替 DATA 判断数据是否完整。CODE 不遍历数据根寻找“最新”或备用数据。

**CODE 只负责：** 根据本文件给出的绝对路径读取 `READY` 数据并实现产品功能。如果路径不存在、权限不足、文件损坏到无法解析或格式与 reader 不兼容，应明确报技术错误；不能自动换其它来源或自行修数据。

## 2. 状态定义

- `READY`：DATA 已确认该数据可供 CODE 按本表说明使用；数据正确性和适用范围由 DATA 负责。
- `NOT_READY`：DATA 明确尚不可供 CODE 使用；对应产品能力应保持未就绪/blocked。
- `REVIEW_REQUIRED`：当前已发现数据或路径，但 DATA 尚未完成本清单审查；**等同于不可供 CODE 正式使用**。
- `DEPRECATED`：DATA 已停止该数据；CODE 应迁移到 DATA 指定的替代项，不自行选择替代路径。

`READY` 只表示“可按本表说明使用”，**不等于 Strict PIT**。每项的资格写在“覆盖 / 用途”一列；除非明确写出 Strict PIT，一律是 `research_only` 或回顾性参考。

## 3. 可供 CODE 使用的数据（READY）

| 数据 ID | 数据内容 | 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |
|---|---|---|---|---|---|---|
| `bars_daily_baostock_raw` | Baostock 日K，不复权 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=baostock/stock_kline_daily` | 每只证券一个 `<sh_600000>.parquet`；列 `date, code, open, high, low, close, volume, amount, adjustflag(=3), fetch_ts`；主键 `(code, date)` | 5,222 只在市 A 股（2026-09-23 参考快照 `type=1, status=1`），1990-12-19 至 **2026-09-22**，约 1,714 万行，单一 schema、0 重复。research_only | `READY` | 直接读取。是否可交易必须连接 `security_status_baostock_v2`，不能把“有K线行”当作可交易 |
| `bars_min5_baostock_raw` | Baostock 5分钟，不复权 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=baostock/stock_kline_min5` | 每只证券一个 parquet；列同日K另加 `time`（`YYYYMMDDHHMMSSmmm`）；主键 `(code, date, time)`；交易日每只 48 根 | 5,222 只，**2020-01-02**（供应商下限）至 2026-09-22，约 3.63 亿行。research_only | `READY` | 直接读取；2020 年前没有 5 分钟数据，不要从日K推算 |
| `security_status_baostock_v2` | 日状态：交易/停牌、ST | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=baostock/daily_status_v2` | 每只证券一个 parquet；列 `date, code, tradestatus, isST`；`tradestatus=0` 为停牌（保留，不删行）；主键 `(code, date)` | 5,222 只，1990-12-19 至 2026-09-22，约 1,714 万行。供应商回顾性状态，**不是 Strict PIT** | `READY` | 用于停牌/ST 判断与研究过滤；需要 Strict PIT 时用 `strict_pit_security_status_f26`（未就绪） |
| `reference_snapshot_baostock_20260923` | 2026-09-23 参考快照：交易日历、证券基础信息、行业、全市场列表、上证50/沪深300/中证500成分 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=baostock/reference_snapshots/snapshot=2026-09-23` | 7 个 parquet（`trade_calendar, stock_basic, industry, all_stock, sz50, hs300, zz500`）+ `manifest.json`（逐文件 SHA256） | 观察日 2026-09-23；在市 A 股 5,222 只；交易日历至 2026-09-23。行业与成分是**观察日当时的快照，不能回填历史**。retrospective_reference | `READY` | 按本表写明的这一个快照日期读取；DATA 发布新快照时会在这里改日期，CODE 不自行找“最新快照” |
| `capture_root` | 捕获包根目录：回溯日线、DailyMarket、公开证据（涨跌停池、龙虎榜、板块、人气）、前瞻参考、Baostock 导入 | `/Volumes/Lexar/niuniu-data/lake/_market_data` | 各子目录格式不变（`retro_daily/<capture_id>/`、`daily_market/<日期>/`、`public_evidence/<来源>/<日期>/` 等），根目录有 `CAPTURE_ROOT.json` | 2026-09-23 从 `artifacts/_market_data` 复制迁入（1,800 文件逐一核 SHA）；工作空间经 `artifacts/_market_data.redirect.json` 指向这里。research_only | `READY` | 继续通过产品已有的 `capture_root()`/各 Store 读取；不要直接读 `artifacts/_market_data`（已冻结，只为历史路径保留） |

## 4. 尚不可用或只供 DATA 内部使用

| 数据 ID | 数据内容 | 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |
|---|---|---|---|---|---|---|
| `qfq_daily_existing` | 旧前复权日线（旧 MQC 构建） | `/Volumes/Lexar/niuniu-data/lake/silver/qfq_kline_daily` | 每只证券一个 parquet；`date, code, open, high, low, close, volume, amount, factor` | 截止 **2026-09-04**（比原始日K落后 12 个交易日）；来源为东财旧分红，构建脚本不在仓库、不可复现；漏掉早年配股和部分特别分红 | `DEPRECATED` | 替代项为 `qfq_published_f24`。在它 `READY` 之前，现有产品默认 qfq 仍读此目录，但只作过渡，不得作为新功能的正式输入 |
| `qfq_min5_existing` | 旧前复权 5 分钟 | `/Volumes/Lexar/niuniu-data/lake/silver/qfq_kline_min5` | 同上加 `time` | 截止 2026-09-04；问题同上 | `DEPRECATED` | 同上 |
| `qfq_daily_v2` | qfq 重建候选（F23） | `/Volumes/Lexar/niuniu-data/lake/silver/qfq_kline_daily_v2` | 列同旧 qfq；`factor` 以最后一根为 1 | 5,222 只至 2026-09-22；54,712 个事件经双源确认；4,588 只与旧版逐日一致；452 只存在无法双源确认的事件，只从最后一个未确认事件日起给出历史 | `NOT_READY` | 不读取。DATA 审完差异报告、确定单源事件处理规则后，以 `qfq_published_f24` 发布 |
| `qfq_min5_v2` | qfq 5 分钟重建候选（F23） | `/Volumes/Lexar/niuniu-data/lake/silver/qfq_kline_min5_v2` | 同上加 `time` | 构建中 | `NOT_READY` | 不读取 |
| `adjustment_factors_v2` | 逐事件复权因子与来源裁决记录 | `/Volumes/Lexar/niuniu-data/lake/silver/adjustment_factors_v2` | 每只证券一个 parquet；每行一个除权日：现金/送股/转增/配股、来源组合、`factor`、`status`（accepted/blocked/ignored）、`blockers` | F23 内部产物 | `NOT_READY` | 不读取；它是 DATA 的审计记录，不是产品接口 |
| `corporate_actions_allotment_cninfo_v2` | 巨潮配股（原始） | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=cninfo/corporate_actions_allotment_v2` | 供应商全列，文件间列签名不统一 | 644 只（TDX 历史配股 ∩ 在市）；2026-09-23 已每日再观察 | `NOT_READY` | DATA 内部治理输入，不对 CODE 发布；CODE 需要公司行动时使用 `company_action_decisions_f22` |
| `corporate_actions_dividend_ths_v2` | 同花顺分红（原始） | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=ths/corporate_actions_dividend_v2` | 供应商全列，含方案原文 | 5,222 只 | `NOT_READY` | 同上 |
| `corporate_actions_dividend_baostock_v2` | Baostock 分红（原始） | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=baostock/corporate_actions_dividend_v2` | 供应商全列，保留 83 条供应商重复 | 5,222 只，2004 年起 | `NOT_READY` | 同上 |
| `tdx_capital_changes` | TDX 股本变动/除权除息（原始） | 通过 `/Volumes/Lexar/niuniu-data/catalog/mqc.duckdb` 视图 `tdx_capital_changes` 读取（`lake/bronze/provider=tdx/capital_changes` 只剩 schema，页数据在 `catalog/tdx_page_archive.sqlite3`） | 每行一条供应商记录，字段在 `record_json` | 个人研究采集，`vendor_observation_personal_research_not_pit` | `NOT_READY` | 同上 |
| `auction_tdx_raw` | TDX 集合竞价（原始） | 通过 `catalog/mqc.duckdb` 视图 `tdx_auction` 读取 | 同一事件多个观察版本，单位未统一 | 沪深采集调度下界 2025-07-22；未治理 | `NOT_READY` | F25 之前不作为 Auction 输入 |
| `company_action_decisions_f22` | 最终公司行动决策数据 | **由 DATA 填写** | 由 DATA 定义 | F23 输入 | `NOT_READY` | 仅变为 `READY` 后读取 |
| `qfq_published_f24` | 正式发布的 qfq（日线、5分钟） | **由 DATA 填写**（预计为 `qfq_kline_daily_v2` / `qfq_kline_min5_v2` 审定后的路径） | 由 DATA 定义 | 正式研究/回测输入 | `NOT_READY` | 仅变为 `READY` 后读取 |
| `auction_governed_f25` | 统一版本/单位后的 Auction | **由 DATA 填写** | 由 DATA 定义 | Auction 产品/研究输入 | `NOT_READY` | 仅变为 `READY` 后读取 |
| `strict_pit_universe_f26` | Strict PIT Universe | **由 DATA 填写** | 由 DATA 定义 | 严格历史资格 | `NOT_READY` | 仅变为 `READY` 后读取 |
| `strict_pit_security_status_f26` | Strict PIT Security Status | **由 DATA 填写** | 由 DATA 定义 | ST/停牌/上市状态 | `NOT_READY` | 仅变为 `READY` 后读取 |
| `strict_pit_market_rules_f26` | Strict PIT Market Rules | **由 DATA 填写** | 由 DATA 定义 | 涨跌停/特殊制度等 | `NOT_READY` | 仅变为 `READY` 后读取 |

旧的零散数据（东财 1 分钟 5 只、新浪/腾讯日K各 14 只、同花顺/巨潮/Baostock 分红的 v1 与试采目录、东财旧分红）已在注册表中标为 superseded 或 legacy，不对 CODE 发布，这里不再列出。

## 5. DATA 更新规则

DATA 新增或修改可供 CODE 使用的数据时，只需要更新对应表项：数据 ID、内容、绝对路径、格式/粒度、覆盖范围、状态和必要使用说明。路径变更、版本替换、停用旧数据也在这里改；不要求 CODE 了解 DATA 内部采集脚本、bronze/silver 分层、证据目录或治理过程。

如果同一种业务数据存在多个内部来源或多个历史版本，DATA 应在完成治理后只向 CODE 指定**当前应该使用的那一项**；CODE 不自行在多个目录中选择。需要保留历史版本时可以在 DATA 内部保留，但只有本表明确标为 `READY` 的路径属于 CODE 的正式数据接口。

每日增量采集会让 `READY` 数据的“覆盖”末端向后推进；DATA 在每次获批采集完成后更新本表的截止日期。

## 6. CODE 使用规则

CODE 开发或运行前先查本表。需要的数据为 `READY` 时按指定路径读取；为 `NOT_READY` / `REVIEW_REQUIRED` / 未登记时，直接报告“数据侧尚未交付该数据”，不要扫描数据湖补找来源。

CODE 可以为稳定读取实现 reader、缓存和产品层格式转换，但这些只属于消费逻辑；不能因此修改 DATA 状态，也不能把 reader 测试通过写成“数据已验证正确”。如果 CODE 发现实际文件与本表描述无法读取，应把问题反馈给 DATA，由 DATA 决定修数据、改路径还是更新本表。

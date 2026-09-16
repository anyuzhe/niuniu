# Strict PIT Security Status

`security_status` 保存经过官方原文与 publication-time receipt 深验的证券状态。状态字段为 `symbol / effective_at / available_at / tradable / risk_warning / source`，`risk_warning` 只允许 `NONE / ST / STAR_ST / UNKNOWN`。

## 两层证据

1. `niuniu-pit-evidence-v1` 的 `security_status` statement 证明一条明确事件；它不能证明期间没有遗漏事件，也不得跨日传播。
2. `niuniu-security-status-coverage-v2` 绑定一个 exact-session `niuniu-pit-universe-v1`，要求 Universe 每个 member 都有当日 `TRADABILITY + RISK_WARNING` 状态、匹配交易所的官方来源、原文字节和 `source published_at <= source available_at <= status created_at <= cutoff_at <= 09:15 Asia/Shanghai`；Universe `created_at` 也不得晚于status归档。只有这层能证明逐日完整覆盖。

v2 receipt 位于 `<data-root>/research/security_status_coverage/<status_snapshot>.json`，官方原文字节位于其 `documents/<sha256>.bin`。归档器只读本地文件、不联网，并要求宿主分别确认 publication time、状态语义和全 Universe 完整性。`UNKNOWN` 可以被完整记录，但该 receipt 的 `strict_pit_eligible=false`。

## 连续状态链

- 首个 snapshot 是 root，只证明初始观测，不冒充“进入”；单日状态可Strict，但transition只有前后两份receipt都Strict时才具Strict资格。
- 后续 snapshot 必须显式绑定 `previous_status_snapshot`，且宿主确认它是相邻交易 session，才能生成进入/持续/撤销：`SUSPENSION_ENTERED/CONTINUED/CLEARED`、`RISK_WARNING_ENTERED/CONTINUED/CLEARED/CHANGED`。
- 缺 previous link、Universe 进出、同 session 多 snapshot 或 previous link 分叉都不得冒充连续状态；chain/materialization 对歧义 fail-closed。
- `security_status_chain(...)` 和 `niuniu-security-status-coverage --call chain` 只读输出单证券链。

## 派生表与消费边界

- `lake/silver/security_status/security_status.parquet` 合并 verified 稀疏 statements 与完整逐日 v2 receipts；receipt 集合变化、分叉、歧义或表哈希变化后必须重新物化。
- 同证券同一 `effective_at` 同时存在一致 sparse/v2 状态时保留完整 v2 行；冲突则拒绝物化。不同生效时刻的日内事件继续独立保留。
- PREP 仅使用状态 `effective_at` 对应的 exact session，不向前或向后传播；v2 行标记为 `STRICT_PIT_DAILY_COVERAGE`。
- 已验证 ST/停牌状态不等于官方逐日涨跌停规则。缺 MarketRules 时，即使状态完整，PREP 仍保持 `RETROSPECTIVE_REFERENCE`。
- SecurityStatus 不等于 PIT Universe；股票池成员资格与 ST/停牌是不同维度。

## 当前真实数据

`/Volumes/Lexar/niuniu-data` 现有 7 份深交所官方公告、7 只证券、14 条稀疏 security_status statements；它们不代表全市场或完整历史链。截至 v2 工程完成时，真实完整逐日 SecurityStatus v2 receipt 仍为 0，不得升级证据等级。第二批来源与验收见 `../../牛牛AI交易工作台_StrictPITSecurityStatus第二批验收说明.md`。

2026-09-16 的目标日前语义复核确认：SSE IS124/IS120可证明产品状态与TradingPhaseCode语义；SZSE v1.42只证明经FTS私有下发的 `securities` 日文件及Status 1/4/5，公开站内搜索与10个受限静态路径均未找到目标日批量文件；BSE v1.1只证明FDEP `bj_securityinfo` 文件，公开 `xxtpbz/xxzrzt` 字典未闭合。规范不能替代目标日实际值，名称、缺公告或字段常量不能推导 `NONE`。因此三所完整状态未同时闭合时，v2 receipt必须继续为0。

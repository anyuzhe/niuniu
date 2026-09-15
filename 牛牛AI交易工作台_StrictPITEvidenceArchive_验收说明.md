# 牛牛 AI 交易工作台 · Strict PIT Evidence Archive v1 验收说明

- 日期：2026-09-15
- 范围：历史资格 / 行业 / 每日市值的 publication evidence 与 Strict PIT 升级门
- 结论：证据归档与验证基础设施完成；真实历史资料覆盖仍需持续补充

> 后续更新：Evidence Archive 已增加 `security_status`；Official MarketRules 使用独立的 publication receipt v2，按 snapshot append-only 保存实际规则 records，并已归档首批7个真实停牌 session。详见《牛牛AI交易工作台_OfficialMarketRulesPublicationReceiptV2_验收说明.md》。本文其余内容保留 v1 当轮口径。

## 1. 本轮解决的问题

此前牛牛已经支持 PIT Universe 的 `effective_at + available_at`，Industry/Size 控制也保存时间与 source，但存在两处缺口：

1. 磁盘中的 `universe_events.parquet` 没有正式 provenance receipt，因此真实文件永远只能是 timing contract，无法通过 Strict PIT provenance gate。
2. Industry / market-cap 的 Strict PIT 只校验 source 字符串是否来自交易所/CNINFO 域名，没有要求本地保存对应官方原文字节。

v1 新增 `PIT Evidence Archive`，把 statement、官方来源、publication time 和原文字节绑定成 checksummed receipt。

## 2. 新增合同

支持三类证据：

- `universe_eligibility`
- `industry_membership`
- `daily_market_cap`

每条 receipt 绑定：

- statement digest
- authoritative HTTPS source URL
- `published_at`
- `available_at`
- 本地归档官方原文路径与 SHA256
- `fetched_at`
- 宿主明确 publication-time confirmation

`published_at > available_at`、非权威域名、原文/receipt 篡改全部 fail-closed。

## 3. 产品接入

新增宿主 CLI：`niuniu-pit-evidence`。

- `list`：只读查看 receipt 数量与分类。
- `verify`：核对指定 statements 是否都有有效 publication evidence。
- `archive`：把本地官方原文复制到数据根并生成 receipt；必须显式 `--confirm-publication-time`。
- CLI 不自动联网下载官方文件，避免把抓取时间误当历史首次可用时间。

System Health 的 PIT/Playbook 组件新增 `pit_evidence` 计数与损坏告警。

PIT Universe receipt 全覆盖后，`build_universe()` metadata 才能标记 `historical_publication_verified=true`。Industry/market-cap 也必须存在 receipt 才能通过对应 Strict PIT 控制项。

## 4. 兼容与边界

- 旧 `research_only / retrospective_reference` 研究不受影响。
- 旧 PIT records 没有 receipt 时继续可运行 PIT 时间逻辑，但资格层只认 timing contract，不自动升级 Strict PIT。
- Approval-time Freeze 保存已验证的 Universe metadata 与 qualification receipt；批准后执行不回退 mutable source。
- receipt 证明的是“宿主把该 statement 映射到已归档权威文档，并确认其 publication time”；v1 不做自然语言语义抽取，也不声称自动证明文档内容。
- Baostock 的 `isST/tradestatus/industry` 仍属于回顾性资料；不能因为 Evidence Archive 存在就自动获得历史 publication time。

## 5. 验收

- PIT Evidence + Qualification + Universe 核心：**15/15**。
- Qualification / Neutralization / Approval Freeze / Proposal / System Health / Session Grant 联合：**75/75**。
- 完整仓库：**950 tests / 0 failed / 0 skipped**，443.920 秒。
- 真实 `/Volumes/Lexar/MQC-DATA` receipt 数：**0**；只读 smoke `artifacts 77006 → 77006`。

因此本轮完成的是 Strict PIT 历史证据基础设施，不是历史资料覆盖本身。下一步应开始按优先级归档真实官方历史资格/行业/市值资料，并量化 coverage。

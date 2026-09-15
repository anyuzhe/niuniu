# Strict PIT Evidence Archive

Strict PIT 不是“记录里写了官方 URL”就成立。任何历史资格、行业或市值控制要升级为严格 PIT，必须同时保留可审计的 publication evidence。

## v1 证据合同

- 支持 `universe_eligibility / industry_membership / daily_market_cap` 三类 statement。
- 每条 statement 必须有明确 `effective_at` 与 `available_at`；industry/market-cap 还必须引用权威 HTTPS source。
- Receipt 必须绑定：规范化 statement digest、权威 source URL、宿主明确确认的 `published_at`、本地官方原文字节、SHA256 与 `fetched_at`。
- `published_at` 不得晚于 statement 的 `available_at`；禁止通过事后抓取时间反推历史可用时间。
- 官方原文或 receipt checksum 任一被修改，验证必须 fail-closed。
- 同一 statement + source + publication_at + document SHA 重复归档必须幂等，`fetched_at` 不参与 evidence identity。

## Qualification / Freeze 边界

- PIT Universe 只有 `effective_at + available_at` 但没有 receipt 时，只能是 `timing_contract_only`；receipt 全覆盖后才允许 `historical_publication_verified=true`。
- Industry / daily market cap 的 Strict PIT 不再只检查 URL 域名；缺 receipt 时分别产生 publication-evidence blocker。
- `research_only / retrospective_reference` 不因 v1 证据门变严而失效；它们继续按原口径使用回顾性资料。
- Approval-time Actual-byte Freeze 会冻结已验证的 universe metadata 与资格回执，执行/恢复不得重新解释成更高或更低等级。
- `niuniu-pit-evidence` 是宿主工具；archive 必须显式 `--confirm-publication-time`，CLI 不自动下载官方网页。
- System Health 的 PIT/Playbook 组件显示 receipt 数量；receipt 损坏显示 WARN，不能静默当作空库。

当前真实 MQC 数据根没有自动获得任何 receipt。没有逐条归档官方材料前，禁止把“Evidence Archive v1 已实现”写成“历史 Strict PIT 覆盖已完成”。

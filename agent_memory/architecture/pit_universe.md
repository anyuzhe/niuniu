# PIT Universe Receipt

PIT Universe 的“全集完整性”不能由零散 `universe_eligibility` statement、当前证券列表、上市日期或历史 bar 文件推断。

## v1 固定合同

- 一个 `niuniu-pit-universe-v1` snapshot 只对应一个 `effective_session` 和明确 scope：`CN_A_SHARE + exchanges + A_SHARE + FULL_OFFICIAL_LIST`。
- receipt 必须绑定全部成员、逐成员 source_id、逐来源交易所 HTTPS URL、本地官方原文字节、SHA256、`published_at / available_at`、`created_at / cutoff_at`。
- 时间链必须满足 `published_at <= available_at <= created_at <= cutoff_at <= session 09:15 Asia/Shanghai`。
- 首次归档晚于 cutoff 必须拒绝；相同已验证 snapshot 的后续重读可幂等返回，不重写 receipt。
- archive 只读本地文件且不联网；宿主必须分别确认 publication time、语义映射和全集完整性。
- source host 必须与 SSE/SZSE/BSE 声明匹配；成员 prefix 必须与其 source exchange 匹配。
- receipt 和文档都不可为 symlink；文档内容寻址保存于 `research/pit_universe/documents/<sha256>.bin`，receipt 保存于 `research/pit_universe/<snapshot>.json`。

## 请求与 PREP 资格

- `UniverseConfig(mode="pit", pit_snapshot_ids=...)` 对每个请求 bar session 要求恰好一个深验通过且 scope 覆盖请求交易所的 receipt；缺失、歧义或 scope 缺口均 fail-closed。
- legacy `research/universe_events.parquet` 继续可作 timing contract，但不能再通过完整 Universe 资格门。
- PREP 必须同时传 `universe_snapshot` 与目标 `universe_effective_session`；receipt session 必须等于目标 trading day。
- PREP 扫描集合必须等于 receipt 的全部 members；禁止使用子集后把 CandidateSet 标成 FULL。
- 调用方布尔值 `universe_pit_verified=True` 没有认证权，不能替代 receipt。
- snapshot 必须进入 source hash、MarketSnapshot、CandidateSet universe_source 和 evidence IDs；approval-time freeze 必须保存实际 receipt membership。

## 解释边界

- `FULL` 只针对 receipt 明确声明的交易所与 A-share instrument scope，不自动覆盖其它市场/证券类型。
- System Health / Coverage 的 receipt 数量是全局完整性 inventory，不证明某个 CandidateSet 已引用对应 snapshot。
- PIT Universe 通过不代表 SecurityStatus、MarketRules、bar vintage、行业、市值或财报 PIT 已通过。
- 当前真实 `niuniu-data` 尚无 v1 receipt；必须在未来 session cutoff 前经宿主授权取得真实官方字节，不允许用当前列表回填历史。

## 2026-09-17 前瞻准备边界

2026-09-16 的 review-only 基线为 SSE 2,318、SZSE 2,901、BSE 344，共5,563只 A_SHARE；它只用于目标日上午 diff。父 capture 与独立 semantic addendum 位于 `staging/pit_universe_security_status/2026-09-17/`，保存官方响应、规范、headers和SHA256，但不是receipt。目标日必须重新刷新三所、官方日标记、分页总数、证券类型和加入/退出；publication time、语义映射、完整官方全集三项确认均成立且仍早于09:15时，才可归档。HTTP Date、文件名日期、规范版本日期或9月16日成员均不能替代这些门。

该session现有一次性无人值守例外：用户明确选择条件式自动归档，LaunchAgent `com.niuniu.pit-20260917` 于08:00执行固定官方白名单抓取，09:10安全停止。它只能把机器验证结果转成确认，不能把授权本身当确认；任一来源没有明确publication timestamp，或完整性/语义检查失败时，Universe receipt必须继续为0。授权不延续到其它session。

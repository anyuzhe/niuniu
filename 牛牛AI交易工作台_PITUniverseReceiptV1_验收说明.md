# 牛牛 AI 交易工作台：PIT Universe Receipt v1 验收说明

- 完成日期：2026-09-16
- 范围：官方证券全集离线归档、逐交易日快照、Qualification / PREP / Daily Orchestrator 接线、深度审计
- 数据边界：本轮只完成代码合同与合成验收，**没有联网，也没有为真实数据根伪造或回填历史 Universe receipt**

## 1. 本轮解决的问题

旧 `universe_eligibility` statement 可以证明“某证券在某时点被声明为 eligible / ineligible”，但不能证明同一交易日没有漏掉其它证券。因此，零散 statement、当前股票列表或 Baostock `stock_basic` 都不能认证“完整市场候选全集”。

本轮新增独立的 `niuniu-pit-universe-v1`：一个 receipt 只对应一个 `effective_session`，并同时绑定：

- 明确的 `CN_A_SHARE`、交易所集合及 `A_SHARE` scope；
- `FULL_OFFICIAL_LIST` 完整性声明；
- 全部规范化成员及其逐条 official source 绑定；
- 每份交易所原文字节、SHA256、字节数和内容寻址路径；
- 逐来源 `published_at / available_at`；
- receipt `created_at / cutoff_at`；
- 宿主对 publication time、语义映射和全集完整性的三项显式确认。

时间链固定为：

`published_at <= available_at <= created_at <= cutoff_at <= effective_session 09:15 Asia/Shanghai`

新 receipt 若在 cutoff 后首次创建会被拒绝；已经验证通过的相同 snapshot 可在 cutoff 后幂等重读，不会重写旧回执。

## 2. 存储与身份

```text
<data-root>/research/pit_universe/
├── <universe_snapshot>.json
└── documents/
    └── <sha256>.bin
```

- receipt 使用 checksummed JSON；`universe_snapshot` 是除 `created_at / universe_snapshot` 外规范内容的 SHA256 identity。
- 官方原文按 SHA256 内容寻址；symlink、空文件、超过 32MB、哈希冲突或路径逃逸全部拒绝。
- receipt append-only；相同内容返回 `created=false`，不同 session/source/member 内容产生不同 snapshot。
- 深度审计重新核对 receipt checksum/schema、snapshot identity、全部时间关系、source host↔exchange、scope、成员↔source、排序/计数/digest 及每份原文字节。

## 3. 宿主工具

新增：

- `niuniu-pit-universe --call archive|audit|get`
- `quantlab pit-universe-archive`
- `quantlab pit-universe-audit`

archive 只读取宿主已经下载的本地文件，**没有 URL 下载代码**。首次归档必须同时给出：

- `--confirm-publication-times`
- `--confirm-semantic-mapping`
- `--confirm-complete-official-universe`

任何一项缺失都不会写 receipt。

## 4. Qualification 与冻结输入

`UniverseConfig(mode="pit")` 新增可选 `pit_snapshot_ids`：

- 每个请求 bar session 必须恰好命中一个深验通过、scope 覆盖请求证券交易所的完整 receipt；
- session 缺失、同日多个候选 snapshot 或 scope 不覆盖都 fail-closed；
- 旧 `research/universe_events.parquet` 即使有零散 publication receipt，也只能保留 `timing_contract_only`，新增 blocker `pit_universe_complete_snapshot_receipt_missing`；
- receipt 中没有某证券时，仅在其交易所属于完整声明 scope 的前提下解释为该日不在 Universe；未知 session 一律排除；
- approval-time actual-byte freeze 现在冻结完整 receipt JSON 和 membership，恢复后版本与 mask 必须一致。

## 5. PREP / Daily Orchestrator 接线

PREP 新增 `universe_snapshot + universe_effective_session`：

- `effective_session` 必须精确等于目标 `trading_day`；
- 扫描证券必须与 receipt 全部 members 完全一致，禁止传子集后冒充完整 CandidateSet；
- 旧调用参数 `universe_pit_verified=True` 不再具有认证能力，并在结果中标为 `legacy_universe_pit_assertion_ignored=true`；
- snapshot 进入 `source_hash`、MarketSnapshot metrics、CandidateSet `universe_source` 与 evidence IDs；
- receipt 缺失或无效时继续保留 `pit_universe_not_certified`，不得升级 `FULL / STRICT_PIT`。

Daily Orchestrator `--init` 新增可选 `--universe-snapshot`，计划身份固定该 snapshot；PREP 使用目标交易日做 exact-session 校验。旧计划没有该字段时保持兼容并继续按 PARTIAL 运行。

## 6. Coverage 与 System Health

- Strict PIT Coverage 新增独立 `pit_universe_archive` inventory 和 `NO_VERIFIED_PIT_UNIVERSE_RECEIPTS` gap。
- 零散 `universe_eligibility` statement 仍单独显示，但不再充当全集分母合同。
- System Health 显示 verified/invalid receipts、effective sessions、member/source/document 数量；invalid receipt 触发 `pit_universe_receipts_invalid`。
- 这些都是全局 archive integrity inventory，不能证明最新 CandidateSet 已引用对应 snapshot。

## 7. Fail-closed 验收

已覆盖：

- 缺任一宿主确认；
- 非交易所 HTTPS host 或 host↔exchange 不一致；
- `published_at > available_at`、`available_at > created_at/cutoff_at`；
- cutoff 晚于目标 session 09:15；
- cutoff 后首次回填；
- source SHA256 不匹配；
- 重复/非法 symbol、symbol↔source exchange 不一致、未使用 source；
- 文档或 receipt 篡改；
- PREP snapshot session 不匹配、显式成员子集不一致；
- Qualification session 缺失/歧义/scope 缺口；
- approval freeze 后 receipt membership/version 漂移。

专项 `PIT Universe + Qualification + PREP + Daily Orchestrator` **46/46 passed**。完整仓库按互斥集合复核为非 Desktop **871/871**、Desktop **119/119**，合计 **990 tests / 0 failed / 0 skipped**。正式测试时按既有流程临时还原已提交 Agent Memory 基线，测试后恢复本轮 Memory 修改。

## 8. 当前真实状态与下一步

截至本说明完成时，`/Volumes/Lexar/niuniu-data` **尚未新增真实 PIT Universe v1 receipt**；实际运行 `pit-universe-audit` 返回 receipt/verified/invalid=`0/0/0`、effective_sessions=0、member_records=0。本轮没有得到针对某个未来交易日下载官方证券全集的显式联网授权，也没有用今天的列表回填历史 session。

下一步必须由宿主针对一个未来交易日显式授权并准备交易所原文字节，逐项复核 publication/availability 和全量成员语义，再在 09:15 cutoff 前创建首个真实 snapshot。之后 Daily Orchestrator 计划必须显式绑定该 snapshot。连续 SecurityStatus v2 工程合同现已完成，但真实逐日状态receipt仍为0；即使 Universe 通过，SecurityStatus、Official MarketRules、DailyMarket/bar vintage 等其它 blocker 仍需独立满足。

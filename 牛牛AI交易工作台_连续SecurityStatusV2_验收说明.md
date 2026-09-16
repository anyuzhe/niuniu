# 牛牛 AI 交易工作台｜连续 SecurityStatus v2 验收说明

## 1. 验收结论

本轮完成 `niuniu-security-status-coverage-v2` 工程合同，用“逐交易日全 Universe 状态快照 + 显式相邻 session 链”替代稀疏事件跨日外推。

通过项：

- 每份 receipt 精确绑定同 session 的 `niuniu-pit-universe-v1`；状态 records 必须与 Universe members 完全相等。
- 每个 member 必须同时绑定 `TRADABILITY` 与 `RISK_WARNING` 官方来源；source HTTPS host、exchange 与证券前缀一致。
- 时间链强制 `source published_at <= source available_at <= status created_at <= cutoff_at <= effective_session 09:15 Asia/Shanghai`，且被引用 Universe 的 `created_at <= status created_at`。
- 归档只读取宿主准备的本地文件，不联网；publication time、语义映射、全 Universe 完整性分别确认。
- 官方原文使用 SHA256 内容寻址，receipt checksummed、append-only、原子写入并加 archive lock。
- root snapshot 只表示初始状态；只有显式 `previous_status_snapshot` 且宿主确认相邻交易 session 时才生成进入、持续、撤销。
- 同 session 多 snapshot、previous link 分叉、断链、Universe/member/source/document/receipt 篡改均 fail-closed。
- `UNKNOWN` 可以留证但固定 `strict_pit_eligible=false`。
- silver SecurityStatus 派生表兼容现有稀疏 statements，并标记完整 v2 行为 `coverage_complete=true`；冲突状态拒绝物化。
- PREP 只在 exact effective session 消费，质量标记为 `STRICT_PIT_DAILY_COVERAGE`，不跨日传播，也不替代 Official MarketRules。
- Coverage 与 System Health 展示全局 v2 inventory、歧义和断链风险，但不冒充 CandidateSet 已覆盖。

## 2. Receipt 与文件布局

```text
<data-root>/research/security_status_coverage/
├── <status_snapshot>.json
└── documents/
    └── <sha256>.bin
```

核心字段：

```text
format / status_snapshot / created_at / effective_session / cutoff_at / available_at
universe_snapshot / universe_member_count / universe_members_digest / scope
previous_status_snapshot / previous_session_contiguous_confirmed
sources[] / records[] / records_digest
unknown_risk_warning_count / strict_pit_eligible
publication_time_confirmed / semantic_mapping_confirmed / complete_daily_status_confirmed
```

`records[]` 固定为：

```text
symbol / tradable / risk_warning / source_ids[]
```

`source.coverage` 仅允许 `TRADABILITY / RISK_WARNING`。完整性确认意味着来源和宿主映射足以对引用 Universe 的每个 member 给出这两个维度；从稀疏公告中“没看到事件”不能构造正常状态。

## 3. 连续链语义

对显式链接的相邻 snapshot，系统可生成：

- `SUSPENSION_ENTERED / SUSPENSION_CONTINUED / SUSPENSION_CLEARED / TRADABLE_CONTINUED`
- `RISK_WARNING_ENTERED / RISK_WARNING_CONTINUED / RISK_WARNING_CLEARED / RISK_WARNING_CHANGED`
- `UNIVERSE_ENTERED / UNIVERSE_CONTINUED / UNIVERSE_EXITED`

首个 root 只输出 `INITIAL_*`，不宣称在该日“进入”状态。Universe 新增/退出也不伪装成 ST 或停复牌变更。单日状态可独立具备 Strict 资格；transition 只有前后两份 receipt 都 Strict 时才标记 `transition_strict_pit_eligible=true`。

## 4. 宿主命令

```bash
niuniu-security-status-coverage \
  --data-root /Volumes/Lexar/niuniu-data \
  --call archive \
  --plan /absolute/path/status-plan.json \
  --confirm-publication-times \
  --confirm-semantic-mapping \
  --confirm-complete-daily-status
```

后续 snapshot 还必须显式加入：

```bash
--confirm-previous-session-continuity
```

只读审计与单证券状态链：

```bash
niuniu-security-status-coverage --data-root /Volumes/Lexar/niuniu-data --call audit
niuniu-security-status-coverage --data-root /Volumes/Lexar/niuniu-data --call chain --symbol sz.000001
quantlab security-status-coverage-audit --data-root /Volumes/Lexar/niuniu-data
quantlab security-status-chain --data-root /Volumes/Lexar/niuniu-data --symbol sz.000001
```

## 5. 测试覆盖

专项覆盖：

- 两日完整 snapshot 形成停牌/ST 的进入与撤销；
- Universe 全成员 exact equality；
- cutoff 后首次归档拒绝；
- previous snapshot 缺失与链分叉拒绝；
- `UNKNOWN` 留证但不升级 Strict；
- receipt 篡改、source/document/时间链校验；
- 同内容幂等且 cutoff 后不重写；
- silver materialization、旧 sparse statement 兼容、PREP exact-session 消费；
- Coverage/System Health 只读 inventory。

聚焦集成 `SecurityStatus v2 + legacy materialization + PREP + Coverage + System Health` **46/46 passed**。完整仓库按互斥集合复核为非 Desktop **879/879**、Desktop **121/121**，合计 **1000 tests / 0 failed / 0 skipped**。正式测试时按既有流程临时还原已提交 Agent Memory 基线，测试后恢复本轮 Memory 修改。

## 6. 真实数据边界

截至本说明完成时，实际只读审计 `/Volumes/Lexar/niuniu-data` 返回 receipt/verified/invalid=`0/0/0`、effective_sessions=0、status_records=0、continuous_links/strict_continuous_links=`0/0`。旧 silver manifest 仍按原 SHA256=`9fb12ec9731d28d5078a878c51bdce9e98a0ee78c642e6968b1fd5dee556b4e1` 只读加载14行/7只证券，证明向后兼容且没有隐式重物化。现有真实数据仍只有14条稀疏事件 statement。

因此本轮完成的是**完整逐日状态与连续链的工程合同**，不是全市场真实状态覆盖。没有未来交易日前官方完整状态字节、对应 PIT Universe snapshot 和宿主逐项确认时，不得制造 v2 receipt、不得回填历史、不得升级 Qualification/PREP/Playbook/Paper 证据等级。

## 7. 2026-09-17 前瞻取证更新

2026-09-16 已在独立 staging 保存三所5,563只 review-only Universe baseline，并以追加式 addendum 固定 SSE/SZSE/BSE 官方状态规范。SSE规范语义较完整；SZSE仅证明FTS私有日文件，3次站内检索与10个受限公开路径未找到目标日批量文件；BSE仅证明FDEP日文件，公开 `xxtpbz/xxzrzt` 权威映射未闭合。技术规范不能替代目标日逐证券实际值，简称和缺公告也不能推导 `NONE`。

因此 publication time、语义映射与完整日状态确认仍为false，SecurityStatus v2 receipt保持0。目标日上午只有在先完成exact-session Universe归档、再取得三所全部member显式 `TRADABILITY + RISK_WARNING` 后，才允许创建root。完整取证与runbook见《牛牛AI交易工作台_20260917前瞻Universe与SecurityStatus取证阶段验收说明.md》。

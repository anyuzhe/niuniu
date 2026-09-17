# 牛牛 AI 交易工作台：P8.7 R2/R3 与 MarketSnapshot Provider 验收说明

> 历史归档（整理于 2026-09-17）：保留原阶段记录；正文中的“当前、下一步、待完成”和测试/数据数字属于原记录时点。使用与当前进度以 [文档导航](../../README.md)、[当前状态](../../project/status.md) 为准。命令仍从仓库根目录执行。

- 阶段：P8.7 扩展 v2
- 日期：2026-09-15
- 基线：P13-B0 `75329bb`
- 最终全仓：**905 tests / 0 failed / 0 skipped**

## 1. 目标

补齐原 P8.7 留下的两个并行缺口：R2/R3 Daily Orchestrator，以及正式 MarketSnapshot Provider 能力合同。

本阶段完成的是 **R2/R3 确定性复核链 + Provider abstraction/readiness**。没有可核验实时行情通道时，不伪造 live provider，也不使用临时网页抓取替代正式源。

## 2. R2 / R3 时间合同

沿用现有 A 股 Frame Policy，不修改业务窗口：R2 为 10:30–13:30，R3 为 13:30–15:30。

确定性数据就绪点采用：
- R2：11:30 午间收盘，实时冻结窗口 11:30–11:40。
- R3：15:00 收盘定稿，实时冻结窗口 15:00–15:10。

所有 R1/R2/R3 前瞻快照继续执行“数据时点后 10 分钟内冻结”规则；超过窗口只能 MISSED/BACKFILL，不能补写 SYSTEM_PREDICTION。

## 3. R2 / R3 Scanner 规则

R2/R3 第一版定位为 **continuation review**，不重新做候选发现：

- R2 必须引用 R1 已冻结的 `SYSTEM_PREDICTION`，只复核其 `selected_symbols`；R3 同理必须引用 R2 冻结 Prediction。
- 前一阶段未选择的股票，即使后续走强，也不能在 R2/R3 被自动新增。
- 继续选择要求当前仍为 `STANDARD_ACCESS`、可交易、非单一价格窗口且相对昨收仍为正收益。
- 当前/前序快照缺失、CandidateSet/快照不完整时 fail-closed 为 NO_TRADE。
- R2/R3 不修改 PREP CandidateSet 的基础候选全集，只追加当时可见的冻结快照特征。

这避免了在盘中后段用新规则追涨，也保持 Selection 与后续状态复核的因果边界。

## 4. Daily Orchestrator v2

新建计划状态现在包含 `prep / auction / r1 / r2 / r3`，`supported_frames` 明确覆盖全部五个日内阶段。

Orchestrator 只有 R3 完成或 MISSED 后才进入 `COMPLETE / COMPLETE_WITH_MISSED`；R1 后会进入 `WAIT_R2_DATA_READY`，R2 后进入 `WAIT_R3_DATA_READY`。

旧的、尚未结束的 v1 计划在 tick 时可兼容补入 R2/R3 状态；历史已经 terminal 的计划不被重写。

## 5. MarketSnapshot Provider

新增 `MarketSnapshotProvider` Protocol、Provider Registry 与 Readiness。

当前唯一注册项是 `manual-import-v1`：
- `implemented=true`
- `live_channel=false`
- `network=false`
- `automatic_capture=false`
- 覆盖 AUCTION/R1/R2/R3 的离线导入合同

因此当前 Provider Readiness 必须返回 `BLOCKED`，并明确缺少 AUCTION/R1/R2/R3 四个 live frame。它不能因为已有手工 MarketSnapshot 就冒充正式实时行情源。

新增 `niuniu-market-provider-status` CLI、MCP `get_market_snapshot_provider_status` 和 System Health `Snapshot Provider` 观察项；全部只读，无 capture/connect/credential 工具。

## 6. System Health 语义

没有正式实时 Provider 时，Snapshot Provider 组件显示 `NOT_CONFIGURED`；它是实时自动化缺口，不等于离线研究系统故障，因此不会单独把 Runtime / Research Readiness 打成 BLOCKED。

Daily Orchestrator 健康证据同步增加 `r2_status / r3_status`，便于区分等待数据、MISSED 与已冻结。

## 7. 测试与真实工作区烟测

- R2/R3 + Provider + Scanner/Orchestrator 专项：**27/27 passed**。
- Provider/Scanner/Orchestrator/System Health/MCP 联合：**44/44 passed**。
- 完整仓库：**905 tests / 0 failed / 0 skipped**，380.437 秒。
- `niuniu-market-provider-status` 可安装运行，当前正确报告四个 live frame 全部缺失。
- 真实工作区：Provider=`BLOCKED`、System Health Provider=`NOT_CONFIGURED`、MCP=`BLOCKED`。
- 真实 `artifacts` 文件数 **77006 → 77006**，只读状态查询没有副作用。

## 8. 当前剩余边界

P8.7 的 R2/R3 编排和 Provider 框架至此完成，但**真正的实时 MarketSnapshot 网络 Provider 仍未实现**。

下一步不应再修改 R2/R3 状态机，而应在取得明确、可审计的数据源后，实现对应 live provider Adapter，并保持 provider_ref、source_hash、capture lag、FULL/strict eligibility 等现有 MarketSnapshot 合同。

# 牛牛 AI 交易工作台：P9 Agent Scorecard 验收说明

> 历史归档（整理于 2026-09-17）：保留原阶段记录；正文中的“当前、下一步、待完成”和测试/数据数字属于原记录时点。使用与当前进度以 [文档导航](../../README.md)、[当前状态](../../project/status.md) 为准。命令仍从仓库根目录执行。

- 阶段：P9 Agent Scorecard v1
- 日期：2026-09-14
- 开发基线：`6354622`
- 最终全仓：**848 tests / 0 failed / 0 skipped**
- 全仓耗时：291.473 秒

## 1. 阶段目标

P9 不做“哪个模型最好”的总排行榜，而是回答：不同固定 Role 在不同任务类型上，已经留下了哪些可观察的运行纪律、证据覆盖和后续跟踪记录。

核心原则：**task type 分离、样本不足保持 UNKNOWN、证据存在不等于证据正确、收益不等于 Agent 能力。**

## 2. Decision Scorecard

对 Chief Researcher、Market Scanner、Skeptic、Quant Researcher 的已保存 Decision 分别统计：

- ON_TIME rate 与 off-window 数量；
- research evidence / MarketSnapshot / rule snapshot 链接覆盖；
- model/provider/prompt identity 覆盖；
- risk / invalidation / exit 条件记录；
- PLAN_OPEN / OPEN / HOLD / REDUCE / EXIT 的计划字段完整性；
- D1 / D2 / D3+ follow-up 覆盖；
- revision 次数。

这些指标只描述保存纪律和覆盖，不自动判断研究结论是否正确。宿主已经拒绝但没有持久化 receipt 的违规尝试不可观察，因此 v1 不臆造 constraint violation 次数。

## 3. Peer Review Scorecard

第一轮 Reviewer 按角色分别统计：

- requested/completed；
- failure count；
- tool use；
- explicit evidence；
- model identity。

Chief Synthesis 独立统计 reviewer input completion 与 synthesis completion。**多数票、一致意见或工具调用次数都不被当成正确性。**

第一轮 Reviewer 的 `SAFE_TOOLS` 明确不包含 Scorecard，防止 Reviewer 在作答前看到自己的评分并迎合指标。

## 4. System Baselines

系统基线与 Agent 分数分离：

- Playbook SYSTEM_PREDICTION：FULL CandidateSet、STRICT_PIT、NO_TRADE；
- 只有同一 CandidateSet 恰有一个 `OBSERVED_EXPERT` 标签时，才计算 Exact / Precision / Recall；
- 显式记录 false positive 与 false negative；
- Paper Lifecycle 只展示预测→计划→成交→复盘的系统运行事实和账户结果。

这些 System Baseline 不归因给单个 Agent，也不构成 Alpha 或盈利认证。

## 5. 样本与评分边界

- 0 个样本：`NO_SAMPLES`。
- 1–2 个样本：`INSUFFICIENT_SAMPLES`。
- 至少 3 个样本才进入 `MEASURED`。
- 不生成 composite score。
- 不自动调整模型权重或 Role 配置。
- 不自动给 evidence correctness 打分。
- 不把 Paper 收益作为 Agent Score。
- Developer 在 P10 正式产品化前不进入 P9 Scorecard。

## 6. 产品接入

新增：

- `AgentScorecardService`；
- `niuniu-agent-scorecard` CLI；
- AI Team 内只读 `Agent Scorecard` 页面；
- AI Research 只读 `get_agent_scorecard` 工具。

Peer Reviewer 明确看不到 `get_agent_scorecard`。

## 7. 真实工作区烟测

对真实 `artifacts` 工作区执行 Scorecard：

- artifacts 文件数运行前后 `77006 → 77006`，无写入副作用；
- 当前 Agent Decision / Peer Review 样本均为 0，因此保持 `NO_SAMPLES`；
- 当前 Playbook 有 3 条 SYSTEM_PREDICTION，但 0 条唯一 OBSERVED_EXPERT 标签，因此 Exact / Precision / Recall 保持 `None`；
- AI 工具响应约 7.7KB，未触发 24KB 结果截断。

这正是 P9 的预期行为：**没样本就不硬评分，没标签就不伪造正确率。**

## 8. 测试与验收

- P9 / Playbook Tool / AI Team 专项：**21/21 passed**。
- editable install 后 `niuniu-agent-scorecard` 已实际存在并可运行。
- 真实 CLI 对工作区读取成功，`composite_score=false`、`automatic_model_weighting=false`。
- 完整仓库：**848 tests / 0 failed / 0 skipped**。

## 9. 下一阶段

下一正式阶段进入 **P10 Dev Studio + Dynamic Agent Orchestrator**。

P9 后续主要工作不再是扩评分维度，而是随着真实前瞻 Decision、Peer Review、Paper Review 样本积累，让当前指标逐步从 `NO_SAMPLES / INSUFFICIENT_SAMPLES` 进入可解释的 `MEASURED`。并行继续补 R2/R3 Daily Orchestrator、正式实时 MarketSnapshot provider 与 Strict PIT 数据覆盖。

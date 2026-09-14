# 牛牛 AI · A股个人交易研究助手改造总计划

- 计划冻结日期：2026-09-12
- 改造基线：`e6502aafdfea7310d46a06b7986f79425846ed71`
- 基线状态：`main` 与 `origin/main` 一致，工作区干净
- 计划冻结时全仓基线：681 passed / 0 failed / 0 skipped
- 计划性质：长期核对合同；阶段实现如需偏离，必须在本文件追加变更记录，不静默改目标

## 2026-09-14 架构 v2：当前权威开发口径

从本节起，牛牛的长期中心从“高手玩法试点”升级为 **Trading Knowledge / Strategy Source → Playbook → Validation → Daily Decision → Review**。若后续目标与早期 P8.5 文字冲突，以本节和《牛牛AI交易助手_项目说明与总体架构.md》为未来开发口径；早期文字保留为历史事实，不回写历史提交。

核心变化：

- “期末50分”只是 `StrategySource(type=TRADER)` 的首个试点，不是一级架构模块。
- 来源扩展为：TRADER / USER_EXPERIENCE / PUBLIC_METHOD / HISTORICAL_CASE / STATISTICAL_DISCOVERY / SYSTEM_REVIEW。
- 一个来源可以支持多个 Playbook；一个 Playbook 可以引用多个支持/反对来源，未来采用多对多关系。
- 当前 `ExpertSource` 保持兼容，不立即破坏性重命名；未来通用 `StrategySource` 必须保留现有 source/case/validation 的身份和哈希链。
- Git/Markdown 只保存人类可读规则、经验、架构和 Agent Operating Memory；数值、时点、候选、预测、PIT、成交和收益继续以 Structured Evidence 为权威源。
- AI Team 不做多数票系统；第一轮独立判断，Chief 综合证据并保留分歧。
- Daily Scanner 是确定性规则运行层；证据不足时允许 UNKNOWN / NO_TRADE / PARTIAL，不为了每日输出而强制推荐。

当前最近完整生产回归：**784 tests / 0 failed / 0 skipped**。

## 1. 改造目标

将牛牛从“统一技术交易因子实验平台”升级为：

> **一个把多来源交易知识持续形式化、结构化留证、数据验证化，并通过 Daily Scanner 与多 Agent 研究形成可追溯交易决策，再通过长期复盘把新经验沉淀回规则库的个人 A 股交易研究系统。**

最终形成四个相互连接的能力域：

1. **Trading Desk**：每天围绕市场、主线、股票、Decision、Strategy Intent、Paper 和复盘工作。
2. **Trading Knowledge / Playbook Lab**：吸收交易者、用户经验、公开方法、历史案例、统计发现与系统复盘，形成可版本化 Playbook。
3. **Research Lab**：保留 Factor / Experiment / PIT / Campaign / Factory / Watch / 统计和执行验证，作为 Playbook 的确定性验证内核。
4. **AI / Dev 能力层**：AI Team 负责研究综合；未来 Dev Studio + Dynamic Agent Orchestrator 负责隔离开发。

核心原则：**来源不是规则，规则不是 Alpha，选择能力不是成交能力，策略意图不是持仓；任何升级都必须有结构化证据。**

## 2. 必须保留的牛牛护城河

以下能力不得因本轮产品化而削弱：

- Proposal / Budget / Human Approval / JobQueue 权限边界。
- Campaign 固定研究包与失败/跳过项保留。
- Research Memory 与 Research Agenda。
- Alpha Factory 的固定候选、固定测试族、Factory 级 Holm 校正。
- DSL.RESTRICTED：禁止任意 `eval` 和未来位移。
- Watch / Tracking / Baostock 固定通道 / daemon / MCP。
- Strict PIT / official-rule 数据资格与 fail-closed blocker。
- 冻结复算、代码指纹、数据哈希、输入来源审计。
- `future label != execution return`，严禁用次日最高价冒充可执行收益。
- AI 不得自行批准研究、注册高风险候选、修改生产权限或自动实盘下单。

## 3. 对标系统只借鉴什么

借鉴：A 股业务导航、主线→股票→动作、跨日股票档案、R1/R2/R3、D1/D2/D3、共享池、动作状态、规则判/AI 判分离、多助理按需复核、高手经验规则化与历史验证、主 Agent 动态拆子任务、开发助理、移动入口、系统健康可视化。

不照搬：助理数量竞赛、多人同意=正确、未经校准的“85%信心”、事后最高价复利、历史回填冒充原判、自由修改生产代码、多模型自动调权。
## 4. 目标产品架构

```text
个人交易者
   │
牛牛 AI
   ├─ Trading Desk
   │   ├─ 今日交易 / Theme Matrix / Stock Dossier
   │   ├─ Decision Ledger / Strategy Intent
   │   └─ 复盘 / Paper（逐步接入）
   ├─ AI Team
   │   └─ Chief + Scanner + Skeptic + Quant Researcher
   ├─ Research Lab
   │   ├─ Trading Knowledge / StrategySource / Playbook Lab
   │   └─ Factor / Experiment / PIT / Campaign / Factory / Watch
   ├─ Dev Studio（P10目标）
   │   └─ Main Agent → Dynamic Subagents → Tests → Review → Human Merge
   └─ System Center
       └─ Data / PIT / Jobs / MCP / daemon / logs / health
```

同时采用第二个视角描述知识流：

`StrategySource → Playbook Hypothesis → Git+Structured Evidence → Validation → Daily Scanner → AI Team → Decision/Intent → Paper/Execution → D1/D2/D3+ Review → 新 StrategySource`。

## 5. 一级导航目标

最终一级导航收敛为：`今日交易 / 主线市场 / 股票中心 / 持仓计划 / 复盘中心 / AI团队 / 研究实验室 / 系统中心`。

现有 12 个研究页不删除，统一进入“研究实验室”；现有数据/PIT/后台管理能力进入“系统中心”。
## 6. 核心新业务对象 A：Decision Ledger

Decision 是交易助手最重要的新一等对象，必须 append-only：旧判断不能覆盖，只能 `revision_of`。

最小合同：

- `decision_id / symbol / trading_day / frame`
- `submitted_at / frozen_at`
- `market_snapshot_id / rule_snapshot_id / research_evidence_ids`
- `agent_id / role_id / model_id / prompt_version`
- `theme / theme_role`
- `machine_state / ai_thesis / risk_flags`
- `action`
- `buy_zone / confirm_trigger / invalidation`
- `hold_reason / add_condition / reduce_condition / exit_condition`
- `revision_of / outcome`

必须严格区分：`Research Opinion`、`Strategy Intent`、`Paper Position`、未来可能的 `Real Account Position`。

## 7. 核心新业务对象 B：Stock Dossier

以股票为中心聚合，而不是以实验为中心聚合：

- 证券与 A 股制度身份
- 当前行业 / 主题 / 主题角色
- 首次进入、最近研究、研究次数
- 历次 Decision 时间线
- 规则证据 / 因子证据 / 实验证据 / Watch 证据
- 当前计划和失效条件
- Paper Position；真实账户以后单独接入
- 后续兑现结果和复盘
## 8. A 股市场与主线模型

新增 `Theme Matrix`，按“主题 × 交易日 × Decision Frame”展示状态，不把分数当概率。

主题状态建议第一版：`预热 / 启动 / 主升 / 分歧 / 修复 / 加速 / 过热 / 退潮 / 未知`。

每个格子可下钻查看：

- 市场事实：宽度、成交、涨停/跌停、20cm、龙头表现等；缺失即缺失，不自动编造。
- Machine Rule：确定性规则判断及版本。
- Quant Evidence：已有因子/实验/Watch 证据。
- AI Thesis：解释和条件化计划。
- Risk Review：反例、PIT blocker、执行风险。
- 原始 Decision 与后续 Outcome。

证券必须绑定 `AshareSecurityProfile`：交易所、板块、风险警示、新股特殊期、当日价格限制/停牌等；能否称 official-rule covered 继续由已完成的数据资格层控制。

## 9. Decision Frame 时间合同

第一版 Frame：`PREP / AUCTION / R1 / R2 / R3 / D1 / D2 / D3_PLUS`。

- PREP：前一日晚或盘前计划。
- AUCTION：竞价确认。
- R1：早盘第一判断。
- R2：午盘/中段复核。
- R3：尾盘/收盘定稿。
- D1/D2/D3_PLUS：后续兑现与持有跟踪。

Frame 的具体时钟时间配置化；业务对象保存真实 `submitted_at`，补交不能伪装成原时点判断。
## 10. 策略动作状态机

策略意图状态第一版：

`DISCOVERED → WATCH → READY → PLAN_OPEN → OPEN → ADD → HOLD → REDUCE → EXIT`

旁路终态：`INVALIDATED / REJECTED / EXPIRED`。

规则：

- 状态改变必须由新 Decision 驱动并留原因。
- `OPEN/ADD/HOLD/REDUCE/EXIT` 首先表示策略动作，不表示真实成交。
- Paper 账户只有模拟成交回执后才改变 `Paper Position`。
- 未来真实账户只有券商成交回报后才改变 `Real Account Position`。
- AI 不能把“建议开仓”写成“已持仓”。

## 11. AI Team 合同

第一版仅设 5 个 Role，不追求 13 个助理：

- `Chief Researcher`：主聊天与最终综合。
- `Market Scanner`：覆盖检查，重点防漏主题、漏股票、漏数据。
- `Skeptic / Risk Reviewer`：专门找反例、执行风险和证据冲突。
- `Quant Researcher`：调用现有 Research Lab、Factory、Watch、PIT 工具。
- `Developer`：仅在 Dev Studio 中修改代码。

`role_id`、`model_provider`、`model_id`、`runtime`、`prompt_version`、`tool_policy` 必须分开存储。

正常任务单助理完成；只有高风险、证据冲突、PIT 不足、规则与 AI 强冲突、重大动作变化时才按需 Peer Review。
## 12. Dev Studio 合同

Dev Studio 允许“AI 帮用户修改牛牛自己”，但与研究权限严格隔离。

固定流程：

`User Request → DevTask → Main Developer Agent → 按需动态 Subtasks → Shared isolated worktree → targeted tests → Reviewer → Main Agent final acceptance → full tests(必要时) → diff/risk/evidence → Human Approval → merge/commit/push`

DevTask 最小记录：

- `dev_task_id / requested_by / created_at`
- `base_commit / worktree / allowed_paths / risk_level`
- `main_agent_id / model_id / prompt_version`
- `subtasks / parent_subtask_id / assigned_agent / tool_policy / path_lease / budget / stop_reason`
- `acceptance_tests`
- `changed_files / diff_hash / test_results / review_result`
- `commit_sha / merged_by / released_at / rollback_sha`

风险级别：

- LOW：UI / 文案。
- MEDIUM：普通业务逻辑。
- HIGH：统计、PIT、回测、数据资格、研究结论语义。
- CRITICAL：权限、真实账户、自动交易。

HIGH/CRITICAL 必须 Developer + Reviewer + 人工批准；任何 Agent 均不得自行向 `main` 发布。
## 13. Trading Cockpit 目标首页

默认首页不是实验统计，而是“今天要处理什么”：

- 当前交易日与当前 Decision Frame。
- 数据新鲜度 / PIT / 规则 / daemon / MCP 状态。
- 市场概览：成交额、宽度、涨跌停、风险状态等已接入事实。
- 主线矩阵摘要：强线、预热、退潮、切换。
- 候选股票：WATCH / READY / INVALIDATED。
- 当前策略动作：PLAN_OPEN / HOLD / REDUCE / EXIT 等。
- Chief Researcher 结论、Machine Rule、Quant Evidence、Risk Review 分栏。
- Agenda、Factory、Watch 与数据异常提醒。
- 点击任一股票进入 Stock Dossier，不在首页堆完整实验 JSON。

## 14. System Health

只做可观察性，不为了模仿对标系统而拆成大量服务。

统一展示：

- Market Data / Series 最新日期与完整性。
- Research Worker / JobQueue。
- Tracking daemon 心跳。
- MCP 状态、transport、工具数量。
- Notifications。
- 最近错误、最近任务、磁盘/产物增长。
- Strict PIT blocker 摘要。

系统健康页不能用“进程在线”代替“研究/数据正确”。
## 15. 分阶段修改顺序

### P0 基线冻结
- 固定基线 `e6502aa` 与 681 项测试。
- 本总计划先独立提交，再开始业务代码改造。

### P1 新导航与 Trading Desk 外壳
- 一级导航改为 8 个业务入口。
- 原 12 个研究页面进入“研究实验室”，功能不删除。
- 建立今日交易、主线市场、股票中心、持仓计划、复盘中心、AI团队、系统中心的空壳与路由。
- 验收：旧研究页仍可达，旧测试不因导航重构失效。

### P2 Decision Ledger
- 新增 append-only 决策存储、schema、hash、revision、查询。
- 人工/AI 只能新建 revision，不能覆盖历史记录。
- 验收：重启后可恢复；同一 decision 内容幂等；篡改/冲突可检测。

### P3 Stock Dossier
- 以证券为中心聚合 Decision、实验、Watch、计划与 Outcome。
- 验收：同一股票跨交易日/跨 Frame 时间线完整，可从证据反向打开原实验。

### P4 A股主线市场 / Theme Matrix
- 主题状态、日历矩阵、事实/规则/AI/量化证据分层。
- 不把主观评分冒充概率；缺少数据时显示未知。
### P5 Decision Frame
- PREP / AUCTION / R1 / R2 / R3 / D1 / D2 / D3_PLUS。
- 保存真实提交时间与数据快照；补交必须标注 late submission。
- 验收：历史判断不可覆盖，跨轮变化可比较。

### P6 策略动作状态机
- DISCOVERED → WATCH → READY → PLAN_OPEN → OPEN → ADD → HOLD → REDUCE → EXIT。
- INVALIDATED / REJECTED / EXPIRED 单独记录。
- 验收：策略意图、Paper Position、未来 Real Position 永不混写。

### P7 今日交易驾驶舱
- 把市场、主线、股票、计划、AI结论、风险、Agenda、Watch 放到单页。
- 验收：打开牛牛首先看到业务待办，不必先进入实验中心。

### P8 AI Team / Peer Review
- Chief 默认单独完成；按条件请求 Scanner / Skeptic / Quant。
- 第一轮独立判断互不可见，复核轮才允许查看对方输出。
- 验收：任务链有 task_id/parent/reviewer/stop_reason，不能出现无限对话。

### P8.5 Trading Knowledge / Playbook Lab 基础能力（已进入前瞻验证）
- 把任何可核验交易经验都视为“研究假设来源”，不是直接当真理；实盘高手只是来源类型之一。
- 现有正式对象继续保留 `ExpertSource / PlaybookDefinition / PlaybookCase / CandidateSet / SelectionDecision / PlaybookValidation`，完整候选集、正负样本、防回填和执行审计不变。
- 第一批“期末50分”研究继续作为历史试点，用于证明来源归档、10选2、Selection/Execution 分离和真正前瞻冻结链路。
- 验收：规则版本、候选全集、未选/失败样本、样本外/走步、可成交收益、成本和 A 股制度约束均可审计；失败必须保留。

### P8.6 StrategySource 通用来源层（已完成，2026-09-14）
- 新增通用 `StrategySource` 概念，支持 `TRADER / USER_EXPERIENCE / PUBLIC_METHOD / HISTORICAL_CASE / STATISTICAL_DISCOVERY / SYSTEM_REVIEW`。
- 一个来源可以支持多个 Playbook，一个 Playbook 也可以引用多个支持/反对来源；来源与规则采用多对多关系。
- 当前 `ExpertSource` 兼容映射为 `StrategySource(type=TRADER)`，不破坏历史 source_id、Case、Validation、哈希和 Git 资料。
- Playbook 名称逐步从“某某高手玩法”解耦成规则本身，如 high_low_switch / leader_reentry / mid_board_acceleration。
- 验收：旧 ExpertSource 全部可读；新来源类型可统一归档、检索、引用和审计；任何新来源都不能绕过 DRAFT→验证→冻结门槛。
- 实际交付：schema v2 新增 `strategy_sources / source_links`；旧库只读无需迁移，首次写新对象时兼容迁移；AI/MCP/Reviewer 只读，桌面宿主可人工导入。全仓 **793/0/0**。

### P8.7 Daily Orchestrator：每日受控运行闭环（v1 已完成，2026-09-14）
- 串起 DailyMarket 数据增量、就绪检查、PREP、09:25 AUCTION、09:35 R1，并继续支持 R2/R3。
- 调度器只触发已定义的确定性阶段，不让模型自己修改时间窗、候选全集或历史结果。
- 网络失败、行情过期、规则/PIT 缺失时必须明确 BLOCKED/UNKNOWN/NO_TRADE，不补造结果。
- 验收：同一交易日重复启动幂等；错过实时窗口不能回填 SYSTEM_PREDICTION；每阶段都可追到具体 MarketSnapshot 和 source hash。
- v1 实际交付：单交易日持久计划、checksum 状态、文件锁、DailyMarket 显式 capture 授权/冷却/修订审核、PREP 预留恢复、AUCTION/R1 实时快照等待与 MISSED_FRAME、`--tick/--run/--status` CLI。R2/R3 和正式实时 provider 仍未实现。全仓 **805/0/0**。

### P8.8 Playbook → Trading Desk → Paper 接线
- Daily Scanner 输出进入 Decision Ledger，再通过合法状态迁移形成 Strategy Intent。
- `SYSTEM_PREDICTION` 不等于成交；Paper 只有模拟成交回执后才改变 Paper Position。
- 建立 NO_TRADE、未成交、QUEUE_DEPENDENT、T+1、费用、滑点和退出条件的长期账户复盘。
- 验收：判断、计划、订单、成交、持仓、收益和复盘全部分层；AI 无自动实盘权限。
- **P8.8-A 已完成**：新增保守 `PlaybookDecisionBridge`。SYSTEM_PREDICTION 首次最多写 WATCH，NO_TRADE 只留 receipt；已有人工 Decision 和 PLAN_OPEN/OPEN/HOLD 不自动覆盖；Orchestrator bridge 默认关闭、需宿主显式启用。
- **P8.8-B 已完成**：新增显式 `PaperPlan`。只有当前 PLAN_OPEN + host confirmation 才能冻结计划并用完成 bars + dated MarketRules 调用 PaperAccount；模拟成交不自动推进 OPEN；固定 universe 不兼容 fail-closed；崩溃后可从 reservation 恢复成交 receipt。全仓 **821/0/0**。
- **P8.8-C 已完成（v1）**：新增独立 `DynamicPaperAccount`，支持跨日动态 universe 且强制历史 NAV/fill/order 前缀不变；PaperPlan 可显式选择 dynamic backend。真实 fill 可在 host confirmation 后推进 PLAN_OPEN→OPEN；ADD/REDUCE/EXIT 通过独立 RebalancePlan 驱动并在实际成交后回写 HOLD/退出完成状态。新增 D1/D2/D3+ `PaperOutcomeReview` 与生命周期统计，明确区分 NO_TRADE、未成交、拒单、费用、滑点、Paper收益和复盘。完整仓库 **842/0/0**。真实券商不在本阶段。

### P9 Agent Scorecard（v1 已完成）
- 按任务类型分开评价 Decision、独立 Peer Review 与 Chief Synthesis，不做跨任务“模型总分”；Developer 在 P10 前不参与评分。
- Decision 可观察指标：ON_TIME/off-window、证据链接、model/prompt identity、风险记录、计划完整性、跨日 follow-up 与 revision 次数。
- Peer Review 可观察指标：completion/failure、tool use、显式 evidence、model identity；Chief 单独记录 reviewer input completion 与 synthesis completion，不按多数票得分。
- System baseline 单独展示 Playbook SYSTEM_PREDICTION 的 FULL/STRICT_PIT/NO_TRADE，以及在唯一 OBSERVED_EXPERT 标签下的 Exact/Precision/Recall、false positive/false negative；Paper 生命周期也只作系统基线，不能归因给某个 Agent。
- 证据内容正确性、宿主拦截但未持久化的违规尝试、Alpha/盈利不自动评分；样本少于3个保持 `INSUFFICIENT_SAMPLES`。
- AI Research 可只读查询 Scorecard；第一轮 Reviewer 明确看不到 Scorecard，避免迎合评分。
- 产品接入：AI Team 新增只读 Scorecard 页面和 `niuniu-agent-scorecard` CLI；不自动调模型权重。
- 完整仓库 **848/0/0**。

### P10 Dev Studio + Dynamic Agent Orchestrator（v1 已完成）
- 新增 `DevTask`、隔离 detached git worktree、Main Developer Agent、动态 depth-1 Subagents、frozen tests、独立 Reviewer 与 Human Merge Gate。
- Main Agent 只通过 Dev Studio 安全工具拆分任务、读取 diff/证据、创建子任务、重开子任务和最终 ACCEPT/REPLAN/BLOCK；没有 shell、直接文件写、commit、push 或 merge 权限。
- 子 Agent 角色为 `EXPLORER / IMPLEMENTER / TESTER / REVIEWER`；默认只读，只有 IMPLEMENTER 可以持有不可变 `path-scoped lease` 并通过 CAS 写文件。最大并行子 Agent 固定为1–3，v1 不允许递归子 Agent。
- 同一 DevTask 共享一个 isolated worktree；冲突 write lease、越出 DevTask allowed_paths、越出 Implementer lease、symlink/path escape、`.git` 写入全部 fail-closed。
- frozen test command 由宿主在 DevTask 创建时确定；Tester 只能运行这些 argv，不能自行换更容易的测试。任何最终 diff 变化都会让旧 test PASS / Reviewer PASS 失效。
- Reviewer 只读且必须覆盖当前最终 worktree fingerprint；Main Acceptance 重新核实际 changed files、lease、test evidence 和 Reviewer PASS，不能相信 Subagent 自报 changed_files。
- `human_merge` 要求显式 confirmation，并再次校验 main branch 与 frozen base SHA；合并产生本地 commit，但 **不会 push**。主分支移动、路径越权、无变更等均拒绝。
- Research Agent 工具表不包含 Dev Studio write/merge；P10 CLI 提供 create/status/list/run-main/run-ready/run-cycle/diff/merge/cleanup，但没有 push action。
- 产品接入：桌面顶级导航新增“开发工作台”，展示 DevTask、Subtask、tests、Reviewer、diff scope 和 Human Merge 状态。
- 测试/验收：P10 专项 **13/13**，Trading Desk 导航 **2/2**，editable install + `niuniu-dev-studio --help` 通过；完整仓库 **861 tests / 0 failed / 0 skipped**，耗时 302.193 秒。
### P11 System Health
- 统一服务、任务、日志、心跳、数据新鲜度、PIT blocker。
- 不把“在线”当作“正确”。

### P12 移动端 / 机器人
- 复用同一 MCP/API、Stock Dossier、Decision Ledger。
- 手机端不得建立第二套独立记忆或第二份持仓状态。

### P13 Paper → Real 的渐进式交易层
- 先把现有模拟账户完整绑定 Decision Ledger。
- 再做 Shadow/Paper 长期运行。
- 真实券商接入、实盘资金与自动交易最后单独立项，不属于本轮默认自动开启范围。

## 16. Research Lab 基础设施并行线

产品层改造期间继续按原计划补：

1. Approval-time data freeze：批准时冻结实际输入字节，而不是只冻结配置。
2. Research Session Grant：有限自主研究沙箱，而不是无限授权。
3. Strict PIT 原始资料继续补齐。
4. Watch 高级指标与序贯/在线衰减统计。
5. 跨 workspace 研究记忆与用户研究偏好。

这些基础设施工作不得被 Trading Desk UI 延后到“以后再说”；每次相关业务功能依赖它们时必须直接复用正式合同。
## 17. 测试与发布纪律

每阶段至少包含：

- 新模块单元测试。
- 权限反向测试：模型不能获得未授权写入/审批/发布能力。
- 向后兼容测试：旧 artifact、旧 research_only 任务、旧页面继续可读。
- UI offscreen 测试：导航、选择、确认按钮不等于执行。
- 与当前核心模块联合回归。
- 阶段结束跑全仓回归；任何失败不得用“与本次无关”直接忽略。
- 真实或保存真实数据的端到端验收，明确 live / offline / synthetic 证据级别。

Git 纪律：

- 每个阶段独立逻辑提交；不使用 `git add .` 混入无关文件。
- 提交前 `git diff --check`、敏感信息扫描、工作区授权检查。
- push 后验证 `origin/main` SHA 与本地一致。
- 阶段验收报告记录测试数、真实验收、源码指纹和 Git SHA。

## 18. 总体验收定义

本计划完成时，用户应能从“今天的 A 股市场”进入，而不是从“因子模块”进入；任何股票可以回看原始判断、轮次、证据、计划、修订和后续结果；AI 可以研究、按需复核并在隔离开发环境改进牛牛，但不能绕过研究/发布权限；现有严谨实验内核仍完整可用且历史结果可复算。

## 19. 计划变更记录

- 2026-09-12：建立 v1 总计划，基线 `e6502aa`。首轮实施范围冻结为 P1 + P2 基础，不在同一提交顺手实现后续 P3–P13。
- 2026-09-12：P1 + P2 基础完成并通过验收。新 8 个业务一级入口已落地，旧 12 个研究页保留兼容；Decision Ledger 已具备 append-only、revision、幂等、checksum、人工桌面创建/修订和股票检索。最终全仓 688 项通过，端到端验收创建研究任务 0。阶段说明见 `牛牛AI交易工作台_P1P2新导航与DecisionLedger_验收说明.md`。下一阶段：P3 Stock Dossier。
- 2026-09-12：P3 Stock Dossier 完成。股票中心已可按证券聚合当前/历史 Decision、精确关联实验、Factor Watch，并可反向打开原实验/跟踪证据；打开档案不创建研究任务。最终全仓 692 项通过，端到端聚合新增研究任务 0。阶段说明见 `牛牛AI交易工作台_P3StockDossier_验收说明.md`。下一阶段：P4 A 股主线市场 / Theme Matrix。
- 2026-09-12：P4 A 股主线市场 / Theme Matrix 完成。Theme Snapshot 已支持 append-only revision、市场事实来源/时点约束、Machine/AI 状态分离、Decision/量化证据关联与只读模型工具；缺失格子保持 UNKNOWN，不从标签或 AI 文本推导事实。最终全仓 700 项通过，隔离端到端验收新增研究任务 0。阶段说明见 `牛牛AI交易工作台_P4主线市场ThemeMatrix_验收说明.md`。下一阶段：P5 Decision Frame。
- 2026-09-13：P5 Decision Frame 完成。PREP/AUCTION/R1/R2/R3/D1/D2/D3+ 已升级为可审计时间合同；真实提交时间、Frame Policy 版本、EARLY/ON_TIME/LATE/BACKFILL、跨轮 missing/变化与 D1+ 原判关联均正式落盘，旧 Decision 保持可读。最终全仓 710 项通过，隔离端到端新增研究任务 0。阶段说明见 `牛牛AI交易工作台_P5DecisionFrame_验收说明.md`。下一阶段：P6 策略动作状态机。

- 2026-09-13：P6 策略动作状态机完成。Strategy Intent 已正式约束 DISCOVERED/WATCH/READY/PLAN_OPEN/OPEN/ADD/HOLD/REDUCE/EXIT 与 INVALIDATED/REJECTED/EXPIRED；非法跳级、同 Frame 重复当前状态、历史插入和后续状态下改写旧动作均被阻断；当前状态按 trading_day + Frame 业务时间计算，策略意图继续与 Paper/真实成交严格分离。最终全仓 720 项通过，隔离端到端新增研究任务 0、模型写状态工具 0。阶段说明见 `牛牛AI交易工作台_P6策略动作状态机_验收说明.md`。下一阶段：P7 今日交易驾驶舱。

- 2026-09-13：P7 今日交易驾驶舱完成。默认首页已统一聚合 Strategy Intent、Theme Snapshot 正式 facts、已保存 AI Thesis、Risk Review、Research Agenda 与 Watch；默认日期取工作空间最新有证据的业务日，不按自然时钟猜盘中 Frame；首页只读，不调用模型、不刷新 Watch、不下载或执行研究。最终全仓 724 项通过，隔离端到端新增研究任务 0、Watch/失败任务归档前后未改。阶段说明见 `牛牛AI交易工作台_P7今日交易驾驶舱_验收说明.md`。下一阶段：P8 AI Team / Peer Review。

## 20. AI Team / Dev Studio 记忆架构：Git-first Markdown Memory

对标系统补充确认：其文件智能体以**文件记忆为主**，规则和经验长期落在 Git 仓库中的 Markdown；每次开工先 `git pull`，再读取约定的记忆入口，没有把向量库作为主记忆层。牛牛采用同类原则，但与研究证据严格分层。

### 20.1 Agent Operating Memory

以下内容以 Git 中的 Markdown 为权威源：

- 智能体角色规则、工具边界、工作流程。
- 开发规范、测试纪律、代码风格、发布规则。
- 已验证的工程经验、常见故障、踩坑与恢复方法。
- 用户明确确认的长期工作偏好与项目约定。
- 各阶段架构决策、变更理由和复盘。

建议目录：`agent_memory/README.md` 作为固定入口，下面分 `rules/`、`experience/`、`incidents/`、`architecture/`、`roles/`。每次 Agent 开工流程固定为：`pull/fetch -> 读取 README -> 按任务读取相关 md -> 工作 -> 将值得长期保留的经验以 diff 提交`。

### 20.2 Research Evidence 不迁移到 Markdown

实验结果、PIT 资格、Decision Ledger、Theme Snapshot、Watch、成交归档、统计检验和冻结复算继续由现有结构化存储承担。Markdown 可以总结这些证据，但不得成为数值事实的唯一来源，也不得用文字覆盖原归档。

### 20.3 不以向量库作为权威记忆

第一阶段不建设向量数据库主记忆。Git Markdown 具备版本历史、diff、review、回滚、分支和人工可读性，更适合个人长期维护。未来如果文件数量过大，可增加全文索引或向量索引作为**可重建的检索加速层**；删除索引后仍必须能从 Git Markdown 恢复全部 Agent Operating Memory。

### 20.4 权限与写入纪律

Research Agent 默认只读 Agent Memory；Developer/Reviewer 可在隔离 worktree 中提出记忆修改。任何自动总结不得直接覆盖已有规则，只能新增或修订并保留 Git diff。涉及统计、PIT、权限、真实账户和自动交易的规则变更仍需人工批准。

- 2026-09-13：根据对标系统实际使用方式，将 P8/P10 的智能体长期记忆正式调整为 **Git-first Markdown Memory**；向量库从“可能的长期记忆方案”降级为未来可选、可删除的检索索引层。

- 2026-09-13：P8 AI Team / Peer Review 完成。固定角色与模型解耦；Reviewer 第一轮互盲、第二轮仅 Chief 综合，最多两轮；Reviewer 仅只读证据工具，模型只能创建 pending 复核请求，真正启动仍需宿主显式发送许可。Git-first Agent Memory 绑定 commit/文件 SHA/memory_hash，`agent_memory/` 有未提交修改时正式 Agent 拒绝启动；Developer 在 P10 前强制关闭。最终全仓 736 项通过，隔离端到端新增研究任务 0。阶段说明见 `牛牛AI交易工作台_P8AITeam与PeerReview_验收说明.md`。下一阶段调整为新增 P8.5 A股高手玩法 / Playbook Lab。

## 21. Dynamic Agent Orchestrator：主 Agent + 动态子 Agent

新增对标信息确认：对方不是固定流水线调用若干 Agent，而是本地 Codex 主 Agent 先理解需求、判断策略、调用工具，并在复杂任务时动态拆分子任务；子 Agent 共享同一工作区，最终回到主 Agent 汇总、判断和验收。牛牛借鉴这一**编排思想**，但保留更严格的工作区与权限合同。

### 21.1 通用编排模型

```text
User
  ↓
Main Agent / Supervisor
  ├─ 理解目标与约束
  ├─ 冻结 acceptance criteria
  ├─ 判断是否需要拆分
  ├─ 分配 role / tools / budget / workspace scope
  ↓
Dynamic Subtasks (0..N)
  ├─ Explorer：查代码/查现有证据，只读
  ├─ Researcher：查资料/接口/历史案例，只读或只写 scratch artifact
  ├─ Implementer：只写分配路径
  ├─ Tester：运行限定测试，不改生产代码
  └─ Reviewer：审 diff / 证据，只读
  ↓
Main Agent Aggregate / Replan / Final Acceptance
  ↓
Human Approval（涉及发布/高风险动作时）
```

子 Agent 数量不是 KPI；简单任务由 Main Agent 自己完成。第一版 `max_parallel_subagents=3`、`max_delegation_depth=1`，不得子 Agent 再无限创建孙 Agent。

### 21.2 Research Profile 与 Dev Profile 必须不同

**Research Profile**：共享的是冻结 evidence snapshot，而不是可变研究状态。Subagent 默认只读，输出写入独立 task artifact；不能修改 Decision、Theme、Watch、授权、实验结果。涉及独立判断时继续沿用 P8 的“首轮互盲”，Main Agent 汇总后才可比较意见。

**Dev Profile**：共享同一个隔离 Git worktree，便于查代码、实现、测试形成同一工作结果；但所有写操作必须持有 `path_lease`，同一路径只能有一个 Writer。Main Agent 可以重新分配 lease，但必须记录历史。

### 21.3 Shared Workspace 不是自由并发写

每个 DevTask 只有一个 isolated worktree；所有 Subagent 读取相同 `base_commit` 和当前 worktree。写入规则：

- Explorer / Researcher / Tester / Reviewer 默认 `read_only`。
- Implementer 仅写 `allowed_paths ∩ leased_paths`。
- 同一文件不能同时被两个 Subagent lease。
- 每个 Subtask 记录 `before_diff_hash / after_diff_hash / changed_files`。
- Subagent 不允许 `git commit`、`git push`、切换 branch、修改 `.git`、改变全局 Git 配置。
- Main Agent 汇总前必须检测跨 Subtask 冲突和越界文件。

### 21.4 Main Agent 才负责“完成”

Subagent 返回“完成”只表示自己的局部任务结束。只有 Main Agent 可以判断 DevTask 是否满足 acceptance criteria。Main Agent 不满意时可在预算内：补充证据、重新拆分、回滚局部修改、再跑测试；达到 `max_replans` 后必须停并向用户报告，不得无限自循环。

最终交付至少保存：`task_tree`、每个 Subtask 的输入/输出、模型与 role、工具调用摘要、workspace lease、changed files、测试、Reviewer 结论、Main Agent final acceptance、停止原因。

### 21.5 与 P8 的关系

P8 Peer Review 不改成“共享答案一起讨论”。P8 保留独立 Reviewer → Chief synthesis，用于高风险交易/研究判断。Dynamic Orchestrator 是更通用的任务执行层：在 Dev Studio 中允许共享 worktree；在 Research 中共享只读 evidence，不破坏独立判断。

## 22. Trading Knowledge / StrategySource / Playbook Lab

牛牛的长期研究中心不是“研究某一个高手”，而是建立一个能够持续吸收、反驳、验证和迭代交易经验的通用知识层。

> **StrategySource → Playbook Hypothesis → Structured Validation → Daily Decision → Review → New StrategySource**

因子、理论和高手案例都只是来源或验证工具之一；系统真正长期积累的是可版本化、可验证、可前瞻检验的 Playbook。

### 22.1 StrategySource 通用来源模型

目标来源类型：

- `TRADER`：可核验实盘交易者、比赛、交割或公开原帖；
- `USER_EXPERIENCE`：用户自己的长期交易经验和人工规则；
- `PUBLIC_METHOD`：书籍、课程、文章或公开交易方法；
- `HISTORICAL_CASE`：历史行情案例和失败案例；
- `STATISTICAL_DISCOVERY`：Quant/Research Lab 得到的市场统计规律；
- `SYSTEM_REVIEW`：牛牛自身真实前瞻运行和复盘产生的新经验。

当前代码已有 `ExpertSource`，先视为 `StrategySource(type=TRADER)` 的兼容实现；后续通用化不得破坏已有 ID、哈希、Case 和 Validation。

### 22.2 Playbook 是来源之上的独立对象

一个来源可以支持多个 Playbook，一个 Playbook 也可以由多个来源共同支持或反对。长期目标不是“期末50分策略”“某某高手策略”，而是独立的规则对象，例如 high_low_switch、leader_reentry、mid_board_theme_leader_acceleration。

现有正式对象继续复用：`PlaybookDefinition / PlaybookCase / CandidateSet / SelectionDecision / PlaybookValidation`。

研究必须同时回答：Eligibility（谁进入候选）、Selection（为什么选A不选B）、Veto/NO_TRADE（为什么不做）、Execution（普通账户能否成交）、P&L（成本后结果）。

### 22.3 双轨知识存储

Git + Markdown 保存人类可读规则、概念、版本理由、经验和复盘；Structured Evidence 保存来源哈希、候选全集、时点事实、预测、PIT、实验、成交和收益。

Markdown 可以总结结构化证据，但不能覆盖它；向量/全文索引未来只能作为可重建检索加速层。

### 22.4 正式研究流程

```text
StrategySource 归档 / 时间戳 / 完整性
  ↓
概念抽取与术语统一
  ↓
Playbook DRAFT
  ↓
历史 CandidateSet 全集（含未选/失败/NO_TRADE）
  ↓
冻结 eligibility / selection / veto / action rules
  ↓
Holdout / Walk-forward / Strict PIT / 执行验证
  ↓
PlaybookValidation
  ↓
Daily Scanner / Decision Ledger
  ↓
D1/D2/D3+ 复盘
  ↓
新 StrategySource / 新 Playbook 版本
```

### 22.5 防止事后偏差与经验神化

必须阻断：只收集赢家；只保存最终买入者；用后来总结替代当时信息；看到结果后反复加条件再称样本外；用理论最高价代替可成交收益；因为来源知名就直接升级规则；因为多个 Agent 一致就把意见当独立证据。

失败样本、反例、未知、不可交易和正确 NO_TRADE 都是正式研究数据。

### 22.6 与现有牛牛模块的连接

Theme Matrix 提供市场上下文；Stock Dossier 聚合股票的 Playbook 历史；Decision Ledger 保存当时真实判断；Strategy Intent 表达计划而非成交；Research Lab 提供因子/统计/执行验证；Strict PIT 决定证据级别；AI Team 负责覆盖、反例、量化证据与综合。

### 22.7 首个历史试点：期末50分

“期末50分”保留为第一批 `TRADER` 来源试点，已经帮助牛牛建立候选全集、10选2、防历史回填、Selection/Execution Access 分层和真实 PREP→AUCTION→R1 前瞻链。

这些成果验证的是**系统如何吸收外部交易经验**，不意味着期末50分成为系统中心，也不意味着其 DRAFT Playbook 已证明存在 Alpha。

## 23. 2026-09-14 后续顺序调整（架构 v2）

完成 P8.5-E1 与架构升级后，后续优先级调整为：

1. **P11 System Health**。
2. P12 移动端。
3. P13 Paper→Real；真实券商最后单独评审。

并行继续 Research Lab 基础设施线：approval-time actual-byte freeze、Research Session Grant、Strict PIT 数据补齐、Watch 序贯统计。

- 2026-09-13：根据新增对标信息，确认“主 Agent 动态拆 Subagent + Shared Workspace + Main Agent 最终验收”主要借鉴到 P10 Dev Studio，并抽象为 Research/Dev 两种 profile；同时新增 P8.5 Expert Playbook Lab，把 A 股短线模式发现从 Factor-first 调整为 Playbook-first + Quant Validation。
- 2026-09-13：P8.5-A Expert Playbook Lab 基础框架完成。新增 ExpertSource / PlaybookDefinition / PlaybookCase / CandidateSet / SelectionDecision / PlaybookValidation 六类严格对象；完整候选全集、selected/unselected、冻结时点 SYSTEM_PREDICTION、FROZEN/FULL/STRICT_PIT/VERIFIED 正式验证门槛和 A 股执行审计均已落地。AI Team 仅获得 Playbook 只读证据工具；Research Lab 与 Stock Dossier 已接入。`playbooks/qimofenshu/` 仍固定为 SOURCE_REQUIRED，不用二手总结填充正式规则。最终全仓 750 项通过。阶段说明见 `牛牛AI交易工作台_P8_5PlaybookLab基础框架_验收说明.md`。P8.5 尚未整体结束，下一步仍是取得可核验“期末50分”原始资料并重建第一批真实 Case/CandidateSet。

- 2026-09-13：P8.5-B 首批真实来源核验启动。已从开发机直接核验期末50分本人 2026-07-24 主帖和交割单公开讨论线程，保存 URL/时间/页面 SHA256；实际工作空间登记 2 个 PARTIAL ExpertSource 与 1 个 DRAFT `source-hypothesis-1`，无 FROZEN、无 Case/CandidateSet，研究 Job 数前后均为 8。公开 KDocs 当前跳转登录页，且讨论线程存在 7 月24日后买卖记录缺口质疑，因此不能把该交割单升级为 VERIFIED。下一道门槛仍是取得连续、可核验交易记录并做持仓勾稽。

- 2026-09-13：P8.5-B 取得用户提供的公开交割表成交副本并完成持仓连续性审计。原始逐笔材料只保存在 Git 忽略的 `playbooks/**/source_raw/`；Git 保存哈希与审计摘要。当前结构化 Playbook Evidence 已登记 8 个来源、3 个 DRAFT 定义、12 个 Case；其中建立 2026-07-01 的 18 只与 2026-07-03 的 16 只 `FULL + RETROSPECTIVE_REFERENCE` 候选全集及真实选择记录。候选重建采用精确涨停价、真实交易日、停牌跳过和逐日特殊价格限制；S佳通 5%、ST通脉摘帽前后 5%→10% 均显式审计。Selection 规则仍未冻结、Validation 仍为 0，因此 P8.5 继续进行，下一步转向“为什么18/16选1”的 Selection 特征提取与未见样本验证。

- 2026-09-13：P8.5-B Selection 研究继续推进。7/2 康欣新材建立第 3 个 FULL CandidateSet（19选1）并保留亏损样本；7/13 立方制药建立第 4 个 FULL CandidateSet（9选1），冻结的 selection-hypothesis-v1 首次未见样本回放选择贵绳股份而真实选择立方制药，结构化 RECONSTRUCTION 为 0 命中，v1 失败永久保留。由此新增 selection-hypothesis-v2 DRAFT：市场节点/题材生命周期 → 可成交性 → 主动拉升确认 → 相对强度，7/13 不回算为验证成功。
- 2026-09-13：交割区间进一步表明期末50分不是单一板数玩法，新增 `meta-playbook-hypothesis-v1` DRAFT，暂分低位2→3、空间龙首次可交易分歧、高位重入、高低切补涨、二波修复五个研究分支。7/1–7/24 的唯一空间板反例表明“见最高就买”不成立；后续必须同时研究未买日和已有持仓/不可成交情形。SYSTEM_PREDICTION 同时增加真实 wall-clock 近实时约束；历史规则回放只能使用 HUMAN_RECONSTRUCTION，禁止伪装成正式样本外预测。

- 2026-09-13：P8.5-B 进一步把高位交易拆成可审计子玩法。空间龙首次可交易分歧分支保存 10 个正负机会日，发现区间内 3 个买入/7 个不买可被同样本规则完全拟合，但只登记为 IN_SAMPLE descriptive，不升级为验证。另建立哈药 7/17 清仓后涨停重入、高低切长缆 7/24、恒尚旧龙二波修复 7/14 三个 DRAFT；二波因全市场旧龙候选未重建保持 PARTIAL。当前禁止继续在7月发现样本上调阈值，下一道正式门槛改为取得新的连续交割记录，在规则不再修改后进行未见样本回放。

- 2026-09-13：P8.5-B 新时间段样本继续扩展。8/7 百花医药暴露 Meta v1 覆盖缺口：它属于非最高空间的 3→4 中位题材核心主动晋级，暂命名 `mid_board_theme_leader_acceleration`，只作为候选 DRAFT 分支。8/28 万向德农与 9/1 竞业达进一步暴露“选股能力”和“排队/通道成交能力”必须分离，新增 `queue-dependent-overnight-board-hypothesis-v1`；普通账户不得默认一字排队可成交。Meta 新建 `meta-playbook-hypothesis-v2`，保留 v1 不覆盖。比赛公开页面还存在 8/20–8/27 报单展示缺口，因此不得直接把比赛可见收益曲线当完整账户收益。当前下一门槛：继续寻找未参与发现的新交易样本，并对 Selection 与 Execution Access 分层验证。

### 2026-09-13：P8.5-B 未见样本与前瞻截止更新
- 新增华西股份 8/13→8/14成功样本：官方年赛买/卖与华安武汉百步亭龙虎榜交叉验证；首板候选本地79 vs 公开约82，CandidateSet fail-closed 为 PARTIAL。
- 新增正裕工业 8/18→8/19失败样本：8/17完整二板10只逐一一致，8/18一字3板买入、8/19次日-10%并割肉；正式证明 QUEUE_DEPENDENT 只提高成交概率，不等于 Alpha。
- 新建 `meta-playbook-hypothesis-v3`：市场节点 → 目标身位 → 身位内相对选择 → 执行访问。研究截止固定为 2026-09-13，之后使用前瞻协议，不再用旧样本反复调参宣称样本外成功。

### 2026-09-13：P8.5-B 桂林/龙版证据分级更新
- 桂林旅游 9/10 建立 FULL 4只3板候选全集与强交叉 `OBSERVED_EXPERT`：账户已验证截图、9/10华安买入、9/11同席位卖出及候选竞价全部可核。
- 龙版传媒 9/4 建立 FULL 2只4板候选全集，但因华安数据来自9/7三日榜，精确买入日不可确认，只保存 `HUMAN_RECONSTRUCTION`；9/8清仓与9/9空仓作为直接事实来源。
- 新建 `mid-board-theme-leader-acceleration-hypothesis-v1`，继续保持 DRAFT / RETROSPECTIVE_REFERENCE；9/13 cutoff 后的前瞻统计不纳入上述旧样本。

### P8.5-C：真正前瞻验证启动（2026-09-14）

- 已将 2026-09-13 固定为 v3 research cutoff；9/14 起只允许前瞻评估，不允许用新结果回改 v3 后宣称样本外成功。
- 9/14 已完成 PREP → AUCTION → R1 三段真实时间冻结；R1 `SYSTEM_PREDICTION` 选择超声电子，专家真实结果尚未知。
- 新增 `niuniu-playbook-forward` 时间闸门执行器；全仓回归 **763 passed / 0 failed / 0 skipped**。

### 2026-09-14：P8.5-D1 MarketSnapshot / Daily Scanner

- 将 9/14 前瞻实验里临时抓取的竞价/分钟行情升级为正式 `MarketSnapshot`：append-only、checksum、captured_at、provider、expected/missing symbols、BACKFILL/近实时资格与原始哈希均可审计。
- 新增 `DailyPlaybookScanner`：只消费冻结 CandidateSet + MarketSnapshot；AUCTION 默认只排序不入场，R1 第一版采用 STANDARD_ACCESS + 正收益 + 相对竞价主动增强；一字板保留为 QUEUE_DEPENDENT，不当成普通账户自动选择。
- 新增 `niuniu-market-snapshot` 与 `niuniu-daily-playbook-scan`；默认扫描只读，只有显式 `--freeze` 才能进入原有 SYSTEM_PREDICTION 时间闸门。
- Trading Cockpit、AI Research、Reviewer、标准 MCP 已接入 MarketSnapshot 只读查询；模型仍无行情写入、预测冻结、Strategy Intent 修改和自动交易权限。
- 使用 9/14 实际行情 BACKFILL 重放仍选择超声电子；全仓 **769 tests / 0 failed / 0 skipped**。阶段说明见 `牛牛AI交易工作台_P8_5D实时快照与DailyScanner_验收说明.md`。
- 下一步：P8.5-D2 全市场 PREP 自动扫描与市场节点→目标身位路由；逐日 official-rule 不足时保持 PARTIAL/UNKNOWN。

### 2026-09-14：P8.5-D2 PREP 全市场自动扫描完成

- 新增 `niuniu-prep-playbook-scan` 与 `prep_scanner.py`：可从全市场日线自动生成 PREP 市场事实、连板高度、目标身位候选和版本化市场节点 Router。
- Router v1 是宿主工程策略，不是期末50分规则；只对极端风险/退潮高风险做自动路由，其余返回 UNKNOWN，避免每天强行出股票。
- Strict 路径要求逐日 MarketRules 完整、官方交易所来源、本地哈希 receipt 与 PIT Universe 证据同时满足；当前旧 MQC 自动保持 PARTIAL/RETROSPECTIVE。
- 真实 5215 只扫描约17.7秒；本地日线最新仍为 2026-09-04，请求9/11会约6.3秒 fail-fast 为 DATA_NOT_UPDATED。
- D2 新增8项测试；完整仓库 **777 passed / 0 failed / 0 skipped**。
- 下一实际优先级：把现有 Baostock/数据更新链接到每日 PREP 前置流程，确保最近交易日数据可用，再继续 Trading Cockpit → Strategy Intent → Paper 闭环。

### 2026-09-14：P8.5-E1 每日全市场增量归档与 PREP 接力

- 新增 DailyMarket 日增量归档层，不再要求为了更新一个交易日重写约 2.5GB / 5215 只单股历史湖。
- 每日快照保存原始响应、规范化 Parquet、manifest 与 SHA256；同内容幂等，同日历史修订进入 revision review，宿主确认后才切换 accepted 版本。
- PREP Scanner 已支持“旧 MQC 历史湖 + accepted DailyMarket 日增量”叠加，并优先使用明确 `preclose / tradestatus / isST`。
- DailyMarket 只补市场事实，不替代 PIT Universe 或交易所逐日 official MarketRules；证据不足时继续保持 PARTIAL / RETROSPECTIVE_REFERENCE。
- 新增 `niuniu-daily-market`；`capture` 是唯一联网动作，默认查询只读。
- 本阶段全仓 **784 tests / 0 failed / 0 skipped**。下一阶段进入受控每日编排：收盘后 capture/就绪检查 → PREP → 09:25 AUCTION → 09:35 R1。

### 2026-09-14：架构 v2 文档升级

- 项目说明从“高手玩法优先”升级为多来源 `StrategySource → Playbook → Validation → Daily Decision → Review`。
- “期末50分”保留为历史首个 TRADER 来源试点，不再作为一级架构节点。
- 新增 P8.6 StrategySource、P8.7 Daily Orchestrator、P8.8 Playbook→Trading Desk→Paper；P9/P10 顺延到真实前瞻样本与每日闭环之后。
- Git Markdown 与 Structured Evidence 双轨边界不变；ExpertSource 保持向后兼容，后续通用化不得破坏历史身份和证据哈希。
- 本次仅调整 README / 项目架构 / 开发计划 / Agent Memory 文档，不修改生产代码；最近完整生产回归仍为 784/0/0。

- 2026-09-14：P8.6 StrategySource 通用来源层完成。新增六类 StrategySource、旧 ExpertSource→TRADER 兼容投影与 PlaybookSourceLink 多对多关系；正式 FROZEN/HOLDOUT 合同仍沿用旧 VERIFIED ExpertSource，不允许新来源绕过验证门槛。真实旧库副本 v1→v2 迁移保持 42 Source / 17 Definition / 36 Case / 26 CandidateSet / 37 Selection / 2 Validation 的 payload+checksum 不变；全仓 793/0/0。下一阶段 P8.7 Daily Orchestrator。

- 2026-09-14：P8.7 Daily Orchestrator v1 完成。新增单交易日受控状态机与 `niuniu-daily-orchestrator`；默认不联网，只有宿主计划显式授权才 capture DailyMarket；PREP/AUCTION/R1 复用现有 Scanner/Forward 合同，错过实时窗口记录 MISSED 而不回填。网络失败有15分钟冷却，DailyMarket revision_review 可人工确认后继续；中断后复用同一 reservation/snapshot。AUCTION/R1 仍依赖正式 LIVE_NEAR_REALTIME MarketSnapshot provider，R2/R3 未宣称支持。全仓 805/0/0。下一阶段 P8.8。

- 2026-09-14：P8.8-A/B 核心接线完成。SYSTEM_PREDICTION 通过保守 Decision Bridge 最多自动进入 WATCH/READY；NO_TRADE 不制造股票状态，人工/已有计划不被覆盖。PLAN_OPEN 经 host confirmation 可冻结 PaperPlan，并在显式完成 bars + dated MarketRules 下调用固定-universe PaperAccount；模拟成交成功也不自动改 Intent=OPEN。新增崩溃后成交 receipt 恢复，Trading Cockpit 只读展示 PaperPlan。全仓 821/0/0。
- 2026-09-14：P8.8-C v1 完成。新增独立 DynamicPaperAccount 支持跨日动态 universe，历史目标对后来新增股票只补零权重并要求旧 NAV/fill/order 前缀不变；PaperPlan 增加显式 dynamic 执行。fill receipt 只有在宿主确认且原 PLAN_OPEN 仍当前有效时才推进 OPEN；ADD/REDUCE/EXIT 通过 RebalancePlan 驱动实际动态账户目标，成交后按严格合同回 HOLD/确认退出。新增 D1/D2/D3+ 因果 PaperOutcomeReview、批量 auto_all 和 NO_TRADE/未成交/费用/滑点/拒单/复盘分层统计。AI/MCP 无任何长期 Paper 写工具。全仓 842/0/0。
- 2026-09-14：P8.8-C 长期 Paper / 复盘闭环 v1 完成。新增独立 DynamicPaperAccount，不破坏固定-universe PaperAccount；跨日加入新证券时过去目标确定性补0并强校验历史 NAV/fill/order 前缀不变。PaperPlan 新增显式 dynamic 执行；真实 fill 经 host confirmation 才能推进 PLAN_OPEN→OPEN。新增 ADD/REDUCE/EXIT RebalancePlan 与成交结果桥、D1/D2/D3+ PaperOutcomeReview、auto_all 批量因果复盘和生命周期统计；AI/MCP 无长期 Paper 写/执行权限。完整仓库 842/0/0。下一阶段 P9 Agent Scorecard。


- 2026-09-15：P10 Dev Studio v1 完成。新增隔离 detached worktree、Main Developer + depth-1 Dynamic Subagents、max_parallel≤3、path-scoped immutable write leases、frozen tests、独立 Reviewer、stale test/review fingerprint 检测和 Human Merge Gate。Main/Subagents 均无 git push 权；只有宿主显式确认后的 human merge 可在 main 创建 commit，且主分支/BASE SHA 变化即阻断。Research Agent 无 Dev Studio 写/merge 工具。新增桌面“开发工作台”和 `niuniu-dev-studio` CLI。专项13/13、Trading Desk导航2/2、完整仓库861/0/0。下一阶段 P11 System Health。

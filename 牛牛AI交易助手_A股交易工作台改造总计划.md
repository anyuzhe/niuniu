# 牛牛 AI · A股个人交易研究助手改造总计划

- 计划冻结日期：2026-09-12
- 改造基线：`e6502aafdfea7310d46a06b7986f79425846ed71`
- 基线状态：`main` 与 `origin/main` 一致，工作区干净
- 计划冻结时全仓基线：681 passed / 0 failed / 0 skipped
- 计划性质：长期核对合同；阶段实现如需偏离，必须在本文件追加变更记录，不静默改目标

## 1. 改造目标

将牛牛从“统一技术交易因子实验平台”升级为：

> **牛牛 AI · 个人 A 股交易研究助手**

最终同时具备三类能力：

1. **Trading Desk**：每天面向 A 股市场、主线、股票、计划、持仓意图和复盘使用。
2. **Research Lab**：保留并继续强化现有因子、实验、PIT、Alpha Factory、Campaign、Watch 等严谨研究能力，并新增面向 A 股短线的高手玩法 / Playbook Lab。
3. **Dev Studio**：允许用户向开发助理提出修改牛牛本身的需求，在隔离 worktree 中开发、测试、复核，人工批准后再合并发布。

核心原则：**不推倒现有研究内核；交易产品层建立在现有严谨研究证据之上。**
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
   │   ├─ 今日交易
   │   ├─ 主线市场 / Theme Matrix
   │   ├─ 股票中心 / Stock Dossier
   │   ├─ 持仓计划 / Position Intent
   │   └─ 复盘中心 / Decision Timeline
   ├─ AI Team
   │   ├─ Chief Researcher
   │   ├─ Market Scanner
   │   ├─ Skeptic / Risk Reviewer
   │   ├─ Quant Researcher
   │   └─ Developer
   ├─ Research Lab
   │   ├─ Factor / Experiment / PIT / Campaign / Factory / Watch
   │   └─ Playbook Lab：高手玩法→候选全集→选择差异→历史验证
   ├─ Dev Studio
   │   └─ DevTask → Worktree → Tests → Review → Human Merge
   └─ System Center
       └─ Data / PIT / Jobs / MCP / daemon / logs / health
```

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

### P8.5 A股高手玩法 / Playbook Lab（新增优先阶段）
- 将淘股吧等公开实盘高手的可核验玩法作为“研究假设来源”，不是直接当真理。
- 先做 source archive / 交割记录 / 当时市场上下文，再抽取 eligibility、候选池、选择条件、否决条件、entry/confirm/invalidation/exit。
- 核心研究问题从“这个因子有没有 Alpha”扩展为“同一时点符合玩法的 10 个候选，为什么高手选择其中 2 个；剩余 8 个是什么反例”。
- Playbook 规则/经验的人类可读版本进入 Git；数值验证、候选全集、失败样本和收益仍进入结构化 Research Evidence。
- 第一批可把“期末50分”作为试点，但只有拿到可核验原始记录后才建正式 Playbook，不凭二手总结补全规则。
- 验收：完整候选集合、正负样本、规则版本、样本外/走步验证、可成交收益、成本与 A 股制度约束均可审计。

### P9 Agent Scorecard
- 评价 Coverage、证据正确、计划完整、及时性、修订纪律、约束违规、后续跟踪，以及 Playbook 候选覆盖/漏选/错误升级。
- 第一阶段只展示，不自动调模型权重；Scorecard 必须按任务类型评价，不做一个“模型总分”。

### P10 Dev Studio + Dynamic Agent Orchestrator
- DevTask、isolated worktree、Main Developer Agent、动态 Subagents、tests、Reviewer、人工 merge。
- 主 Agent 负责理解需求、冻结验收标准、决定是否拆分、分配工具/路径/预算、汇总结果、最终验收；不满意可以在预算内重新规划。
- 子 Agent 按任务动态创建，不固定长期常驻；典型分工为代码检索、资料/接口核对、局部实现、测试/分析、diff review。
- 同一 DevTask 共享一个隔离 worktree，但写入必须 path-scoped lease；禁止两个子 Agent 同时修改同一文件/目录。默认 Explorer/Reviewer 只读，只有明确 Implementer 获得分配路径写权限。
- 子 Agent 不得自行 commit/push；Main Agent 负责最终 diff、测试证据和验收，仍需人工批准后才能 merge/push main。
- 验收：研究 Agent 无 repo write 权；开发 Agent 无生产 main 自动发布权；任务树、subtask、workspace lease、changed files、tests、review、stop_reason 全部可追溯。
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

## 22. A股高手玩法 / Expert Playbook Lab

新增研究主线：对于 A 股短线主线、情绪周期、龙头、弱转强、分歧转一致、二波/龙回头等高度条件化模式，**高手玩法比单一通用因子更接近日常交易问题的形态**。牛牛因此从 Factor-first 调整为：

> **Playbook-first hypothesis discovery + deterministic market facts + Quant/PIT validation**

因子不删除，也不降级为无用；它从“唯一中心”变成 Playbook 的特征、控制变量、对照和增量验证工具之一。

### 22.1 研究对象

第一版新增正式对象：

- `ExpertSource`：高手、原帖/实盘赛/交割记录、来源 URL/文件、发布时间、可用时间、完整性说明。
- `PlaybookDefinition`：玩法定义、市场上下文、eligibility、候选生成、选择条件、否决条件、entry、confirm、invalidation、hold/add/reduce/exit。
- `PlaybookCase`：一次历史事件/交易案例，绑定当时可见数据和原始来源。
- `CandidateSet`：在当时规则下**所有**符合 eligibility 的股票，不只保存最终买入者。
- `SelectionDecision`：高手/系统从 CandidateSet 中选择谁、没选谁，以及能否从当时证据解释差异。
- `PlaybookValidation`：冻结版本后的历史验证、样本外、walk-forward、执行收益、失败样本与局限。

### 22.2 “10选2”是核心问题，不只是规则命中率

如果某玩法一天筛出 10 只而高手只选 2 只，研究必须保留全部 10 只。不能只拿 2 个赢家反推规则。

验证拆成两层：

1. **Eligibility**：哪些股票在当时确实符合这套玩法；规则负责召回。
2. **Selection**：为什么选择 A/B 而不选择其余 8 只；可能涉及主线强度、龙头身份、主动性、带动性、竞价、换手、市场节点和相对排序。

Selection 可以使用 deterministic features、pairwise/ranking 分析和 AI 条件解释，但最终必须在冻结候选全集上验证，不能看完结果再补选择条件。

### 22.3 高手经验进入 Git，但收益事实不进 Markdown

建议新增：

```text
playbooks/
  README.md
  qimofenshu/
    README.md          # 人类可读玩法假设、来源和版本历史
    definition.json    # 受 schema 约束的机器规则
    notes/             # 公开资料的摘要/人工标注，不替代原始来源
```

Git 保存规则、概念定义、变更理由和人工复盘。大体积/受版权约束的原始材料只保存引用、哈希和合法本地归档位置；交易结果、CandidateSet、回测和统计证据继续进入结构化 Research Evidence。

### 22.4 正式研究流程

```text
原始高手资料/交割记录
  ↓ 来源归档 + 时间戳
概念抽取 / 术语统一
  ↓
Playbook hypothesis v0
  ↓
历史候选全集重建（含未选/失败样本）
  ↓
机器事实 + 主线/情绪/龙头上下文
  ↓
冻结 eligibility / selection / veto / action rules
  ↓
训练期探索 + holdout / walk-forward
  ↓
A股可成交执行：涨跌停、停牌、T+1、费用、滑点、资金占用
  ↓
PlaybookValidation
  ↓
通过后进入 Daily Scanner / Decision Ledger
  ↓
D1/D2/D3+ 复盘 → 规则版本迭代
```

### 22.5 防止“高手幸存者偏差 / 事后神化”

Playbook Lab 必须额外阻断：

- 只选知名高手成功交易、不保存其失败交易。
- 只保存最终买入股票、不保存当时同样符合条件的其他候选。
- 用后来总结替代当时公开/可见的信息。
- 看到历史结果后不断添加规则，再把同一历史区间当验证。
- 用次日最高价/理论涨幅代替可执行账户收益。
- 因为某高手长期赚钱就直接推导“玩法已被牛牛提取成功”。

### 22.6 与现有牛牛模块的连接

- Theme Matrix：提供主线/情绪上下文。
- Stock Dossier：显示该股票历史命中过哪些 Playbook、何时被选/未选。
- Decision Ledger：保存系统在当时基于 Playbook 的真实判断，不能事后覆盖。
- Strategy Intent：Playbook 命中只能产生候选/计划，不等于成交。
- Research Lab：因子、事件研究、Campaign、Factory 可作为验证器。
- Strict PIT：决定某次历史重建能否称严格时点验证。
- AI Team：Scanner 防漏候选，Skeptic 找反例，Quant Researcher 做正式验证；Chief 最终综合。
- Agent Scorecard：以后评价谁在 Playbook 候选覆盖、选择、风险识别上更可靠。

### 22.7 首个试点：期末50分

“期末50分”只作为第一批试点方向，不把当前二手描述直接固化为交易规则。正式启动条件：拿到足够可核验的原帖/实盘记录/交易时间/候选上下文；先重建若干真实案例，再判断能否形成稳定 Playbook。第一阶段目标不是证明能赚钱，而是回答：**规则能不能稳定重建候选集合，以及系统能不能解释并样本外验证‘为什么10选2’。**

## 23. 2026-09-13 后续顺序调整

完成 P8 后，后续优先级调整为：

1. **P8.5 Expert Playbook Lab**：先建立 A 股高手玩法的数据合同和首个试点。
2. **P9 Agent Scorecard**：有真实 Playbook/Decision 使用后再评价 Agent，避免空跑排行榜。
3. **P10 Dev Studio + Dynamic Agent Orchestrator**：把主 Agent 动态拆任务、Shared Worktree、Subagent 工具/路径权限正式产品化。
4. P11 System Health。
5. P12 移动端。
6. P13 Paper → Real 渐进交易层。

并行继续 Research Lab 基础设施线（approval-time freeze、Session Grant、Strict PIT 数据补齐、Watch 序贯统计）。

- 2026-09-13：根据新增对标信息，确认“主 Agent 动态拆 Subagent + Shared Workspace + Main Agent 最终验收”主要借鉴到 P10 Dev Studio，并抽象为 Research/Dev 两种 profile；同时新增 P8.5 Expert Playbook Lab，把 A 股短线模式发现从 Factor-first 调整为 Playbook-first + Quant Validation。
- 2026-09-13：P8.5-A Expert Playbook Lab 基础框架完成。新增 ExpertSource / PlaybookDefinition / PlaybookCase / CandidateSet / SelectionDecision / PlaybookValidation 六类严格对象；完整候选全集、selected/unselected、冻结时点 SYSTEM_PREDICTION、FROZEN/FULL/STRICT_PIT/VERIFIED 正式验证门槛和 A 股执行审计均已落地。AI Team 仅获得 Playbook 只读证据工具；Research Lab 与 Stock Dossier 已接入。`playbooks/qimofenshu/` 仍固定为 SOURCE_REQUIRED，不用二手总结填充正式规则。最终全仓 750 项通过。阶段说明见 `牛牛AI交易工作台_P8_5PlaybookLab基础框架_验收说明.md`。P8.5 尚未整体结束，下一步仍是取得可核验“期末50分”原始资料并重建第一批真实 Case/CandidateSet。

- 2026-09-13：P8.5-B 首批真实来源核验启动。已从开发机直接核验期末50分本人 2026-07-24 主帖和交割单公开讨论线程，保存 URL/时间/页面 SHA256；实际工作空间登记 2 个 PARTIAL ExpertSource 与 1 个 DRAFT `source-hypothesis-1`，无 FROZEN、无 Case/CandidateSet，研究 Job 数前后均为 8。公开 KDocs 当前跳转登录页，且讨论线程存在 7 月24日后买卖记录缺口质疑，因此不能把该交割单升级为 VERIFIED。下一道门槛仍是取得连续、可核验交易记录并做持仓勾稽。

- 2026-09-13：P8.5-B 取得用户提供的公开交割表成交副本并完成持仓连续性审计。原始逐笔材料只保存在 Git 忽略的 `playbooks/**/source_raw/`；Git 保存哈希与审计摘要。当前结构化 Playbook Evidence 已登记 8 个来源、3 个 DRAFT 定义、12 个 Case；其中建立 2026-07-01 的 18 只与 2026-07-03 的 16 只 `FULL + RETROSPECTIVE_REFERENCE` 候选全集及真实选择记录。候选重建采用精确涨停价、真实交易日、停牌跳过和逐日特殊价格限制；S佳通 5%、ST通脉摘帽前后 5%→10% 均显式审计。Selection 规则仍未冻结、Validation 仍为 0，因此 P8.5 继续进行，下一步转向“为什么18/16选1”的 Selection 特征提取与未见样本验证。

- 2026-09-13：P8.5-B Selection 研究继续推进。7/2 康欣新材建立第 3 个 FULL CandidateSet（19选1）并保留亏损样本；7/13 立方制药建立第 4 个 FULL CandidateSet（9选1），冻结的 selection-hypothesis-v1 首次未见样本回放选择贵绳股份而真实选择立方制药，结构化 RECONSTRUCTION 为 0 命中，v1 失败永久保留。由此新增 selection-hypothesis-v2 DRAFT：市场节点/题材生命周期 → 可成交性 → 主动拉升确认 → 相对强度，7/13 不回算为验证成功。
- 2026-09-13：交割区间进一步表明期末50分不是单一板数玩法，新增 `meta-playbook-hypothesis-v1` DRAFT，暂分低位2→3、空间龙首次可交易分歧、高位重入、高低切补涨、二波修复五个研究分支。7/1–7/24 的唯一空间板反例表明“见最高就买”不成立；后续必须同时研究未买日和已有持仓/不可成交情形。SYSTEM_PREDICTION 同时增加真实 wall-clock 近实时约束；历史规则回放只能使用 HUMAN_RECONSTRUCTION，禁止伪装成正式样本外预测。

- 2026-09-13：P8.5-B 进一步把高位交易拆成可审计子玩法。空间龙首次可交易分歧分支保存 10 个正负机会日，发现区间内 3 个买入/7 个不买可被同样本规则完全拟合，但只登记为 IN_SAMPLE descriptive，不升级为验证。另建立哈药 7/17 清仓后涨停重入、高低切长缆 7/24、恒尚旧龙二波修复 7/14 三个 DRAFT；二波因全市场旧龙候选未重建保持 PARTIAL。当前禁止继续在7月发现样本上调阈值，下一道正式门槛改为取得新的连续交割记录，在规则不再修改后进行未见样本回放。

- 2026-09-13：P8.5-B 新时间段样本继续扩展。8/7 百花医药暴露 Meta v1 覆盖缺口：它属于非最高空间的 3→4 中位题材核心主动晋级，暂命名 `mid_board_theme_leader_acceleration`，只作为候选 DRAFT 分支。8/28 万向德农与 9/1 竞业达进一步暴露“选股能力”和“排队/通道成交能力”必须分离，新增 `queue-dependent-overnight-board-hypothesis-v1`；普通账户不得默认一字排队可成交。Meta 新建 `meta-playbook-hypothesis-v2`，保留 v1 不覆盖。比赛公开页面还存在 8/20–8/27 报单展示缺口，因此不得直接把比赛可见收益曲线当完整账户收益。当前下一门槛：继续寻找未参与发现的新交易样本，并对 Selection 与 Execution Access 分层验证。

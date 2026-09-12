# 牛牛 AI · A股个人交易研究助手改造总计划

- 计划冻结日期：2026-09-12
- 改造基线：`e6502aafdfea7310d46a06b7986f79425846ed71`
- 基线状态：`main` 与 `origin/main` 一致，工作区干净
- 当前全仓基线：681 passed / 0 failed / 0 skipped
- 计划性质：长期核对合同；阶段实现如需偏离，必须在本文件追加变更记录，不静默改目标

## 1. 改造目标

将牛牛从“统一技术交易因子实验平台”升级为：

> **牛牛 AI · 个人 A 股交易研究助手**

最终同时具备三类能力：

1. **Trading Desk**：每天面向 A 股市场、主线、股票、计划、持仓意图和复盘使用。
2. **Research Lab**：保留并继续强化现有因子、实验、PIT、Alpha Factory、Campaign、Watch 等严谨研究能力。
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

借鉴：A 股业务导航、主线→股票→动作、跨日股票档案、R1/R2/R3、D1/D2/D3、共享池、动作状态、规则判/AI 判分离、多助理按需复核、开发助理、移动入口、系统健康可视化。

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
   │   └─ 现有全部因子、实验、PIT、Campaign、Factory、Watch 能力
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

`User Request → DevTask → isolated git worktree → Developer → targeted tests → Reviewer → full tests(必要时) → diff/risk/evidence → Human Approval → merge/commit/push`

DevTask 最小记录：

- `dev_task_id / requested_by / created_at`
- `base_commit / worktree / allowed_paths / risk_level`
- `agent_id / model_id / prompt_version`
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

### P9 Agent Scorecard
- 评价 Coverage、证据正确、计划完整、及时性、修订纪律、约束违规、后续跟踪等。
- 第一阶段只展示，不自动调模型权重。

### P10 Dev Studio
- DevTask、worktree、Developer、Reviewer、tests、人工 merge。
- 验收：研究 Agent 无 repo write 权；开发 Agent 无生产 main 自动发布权。
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
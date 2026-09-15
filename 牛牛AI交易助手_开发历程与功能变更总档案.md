# 牛牛 AI 交易助手：开发历程与功能变更总档案

- 文档性质：长期维护的产品开发史 / 功能变更日志 / 发布索引
- 首次建立：2026-09-14
- 仓库：`github.com:anyuzhe/niuniu`
- 当前主线：牛牛从统一技术交易因子实验平台升级为“牛牛 AI · 个人 A 股交易研究助手”
- 维护要求：本文件不是一次性总结。今后任何有意义的功能、架构、数据、权限、研究语义、AI Agent、部署、测试基线或发布变化，都必须同步追加记录。

## 1. 文档目标

本档案用于回答四个长期问题：

1. 牛牛从哪里开始，为什么一步步演进成现在的形态。
2. 每个阶段具体开发了什么、解决了什么问题。
3. 每次关键改动发生在什么时间、对应什么提交、测试状态如何。
4. 当前还缺什么，以及后续新功能是在什么历史背景下加入的。

本档案与代码、结构化 Research Evidence 的关系：

- Git 代码和提交历史是工程事实的权威来源。
- 结构化实验、PIT、Decision、Playbook、Watch、交易证据是数值/研究事实的权威来源。
- 本文件负责“人类可读的开发史和变更说明”，不得用文字覆盖原始结构化证据。
## 2. 后续维护规则

从本文件建立之日起，每次开发完成后必须检查是否需要追加记录。以下变化必须记录：

- 新功能、新页面、新 CLI、新 MCP 工具、新后台服务。
- 已有功能的重要行为变化、权限变化、数据合同变化。
- AI Agent 角色、模型路由、Peer Review、记忆规则、工具权限变化。
- 研究语义变化，例如 PIT、候选全集、回测口径、Alpha 结论边界。
- 重要 Bug 修复，尤其是可能导致未来函数、数据污染、重复执行、错误成交或权限越界的问题。
- 数据源、数据更新链、部署方式、实时行情、跟踪 daemon、券商/Paper 接口变化。
- 全仓测试基线、关键验收结果、重要性能或兼容性变化。
- 阶段性计划调整、功能延期、删除、降级或替换。

每条记录至少应包含：

`日期时间 / 类型 / 模块 / 改动内容 / 改动原因 / 关键约束 / 测试证据 / Git提交 / 后续事项`

不要求记录临时 scratch、被 Git 忽略的原始网页/行情快照、一次性调试输出；但如果这些材料导致正式功能或研究结论变化，必须记录其产生的正式变化。

未来规则：**代码提交完成但本档案未同步更新时，该阶段不视为完整收尾。**

## 3. 当前产品快照（2026-09-15）

当前牛牛已经从“因子实验平台”演进为一个以**多来源交易知识 → Playbook → 验证 → Daily Decision → Review**为研究主循环的个人 A 股交易研究系统。

产品模块仍分层组织：

- **Trading Desk**：今日交易、主线市场、股票中心、Decision Frame、Strategy Intent、复盘。
- **AI Team**：Chief、Market Scanner、Skeptic、Quant Researcher 与按需 Peer Review；不采用多数票替代证据。
- **Trading Knowledge / Playbook Lab**：当前已有 ExpertSource、候选全集、Selection、Validation、前瞻冻结；架构 v2 将其继续泛化为 StrategySource 多来源模型。
- **Research Lab**：因子、理论、PIT、Campaign、Alpha Factory、Watch、统计验证、执行回测、数据归档。
- **Dev Studio / System**：P10 Dev Studio / Dynamic Agent Orchestrator 与 P11 System Health v1 均已完成；System Center 已统一服务/任务/数据/PIT/通知/Dev/日志的只读可观察性。
- **Mobile / Broker / Readiness**：P12 同源移动端、P13-A 只读 Broker/Shadow 与 P13-B0 RealTrade Readiness 均已完成；当前无具体券商实时通道，真实券商连接、认证与订单能力仍未启用。

知识存储采用双轨：Git/Markdown 保存人类可读规则、经验、架构和 Agent Operating Memory；结构化存储保存来源哈希、CandidateSet、MarketSnapshot、Decision、PIT、实验、成交和收益。

当前正式代码全仓基线：**897 passed / 0 failed / 0 skipped**。
当前已完成：P1～P8、P8.5-A～E1、P8.6 StrategySource、P8.7 Daily Orchestrator v1、P8.8 长期 Paper 核心闭环、P9 Agent Scorecard v1、P10 Dev Studio v1、P11 System Health v1、P12 Mobile / Bot v1、P13-A Broker Read-only / Shadow v1、P13-B0 RealTrade Readiness v1。
下一阶段：P13-B1 Live Read-only Broker Adapter；等待明确可用的具体券商通道，订单能力仍不默认开启。

## 4. 第一阶段：统一量化研究平台形成（2026-09-10 ～ 2026-09-12）

### 2026-09-10 18:53｜初始研究平台导入

- 类型：平台基线
- Git：`56dfa48` `Initial import of Niuniu research platform with bilingual documentation`
- 形成 PyQt6 桌面、CLI、本地 Web、数据读取、因子、结构/事件、理论实验、统计研究、策略回测、归档复算等统一研究骨架。
- 已覆盖经典缠论、威克夫、Brooks、ICT/SMC、Alpha101/158 等明确规则化研究路径。
- 产品定位当时仍是“统一技术交易因子实验平台”，AI 和每日 Trading Desk 尚未成为主线。

### 2026-09-10 23:36｜客户端、科研验证、断点恢复增强

- Git：`c6cb2fd`
- 完善客户端交互、科研验证、任务恢复和中断续算。
- 强化“研究结果必须可复现、失败不能静默消失”的工程基础。

### 2026-09-11 08:55｜AI 研究助手正式接入

- Git：`ac12962`
- 新增可配置研究助手、提案审批与 Codex 对话。
- AI 可以理解研究需求、查询证据、提出研究计划，但不能自行越过宿主审批执行高风险研究。
- 这是牛牛从“纯量化工具”向“AI研究助手”转型的第一个关键节点。

### 2026-09-11 09:30｜证据化研究记忆

- Git：`49fa6de`
- 新增研究记忆与跨会话检索，强调记忆必须能回指真实实验/证据。
- 为后续 AI Team、Stock Dossier、长期 Watch 奠定跨会话上下文基础。
### 2026-09-11 10:34 ～ 18:45｜研究包、Baostock、长期跟踪体系

- `756847f`：固定研究包、复算与持久手动因子跟踪。
- `7c136b3`：接入 Baostock 数据、滞后估值因子和交易日历检查。
- `9814ac9`：增加有限预授权自动跟踪、同步与应用内提醒。
- `358dc76`：增加候选因子共同样本对照，完善跟踪恢复和通知。
- 这一阶段将“单次实验”推进为“可长期观察、可更新、可恢复”的研究工作流。

### 2026-09-11 20:31 ～ 23:55｜数据通道与持续更新闭环

- `c8e1dbb`：跟踪基准换版与进度索引。
- `1dd3923`：修复逐交易日覆盖检查和休市截止逻辑。
- `a84f8c8`：Baostock 跨批次固定更新通道与发布审计。
- `685751a`：有限自动下载与持续跟踪闭环。
- 数据更新开始具备“固定通道、版本、发布链、恢复和审计”语义，而不是简单覆盖文件。

### 2026-09-12 10:40 ～ 17:28｜受限 DSL、MCP、Alpha Factory

- `b01c312`：受限 DSL 候选与固定增量证据闭环；禁止任意 eval 和未来位移。
- `3301baa`：标准 MCP 与常驻跟踪部署；MCP 保持受控只读/提案边界，后台 daemon 复用正式任务队列。
- `6687c43`：主动 Research Agenda 与 Safe Alpha Factory；研究候选、固定测试族和观察池晋级均受宿主权限约束。
- 这一阶段使 AI 能“持续研究”，但仍不能自己把结果晋级为生产真理。

### 2026-09-12 19:21｜A股数据资格与 Strict PIT 阻断层

- Git：`e6502aa`
- 建立 `research_only / retrospective_reference / strict_pit / official_rule_covered` 等数据资格语义。
- bar vintage、复权信息、股票池、外部字段、中性化控制、逐日交易制度不足时严格 fail-closed。
- 该提交成为之后 Trading Desk 改造的技术基线；当时全仓基线记录为 **681 passed / 0 failed / 0 skipped**。
## 5. 第二阶段：从量化平台正式改造为 AI 交易助手（2026-09-12 ～ 2026-09-13）

### 2026-09-12 19:46｜AI Trading Desk 总计划冻结

- Git：`aff4949` `docs: 固定牛牛AI交易工作台改造总计划`
- 明确最终产品三层：Trading Desk / Research Lab / Dev Studio。
- 冻结 P1～P13 路线，不推倒原研究内核，而是在严谨研究证据之上增加每日交易产品层。
- 关键原则：策略意图、Paper Position、真实账户永不混写；AI 不得绕过批准、PIT 或执行权限。

### 2026-09-12 21:01｜P1 + P2：新导航与 Decision Ledger

- Git：`5a8159f`
- 新增八个一级业务入口：今日交易、主线市场、股票中心、持仓计划、复盘中心、AI团队、研究实验室、系统中心。
- 原 12 个研究页面保留并收纳到 Research Lab。
- Decision Ledger 成为一等对象：append-only、revision、幂等、checksum、证据引用、提交时间。
- 阶段全仓：**688 passed**。

### 2026-09-12 21:31｜P3：Stock Dossier 股票研究档案

- Git：`ac7baa6`
- 从“以实验为中心”改为支持“以股票为中心”的跨日聚合。
- 聚合 Decision、实验、Factor Watch、计划与后续 Outcome；可以从股票反向打开原始研究证据。
- 阶段全仓：**692 passed**。

### 2026-09-12 23:40｜P4：Theme Matrix 主线市场

- Git：`94d315f`
- 新增主题 × 交易日 × Decision Frame 的主线市场矩阵。
- 市场事实、Machine Rule、Quant Evidence、AI Thesis、Risk Review 分层保存。
- 缺失状态保持 `UNKNOWN`，禁止从 AI 文本或股票标签反推市场事实。
- 阶段全仓：**700 passed**。
### 2026-09-13 00:50｜P5：Decision Frame 时间合同

- Git：`a45ec8c`
- 正式引入 `PREP / AUCTION / R1 / R2 / R3 / D1 / D2 / D3_PLUS`。
- 保存真实 submitted_at、Frame Policy 版本和 `EARLY / ON_TIME / LATE / BACKFILL`。
- 历史补交不能伪装成原时点判断；跨轮 missing 和变化可比较。
- 阶段全仓：**710 passed**。

### 2026-09-13 01:27｜P6：Strategy Intent 状态机

- Git：`1c3b81f`
- 建立 `DISCOVERED → WATCH → READY → PLAN_OPEN → OPEN → ADD → HOLD → REDUCE → EXIT`。
- 增加 `INVALIDATED / REJECTED / EXPIRED` 旁路终态。
- 阻止非法跳级、历史插入、后续状态下回写旧动作。
- Strategy Intent 只表达策略意图，不冒充 Paper/真实成交。
- 阶段全仓：**720 passed**。

### 2026-09-13 01:58｜P7：今日交易驾驶舱

- Git：`c04d434`
- 默认首页开始面向“今天要处理什么”，而不是实验列表。
- 聚合 Strategy Intent、Theme Snapshot、AI Thesis、Risk Review、Agenda、Watch 与数据状态。
- 首页默认只读，不因打开页面自动调用模型、刷新 Watch 或创建研究任务。
- 阶段全仓：**724 passed**。

### 2026-09-13 02:57 ～ 04:01｜Git-first Agent Memory 与 P8 AI Team

- `5706f2a`：初始化 `agent_memory/`，确立 Git Markdown 为 Agent Operating Memory 权威源。
- `7a8ebd1`：完成 AI Team / Peer Review。
- 固定 Role 与模型解耦；Reviewer 第一轮互盲，第二轮仅 Chief 综合，最多两轮。
- Reviewer 只拥有只读证据工具；模型只能创建 pending 复核请求，真正发送/执行仍需宿主许可。
- 正式 Agent 启动时要求 Agent Memory 对应 Git 状态可审计。
- 阶段全仓：**736 passed**。
## 6. 第三阶段：Expert Playbook Lab 与高手玩法研究（2026-09-13 ～ 2026-09-14）

### 2026-09-13 04:06 ～ 08:46｜P8.5 规划与基础框架

- `6a0e971`：增加 Playbook Lab 与动态 Agent 编排计划，后续优先级调整为 P8.5 → P9 → P10。
- `d90649c`：建立 Expert Playbook Lab 与“10选2”验证框架。
- 正式对象：`ExpertSource / PlaybookDefinition / PlaybookCase / CandidateSet / SelectionDecision / PlaybookValidation`。
- 核心变化：不再只研究“高手买了谁”，必须保存当时全部候选、没买的股票、失败样本和选择差异。
- 正式 HOLDOUT/WALK_FORWARD 要求 FROZEN、VERIFIED、FULL、STRICT_PIT、实时 SYSTEM_PREDICTION 和执行审计。
- P8.5-A 完成时全仓：**750 passed**。

### 2026-09-13 08:52 ～ 12:02｜期末50分真实来源与候选全集

- `83d3b5e`：核验期末50分本人主帖、公开交割讨论和来源完整性限制。
- 用户随后提供公开 KDocs 交割表成交副本；原始材料只保存在 Git 忽略的 `source_raw/`，Git 保存哈希和审计摘要。
- `d1ea2e6`：重建首批完整候选池。
- 7/1 重建 18 只 `FULL + RETROSPECTIVE_REFERENCE` 二板候选，真实选择浙江东日。
- 7/3 重建 16 只候选，真实选择宜宾纸业。
- 加入精确涨停价、真实交易日、停牌跳过、S股/ST特殊价格限制，禁止用“涨幅≥9.7%”近似涨停。
- 本阶段收尾全仓：**756 passed**。

### 2026-09-13 14:16｜Selection 外推与防历史回填

- Git：`8e06f90`
- 7/2 康欣新材建立 19选1失败样本；7/13立方制药作为首个未参与发现的回放样本。
- selection-hypothesis-v1 在 7/13 回放错误选择贵绳股份，真实选择立方；0命中被永久保存，不允许事后抹掉。
- 建立 v2 DRAFT：市场节点/题材生命周期 → 可成交性 → 主动拉升确认 → 相对强度。
- SYSTEM_PREDICTION 增加 wall-clock 近实时约束；历史回放只能用 HUMAN_RECONSTRUCTION。
- 全仓：**758 passed / 0 failed / 0 skipped**。
### 2026-09-13 14:42 ～ 15:04｜高位子玩法、未见样本与执行访问边

- `5274628`：固化空间龙首次可交易分歧、同日重入、高低切、旧龙二波修复等高位研究分支。
- 7/1～7/24 的“唯一最高板”机会同时保存正负样本，证明“见最高板就买”不是充分条件。
- `f8c7036`：扩展 8 月/9 月未见样本，并正式拆分 `Selection Alpha` 与 `Execution Access`。
- 万向德农、竞业达暴露隔夜排板/通道依赖；普通账户回测不能默认一字板可成交。
- 8/7 百花医药暴露原 Meta-Playbook 覆盖缺口，增加“中位题材核心加速”研究方向。
- 比赛页面 8/20～8/27 报单展示缺口被记录为 source integrity caveat，不能把可见收益曲线当完整账户收益。

### 2026-09-13 23:27｜华西成功 / 正裕失败正反例与 v3

- Git：`e9a8b51`
- 华西股份：8/13买入、8/14卖出+9.94%，华安武汉百步亭席位金额与整股数量交叉验证；候选全集因制度差异保持 PARTIAL。
- 正裕工业：8/17完整二板10只，8/18一字3板买入，8/19次日-10%割肉；成为 `QUEUE_DEPENDENT` 的明确失败样本。
- 结论：高速通道只改变“能不能成交”，不保证正期望收益。
- 新建 `meta-playbook-hypothesis-v3`：**市场节点 → 目标身位 → 身位内相对选择 → 执行访问**。
- 将 **2026-09-13** 固定为 v3 research cutoff；之后的新结果只能评估 v3，不能反过来改 v3 再宣称样本外成功。

### 2026-09-13 23:53｜桂林强样本与龙版证据边界

- Git：`e822e60`
- 桂林旅游：9/9四只3板全集，9/10竞价唯一涨停；账户截图、龙虎榜买卖和候选竞价形成强交叉 `OBSERVED_EXPERT`。
- 龙版传媒：9/4 两只4板候选中历史回放选择龙版，但三日龙虎榜无法确认精确买入日，因此只写 `HUMAN_RECONSTRUCTION`。
- 继续强化“证据够多少就说多少”，不因为结果漂亮而升级证据等级。
### 2026-09-14 00:01｜真正前瞻验证 PREP 启动

- Git：`16303a0`
- 9/14 尚未开盘时，首次真实冻结 PREP 快照。
- 市场节点：退潮 / HIGH_RISK；目标观察身位：2→3。
- 候选全集提前冻结为：超声电子、九鼎新材、中新赛克、凯盛新能。
- PREP 阶段不提前选具体股票，避免在竞价数据不存在时“预测”答案。
- 该提交标志 P8.5 从历史研究正式进入“先预测、后揭晓”的前瞻阶段。

### 2026-09-14 09:39｜Playbook 前瞻冻结执行器

- Git：`2b313ea` `feat: 增加Playbook前瞻冻结执行器`
- 新增命令：`niuniu-playbook-forward`。
- PREP / AUCTION / R1 各自有数据就绪时间闸门；09:25 前不能写 AUCTION，09:35 前不能写 R1。
- 快照超过10分钟不能冒充实时预测；同一 Frame 一旦冻结，不能用不同答案覆盖。
- 相同 payload 可幂等重试，不重复制造 Case/CandidateSet/Prediction。
- 新增5个前瞻闸门测试，全仓最终：**763 passed / 0 failed / 0 skipped**。

### 2026-09-14 09:44｜首条 PREP → AUCTION → R1 完整前瞻链

- Git：`55062c8` `research: 冻结9月14日AUCTION与R1前瞻`
- 09:25竞价快照：超声电子 +1.12%、九鼎新材 -5.23%、中新赛克 +10%、凯盛新能 +6.21%。
- AUCTION 冻结结论：`NO_AUCTION_ENTRY`，不把“竞价涨停”直接等同于买入。
- 09:31～09:35：超声电子从竞价+1.12%主动拉至约+6.13%；中新赛克持续一字涨停但为 `QUEUE_DEPENDENT`；凯盛新能高开回落；九鼎新材仍弱。
- R1 在真实时间冻结 `SYSTEM_PREDICTION`：**选择超声电子**。
- 当前尚未取得同日专家真实 `OBSERVED_EXPERT` 标签，因此该预测不能提前宣称命中或 Alpha。
## 7. 当前功能地图

### 7.1 Trading Desk

已完成：八大业务导航、今日交易驾驶舱、Decision Ledger、Stock Dossier、Theme Matrix、Decision Frame、Strategy Intent、跨轮复盘与证据跳转。

仍需加强：真正的实时 Market Snapshot、自动 Daily Scanner、Playbook 命中自动进入 Trading Desk、Paper Position 长期闭环。

### 7.2 AI 与 Agent

已完成：AI Research Chat、提案审批、AI Team、Peer Review、Git-first Agent Memory、标准 MCP、长期跟踪与受限自动化。

已完成：P9 Agent Scorecard v1、P10 Dev Studio + Dynamic Agent Orchestrator v1、P11 System Health v1、P12 Mobile / Bot v1、P13-A Broker Read-only / Shadow v1 与 P13-B0 RealTrade Readiness v1。下一正式阶段为 P13-B1 Live Read-only Broker Adapter；等待具体券商通道。

### 7.3 Research Lab

已完成：数据/PIT、Factor、理论、结构事件、组合评分、Holdout、Walk-forward、Bootstrap、多重检验、独立成交回测、Campaign、Alpha Factory、Watch、复算归档。

仍需加强：approval-time actual-byte freeze、Research Session Grant、更多 Strict PIT 历史原始资料、Watch 序贯统计。

### 7.4 Trading Knowledge / Playbook Lab

已完成：ExpertSource 试点、来源归档、候选全集、selected/unselected、规则版本、历史回放、前瞻冻结、防回填、Selection/Execution Access 分离、PREP/AUCTION/R1 Scanner 与 DailyMarket 增量接力。

当前架构已推进到 P13-B0：StrategySource、Daily Orchestrator、Prediction→Decision→动态 Paper→跨日复盘、Agent Scorecard、Dev Studio、System Health、同源 Mobile/Bot、只读 Broker Shadow 与 RealTrade fail-closed Readiness 均已落地；当前没有可用的具体券商实时通道。

## 8. 尚未完成的正式阶段

- **P8.7 扩展项（并行）**：R2/R3 自动编排与正式实时 MarketSnapshot provider 仍未产品化。
- **P8.8 运行验证（并行）**：核心长期 Paper 闭环已实现，但仍需积累足够真实前瞻运行天数来评价稳定性和绩效。
- **P13-B1 Live Read-only Broker Adapter**：等待明确可用的具体券商实时只读通道；不默认包含订单权限。
- **P13-B2/B3**：认证/密钥、实时 Shadow、kill switch、风险限额、逐单确认、订单 Gateway 和最终真实订单继续分别评审。

## 9. 当前推荐的后续主线

1. 出现具体券商通道后推进 P13-B1，只做实时只读 Adapter；不把 Paper/Mobile/Broker Snapshot/Shadow MATCH/完整 policy 自动外推为订单权限。
2. 无 B1 通道期间，优先推进 R2/R3 Orchestrator、正式实时 MarketSnapshot provider、Strict PIT 原始资料、approval-time actual-byte freeze、Research Session Grant 与 Watch 序贯统计，同时继续积累真实前瞻 Paper 样本。

## 10. 关键测试基线演进

| 日期 | 阶段 | 全仓结果 |
|---|---|---:|
| 2026-09-12 | Trading Desk 改造基线 / Strict PIT | 681 passed |
| 2026-09-12 | P1+P2 导航 + Decision Ledger | 688 passed |
| 2026-09-12 | P3 Stock Dossier | 692 passed |
| 2026-09-12 | P4 Theme Matrix | 700 passed |
| 2026-09-13 | P5 Decision Frame | 710 passed |
| 2026-09-13 | P6 Strategy Intent | 720 passed |
| 2026-09-13 | P7 Trading Cockpit | 724 passed |
| 2026-09-13 | P8 AI Team / Peer Review | 736 passed |
| 2026-09-13 | P8.5-A Playbook Lab 基础框架 | 750 passed |
| 2026-09-13 | P8.5-B 首批完整候选池 | 756 passed |
| 2026-09-13 | Selection 外推 / 防回填 | 758 passed |
| 2026-09-14 | 前瞻冻结执行器 | **763 passed / 0 failed / 0 skipped** |
| 2026-09-14 | P8.5-D1 MarketSnapshot / Daily Scanner | **769 passed / 0 failed / 0 skipped** |
| 2026-09-14 | P8.5-D2 PREP 全市场扫描 | **777 passed / 0 failed / 0 skipped** |
| 2026-09-14 | P8.5-E1 DailyMarket 增量 / PREP Overlay | **784 passed / 0 failed / 0 skipped** |
| 2026-09-14 | P8.6 StrategySource 通用来源层 | **793 passed / 0 failed / 0 skipped** |
| 2026-09-14 | P8.7 Daily Orchestrator v1 | **805 passed / 0 failed / 0 skipped** |
| 2026-09-14 | P8.8-A/B Decision Bridge + PaperPlan | **821 passed / 0 failed / 0 skipped** |
| 2026-09-14 | P8.8-C Dynamic Paper / Fill Intent / Review / Rebalance | **842 passed / 0 failed / 0 skipped** |
| 2026-09-14 | P9 Agent Scorecard v1 | **848 passed / 0 failed / 0 skipped** |
| 2026-09-15 | P10 Dev Studio / Dynamic Agent Orchestrator v1 | **862 passed / 0 failed / 0 skipped** |
| 2026-09-15 | P11 System Health v1 | **876 passed / 0 failed / 0 skipped** |
| 2026-09-15 | P12 Mobile / Bot v1 | **882 passed / 0 failed / 0 skipped** |
| 2026-09-15 | P13-A Broker Read-only / Shadow v1 | **889 passed / 0 failed / 0 skipped** |
| 2026-09-15 | P13-B0 RealTrade Readiness v1 | **897 passed / 0 failed / 0 skipped** |

说明：本表只记录仓库文档中已有明确证据的基线，不补猜未记录阶段的测试数量。

## 11. 持续变更日志

从 2026-09-14 起，本节按实际发生顺序持续追加。历史大阶段见前述章节；这里用于未来日常变更。

### 记录模板

```markdown
### YYYY-MM-DD HH:MM｜[类型] 简短标题
- 模块：
- Git：`<commit>` `<subject>`
- 改动内容：
- 改动原因：
- 关键约束/兼容性：
- 测试/验收：
- 后续事项：
```

### 2026-09-14｜建立本开发历程与功能变更总档案

- 模块：工程治理 / Agent Memory
- 改动内容：首次把 2026-09-10 起的研究平台、AI研究助手、Trading Desk、AI Team、Playbook Lab 与前瞻验证过程统一整理为长期总档案。
- 改动原因：避免功能越来越多后只能依赖聊天记录或零散验收文档恢复历史。
- 新规则：以后每次有意义的新改动必须同步追加本文件；未更新开发史的功能改动不视为完整收尾。
- 后续事项：由 `agent_memory/rules/development_history.md` 对后续 Agent 强制提示该维护要求。
- 测试/验收：本次仅新增文档与 Agent 维护规则，不修改生产代码；`git diff --check` 通过。
- Git：本条记录随本总档案首次提交一并发布，具体 SHA 以该提交的 Git 历史为准。

### 2026-09-14 12:15｜[功能] P8.5-D1 MarketSnapshot 与 Daily Playbook Scanner

- 模块：实时市场证据 / Expert Playbook / Trading Cockpit / AI只读工具
- Git：本条与功能代码同一提交发布，提交标题 `feat: 增加MarketSnapshot与Daily Playbook Scanner`；SHA 以该提交 Git 历史为准。
- 改动内容：新增 append-only `MarketSnapshotStore`，把竞价/R1 等当时行情正式冻结为可哈希、可审计对象；新增 `DailyPlaybookScanner`，在已冻结 CandidateSet 内做 AUCTION/R1 确定性排序与选择。
- 改动原因：9/14 第一条真实前瞻实验已经证明手工脚本可跑，但事实层仍是临时文件；需要把“抓到什么行情、何时抓到、是否完整、能否称实时”升级为产品合同。
- 关键约束：未来时间拒绝；超过近实时窗口只能 BACKFILL；候选缺失 fail-closed；QUEUE_DEPENDENT 不冒充普通账户可成交；Scanner 默认只读，显式 `--freeze` 才能写 SYSTEM_PREDICTION。
- 产品接入：新增 `niuniu-market-snapshot`、`niuniu-daily-playbook-scan`；Trading Cockpit、AI Research、Reviewer、标准 MCP 均可只读查看正式快照。
- 测试/验收：9/14真实数据 BACKFILL 重放仍选择超声电子；新增6项核心测试；最终全仓 **769 tests / 0 failed / 0 skipped**；editable install 后两个新 CLI 已实际可运行。
- 后续事项：P8.5-D2 自动化 PREP 全市场扫描、市场节点→目标身位路由和完整 CandidateSet 生成；official-rule 不足时保持 PARTIAL/UNKNOWN。

### 2026-09-14 15:20｜[功能] P8.5-D2 PREP全市场扫描与市场节点路由

- 模块：PREP全市场扫描 / Market Node Router / 数据资格 / Playbook前瞻链。
- Git：本条与功能代码同一提交发布，提交标题 `feat: 增加PREP全市场扫描与节点路由`；SHA 以该提交 Git 历史为准。
- 改动内容：新增 `prep_scanner.py` 与 `niuniu-prep-playbook-scan`，从全市场日线读取、涨跌停/连板高度、市场宽度与最高板事实，生成版本化市场节点路由和目标身位 CandidateSet；可进一步保存 PREP MarketSnapshot 并接入既有 forward freeze。
- 改动原因：D1 已能对冻结候选做 AUCTION/R1 扫描，但 PREP 候选仍依赖人工；D2 将“全市场 → 市场节点 → 目标身位 → 候选集”产品化。
- 关键约束：Router v1 明确标记 `host_engineering_policy_not_expert_rule`，不是期末50分已验证规则；其余节点证据不足时返回 UNKNOWN，不强行每日推荐。
- 数据资格：逐日 MarketRules 只有同时满足无缺口、官方交易所来源、本地哈希 receipt 以及 PIT Universe 资格时才能升级严格口径；旧 MQC 自动降级为 `PARTIAL + RETROSPECTIVE_REFERENCE`。
- 数据新鲜度：新增 Parquet 元数据 fail-fast；若请求交易日晚于本地最新日线，返回 `DATA_NOT_UPDATED` 与实际最新日期。
- 真实验收：2026-09-04 全市场 5215 只完整扫描约17.7秒；本地数据请求 2026-09-11 时约6.3秒确认最新仅到2026-09-04并阻断。
- 测试/验收：D2 新增8项测试；D1+D2+Playbook 联合回归 32/32；完整仓库 **777 tests / 0 failed / 0 skipped**。
- 后续事项：建设每日全市场数据自动更新链，并把数据更新成功事件接到 PREP 自动运行，再衔接 AUCTION/R1 定时扫描。

### 2026-09-14 16:45｜[功能] P8.5-E1 每日全市场增量归档与 PREP Overlay

- 模块：市场数据更新 / PREP Scanner / Expert Playbook 前瞻基础设施。
- Git：本条与功能代码同一提交发布，提交标题 `feat: 增加每日全市场增量归档与PREP接力`；SHA 以该提交 Git 历史为准。
- 改动内容：新增 append-only `DailyMarketArchive`，按交易日保存 Baostock 全A股日快照的原始响应、规范化 Parquet、manifest 与 SHA256；PREP Scanner 支持“旧 MQC 历史湖 + accepted DailyMarket 日增量”叠加，不再要求每天重写 5215 个单股历史文件。
- 改动原因：D2 已发现当前 MQC 全市场湖会出现数据截止日落后；每日自动 PREP 需要轻量、可审计、可修订的最近交易日数据层。
- 关键约束：同内容幂等；历史修订进入 revision review，宿主显式确认才切换；重叠数据冲突 fail-closed；`preclose/tradestatus/isST` 可补市场事实，但 PIT Universe 与官方逐日 MarketRules 仍独立审核，不能因此升级 Strict PIT。
- 产品接入：新增 `niuniu-daily-market`；`capture` 是唯一联网动作，查询默认只读；`niuniu-prep-playbook-scan` 自动消费 accepted 日增量。
- 测试/验收：DailyMarket + PREP 联合专项 **15/15 passed**；完整仓库 **784 tests / 0 failed / 0 skipped**；editable install 与 CLI smoke 通过。
- 已知限制：本次会话真实 Baostock provider 请求未成功返回，网络可用性仍为运行期依赖；SDK 函数/字段合同来自本机安装包源码及 demo，联网路径由 fixture 测试覆盖。
- 后续事项：另起阶段实现受控每日编排（收盘 capture → 数据就绪 → PREP → 09:25 AUCTION → 09:35 R1）。
### 2026-09-14 17:35｜[架构] Trading Knowledge / StrategySource 架构 v2

- 模块：项目定位 / Trading Knowledge / Playbook / 开发路线。
- Git：本条与 README、项目总体架构和总开发计划同一文档提交发布；SHA 以 Git 历史为准。
- 改动内容：将“高手玩法/期末50分试点”上收为通用 `StrategySource → Playbook → Validation → Daily Decision → Review` 架构；期末50分明确降为首个 `TRADER` 类型来源样本。
- 新来源模型：目标支持 TRADER / USER_EXPERIENCE / PUBLIC_METHOD / HISTORICAL_CASE / STATISTICAL_DISCOVERY / SYSTEM_REVIEW；来源与 Playbook 为多对多。
- 兼容边界：当前 `ExpertSource` 不破坏性重命名，先兼容映射为 TRADER；结构化历史 ID、Case、Validation 和来源哈希必须保持可追溯。
- 知识边界：Git Markdown 与 Structured Evidence 双轨继续保持；多 Agent 一致不等于市场证据。
- 路线调整：P8.6 StrategySource → P8.7 Daily Orchestrator → P8.8 Playbook-to-Paper → P9 Scorecard → P10 Dynamic Agent。
- 测试/验收：本次仅改架构/计划/说明文档，不修改生产代码；沿用最近完整生产回归 **784/0/0**，发布前执行文档 diff/sensitive 检查。


### 2026-09-14 18:30｜[功能] P8.6 StrategySource 通用来源层

- 模块：Trading Knowledge / Playbook Lab / AI只读工具 / PyQt Research Lab。
- Git：本条与功能代码同一提交发布，提交标题 `feat: 增加StrategySource通用交易知识来源`；SHA 以该提交 Git 历史为准。
- 改动内容：新增六类 `StrategySource` 与 `PlaybookSourceLink` 多对多关系；旧 `ExpertSource` 无损投影为 `TRADER`，统一查询可同时看到旧高手来源与 USER_EXPERIENCE / PUBLIC_METHOD / HISTORICAL_CASE / STATISTICAL_DISCOVERY / SYSTEM_REVIEW。
- 兼容策略：PlaybookStore schema v2 增量增加新表；旧 v1 库只读无需迁移，首次写新对象时创建新表。真实旧库副本迁移后，42 Source / 17 Definition / 36 Case / 26 CandidateSet / 37 Selection / 2 Validation 的 payload+checksum 指纹全部不变。
- 关键约束：P8.6 的新来源关系只是知识证据层；正式 FROZEN / HOLDOUT / WALK_FORWARD 仍使用旧 `definition.source_ids` + VERIFIED ExpertSource 合同，不能通过新增 StrategySource 绕过正式验证。
- 产品接入：Playbook Lab 改为“交易知识 / Playbook Lab”，桌面宿主可导入 StrategySource/关系；AI Research、MCP、Peer Reviewer 只能只读查询统一来源与关系，无创建/链接工具。
- 测试/验收：StrategySource 核心 7/7、产品专项 13/13、相关联合 41/41；完整仓库 **793 tests / 0 failed / 0 skipped**。
- 后续事项：P8.7 Daily Orchestrator，将 DailyMarket → PREP → AUCTION → R1/R2/R3 串成受控、幂等、可恢复的每日运行链。


### 2026-09-14 18:55｜[功能] P8.7 Daily Orchestrator v1

- 模块：DailyMarket / PREP / MarketSnapshot / Daily Scanner / Forward Freeze / 宿主调度。
- Git：本条与功能代码同一提交发布，提交标题 `feat: 增加Daily Playbook受控编排器`；SHA 以该提交 Git 历史为准。
- 改动内容：新增持久 `DailyPlaybookOrchestrator` 与 `niuniu-daily-orchestrator`。宿主按交易日初始化计划后，可 `--tick` 单步或 `--run` 轮询；状态使用 checksum + 文件锁保存，重启可继续。
- 数据阶段：默认绝不联网；显式 `allow_daily_market_capture` 后才允许在上一交易日18:30后抓 DailyMarket。失败15分钟冷却、最多8次；未确认 revision_review 阻断，人工接受后可恢复。
- PREP：复用全市场 PrepScanner，预留 as_of/scan/snapshot request 后再写副作用；中断后重试复用同一 MarketSnapshot 与 Forward payload，不重复 Case/Selection。
- AUCTION/R1：只消费正式 `LIVE_NEAR_REALTIME` MarketSnapshot。AUCTION只接受09:25–09:30快照；R1第一窗口只接受09:35–09:40。错过窗口写 MISSED，不历史补 SYSTEM_PREDICTION；AUCTION预测错过但当时实时竞价事实存在时，R1仍可继续。
- Fail-closed：当前自动 PREP 在缺 PIT Universe/官方逐日规则时保持 PARTIAL，因此后续 R1 可以正常冻结但必须 NO_TRADE；编排器不会为了“自动选股”突破数据资格。
- 权限：AI Research/MCP 没有 init/tick/run 工具；这是宿主编排器。真实工作区验收前后没有创建 `_daily_orchestrator` 状态，PlaybookStore 原计数保持 42/17/36/26/37/2。
- 测试/验收：P8.7 自身12/12；DailyMarket+Orchestrator 16/16；Forward/Scanner联合36/36；editable install 与 CLI help 通过；完整仓库 **805 tests / 0 failed / 0 skipped**。
- 已知边界：v1 仅 PREP/AUCTION/R1；R2/R3 仍 unsupported。AUCTION/R1 的正式实时 MarketSnapshot provider 尚未产品化，Orchestrator 不使用临时网页抓取替代。
- 后续事项：P8.8 将已有前瞻预测接入 Decision Ledger → Strategy Intent → Paper/Execution → D1/D2/D3+ 复盘。


### 2026-09-14 20:30｜[功能] P8.8-A/B Playbook → Trading Desk → PaperPlan

- 模块：SYSTEM_PREDICTION / Decision Ledger / Strategy Intent / PaperPlan / Trading Cockpit。
- Git：本条与功能代码同一提交发布，提交标题以最终 Git 历史为准。
- P8.8-A：新增 `PlaybookDecisionBridge` 与 `niuniu-playbook-decision-bridge`；只接受真实 SYSTEM_PREDICTION，首次选择最多 WATCH，已有 DISCOVERED→WATCH，READY 保持，NO_TRADE 只留 receipt；人工同 Frame Decision 和 PLAN_OPEN/OPEN/HOLD 等状态不自动覆盖。
- P8.8-A 与 Orchestrator：新增显式 `bridge_to_trading_desk` 计划开关，默认 false，旧 P8.7 行为不变。
- P8.8-B：新增 `PlaybookPaperPlanService` 与 `niuniu-playbook-paper-plan`。只有当前 PLAN_OPEN + 宿主显式确认才能创建/执行；target_weights 必须精确覆盖 Selection selected_symbols；完成 bars + dated MarketRules 后才调用现有 PaperAccount。
- 执行边界：模拟成交 receipt 保存 account revision / order IDs / fills / summary，但**不会自动把 Strategy Intent 从 PLAN_OPEN 改成 OPEN**。
- 恢复：执行 reservation 冻结成交前 order/fill 基线；即使 PaperAccount 已提交成交、PaperPlan receipt 写盘前崩溃，重启仍能恢复原 fills/orders。
- 固定 universe：现有 PaperAccount 不允许历史 universe 被改写；复用账户 universe 不一致时 fail-closed。动态跨日 universe 留给 P8.8-C。
- 产品接入：Trading Cockpit 只读显示 PaperPlan 状态、账户、Universe、Selection Frame、revision 和本次成交数；打开首页无执行副作用。
- 测试/验收：P8.8 联合 Decision/Intent/Paper/Orchestrator/Cockpit **40/40 passed**；完整仓库 **821 tests / 0 failed / 0 skipped**；两个新 CLI editable install / help 烟测通过。
- 后续事项：P8.8-C 动态 universe 长期 Paper、fill→Intent 严格状态合同、D1/D2/D3+ 自动复盘；随后再进入 P9 Agent Scorecard。
### 2026-09-14 22:05｜[功能] P8.8-C 长期动态 Paper 与跨日复盘闭环

- 模块：Dynamic Paper / PaperPlan / Strategy Intent / Rebalance / D1-D3+ Review / 生命周期统计。
- Git：本条与功能代码同一提交发布，提交标题 `feat: 完成长周期Paper与复盘闭环`；SHA 以该提交 Git 历史为准。
- 改动内容：新增独立 `DynamicPaperAccount`，允许跨交易日动态增加证券，同时将新证券在旧 target 中确定性补0，并要求历史 NAV/fill/order 前缀完全不变；旧固定-universe `PaperAccount` 原合同不修改。
- 成交状态：真实 Paper buy fill 经宿主显式确认后才允许 PLAN_OPEN→OPEN；无成交保持 PLAN_OPEN；人工已推进/修订状态时人工状态优先；Decision 已写但 receipt 丢失的崩溃场景可恢复。
- 持仓调整：新增 `PaperRebalancePlan`，ADD/REDUCE/EXIT/INVALIDATED 只能作用于已有动态账户证券，不能借再平衡新增股票；ADD/REDUCE 实际成交后回 HOLD，EXIT 清仓后保留 EXIT 并记录完成回执。
- 跨日复盘：新增 D1/D2/D3+ `PaperOutcomeReview` 与 `auto_all`，只读取复盘日及以前的 bars/fills/nav；未来 D2/D3 数据到达后不能改变已冻结 D1 review_hash；复盘不自动做新的 HOLD/REDUCE/EXIT 判断。
- 长期统计：新增只读生命周期汇总，分开统计 Prediction、NO_TRADE、PaperPlan、成交/未成交、rejection reason、费用、滑点、review 和动态账户收益；打开 Cockpit/统计不会产生交易副作用。
- 权限：新增宿主 CLI，AI/MCP 不获得 Paper 创建、执行、再平衡或 Intent 写权限；真实券商仍属于 P13。
- 测试/验收：P8.8-C 联合链路 52/52 通过；动态账户/再平衡/复盘/权限专项继续全绿；最终完整仓库 **842 tests / 0 failed / 0 skipped**，耗时 292.278 秒。
- 后续事项：进入 P9 Agent Scorecard；并行积累真实前瞻 Paper 样本，补 P8.7 R2/R3 与正式实时 MarketSnapshot provider。

### 2026-09-14 23:20｜[功能] P9 Agent Scorecard v1

- 模块：AI Team / Decision Ledger / Peer Review / Playbook / Paper Lifecycle / Scorecard。
- Git：本条与功能代码同一提交发布，提交标题 `feat: 增加按任务类型Agent Scorecard`；SHA 以该提交 Git 历史为准。
- 改动内容：新增只读 `AgentScorecardService`、`niuniu-agent-scorecard` 和 AI Team Scorecard 页面；按 Decision、独立 Peer Review、Chief Synthesis 三类任务分别展示指标，不生成跨任务模型总分。
- Decision 指标：ON_TIME/off-window、证据链接、model/prompt identity、风险记录、计划完整性、跨日 follow-up 与 revision；字段齐全不等同于判断正确。
- Peer Review 指标：completion/failure、tool use、显式 evidence、model identity；Chief 单独记录 reviewer input completion 与 synthesis completion，不以多数票作为正确性。
- System baseline：Playbook Prediction 单独展示 FULL/STRICT_PIT/NO_TRADE；只有同一 CandidateSet 恰有唯一 OBSERVED_EXPERT 标签时才计算 Exact/Precision/Recall，并显式记录 false positive / false negative；Paper Lifecycle 仅为系统运行基线，不归因给某个 Agent。
- 样本纪律：少于3个样本标记 INSUFFICIENT_SAMPLES；真实工作区当前 Agent Decision/Peer Review 为0样本，因此保持 NO_SAMPLES。Playbook 有3条 SYSTEM_PREDICTION 但0条 observed label，匹配率保持 None。
- 约束边界：宿主拦截但未持久化的违规尝试不可观察，Scorecard 不臆造 violation 次数；证据正确性、Alpha、盈利不自动评分。
- 防迎合：AI Research 可只读查询 Scorecard，但第一轮 Reviewer 的 SAFE_TOOLS 明确排除 Scorecard。
- 真实烟测：Scorecard 运行前后 artifacts 文件数 77006→77006，无写入副作用；AI 工具响应约7.7KB，未触发结果截断。
- 测试/验收：P9/AI Team/Playbook 专项 **21/21 passed**；editable install + CLI 真实运行通过；最终全仓 **848 tests / 0 failed / 0 skipped**，耗时 291.473 秒。
- 后续事项：进入 P10 Dev Studio + Dynamic Agent Orchestrator；并行继续真实前瞻 Paper 样本、R2/R3 Orchestrator、正式实时 MarketSnapshot provider 与 Strict PIT 数据补齐。


### 2026-09-15 01:10｜[功能] P10 Dev Studio + Dynamic Agent Orchestrator v1

- 模块：DevTask / isolated worktree / Main Developer / Dynamic Subagents / Tester / Reviewer / Human Merge。
- 改动内容：新增 P10 Dev Studio 核心、role-scoped tools、Codex runtime、宿主 CLI 和桌面“开发工作台”。
- 权限模型：Main Agent 无 shell/直接写/commit/push/merge；EXPLORER/TESTER/REVIEWER 只读；IMPLEMENTER 只能在不可变 path-scoped lease 内写。动态深度固定1，并行上限3。
- 工作区：每个 DevTask 使用仓库外 detached worktree，冻结 base SHA/branch；symlink、path escape、`.git`、越出 allowed_paths/lease 均 fail-closed。
- 验收：frozen test argv + host实际输出 + Reviewer PASS 均绑定 final worktree fingerprint；diff变化后旧测试/Review 自动失效。Main Acceptance 重新核实际 diff，不相信模型自报 changed_files。
- 发布边界：Human Merge 必须显式确认，main branch/base SHA 变化会阻断；merge 只创建本地 commit，不自动 push。Research Agent 无 Dev Studio 写/merge 工具。
- 产品接入：新增 `niuniu-dev-studio` 和顶级“开发工作台”。
- 测试/验收：P10专项14/14、Trading Desk导航2/2、CLI install/help通过；完整仓库 **862 tests / 0 failed / 0 skipped**，298.180秒。
- 后续事项：进入 P11 System Health；并行继续真实前瞻 Paper 样本、正式实时 MarketSnapshot provider、R2/R3 Orchestrator 与 Strict PIT 数据补齐。

### 2026-09-15 07:35｜[功能] P11 System Health v1

- 模块：System Center / JobQueue / Tracking / MCP / Market Data / PIT / Paper / Dev Studio / Notifications。
- 改动内容：新增只读 `SystemHealthService`、`niuniu-system-health`、桌面 `SystemHealthWidget` 与 AI/MCP `get_system_health`。统一聚合 Workspace、Artifact Growth、JobQueue、Tracking daemon、MCP adapter、Notifications、Market Data/Series、DailyMarket、MarketSnapshot、Daily Orchestrator、PIT/Playbook、Paper Lifecycle、Dev Studio 与日志元数据。
- 状态语义：顶层分离 Runtime 与 Research Readiness，组件只用 OK/WARN/BLOCKED/UNKNOWN/NOT_CONFIGURED；`health_score=None`。进程/adapter 在线从不替代数据资格、PIT、策略正确性或盈利证据。
- 关键修正：历史 Orchestrator BLOCKED/MISSED 降为 WARN，不永久阻断今天；当天 blocker 才进入当前 readiness。MCP 无持久 heartbeat 时明确 `server_liveness=None`。通知 Qt hand-off 不冒充用户已看见。
- 性能：最初递归扫描约77006个 artifacts 文件使健康刷新约14秒，改成顶层 run/system 目录增长代理后真实 CLI 约0.82秒；磁盘剩余容量仍独立检查。
- 权限：System Health 没有 restart/retry/download/接受修订/修改 PIT/merge/push/trade 动作；AI/MCP 仅可只读查询。
- 真实烟测：真实 artifacts 文件数 77006→77006，无写入副作用；当前 Runtime=OK、Research Readiness=WARN、0 blocker，warning 为 no_frozen_playbook_definition；MCP adapter 工具数47。
- 测试/验收：P11 专项+offscreen UI **14/14 passed**；最终完整仓库 **876 tests / 0 failed / 0 skipped**，299.890秒。
- 后续事项：下一正式阶段 P12 移动端 / 机器人；必须复用同一 MCP/API、Decision Ledger、Stock Dossier、System Health、记忆与持仓状态源。

### 2026-09-15 08:10｜[功能] P12 Mobile / Bot v1

- 模块：Mobile Brief / Workbench Mobile / Stock Dossier / Decision Ledger / System Health / MCP。
- 改动内容：新增 `MobileBriefService`、`niuniu-mobile-brief`、MCP `get_mobile_brief` 与同一 Workbench `/mobile`；移动 JSON API 覆盖 brief、stock、decisions、system-health。
- 单一状态源：手机/机器人不创建 `_mobile`、mobile SQLite、第二份 Decision、第二份持仓、第二套 Strategy Intent 或第二套 Agent Memory；所有内容直接读取原有权威存储。
- 安全边界：Workbench 继续只监听 127.0.0.1；mobile API 全部 GET 只读，无 POST 写端点；跨设备必须通过安全隧道或有认证反向代理。P12 不开启真实券商或自动实盘。
- 性能：首版复用完整 Trading Cockpit 导致真实 brief 约7.8秒；定位到 Agenda/Watch 重聚合后改为直接读取同一 Decision/Theme/Paper/Health 存储并复用业务常量，Direct+MCP 连续两次约1.02秒。Stock Dossier 全历史实验关联约7–8秒，仅按需加载且不另建手机缓存库。
- 真实烟测：CLI 与 HTTP `/mobile` 读取真实 artifacts 前后文件数 77006→77006；空股票简报约2.5–2.8KB，`sh.600000` 完整紧凑档案约12KB，均未触发24KB工具结果限制。
- 测试/验收：P12新增专项 **6/6 passed**，相关联合回归 **18/18 passed**；最终完整仓库 **882 tests / 0 failed / 0 skipped**，305.026秒。
- 后续事项：P13 真实券商/真实资金/自动下单按原路线单独评审，不自动启动。
### 2026-09-15 09:20｜[功能] P13-A Broker Read-only / Shadow v1

- 模块：Broker Adapter / Broker Snapshot / Dynamic Paper Shadow / System Health / MCP。
- 改动内容：新增 `ReadOnlyBrokerAdapter`、`JsonBrokerExportAdapter`、append-only `BrokerSnapshotStore`、`BrokerShadowReconciler`、`niuniu-broker-shadow`、MCP `get_broker_shadow` 和 System Health Broker Shadow 观察项。
- 隐私边界：递归拒绝密码、Token、API Key、Cookie、Session、真实券商账号等敏感字段；account alias 不能使用8位以上纯数字账号；导入只读快照需要宿主 `--confirm`。
- 对账语义：Broker 与 Dynamic Paper 比较证券数量和现金；权益差仅描述，不因估值时点差异硬判 MATCH。Shadow MATCH 不生成 Decision、Intent、Paper target 或真实订单。
- 权限：模型没有 Broker Snapshot 导入、券商连接、下单、撤单或资金划转工具；即使存在导入快照，`real_broker_connected=false`。
- 真实烟测：未配置 Broker 的真实工作区查询 artifacts 文件数 **77006→77006**；CLI/MCP 均返回 NOT_CONFIGURED，MCP 返回约412 bytes，写工具交集为空。
- 测试/验收：P13-A 专项 **7/7 passed**，Broker+System Health+MCP **24/24 passed**；完整仓库 **889 tests / 0 failed / 0 skipped**，305.046秒。
- 后续事项：P13-B+ 具体券商实时连接、认证/密钥、真实资金与订单能力必须重新单独评审，不自动启动。

### 2026-09-15 10:20｜[安全架构] P13-B0 RealTrade Readiness v1

- 模块：Broker Capability / RealTrade Safety Policy / Readiness Gate / System Health / MCP。
- 背景：当前没有明确可用的具体券商实时接入通道；禁止为了“继续进度”伪造 Gateway 或把 P13-A 导出快照冒充实时连接。
- 改动内容：新增 `BrokerCapabilityRegistry`、`niuniu-real-trade-policy-v1`、`RealTradeReadinessService`、`niuniu-real-trade-readiness`、MCP `get_real_trade_readiness` 和 System Health `RealTrade Readiness` 观察项。
- 当前能力：唯一 `json-export-v1` 为 offline-file，`live_channel=false / order_submit=false`；真实工作区固定出现 `NO_LIVE_BROKER_CHANNEL`，`ready_for_live_connection=false`、`ready_for_real_orders=false`。
- 安全门：认证运行时、kill switch、逐单风险门、人工确认 Gate、订单 Gateway、真实回执/成交/撤单对账链未实现时全部显式 blocker；未来时间/过期 Broker Snapshot 与 Shadow 非 MATCH 也 fail-closed。
- Policy：B0 固定 `enabled=false`；不猜用户单笔、单票、总敞口、日损、订单数和快照新鲜度。关闭人工确认/kill switch/Shadow/Strict PIT/System Health 或写 `enabled=true` 会拒绝。
- 权限：CLI/MCP/System Health 全部只读；模型没有 policy 写入、connect、place_order、cancel_order、transfer_funds 工具。
- 真实烟测：`artifacts` **77006→77006**；普通 readiness 与示例 policy 均 BLOCKED，MCP 约2.3KB，System Health 对无通道显示 NOT_CONFIGURED 而不污染正常 Research/Paper 健康轴。
- 测试/验收：P13-B0 专项 **8/8 passed**，Readiness+P13-A+System Health+MCP **32/32 passed**；完整仓库 **897 tests / 0 failed / 0 skipped**，352.959秒。
- 后续事项：P13-B1 等待具体券商实时只读通道；无通道期间转向 R2/R3 Orchestrator、正式实时 MarketSnapshot、Strict PIT、approval-time freeze、Research Session Grant、Watch 序贯统计等并行线。

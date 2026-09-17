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
- **Trading Knowledge / Playbook Lab**：当前已有 ExpertSource、候选全集、Selection、Validation、前瞻冻结及 StrategySource 多来源模型；External Research Skill v3 在其上游固定外部Git字节、选择性策展原文/方法/言行结果，并通过Git授权只读Library供界面/Agent检索，不把第三方脚本接入交易核心。
- **Research Lab**：因子、理论、PIT、Campaign、Alpha Factory、Watch、统计验证、执行回测、数据归档。
- **Dev Studio / System**：P10 Dev Studio / Dynamic Agent Orchestrator 与 P11 System Health v1 均已完成；System Center 已统一服务/任务/数据/PIT/通知/Dev/日志的只读可观察性。
- **Mobile / Broker / Readiness**：P12 同源移动端、P13-A 只读 Broker/Shadow 与 P13-B0 RealTrade Readiness 均已完成；当前无具体券商实时通道，真实券商连接、认证与订单能力仍未启用。

知识存储采用双轨：Git/Markdown 保存人类可读规则、经验、架构和 Agent Operating Memory；结构化存储保存来源哈希、CandidateSet、MarketSnapshot、Decision、PIT、实验、成交和收益。

当前正式代码全仓基线：**1006 passed / 0 failed / 0 skipped**。
当前已完成：P1～P8、P8.5-A～E1、P8.6 StrategySource、P8.6-A/B/C External Research Skill Adapter + Git Archive/Curation + Read-only Library、P8.7 Daily Orchestrator（含 R2/R3、三源实时 MarketSnapshot Provider、个股问答ad-hoc只读报价与空候选 `COMPLETE_NO_TRADE`）、P8.8 长期 Paper 核心闭环、P9 Agent Scorecard v1、P10 Dev Studio / P11 System Health v1、P12 Mobile / Bot v1、P13-A Broker Read-only / Shadow v1、P13-B0 RealTrade Readiness v1，以及 Research Lab Approval-time Actual-byte Freeze、Research Session Grant、Watch Sequential Monitor、Strict PIT Evidence Archive/Coverage、PIT Universe Receipt v1、连续SecurityStatus v2工程合同和 Official MarketRules publication receipt v2 + 全局深度审计。2026-09-16 首轮当前工作空间前瞻 PREP 已以 `EXTREME_RISK / NO_TRADE` 正常留证；MarketRules 真实证据现有7个停牌 session，另有7个复牌日 exact 算术回顾性参考但未获得 Strict PIT 资格。郑希上游Git字节已归档、生成首个回顾性DRAFT策展包并接入精确snapshot只读检索，但未写StrategySource/Playbook且未完成Quant Validation。
外部下一阶段：P13-B1 Live Read-only Broker Adapter，等待明确券商通道；内部并行主线：持续真实前瞻每日运行，经宿主授权在未来09:15前同步取得首个真实PIT Universe与完整SecurityStatus snapshot，并继续寻找复牌日开盘前静态参数publication receipt，再推进历史行业与每日真实市值。

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

仍需加强：三源公开网页实时行情已可支撑当前研发/自用，但后续仍可用 QMT/XtQuant/券商级 feed 升级主源；长期 Paper 继续积累真实前瞻样本。

### 7.2 AI 与 Agent

已完成：AI Research Chat、提案审批、AI Team、Peer Review、Git-first Agent Memory、标准 MCP、长期跟踪与受限自动化。

已完成：P9 Agent Scorecard v1、P10 Dev Studio + Dynamic Agent Orchestrator v1、P11 System Health v1、P12 Mobile / Bot v1、P13-A Broker Read-only / Shadow v1 与 P13-B0 RealTrade Readiness v1。下一正式阶段为 P13-B1 Live Read-only Broker Adapter；等待具体券商通道。

### 7.3 Research Lab

已完成：数据/PIT、Factor、理论、结构事件、组合评分、Holdout、Walk-forward、Bootstrap、多重检验、独立成交回测、Campaign、Alpha Factory、Watch、复算归档、Approval-time Actual-byte Freeze 与 Research Session Grant。

仍需加强：真实官方 Strict PIT 历史资料 coverage；Evidence Archive v1 与 Watch 序贯/在线衰减统计 v1 已完成。

### 7.4 Trading Knowledge / Playbook Lab

已完成：ExpertSource 试点、来源归档、候选全集、selected/unselected、规则版本、历史回放、前瞻冻结、防回填、Selection/Execution Access 分离、PREP/AUCTION/R1 Scanner 与 DailyMarket 增量接力。

当前架构已推进到 P13-B0：StrategySource、Daily Orchestrator、Prediction→Decision→动态 Paper→跨日复盘、Agent Scorecard、Dev Studio、System Health、同源 Mobile/Bot、只读 Broker Shadow 与 RealTrade fail-closed Readiness 均已落地；当前没有可用的具体券商实时通道。

## 8. 尚未完成的正式阶段

- **P8.8 运行验证（并行）**：核心长期 Paper 闭环已实现，但仍需积累足够真实前瞻运行天数来评价稳定性和绩效。
- **P13-B1 Live Read-only Broker Adapter**：等待明确可用的具体券商实时只读通道；不默认包含订单权限。
- **P13-B2/B3**：认证/密钥、实时 Shadow、kill switch、风险限额、逐单确认、订单 Gateway 和最终真实订单继续分别评审。

## 9. 当前推荐的后续主线

1. 出现具体券商通道后推进 P13-B1，只做实时只读 Adapter；不把 Paper/Mobile/Broker Snapshot/Shadow MATCH/完整 policy 自动外推为订单权限。
2. 无 B1 通道期间，R2/R3 Orchestrator、三源实时 MarketSnapshot、approval-time actual-byte freeze、Research Session Grant、Watch Sequential Monitor 与 Strict PIT Evidence Archive 已补齐；下一内部优先级是实际归档官方历史资料、量化 receipt coverage，同时继续积累真实前瞻 Paper 样本。

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
| 2026-09-15 | P8.7 v2 R2/R3 + MarketSnapshot Provider | **905 passed / 0 failed / 0 skipped** |
| 2026-09-15 | Approval-time Actual-byte Freeze v1 | **912 passed / 0 failed / 0 skipped** |
| 2026-09-15 | Research Session Grant v1 | **925 passed / 0 failed / 0 skipped** |
| 2026-09-15 | 三源实时 MarketSnapshot Provider v1 | **935 passed / 0 failed / 0 skipped** |
| 2026-09-15 | Watch Sequential Monitor v1 | **945 passed / 0 failed / 0 skipped** |
| 2026-09-15 | Strict PIT Evidence Archive v1 | **950 passed / 0 failed / 0 skipped** |
| 2026-09-15 | Strict PIT Coverage v1 | **956 passed / 0 failed / 0 skipped** |
| 2026-09-15 | Strict PIT SecurityStatus v1 | **961 passed / 0 failed / 0 skipped** |
| 2026-09-15 | 首轮 Daily Orchestrator 前瞻 NO_TRADE / 空候选终态 | **962 passed / 0 failed / 0 skipped** |
| 2026-09-15 | Official MarketRules Publication Receipt v2 / 首批7个停牌 session | **964 passed / 0 failed / 0 skipped** |
| 2026-09-15 | Official MarketRules v2 全局审计 / System Health 接线 | **965 passed / 0 failed / 0 skipped** |
| 2026-09-16 | 复牌日 Exact 价格边界回顾性参考归档 / 审计 | **967 passed / 0 failed / 0 skipped** |
| 2026-09-16 | External Research Skill Adapter / 郑希 SOURCE_REQUIRED 脚手架 | **971 passed / 0 failed / 0 skipped** |
| 2026-09-16 | External Research Skill Git Archive / 郑希回顾性策展包 | **976 passed / 0 failed / 0 skipped** |
| 2026-09-16 | Research Skill Library / Agent只读检索 | **982 passed / 0 failed / 0 skipped** |
| 2026-09-16 | PIT Universe Receipt v1 / Qualification-PREP-Orchestrator接线 | **990 passed / 0 failed / 0 skipped** |
| 2026-09-16 | 连续 SecurityStatus Coverage v2 / silver-PREP-Coverage-Health接线 | **1000 passed / 0 failed / 0 skipped** |
| 2026-09-16 | 个股问答自动实时行情 v1 / 宿主临时报价注入 | **1006 passed / 0 failed / 0 skipped** |

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

### 2026-09-15 11:10｜[功能] P8.7 v2 R2/R3 + MarketSnapshot Provider

- 模块：Daily Orchestrator / Forward Freeze / Daily Scanner / MarketSnapshot Provider / System Health / MCP。
- 改动内容：Forward/Scanner/Orchestrator 从 PREP/AUCTION/R1 扩展至 R2/R3；R2 数据就绪点 11:30、R3 15:00，各自只允许10分钟内前瞻冻结。
- 规则边界：R2/R3 只对前一阶段 selected_symbols 做 continuation review，不允许盘中后段新增股票；缺失/PARTIAL/BACKFILL 快照继续 fail-closed。
- Provider：新增 `MarketSnapshotProvider` Protocol、Registry/Readiness、`niuniu-market-provider-status`、MCP `get_market_snapshot_provider_status` 与 System Health `Snapshot Provider`。当前唯一 `manual-import-v1` 为离线导入，live_channel=false，不冒充实时行情。
- 真实烟测：Provider BLOCKED（AUCTION/R1/R2/R3 均缺 live source），System Health Provider=NOT_CONFIGURED，Research Readiness= WARN；artifacts **77006→77006**。
- 测试/验收：R2/R3+Provider 专项 **27/27**，Provider/Scanner/Orchestrator/System Health/MCP 联合 **44/44**；完整仓库 **905 tests / 0 failed / 0 skipped**，380.437秒。
- 后续事项：R2/R3 状态机已收尾；下一数据侧缺口是真实、可审计的 live MarketSnapshot Provider。无合适数据源时继续 Strict PIT / approval-time actual-byte freeze / Research Session Grant / Watch 序贯统计等并行线。

### 2026-09-15 11:55｜[研究基础设施] Approval-time Actual-byte Freeze v1

- 模块：Research Proposal / JobQueue / DataProvider / Universe / Campaign / Execution / System Health。
- 关键变化：正式 Proposal 在宿主批准时先创建 `_approval_input_freezes/<proposal_id>/`，冻结实际规范化研究 bars、Context、qfq/raw 双价格输入与 Universe eligibility mask，再进入 approved/submitted。
- 执行语义：submit/resume/run 都验证同一 freeze receipt、manifest、spec digest 与文件 SHA256；批准后源数据变化或下线不改变任务，冻结包自身变化则 fail-closed，不回退 live data。
- 来源语义：冻结执行仍保留原 provider / adjustment；`approval_time_frozen=true` 进入文件元数据和 receipt，避免 Watch/Rebase 把冻结存储误判成新行情口径。
- 组合研究：Holdout/Walk-forward 从冻结大区间切片；Campaign 多节点共享一个 approval bundle；精细账户模式同时冻结 qfq signal 与 raw execution；PIT Universe 使用批准时 eligibility mask。
- 权限：模型仍只能 qualify/preview/propose/query，不能 approve、创建/替换 freeze 或修改 JobQueue guard。旧 direct JobQueue / tracking input_signature 保持兼容。
- 可观察性：System Health 新增 Approval Input Freeze 轻量 manifest/文件存在性视图；真正使用边界才做完整 SHA256。
- 真实烟测：capability/System Health 查询前后 artifacts **89484→89484**，未创建冻结目录；冻结目录只在真实宿主批准时生成。
- 测试/验收：专项 **7/7**，Proposal/Campaign/JobQueue/System Health/Execution/Qualification 联合 **64/64**；完整仓库 **912 tests / 0 failed / 0 skipped**，366.669秒。
- 后续事项：内部主线进入 Research Session Grant；外部依赖继续等待正式 live MarketSnapshot provider 与 P13-B1 券商只读通道。


### 2026-09-15 12:35｜[研究基础设施] Research Session Grant v1

- 宿主授权：桌面/CLI 先预览完整范围，再显式确认；模型无 authorize/revoke 权限。
- 范围：证券、日期、周期、复权、qualification、白名单 factor@version 与允许 mode 精确冻结；v1 禁止 Campaign/Execution/Theory/Context、Shell、联网下载、代码写与真实交易。
- 预算：任务数、并行数、单/总叶子研究、总K线评价量、总重采样量、单任务合作式时限均有硬上限；失败/取消不退额度。
- 执行：模型只在有效 Grant 下使用 `submit_granted_experiment`；宿主重写 request_id，每项任务做 Approval Input Freeze，并进入现有唯一共享 JobQueue。
- 生命周期：撤销/过期后新任务立即阻断，运行任务在 cooperative checkpoint 取消；有未终止任务时不能以新 Grant 覆盖旧状态，历史 Grant 保留归档。
- 可观察性：System Health 显示 Grant、到期、binding、used/remaining budget；无 Grant 不影响 Research Readiness。
- 验收：核心专项 **12/12**、桌面链 **8/8**、相关联合 **110/110**；真实工作区只读状态查询 `artifacts` **77006→77006**；完整仓库 **925/0/0**，365.415秒。
- 后续事项：内部主线转向 Strict PIT 原始资料与 Watch 序贯/在线衰减统计；外部继续等待正式 live MarketSnapshot provider 与 P13-B1 券商只读通道。

### 2026-09-15 13:25｜[数据/实时行情] 腾讯 + 东财 + 新浪三源 MarketSnapshot Provider v1

- 模块：MarketSnapshot Provider / Daily Orchestrator / Daily Scanner / System Health / 宿主 CLI。
- 改动内容：新增 `public-web-consensus-v1` 与 `niuniu-market-snapshot-live`；腾讯作为主实时源，东方财富作为第二源，新浪作为备用与交叉校验。
- 共识：单证券至少两个来源在前收、当前价和对应 Frame 所需 OHLC 上一致才可用；三源全一致优先三源，一源偏离自动剔除，只剩一源 fail-closed。
- 时间防脏：来源必须属于目标交易日；明显未来时间剔除；真实 `LIVE_NEAR_REALTIME/BACKFILL` 仍由 MarketSnapshotStore 按 `as_of/captured_at` 判定。
- 执行访问：`STANDARD_ACCESS` 需要至少两个接受来源共同提供双边买卖盘且不是一字状态；东财轻量接口缺稳定盘口时不会单独把腾讯+东财升级为普通可达。
- PIT 边界：公开网页源固定 `strict_pit_source_verified=false`，即使 FULL+LIVE 也不升级 Strict PIT；未来 QMT/XtQuant/券商/交易所级 feed 可替换正式主源。
- 宿主权限：CLI 必须 `--confirm-network` 才联网、`--store` 才写快照；Daily Orchestrator 默认不联网，只有计划显式 `allow_market_snapshot_capture=true` 才自动抓取，每 Frame 30秒冷却、最多3次；AI/MCP 无 capture/connect/credential 工具。
- 真实烟测：盘中两只股票曾由腾讯/东财/新浪 3/3 共识；随后一次东财临时无有效返回，腾讯+新浪仍以2/2形成 FULL 共识并把东财缺失留在 source health。只读 smoke `artifacts` **77006→77006**。
- 测试/验收：Provider+PublicWeb+Orchestrator 专项 **28/28**；MarketSnapshot/Scanner/PREP/Orchestrator/System Health 联合 **74/74**；完整仓库 **935 tests / 0 failed / 0 skipped**，332.681秒。
- 后续事项：内部主线继续 Strict PIT 原始历史资料与 Watch 序贯/在线衰减统计；外部有条件时用 QMT/XtQuant/券商级行情替换实时主源，并保留三家公开源做备份校验。
### 2026-09-15 14:30｜[研究统计] Watch Sequential Monitor v1

- 模块：Factor Watch / Tracking / Research Agenda / AI只读工具 / PyQt Watch。
- 改动内容：新 Watch 创建时冻结经验 Rank IC 基线、family alpha、最小实际衰减、最少新增成熟日期、固定非重叠 block 与序贯算法指纹；后续只消费基线截止后成熟的每日 Rank IC。
- 统计方法：默认5个交易日组成非重叠 block，尾部不足 block 不进入证据；完整 block 使用 fixed-lambda mixture e-process，同一 Watch 多次查看不重复消耗一次性检验。family alpha 在 horizons 间预先分配。
- 状态：样本不足保持 INSUFFICIENT；未越界为 NO_DECISIVE_CHANGE；越过预先冻结 e-value 阈值才为 DEGRADATION_EVIDENCE。历史输入 revision 直接 HISTORICAL_REVISION_BLOCKED。
- 兼容性：旧 Watch 继续 LEGACY_NOT_CONFIGURED，不静默升级；正式 Rebase 保留原序贯设置，算法 hash 变化要求新 Watch/换版。
- 权限：衰减证据只追加 review alert 并进入 Research Agenda；模型没有自动停用、接受衰减、改因子参数或交易动作工具。
- 解释边界：e-process 相对冻结经验基线，不把样本均值冒充总体真值；跨多个事后选择 Watch 不共享一次全局 family-alpha 认证。
- 验收：Watch/Tracking/Agenda/Factory/System Health 联合 **99/99**；真实工作区 Watch=0，只读查询 artifacts **77006→77006**；完整仓库 **945 tests / 0 failed / 0 skipped**，376.376秒。
- 后续事项：内部主线集中到 Strict PIT 历史原始资料补齐；外部继续等待券商/QMT级行情和 P13-B1，并持续积累真实前瞻 Paper 样本。

### 2026-09-15 15:15｜[数据资格] Strict PIT Evidence Archive v1

- 模块：Data Qualification / PIT Universe / Industry & Size Neutralization / System Health / 宿主 CLI。
- 改动内容：新增 `niuniu-pit-evidence-v1` publication-evidence 归档，支持 `universe_eligibility / industry_membership / daily_market_cap` 三类 statement；新增宿主 CLI `niuniu-pit-evidence` 的 list/verify/archive。
- 证据合同：每条严格证据绑定规范化 statement digest、交易所/CNINFO 权威 HTTPS URL、宿主明确确认的 `published_at`、本地官方原文字节、SHA256、`fetched_at`；`published_at` 不得晚于 statement 的 `available_at`。同一 statement + source + publication_at + document SHA 重复归档幂等，fetched_at 不参与 identity。
- Fail-closed：非权威 URL、未确认 publication time、原文或 receipt checksum 篡改均拒绝；CLI 不自动联网下载，避免把抓取时间冒充历史首次可用时间。
- Qualification：磁盘 `universe_events.parquet` 现在只有 receipt 全覆盖时才标 `historical_publication_verified=true`；Industry / daily market cap 不再因为只写 CNINFO/交易所 URL 就通过 Strict PIT，缺 receipt 分别产生 publication-evidence blocker。
- 兼容：`research_only / retrospective_reference` 保持原行为；旧 PIT records 仍可运行时间逻辑，但无 receipt 只能是 timing contract。Approval-time Freeze 保留已验证的 Universe metadata/qualification identity。
- 可观察性：System Health 的 PIT/Playbook 组件显示 receipt 总数与三类计数；损坏 receipt 显示 WARN，不静默当空库。
- 真实烟测：`/Volumes/Lexar/MQC-DATA` 当前 receipt **0**，因此没有虚假升级 Strict PIT；只读 list/System Health 前后 `artifacts` **77006→77006**。
- 测试/验收：PIT Evidence + Qualification + Universe **15/15**；Qualification/Neutralization/Approval Freeze/Proposal/System Health/Session Grant 联合 **75/75**；完整仓库 **950 tests / 0 failed / 0 skipped**，443.920秒。
- 后续事项：框架已收尾；下一内部工作是实际归档官方历史资格、行业变更和每日市值资料，并按证券/交易日/statement 类型量化 coverage。
### 2026-09-15 16:15｜[数据资格] Strict PIT Coverage v1

- 模块：Strict PIT / Evidence Archive / MQC inventory / System Health / AI只读工具 / 桌面历史资料。
- 改动内容：新增 `strict_pit_coverage()`、`niuniu-pit-coverage`、AI/MCP `get_strict_pit_coverage` 和桌面“查看当前 Strict PIT Coverage”。
- 统计合同：只统计深度验证通过的 `universe_eligibility / industry_membership / daily_market_cap` receipt；支持按年份、证券、日期范围看 evidence presence，并单独展示回顾性 source inventory。
- 防误导：`overall_strict_pit_coverage_ratio=None`、`dataset_strict_pit_certified=false`；receipt presence 不证明没有漏掉其他历史变更，只有具体研究通过 `qualify_research_data` 才能叫 strict PIT。
- 真实性：官方原文被篡改后 receipt 自动从 verified coverage 剔除；模型没有 archive/download/certify/write 工具。
- 真实性能：真实 MQC 优先使用只读 `catalog/mqc.duckdb`，完整 inventory 查询约2.8秒；System Health 只显示轻量 receipt 摘要，不在刷新时深扫数据湖。
- 真实基线：Baostock 日线 5215 个证券文件、17,075,243 行、1990-12-19～2026-09-04；bar lake `tradestatus/isST` 均为0；stock_basic 8940行；industry 5546行且只有2026-08-31单快照；三类 strict receipt=0。
- 真实烟测：指定 `sh.600000 / sz.000001`、2025-01-01～2026-09-15，三类均明确列为 missing evidence；`artifacts` **77006→77006**。
- 测试/验收：Coverage+Evidence+Qualification 18/18，Coverage+System Health/UI 19/19，相关 Baostock/Series/Session/MCP 回归全绿；完整仓库 **956 tests / 0 failed / 0 skipped**，412.711秒。
- 后续事项：不再扩 Coverage 框架；直接按 gap 收集并归档真实官方历史资料，优先历史资格/ST/停牌，其次行业变更、每日市值和逐日特殊交易制度。

### 2026-09-15 16:50｜[数据基础设施] 牛牛独立数据根

- 将 `/Volumes/Lexar/MQC-DATA` 完整复制为 `/Volumes/Lexar/niuniu-data`，原目录不删除、不改写。
- 复制后源/目标均为 26,445 个文件、14,460,345,471 bytes；关键 DuckDB/manifest/parquet SHA256 一致，二次 rsync checksum dry-run 无内容差异。
- 牛牛两个 macOS 启动入口、当前 README/Workbench 提示和活跃 examples 默认切到 `niuniu-data`。历史 artifacts 与历史开发记录中的 `MQC-DATA` 绝对路径保持原样，避免破坏来源身份。
- 新数据根真实读取：raw/qfq 正常，`catalog/mqc.duckdb` 仍为 17,075,243 条日线、5,215 只证券、1990-12-19～2026-09-04；Strict PIT 三类 receipt 仍为 0。
- 后续牛牛新增数据、Strict PIT 证据和官方历史资料只写入 `niuniu-data`。

### 2026-09-15 18:30｜[数据资格] Strict PIT SecurityStatus v1

- 数据根：牛牛后续数据统一写入 `/Volumes/Lexar/niuniu-data`；原 MQC-DATA 保留旧副本。
- 证据：PIT Evidence 新增 `security_status`，真实核验3份深交所PDF，覆盖 `sz.002512 / sz.002538 / sz.300081` 各自停牌日与次日复牌/ST生效，共6条 verified receipts。
- 派生层：新增 `lake/silver/security_status/security_status.parquet` + checksummed manifest；表 SHA/evidence集合变化均 fail-closed。
- 工具：新增 `niuniu-security-status status|materialize`，只从 verified receipts 派生，不联网抓取。
- PREP：优先消费 security_status，但稀疏 receipt 只在明确 effective session 作为 Strict 状态证据；未覆盖日期继续 `historical_st_tradestatus_missing`。
- 规则边界：状态证据不推断官方涨跌停；即使状态完整，缺 MarketRules 时仍不能升级 Strict PIT。
- 真实 smoke：每个3日窗口命中2个 strict status observations，整段窗口仍不完整，符合 fail-closed。
- 测试：SecurityStatus/PREP/Coverage 20/20；相关联合71/71；完整仓库 **961 tests / 0 failed / 0 skipped**，381.649秒。
- 后续：继续收集官方状态事件形成更连续的 SecurityStatus 链，再进入历史行业变更与每日真实市值。

### 2026-09-15 19:34｜[数据资格] Strict PIT SecurityStatus 第二批真实证据

- 模块：PIT Evidence / SecurityStatus / Coverage / PREP / Agent Operating Memory。
- Git：本条与验收文档同一提交发布，提交标题 `data: 扩充Strict PIT证券状态证据`；SHA 以该提交 Git 历史为准。
- 数据：在独立数据根新增东旭蓝天、易事特、得润电子、合力泰4份深交所官方公告，归档8条停牌/复牌及ST生效 statement；累计由3只/6条提升到7只/14条。
- 时间证据：发布时间取自深交所公告查询接口精确 `publishTime`，每份 PDF 原文字节、来源 URL、SHA256、`published_at/available_at/effective_at` 与 receipt checksum 绑定；归档前已备份 receipts、parquet 与 manifest。
- 派生层：`security_status.parquet` 重物化为14行，table SHA256=`9fb12ec9731d28d5078a878c51bdce9e98a0ee78c642e6968b1fd5dee556b4e1`，evidence digest=`e75bd80794ab3651303c7ceb1bf8034bb30e7c248aa080a9492bc55000969bf5`。
- 验证：深度审计 stored/verified/invalid=`14/14/0`；7只指定证券均有 SecurityStatus evidence presence，其它三类仍为0。`sz.300376` PREP 烟测消费2条新 evidence，但因完整状态链、官方 MarketRules 与 PIT Universe 缺失保持 `PARTIAL/RETROSPECTIVE_REFERENCE`。
- 测试：SecurityStatus/Coverage/PREP 专项 **20/20 passed**；完整仓库 **961 tests / 0 failed / 0 skipped**，354.598秒。
- 文档纪律：按宿主要求新增本批验收说明，更新 README、总体架构、总计划与 Agent Memory；以后每个完成任务都同步文档并形成独立 Git commit。
- 边界：14条稀疏事件不等于完整历史状态链或数据集证书；不推断逐日涨跌停，不改变 Playbook/Paper/实盘权限。
- 后续：继续补同证券进入/持续/撤销状态链，并建设官方逐日 MarketRules receipt；随后推进历史行业与每日真实市值。

### 2026-09-15 20:05｜[真实前瞻运行/状态机] 首轮 Daily Orchestrator PREP NO_TRADE

- 模块：DailyMarket / PREP Scanner / Daily Orchestrator / Playbook Forward / Trading Desk Bridge / Agent Operating Memory。
- Git：本条与代码及验收文档同一提交发布，提交标题 `feat: 完成首轮前瞻NO_TRADE闭环`；SHA 以该提交 Git 历史为准。
- DailyMarket：第一次 Baostock 调用接收超时并保留 `PROVIDER_ERROR`；20秒后重试成功，接受 2026-09-15 全市场 5,219 行，snapshot=`b042c420-4bde-5a63-b745-99470e66ed0d`，revision=0。
- 前瞻时间：2026-09-15 19:45:59 +08:00 为 2026-09-16 PREP 合法窗口内，MarketSnapshot 为 `ON_TIME / LIVE_NEAR_REALTIME`；引用 DRAFT `meta-playbook-hypothesis-v3`，research cutoff 仍为 2026-09-13。
- 事实与结论：上涨1,054、下跌4,103、估计涨停34/跌停32、最高2板；工程 Router 给出 `EXTREME_RISK / NO_TRADE`。CandidateSet 为 `PARTIAL / RETROSPECTIVE_REFERENCE` 且为空，保留 `official_market_rules_missing / historical_st_tradestatus_missing / pit_universe_not_certified`。
- 状态机修正：空 PREP CandidateSet 先按显式配置写 NO_TRADE bridge receipt，再进入 `COMPLETE_NO_TRADE`；AUCTION/R1/R2/R3 为 `SKIPPED_NO_TRADE`，不再请求无标的实时行情。非空 CandidateSet 的 PREP 空选择仍继续等待 AUCTION，二者不得混淆。
- 结果边界：0股票 Decision、0 PaperPlan、0执行、0动态账户；不为了积累 Paper 样本伪造交易。该记录不是 Strict PIT、Alpha 或实盘证明。
- 幂等：终态重复 tick 前后状态文件 SHA256=`5a9e2a5461d7446f7a02bf778b3e363da6339981fa709e7b1ca869b01ad0fee0`，mtime、Prediction ID 与 bridge receipt 数量均不变。
- 验证：Orchestrator+Bridge+Health 专项 **38/38 passed**；完整仓库 **962 tests / 0 failed / 0 skipped**，345.160秒。System Health Runtime/DailyMarket/Orchestrator 为 OK，Research Readiness 因最新 CandidateSet 非 FULL/STRICT_PIT 且无 FROZEN Playbook 保持 WARN。
- 文档：新增《牛牛AI交易工作台_首轮DailyOrchestrator前瞻NoTrade_验收说明.md》和 `playbooks/qimofenshu/notes/forward_prediction_20260916_prep.md`，同步 README、总体架构、总计划、核心进度与 Agent Memory。
- 后续：该交易日已正确终止，不在 9/16 补造盘中预测；下一交易日重新接受 DailyMarket 并独立建计划，只有非空 CandidateSet 才进入 live Frame。并行继续官方 MarketRules、PIT Universe 与 SecurityStatus 完整链建设。

### 2026-09-15 20:40｜[数据资格/真实证据] Official MarketRules Publication Receipt v2

- 模块：Official Rule Archive / MarketRules / Data Qualification / Rules Audit / CLI / Agent Operating Memory。
- Git：本条与代码及验收文档同一提交发布，提交标题 `data: 增强MarketRules发布时间证据`；SHA 以该提交 Git 历史为准。
- v2 合同：每个 snapshot 在 `research/official_market_rules/<rules_snapshot>.json` append-only 保存实际 records、官方原文字节 SHA256、`published_at/fetched_at` 与宿主 publication-time confirmation；同一数据根可持有多个 snapshot。
- 防回填：每个 record 的 `available_at` 不得早于其 source `published_at`；CLI 未提供逐URL `--published-at` 或未显式 `--confirm-publication-time` 时在联网前拒绝。旧 v1 单文件仍可读，但因没有 publication time 返回 `official_rule_publication_time_unverified`，不能再通过新的 `official_rule_covered` gate。
- 来源：官方域名白名单补入深交所 `docs.static / disc.static / reportdocs.static`；非交易所域名、非官方跳转、原文哈希/record snapshot 篡改继续 fail-closed。
- 真实数据：复用并重新下载7份已核验深交所公告，形成7条明确停牌 MarketRules；snapshot=`94b7cfedb136ecd83566ac04d5adaf2776e1b57232537839179005e507bbe1a1`，receipt SHA256=`28ad3f2d81a3286999b0a6960fe73a6f7c12b8415734f3d29dfa5fd6391933f8`。7个下载哈希与 SecurityStatus archive 逐项一致。
- 审计：逐证券逐 session 7/7 covered；`suspended_sessions=7`、`suspended_sessions_without_price_bounds=7`、`explicitly_unbounded_sessions=0`。停牌 null bounds 不再显示成无限价格交易。
- 幂等：重复归档 `created=false` 且不联网；receipt SHA256、mtime、文档数和 snapshot 不变。
- 边界：只覆盖7个停牌 session；公告给出的复牌后5%/20%比例不能与回顾性前收盘自动拼成 exact 官方上下限。当前2026-09-15全市场 PREP 仍缺 official MarketRules/PIT Universe/完整状态链，Playbook/Paper/实盘权限不变。
- 验证：Qualification+PREP+Rules Audit 专项 **28/28 passed**；完整仓库 **964 tests / 0 failed / 0 skipped**，367.662秒。
- 文档：新增《牛牛AI交易工作台_OfficialMarketRulesPublicationReceiptV2_验收说明.md》，同步 README、数据资格说明、总体架构、总计划、核心进度与 Agent Memory。
- 后续：先补同7只股票复牌/ST session 的官方参考价与 exact 涨跌停价证据，再按受限股票池持续追加逐日 snapshot；同时推进 PIT Universe 和连续状态链。

### 2026-09-15 22:15｜[修复/可观察性] Official MarketRules v2 全局深度审计

- 模块：Official Rule Archive / Qualification Verifier / System Health / CLI / Agent Operating Memory。
- Git：本条与代码及文档同一提交发布，提交标题 `fix: 审计MarketRules v2回执`；SHA 以该提交 Git 历史为准。
- 改动：新增只读 `quantlab official-rule-audit --data-root ...`；扫描所有 v2 snapshot，重建 MarketRules，并深度核对 source/publication time、records identity、content-addressed path 和官方原文字节。
- 防篡改：重复 source、非法 SHA256、v2 非 `research/official_rules/<sha>.bin` 路径、文档 symlink 及畸形字段都返回 invalid；Qualification 不因坏 receipt 字段崩溃。
- System Health：PIT/Playbook evidence 新增 `official_rule_archive` 和 `official_rule_archive_verified_present`；兼容 `official_rule_receipt_present`。invalid receipt 触发 `official_rule_receipts_invalid` WARN；legacy v1 单文件触发不具资格提示。
- 语义：上述字段是全局 archive 完整性 inventory，不是最新 CandidateSet 的 rule binding，也不会把 PARTIAL/RETROSPECTIVE_REFERENCE 升级。
- 真实烟测：`niuniu-data` 为 receipt files=1、verified=1、invalid=0、records=7、sources=7、unique documents=7、legacy=false；System Health 显示 verified present=true，但最新2026-09-16 CandidateSet 及 Research Readiness 仍为 WARN。
- 验证：Qualification+PREP+Health+Rules Audit 专项 **42/42 passed**；完整仓库 **965 tests / 0 failed / 0 skipped**，336.996秒。
- 后续：审计链已足够支撑追加批次；开发主线返回真实数据，补复牌 exact 价格边界、PIT Universe 与连续状态链。

### 2026-09-16 00:05｜[数据资格/真实证据] 复牌日 Exact 价格边界回顾性参考

- 模块：Official Rule Reference Archive / Strict PIT Evidence linkage / CLI / Agent Operating Memory。
- Git：本条与代码及验收文档同一提交发布，提交标题 `data: 固化复牌价格边界参考证据`；SHA 以该提交 Git 历史为准。
- 来源：取得当时适用的《深圳证券交易所交易规则（2023年修订）》官方 PDF/通知元数据，以及深交所 `1815_stock / 1815_stock_snapshot` 对7个复牌日的官方历史行情 JSON 与 HTTP headers；继续引用原7份 verified ST 复牌公告 evidence。
- 结果：依据0.01元档位、前收×(1±比例)和四舍五入，核出7组 exact 上下限：`000040 2.53/2.29`、`300376 4.81/3.21`、`002055 7.08/6.40`、`002512 6.33/5.73`、`002538 7.60/6.88`、`300081 5.27/3.51`、`002217 2.66/2.40`；7/7推导跌停等于官方当日最低。
- 参考归档：新增 append-only `research/official_market_rule_references/<snapshot>.json` 与16份内容寻址文档；snapshot=`d8b9c1e9f2874b4f897eb4bf66abd8e146876688584403b6fc32937bf96f4b36`，receipt SHA256=`772dae7d3573553722fc6c36268a16478eafc6f1e037ff2ad78de050a4faf391`。重复导入 `created=false`。
- 工具：新增本地、无联网 `official-rule-reference-archive --confirm-retrospective-only` 和只读 `official-rule-reference-audit`；深验 receipt/snapshot、文档哈希、公告 evidence、通知 pubTime、查询身份、HTTP Date、目标行与 Decimal 算术。
- 防未来信息：全部 ShowReport 响应是在目标 session 后的2026-09-15才观察；reference 固定 `historical_reference_publication_verified_before_open=false`、Strict PIT eligible=0、MarketRules appended=0，且不接入 Qualification/PREP/Paper/execution。原 v2 snapshot 仍只有7个停牌 session。
- 验证：Reference + Qualification + Rules Audit + PREP + System Health 专项 **44/44 passed**；完整仓库 **967 tests / 0 failed / 0 skipped**，355.564秒。
- 文档：新增《牛牛AI交易工作台_复牌日Exact价格边界参考证据_验收说明.md》，同步 README、总体架构、总计划、核心进度、Official MarketRules v2 说明与 Agent Memory。
- 后续：优先取得历史开盘前 `cashauctionparams_YYYYMMDD.xml` 或同等 publication-time-confirmed 官方静态快照；在其不可得时保持 blocker，主线转向当前时点可前瞻留存的 PIT Universe 与连续 SecurityStatus 状态链。

### 2026-09-16 01:16｜[知识架构/安全边界] External Research Skill Adapter v1

- 模块：`quantlab.knowledge` / Research Skill package audit / StrategySource preview / Agent Operating Memory。
- Git：本条与代码、郑希脚手架及验收文档同一提交发布，提交标题 `feat: 建立外部Research Skill接入边界`；SHA 以该提交 Git 历史为准。
- 决策：不把外部 `zhengxi-views` 或以后 Brooks/ICT/基金经理库整体塞进 Trading/Execution 核心；统一先走 `Research Skill → StrategySource → Playbook DRAFT → Quant Validation`。
- 包合同：固定 `skill.yml / SKILL.md / references / method.md / scorecard.md / scripts`；manifest 使用 JSON-compatible YAML，资源清单闭合且逐项核 bytes/SHA256，拒绝 symlink、路径越界、重复 ID/key、超预算和证据时点倒置。
- 认知分层：原始观点、披露行为、后续结果分别建模；claim 区分 DIRECT_QUOTE、METHOD_INFERENCE、FACT_TO_VERIFY；alignment 保存“说/做/结果”及 CONSISTENT/INCONSISTENT/MIXED/UNKNOWN，不将一致性写成因果或 Alpha。
- 权限：`research-skill-audit` 只读本地字节，不联网、不执行声明脚本、不写 Playbook SQLite；只返回与现有 StrategySource 合同兼容的 PENDING/PARTIAL preview，宿主仍需人工复核导入。
- 评分/数据边界：score 固定 `SOURCE_STYLE_SIMILARITY_ONLY`，hypothesis 固定 DRAFT；Strict PIT、Alpha、Daily Scanner、direct trade 均 false。季度机构持仓只作为 Theme/Dossier 中期辅助证据，不进入 AUCTION/R1/R2/R3。
- 郑希脚手架：snapshot=`d9660110e0105404adb2ee4ddfc757214b27e59985c0359c18fbd58be05dd43c`；5 resources、5 DRAFT hypothesis，0 primary statement/claim/disclosed action/outcome/alignment，状态 SOURCE_REQUIRED，preview=PENDING。未联网或复制外部 corpus/基金数据/脚本。
- 测试：Research Skill + StrategySource + Playbook Lab/Tools 专项 **23/23 passed**；完整仓库按互斥集合复核为非Desktop 853/853 + Desktop 118/118，合计 **971 tests / 0 failed / 0 skipped**。单进程 discover 亦报告971/OK，但一次在输出结果后的 macOS/PyQt teardown 触发 Bus error，已如实记录且不影响双进程0退出码复核。
- 文档：新增《牛牛AI交易工作台_外部ResearchSkill接入规范_验收说明.md》，同步 README、项目架构、总计划、核心进度、Playbook 说明及 Agent Memory。
- 后续：若宿主提供外部仓库本地路径，或对明确 URL 单独授权联网，再逐项归档原文、publication metadata、季度持仓和结果；之后仍只建立 StrategySource/Playbook DRAFT，Alpha 交由牛牛 Quant Validation。

### 2026-09-16 02:27｜[外部证据/安全归档] Research Skill Git Archive / Curation v2

- 授权与获取：宿主明确允许直接Git下载；从 `https://github.com/lyra81604/zhengxi-views.git` clone 到独立数据根，固定 commit=`304ac3e4...bebb536`、tree=`ef5833f6...8fe2f`。第三方内容未复制进主仓库。
- 许可证：上游MIT只覆盖代码与项目文档；corpus/fund_data权利归原权利人。因此原始/衍生字节只保存在独立数据根，Git仅保存控制合同、lock和策展计划。
- Git archive：新增 `research-skill-git-archive/audit`。归档命令本身不clone/fetch并禁用lazy fetch；核HTTPS origin、完整commit/tree、clean worktree、普通blob、预算及SHA256。真实receipt=`a48a85cb...383fd3a`，143文件/11,367,050 bytes，1/1 verified、0 invalid。
- Curation：新增 `research-skill-git-curate --confirm-retrospective-only`，只从verified对象按 `research_skills/curation/zhengxi-304ac3e4.json` 选材；不复制/执行7个上游脚本。生成包=`f9e72ecd...74bf10`，14 resources、1 statement/1 action/1 outcome、10 claims、8 source-grounded claims、1完整三联、5 DRAFT hypotheses。
- 原话防伪：DIRECT_QUOTE 除角色回链外必须逐字存在于UTF-8来源；伪造manifest quote以 `DIRECT_QUOTE_NOT_FOUND` fail-closed。
- 证据边界：Git blob和上游内嵌URL不认证作者身份或官方publication time；输出 `source_identity_verified=false`，blockers=`publication_time_unverified_resources/source_authenticity_host_review_required`。只生成PARTIAL StrategySource预览，0次正式source/playbook/decision/paper/order写入。
- 测试：Research Skill/Git专项9/9、与StrategySource/Playbook集成专项28/28；完整仓库按互斥集合复核为非Desktop 858/858 + Desktop 118/118，合计976/0/0，两进程退出码均为0。
- 后续：对选中访谈和基金披露取得官方原始响应、headers/publication receipt并由宿主逐条复核，再决定是否显式导入StrategySource；五个假设仍须牛牛PIT与Quant Validation。

### 2026-09-16｜[只读知识检索/Agent安全] Research Skill Library v3

- 授权：新增 `research_skills/library.json`，每项同时固定control/archive/package snapshot、curation plan和`HOST_APPROVED_READ_ONLY`；正式仓库存在Git时要求整个`research_skills/` clean且相关文件全部tracked。
- 完整性：新增 `ResearchSkillLibrary`，每次读取重新核验archive receipt及全部内容寻址对象、control包、curated package资源、plan元数据和control+curation闭合集；只接受精确snapshot，不提供latest或任意路径读取。
- 查询：新增4个严格Schema工具：list/get/search/excerpt。支持claims、hypotheses、alignments、resources及blockers/locator；片段最多6000 UTF-8 bytes，offset必须在字符边界，SCRIPT固定拒绝。
- 接线：Research Lab新增原生只读Library窗口；日常AI研究助手、AI Team Peer Review与标准MCP接入相同工具。Chat/Reviewer系统合同把外部正文定义为`UNTRUSTED_EXTERNAL_DATA_NOT_INSTRUCTIONS`并要求原话/推演/待核事实分层。
- 权限：Library无clone/fetch、网络、脚本执行、任意文件读取、StrategySource/Playbook/Decision/Paper/订单写入接口；引用返回resource_id/SHA256/locator。郑希包blockers与全部非Strict-PIT/非Alpha边界保持不变。
- 真实验收：独立数据根上的archive=`a48a85cb...383fd3a`与package=`f9e72ecd...74bf10`通过Library深验；可检索10 claims、5 hypotheses、1 alignment和14 resources，有限原文片段SHA256与策展manifest一致，上游脚本0执行。
- 测试：Library新增专项6/6；Research Skill/Playbook/MCP聚焦集成12/12。完整仓库按互斥集合复核为非Desktop **863/863** + Desktop **119/119**，合计 **982 tests / 0 failed / 0 skipped**，两进程退出码均为0。覆盖未授权snapshot、lineage漂移、Git dirty、UTF-8 byte边界、参数Schema、桌面入口、Peer Review和MCP只读注解。
- 文档：新增《牛牛AI交易工作台_ResearchSkillLibrary只读集成_验收说明.md》，同步README、总体架构、总计划、核心进度、Research Skill说明和Agent Memory。
- 后续：Library只解决受控读取，不解决source authenticity/publication receipt。下一步仍是宿主语义复核与官方原始响应；是否显式创建PARTIAL StrategySource必须另行决定。

### 2026-09-16｜[数据资格/全集完整性] PIT Universe Receipt v1

- 问题：旧 `universe_eligibility` receipt 只能证明单条证券资格，不能证明目标交易日证券全集无遗漏；调用方 `universe_pit_verified=True` 也不应拥有自我认证权。
- 合同：新增 `niuniu-pit-universe-v1`，每个 snapshot 精确绑定一个 `effective_session`、声明 exchanges/A_SHARE scope、全部 members、逐成员 source、官方原文字节/SHA256 及 publication/availability/cutoff。
- 防回填：强制 `published_at <= available_at <= created_at <= cutoff_at <= session 09:15 Asia/Shanghai`；cutoff 后首次创建拒绝。相同已验证 snapshot 重试幂等，receipt/document append-only、symlink/篡改/路径逃逸 fail-closed。
- 宿主边界：archive 完全离线，要求 publication time、语义映射、完整官方全集三项独立确认；本轮未授权联网，因此真实 `niuniu-data` snapshot 仍为0，没有用当前列表补历史。
- 接线：`UniverseConfig.pit_snapshot_ids` 与 Qualification 对每个 bar session 要求唯一 receipt；approval-time freeze 保存完整 receipt membership；PREP/Orchestrator 校验 snapshot session 等于目标 trading day 并扫描全部 members；snapshot 进入 source hash、MarketSnapshot、CandidateSet universe_source/evidence。
- 可观察性：Coverage 新增 PIT Universe archive inventory/gap；System Health 深验 receipt/member/document，invalid receipt WARN，但全局库存不冒充最新 CandidateSet coverage。
- 工具：新增 `niuniu-pit-universe`、`quantlab pit-universe-archive`、`quantlab pit-universe-audit`，均不下载网络数据。
- 测试：专项覆盖确认门、时间链、幂等、文档/receipt篡改、scope/source/member绑定、Qualification逐日覆盖、PREP证据链和approval freeze恢复，46/46；完整仓库按互斥集合为非Desktop 871/871 + Desktop 119/119，合计990/0/0。
- 文档：新增《牛牛AI交易工作台_PITUniverseReceiptV1_验收说明.md》与 `agent_memory/architecture/pit_universe.md`，同步README、总体架构、总计划、核心进度及相关Memory。
- 后续：经宿主明确授权，为未来交易日在09:15 cutoff前保存首个真实官方全集 snapshot；随后实现连续 SecurityStatus v2 的进入/持续/撤销与每日覆盖证明。

### 2026-09-16｜[数据资格/连续状态] SecurityStatus Coverage v2

- 问题：14条真实稀疏 status statement 只证明明确事件日；“上次是ST/停牌且没看到新公告”不能证明中间每天持续，也不能证明某日全市场没有遗漏状态。
- 合同：新增 `niuniu-security-status-coverage-v2`。每份 receipt 精确绑定同 session 的 PIT Universe v1，records 必须与全部 members 完全相等，每个 member 同时绑定交易所匹配的 `TRADABILITY + RISK_WARNING` 官方来源。
- 时点与宿主边界：强制 `published_at <= available_at <= created_at <= cutoff_at <= 09:15 Asia/Shanghai`；归档只读本地原文字节，不联网，并分别要求 publication time、语义映射、全Universe状态完整性确认。`UNKNOWN` 可留证但固定非 Strict。
- 连续链：首个 snapshot 仅为 initial root；后续必须显式绑定 `previous_status_snapshot` 并由宿主确认相邻交易session，才生成 suspension/risk-warning 的进入、持续、撤销。Universe进出不冒充状态事件；同session歧义、断链和previous分叉均fail-closed。
- 接线：silver `security_status.parquet` 合并稀疏statement与完整v2，冲突拒绝；PREP只消费exact effective session并标记`STRICT_PIT_DAILY_COVERAGE`；Coverage/System Health显示全局receipt、歧义、分叉与transition inventory，不冒充case coverage。
- 工具：新增 `niuniu-security-status-coverage` 与 `quantlab security-status-coverage-archive/audit/security-status-chain`，全部离线或只读。
- 真实边界：`/Volumes/Lexar/niuniu-data` 实际只读audit为receipt/verified/invalid=`0/0/0`、status_records=0、continuous_links=0；本轮未联网、未制造历史receipt。现有7只证券/14条statement继续按稀疏证据处理。
- 测试：覆盖四日进入/持续/撤销链、Universe全成员、确认门、source scope、cutoff、幂等、篡改、UNKNOWN、断链/分叉、sparse冲突、silver与PREP exact-session消费；聚焦集成46/46。完整仓库按互斥集合为非Desktop879/879 + Desktop121/121，合计1000/0/0。
- 文档：新增《牛牛AI交易工作台_连续SecurityStatusV2_验收说明.md》，同步README、总体架构、总计划、核心进度与Agent Memory。
- 后续：宿主先在未来09:15前取得真实PIT Universe及完整官方状态字节，再创建首个root；后续逐交易日连续归档。MarketRules、历史行业、每日真实市值与财报PIT仍是独立 blocker。

### 2026-09-16 14:37｜[前瞻取证/数据边界] 2026-09-17 Universe 与 SecurityStatus 准备收口

- 范围：在用户已授权的 SSE/SZSE/BSE 官方 HTTPS 只读范围内，完成目标日前能够安全完成的抓取、规范补证、有界公开源排查和目标日 runbook；未调用 PIT archive，未配置后台定时任务。
- 父 capture：`capture-20260916T132034+0800` 共77文件，review-only A_SHARE 为 SSE 2,318、SZSE 2,901、BSE 344，合计5,563；manifest=`e3174698...714a8`、review=`f2121a56...0f37`、members=`d7a4d87c...748f`，父目录未改写。
- 语义 addendum：新增独立 `semantic-addendum-20260916T143747+0800`，46文件/19,660,328逻辑字节；21项材料包含8份三所官方页面/规范/通知、3次SZSE官方站内搜索、10次官方静态域名有界路径响应。manifest=`3ffccf93...ec41`，materials digest=`5b9f6892...edb1`。
- SSE：IS124/IS120已证明盘前产品文件、产品状态D/S和TradingPhaseCode P/0/1语义；仍需目标日刷新、公共接口正式映射、publication time与完整性确认。
- SZSE：v1.42及官方通知已证明FTS私有 `pre_securities/securities` 文件与Status 1/4/5；站内精确目标文件搜索为0，10个受限公开路径均404。该负面结果仅限本次有界排查；公开单证券接口不能替代2,901只的批量完整状态，继续阻塞v2。
- BSE：v1.1已证明FDEP `bj_securityinfo` 全量文件、T-1后发送及Status 1/4/5；公开 `xxtpbz/xxzrzt` 权威字典未闭合，不能从简称或缺公告推导NONE。
- Fail-closed：HTTP Date/Last-Modified只作候选；publication time、公共字段映射、目标日Universe完整性和逐日状态完整性均未确认。正式 `research/pit_universe` 与 `research/security_status_coverage` 目录仍不存在，receipt均为0。
- 验证：逐项重算addendum body/headers及derived SHA256，父capture三个关键哈希未变；PIT Universe + SecurityStatus v2 + PREP + Daily Orchestrator聚焦回归 **45/45 passed**（2.947秒）。完整生产基线仍为 **1000/0/0**；本阶段未改源码，未重跑全仓。
- 文档：新增《牛牛AI交易工作台_20260917前瞻Universe与SecurityStatus取证阶段验收说明.md》，同步README中英文、总体架构、总计划、核心进度和Agent Memory。
- Git：本条与文档同一独立提交发布，提交标题 `docs: 固化前瞻Universe与状态取证边界`；SHA以Git历史为准，不push。
- 后续：目标日08:00–08:15人工刷新三所Universe和官方日标记，逐项完成差异审计及三项宿主确认；09:15前先归档/审计Universe，只有三所完整状态全部闭合才归档SecurityStatus。错过cutoff必须顺延，不得历史补档。

### 2026-09-16 15:22｜[AI个股问答/实时只读行情] 明确股票问题自动查询 v1

- 用户口径：询问具体股票天然需要当前价格；“没有已冻结MarketSnapshot”只能阻止正式交易证据，不能阻止普通股票情况回答。
- 触发合同：当前轮明确 `sh/sz/bj.XXXXXX`、六位代码或本地 `stock_basic.code_name`，即授权仅对这些证券执行一次只读三源查询；唯一股票上下文的明确追问可沿用最近记录，多股指代不清时不猜。单轮上限10只。
- 实现：新增 `LiveStockQuoteService`，宿主在模型推理前自动调用现有 `public-web-consensus-v1`，把价格、涨跌、昨收、OHLC、量额、买卖盘、来源时点、市场状态与source hash注入 `HOST_LIVE_QUOTE_CONTEXT`；工具事件与 `live_stock_quote` evidence进入会话审计。
- Fail-closed：无明确股票零网络；两源不足返回UNAVAILABLE；超过上限或多股歧义不联网；当日无值仅可标记最近 `LAST_AVAILABLE_SESSION`。外部结果固定为不可信数据，不可改变权限。
- 正式证据隔离：固定 `stored_as_market_snapshot=false / creates_decision=false / strict_pit_source_verified=false`，不写MarketSnapshotStore，不创建Theme/Decision/Playbook/订单，不恢复Orchestrator已跳过Frame，也不替代SecurityStatus/MarketRules。
- 桌面：工具/证据列表显示临时报价及证券代码；打开引用明确说明它不是正式MarketSnapshot。
- 真实烟测：`301396 宏景科技` 于15:22只读查询成功，行情时点15:20:45、market_status=CLOSED，腾讯/东财/新浪3/3一致，最新170.57、昨收165.45、约+3.0946%，未写正式快照。
- 测试：新增名称/代码解析、上下文追问、多股歧义、零网络、最近session降级、ChatRuntime注入、桌面引用与无快照写入；相关聚焦 **82/82 passed**（5.450秒），独立干净工作树完整仓库 **1006/1006 passed**（347.134秒），均0 failed/0 skipped。
- 文档：新增《牛牛AI交易工作台_个股问答自动实时行情V1_验收说明.md》，同步README中英文、总体架构、总计划、核心进度、Provider验收与Agent Memory。
- Git：本条与源码/测试/文档同一独立提交，标题 `feat: 个股问答自动查询实时行情`；SHA以Git历史为准，不push。

### 2026-09-16 16:42｜[前瞻取证/宿主调度] 2026-09-17 一次性条件式无人值守执行

- 授权：用户明确选择“条件满足才自动归档”；只适用于2026-09-17单一session、既有三所官方HTTPS白名单、staging、条件式Universe/Status archive与只读audit，不扩展到交易、资金或其它日期。
- 调度：安装用户级LaunchAgent `com.niuniu.pit-20260917`；08:00主触发，08:05/08:15只在无完成标记时恢复，runner内部对未就绪来源每10分钟重试，09:10安全停止，09:15后绝不归档。完成后自动disable后续trigger。
- 取证：固定抓取SSE system date、主板/科创列表与bulk status、SZSE catalog 1110/XLSX/状态公开路径、BSE服务端声明全部页；每次先写正文、headers、URL、available_at与SHA256，再做日期、分页、类型、重复、基线差异和全连接检查。
- 确认边界：HTTP Date、Last-Modified、网页/业务日期、`xxjsrq/xxgxsj`和抓取时间都不认证publication time。只有明确带时区的官方publication字段、既定语义和全集完整性全部机器验证通过，runner才传CLI确认参数；授权本身不是确认。
- Status边界：SZSE公开完整批量源与BSE公共字段映射仍是硬blocker；名称、`xxtpbz=F`或公告缺失不能推导NONE。因此Status v2预计仍保持0，除非目标日上午出现并通过全部显式证据。
- 可复现：操作根=`/Volumes/Lexar/niuniu-data/automation/pit-20260917`；固定archive/audit源码commit=`648a16275c3a6f1feb940115805bb904c2f011d0`；installation receipt=`ff1babd...152fc`。
- 演练：当前日官方只读演练返回SSE 2,318、SZSE 2,901、BSE 344，共5,563只，0 errors；manifest=`aece8a72...40cd8`。目标marker/publication gate均正确为false，archive 0次，正式Universe/Status目录继续不存在。
- 电源前提：安装时Mac接交流电并启动`caffeinate`至09:20；LaunchAgent不能自动开机或突破合盖睡眠，必须保持登录、联网、数据盘挂载和上盖打开。若到点不可用或醒来已过安全停止，只记录missed并fail-closed。
- 文档：同步README中英文、总体架构、总计划、核心进度、前瞻验收与Agent Memory；操作脚本和官方字节只在独立数据根，不进入主仓库。

### 2026-09-16 18:51｜[规划/自主研究] P14 / AR 自主研究与打板情绪研究线规划

- 用户目标：让牛牛自己研究行情、情绪与打板规律，并按规划文档一步一步实施、每步同步记录。
- 改动：新增《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》，包含目标/非目标、已确认决策、与现有 PIT/Decision/AI 权限体系的边界、10 项现状差距、AR-0～AR-6 分阶段计划、涨跌幅制度表/涨停状态/情绪指标数据合同、实施流程、待决定事项、进度表与验收记录；同步 README 中英文、总计划（新增 P14 与变更记录）和总体架构入口。
- 核查依据：`prep_scanner` 回退与 `mark_limit_closes` 使用固定涨跌幅比例（创业板改革前、创业板/科创板 ST、2026-07-06 起主板 ST 10%、新股无涨跌幅窗口均未覆盖，`sz.302`/`sh.689` 未归类）；Theme 事实仅手工录入；受限 DSL 只支持单股 OHLCV 滚动运算；Research Session Grant ≤24 小时且禁止联网；`ExecutionConfig` 与 qimo 模拟盘配置未计印花税/过户费。
- 用户决定：每步独立本地提交不推送；Tushare 等付费源暂不接；授权收盘后低频公开数据归档（留证、不补历史、遵守站点限制）；连续推进；盘中/竞价采集与 qimo 费用配置列为待决定事项。
- 基线测试：Linux arm64 隔离克隆逐模块全仓 1025 个测试，1022 通过；2 个离线解释器包平台限定测试与 1 个 System Health 桌面固定等待测试失败（AR-0.1 处理）。本条为纯文档变更，未改源码。
- Git：本条与规划文档同一独立提交，标题 `docs: 建立自主研究与打板情绪研究规划`；不 push。
- 后续：AR-0.1 测试稳定性修复，随后按 AR-1.1 起顺序实施。

### 2026-09-16 18:56｜[测试/稳定性] AR-0.1 Linux 下离线环境与 System Health 桌面测试稳定性

- 背景：在 Linux arm64 隔离克隆跑全仓时有 3 个失败，均非功能问题：离线解释器包测试被平台前置检查拦截；System Health 桌面测试固定等待 250ms 早于异步渲染完成。
- 改动：`tests/test_offline_environment.py` 在用例内固定受支持平台身份并新增不受支持平台反向用例；`tests/test_system_health_desktop.py` 改为轮询等待 Runtime 卡片（上限 10 秒）。源码未改。
- 测试：聚焦 5/5；Linux 隔离克隆逐模块全仓 1026/0/0。17 个桌面模块单独进程运行时退出阶段 Qt 清理返回非零码，测试结果均为 OK，合并运行正常退出，列为已知现象。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》进度与验收记录。
- Git：独立提交 `test: 修复Linux下离线环境与健康页测试稳定性`；不 push。

### 2026-09-16 19:06｜[数据语义/涨跌停] AR-1.1 按交易日生效的 A 股涨跌幅制度表 v1

- 背景：PREP 无官方规则时的回退与 Playbook 历史重建使用固定比例：ST 一律 5%、创业板一律 20%，未覆盖 2020-08-24 创业板改革、创业板/科创板 ST 20%、2026-07-06 起沪深主板 ST 10%、注册制新股无涨跌幅窗口，`sz.302`/`sh.689` 未归类，会把历史涨停与连板标错。
- 改动：新增 `quantlab.trading.price_limit_regime`（`a-share-price-limit-regime-v1`：板块识别、NORMAL/NO_LIMIT/UNMODELED 规则与原因码、交易所舍入价格、制度变更表）；`prep_scanner` 回退与 `mark_limit_closes` 默认比例改为按日期推算；非 NORMAL 日不推断涨跌停价。
- 关键约束：制度表是研究重建，不是官方逐日 MarketRules，不提升 strict PIT / official_rule_covered；正式 MarketRules、显式覆盖参数优先级、扫描输出字段与 `source_hash` 组成不变；PREP 回退不解析新股窗口（事件库另行精确解析）。
- 测试：新增制度表 12 项、PREP 与重建各 1 项；修正 1 个按旧 ST 5% 口径构造的 PREP 用例（2026-09-09 ST 涨停价应为 12.10）。聚焦 34/34；Linux 隔离克隆全仓 1040/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-1.1 进度与验收记录。
- Git：独立提交 `feat: 按交易日生效的A股涨跌幅制度表`；不 push。
- 后续：AR-1.2 涨停状态标注器。

### 2026-09-16 19:12｜[研究数据/涨停状态] AR-1.2 向量化涨停状态标注器 v1

- 改动：新增 `quantlab.trading.limit_states`（`limit-state-v1`），在规范化逐日面板上输出涨跌停价、收盘涨停/触板/炸板/一字板/T 字板、跌停/触及跌停、天地板/地天板、连板数、近 5/10 日涨停次数、首板、前一交易日状态与越界标记。
- 原因：打板研究需要比“收盘价等于涨停价”更完整的日内形态事实，且需在全市场多年数据上高效计算。
- 关键约束：制度判断与 AR-1.1 标量规则在 9,120 个边界组合上逐项一致；价格按整数分比较；连板等序列只在可交易日计算，停牌不增不断；非 NORMAL 规则日与停牌日不推断状态；结果是研究重建，不认证 strict PIT / official rule。
- 测试：新增 8 项；125 万行约 1.2 秒；Linux 隔离克隆全仓 1048/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-1.2 进度与验收记录。
- Git：独立提交 `feat: 向量化涨停状态标注器`；不 push。
- 后续：AR-1.3 回溯全市场日线数据集。

### 2026-09-16 22:37｜[研究数据/回溯日线] AR-1.3 沪深A股回溯日线数据集 v1（代码）

- 改动：新增 `quantlab.data.retro_daily`（`retro-daily-baostock-v1`）与 CLI `quantlab.agent.retro_daily_cli`（pyproject 登记 `niuniu-retro-daily`）。抓取计划冻结区间、字段、stock_basic 与交易日历；按证券调用 Baostock 不复权日线（含 isST/tradestatus/前收），可断点续传、分片并行；每只证券目录含 gzip 原始行、类型化 parquet 与 checksum manifest，原子写入；失败记录重试；读取时逐文件哈希校验。
- 原因：打板与情绪研究需要覆盖多年、含历史 ST/停牌状态、不遗漏已退市证券的全市场日线；现有 MQC 日线湖缺 ST/停牌字段。
- 设计调整：实测按日全市场查询 18–53 秒/天，按证券 2–6 秒/只，服务端吞吐约 1,300–1,400 行/秒，故由原规划的按日抓取改为按证券回溯，回溯区间之后由 DailyMarket 按日补齐。
- 关键约束：资格 research_only；stock_basic/日历为抓取快照，不是 PIT Universe；isST/tradestatus 不等于官方 SecurityStatus；不覆盖北交所。
- 测试：新增 10 项；Linux 隔离克隆全仓 1058/0/0。真实烟测：2019-01-01～2026-09-15 计划 5,455 只证券、1,870 个交易日；抓取 135 只 239,159 行 0 失败，与制度表交叉核对仅 5 行越界且均为退市整理期。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-1.3 规划（设计调整）、进度与验收记录。
- Git：独立提交 `feat: 沪深A股回溯日线数据集与分片抓取`；不 push。
- 后续：在 `artifacts` 执行 2019-01-01～2026-09-15 正式回溯，完成后补记覆盖；并行开发 AR-1.4 涨停事件库。

### 2026-09-16 23:09｜[研究数据/涨停事件] AR-1.4 涨停事件库 v1（代码）

- 改动：新增 `quantlab.trading.limit_events` 与 CLI `quantlab.agent.limit_events_cli`（pyproject 登记 `niuniu-limit-events`）。由完整、首尾相接的回溯日线 capture 构建涨停/跌停/炸板及次日事件表，含 T 日收盘可知特征与 T+1/T+2 标签，输出到 `artifacts/_limit_research/limit_events/<build_id>/`（events.parquet + checksum manifest）。
- 关键约束：按交易日历精确计算上市/退市交易日序号；新股无涨跌幅期、临近退市、未建模制度与价格越界行不进入事件，越界日也不触发次日事件；标签以交易所前收复利、未计费用与成交可行性；build_id 绑定输入与源码指纹，`verify` 从输入重算逐值比较；资格 research_only。
- 制度表修正：仅有上市日期时，上市后无多日无涨跌幅窗口的板块从上市次日起可解析。
- 测试：新增事件库 5 项、制度表 1 项；Linux 隔离克隆全仓 1064/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-1.4 进度与验收记录。
- Git：独立提交 `feat: 涨停事件库构建与复算校验`；不 push。
- 后续：AR-1.3 回溯完成后真实构建并抽样核对；并行开发 AR-1.5 日度情绪指标。

### 2026-09-16 23:28｜[研究数据/市场情绪] AR-1.5 日度打板情绪指标 v1（代码）

- 改动：新增 `quantlab.trading.market_sentiment` 与 CLI `quantlab.agent.market_sentiment_cli`（pyproject 登记 `niuniu-market-sentiment`）。按交易日汇总 40 个指标：涨跌家数、涨跌停（含/不含 ST）、触板、炸板与炸板率、一字板、首板与连板梯队、最高连板、1进2 与连板晋级率、昨日涨停股今日收益均值/中位数/胜率、昨日炸板股收益、大面数、天地板/地天板、成交额及变化、高度板断板，以及停牌/未建模/越界等数据质量计数。
- 关键约束：T 日收盘后可用、只用于 T+1 及以后；涨跌停由研究制度表推算，资格 research_only；不覆盖北交所；build_id 绑定输入与源码指纹，可重算校验。
- 重构：事件库标注逻辑提取为共享 `prepare_states`（行为不变）；测试夹具提取为 `tests/limit_research_fixtures.py`。
- 测试：新增 4 项（手工夹具逐项核对指标值 + 库/CLI）；Linux 隔离克隆全仓 1068/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-1.5 进度与验收记录。
- Git：独立提交 `feat: 日度打板情绪指标`；不 push。
- 后续：AR-1.6 情绪周期与相似日；AR-1.3 回溯完成后统一真实构建 AR-1.4/1.5。

### 2026-09-16 23:45｜[研究数据/情绪周期] AR-1.6 情绪周期机器状态 v1 与相似日检索（代码）

- 改动：新增 `quantlab.trading.sentiment_cycle` 与 CLI `quantlab.agent.sentiment_cycle_cli`（pyproject 登记 `niuniu-sentiment-cycle`）。以 8 个情绪指标在此前 250 个交易日中的因果分位数合成温度，按版本化规则给出冰点/修复/发酵/高潮/分歧/退潮/偏暖震荡/偏冷震荡；相似日按分位数画像检索严格历史日期并附下一交易日结果。
- 关键约束：规则是工程阈值（`host_engineering_policy_not_expert_rule`），不是专家规则或交易信号；分位数不含当日；截断未来数据不改变历史结果（单测）；相似日只用目标日前已知数据；资格 research_only。
- 测试：新增 7 项；Linux 隔离克隆全仓 1075/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-1.6 进度与验收记录。
- Git：独立提交 `feat: 情绪周期机器状态与相似日检索`；不 push。
- 后续：AR-1.3 回溯完成后统一真实构建与核对 AR-1.4/1.5/1.6；随后进入 AR-2 公开市场证据归档。

### 2026-09-17 00:07｜[公开证据/前瞻归档] AR-2.1 公开证据采集框架 + AR-2.2 东方财富五个股池

- 改动：新增 `quantlab.data.public_evidence`（白名单 HTTPS、收盘后时点分类、原始字节与规范化表不可变归档、accepted/修订审查）、`quantlab.data.eastmoney_sources`（涨停/昨日涨停/炸板/跌停/强势股池解析器 `em-pool-v1`）与 CLI `quantlab.agent.public_evidence_cli`（pyproject 登记 `niuniu-public-evidence`）。
- 原因：首次/最后封板时间、封板资金、炸板次数等打板关键明细只能从公开股池获得，而接口只保留约一个月数据，必须从现在开始每天归档。
- 关键约束：用户授权收盘后低频归档；盘中抓取未授权，直接拒绝；错过下一交易日 09:15 须显式补抓并标记 LATE；公开网页接口不是官方数据、不认证 strict PIT；结构变化即拒绝写入。
- 真实归档：2026-09-16 五个股池（涨停 89、昨日涨停 32、炸板 11、跌停 4、强势 107），时点 BEFORE_NEXT_SESSION。
- 测试：新增 8 项；Linux 隔离克隆全仓 1083/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-2.1/2.2 进度与验收记录。
- Git：独立提交 `feat: 公开市场证据收盘后归档与东方财富股池`；不 push。
- 后续：AR-2.3 龙虎榜、AR-2.4 板块、AR-2.5 人气榜、AR-2.6 收盘后调度。

### 2026-09-17 00:20｜[公开证据/龙虎榜] AR-2.3 东方财富龙虎榜上榜明细与买卖席位

- 改动：新增通用 `EastmoneyDatacenterSource`（`em-datacenter-v1`）与 `em_billboard_daily`、`em_billboard_buy_seats`、`em_billboard_sell_seats` 三个来源，纳入默认公开证据来源（共 8 个）。
- 关键约束：按交易日过滤并翻页取全，页数/行数/交易日逐项校验；未发布返回 NOT_READY 不写入；供应商未来收益列丢弃；供应商解读字段加 `em_` 前缀并注明不是事实。
- 真实归档：2026-09-16 上榜 73、买入席位 365、卖出席位 365。
- 测试：新增 3 项；Linux 隔离克隆全仓 1086/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-2.3 进度与验收记录。
- Git：独立提交 `feat: 龙虎榜上榜明细与营业部席位归档`；不 push。

### 2026-09-17 00:34｜[公开证据/板块与人气] AR-2.4 东方财富板块与成分 + AR-2.5 人气榜

- 改动：新增概念/行业板块列表、概念/行业板块成分、人气榜前 100 共 5 个快照来源（默认来源增至 13 个）；框架新增 `snapshot_only`（快照类来源禁止 LATE 补抓）与单来源 `max_requests`。
- 主机调整：`push2.eastmoney.com` 当前拒绝本机出口连接，板块来源改用 `push2delay.eastmoney.com`（收盘后与收盘值一致）并加入白名单。
- 真实归档：2026-09-16 概念板块 504、行业板块 496、人气榜 100；成分全量（约 1,100+ 请求）交由 AR-2.6 在 Mac 调度执行，隔离烟测 25 个板块 3,763 行通过。
- 测试：新增 4 项；Linux 隔离克隆全仓 1090/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-2.4/2.5 进度与验收记录。
- Git：独立提交 `feat: 板块成分与人气榜快照归档`；不 push。
- 后续：AR-2.6 收盘后调度与 System Health；提醒东财 push2 被拒对三源实时行情的影响。

### 2026-09-17 00:44｜[公开证据/调度] AR-2.6 收盘后公开证据与当日日线自动归档调度

- 改动：新增 `quantlab.agent.evidence_scheduler` 与 CLI（pyproject 登记 `niuniu-evidence-scheduler`），System Health 新增 `public_evidence` 组件，桌面系统中心同步显示。
- 行为：宿主显式启用后每 10 分钟 tick；按 Baostock 交易日历只处理收盘后/下一交易日开盘前窗口内的交易日；按时间表抓取股池、人气、板块（15:40/15:45）、龙虎榜（17:30）、DailyMarket（18:00），成分每周一次；失败冷却 15 分钟、每日最多 8 次；文件锁防并发；无动作不写日志。
- 关键约束：不盘中抓取、不补历史、不交易；LaunchAgent 只能在 Mac 上安装。
- 测试：新增 4 项；Linux 隔离克隆全仓 1094/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-2.6 进度与验收记录。
- Git：独立提交 `feat: 收盘后公开证据自动归档调度与健康检查`；不 push。
- 后续：在工作区启用调度；用户在 Mac 上执行一次 `--install-agent`。

### 2026-09-17 00:58｜[研究能力/事件研究] AR-3.1 预登记涨停事件研究引擎 v1（代码）

- 改动：新增 `quantlab.trading.event_study` 与 CLI `quantlab.agent.event_study_cli`（pyproject 登记 `niuniu-event-study`）。研究规格先登记冻结再计算；条件用白名单表达式（禁止标签列）；统计按交易日等权聚合，沿用区块符号随机化检验，可与基准条件做同日差值，分样本内/外、分年、分组；同 family 全部登记研究 Holm 校正。
- 运行记录：工作区已启用收盘后公开证据调度并抓取 DailyMarket 2026-09-16（5,220 行）；LaunchAgent 待用户在 Mac 上安装。
- 关键约束：结果只算一次不可覆盖；标签收益未计费用与成交可行性；Holm 不能控制登记之外的探索；资格 research_only。
- 测试：新增 6 项；Linux 隔离克隆全仓 1100/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-2.6 运行记录与 AR-3.1 进度、验收记录。
- Git：独立提交 `feat: 预登记涨停事件研究引擎`；不 push。

### 2026-09-17 09:20｜[打板研究/数据底座] AR-1.3～1.6 真实数据完成：回溯日线、涨停事件库、日度情绪与周期

- 数据：Baostock 回溯日线补齐 2019-01-02～2026-09-15，共 5,455 只、8,644,474 行，0 失败，深度哈希复核通过。真实构建涨停事件库 `7eb4809f…`（423,618 个事件）和日度情绪 `b22b469a…`（1,870 个交易日），两者 `verify` 重算均一致。
- 改动：
  - 事件库与情绪指标改为每批 500 只证券分批标注，横截面量在合并后计算。
  - 制度表向量化改用整数编码；回溯面板改为流式哈希加一次扫描；新增 `panel_evidence`。
  - Baostock 会话掉线时自动重新登录一次。
  - 虚拟机 3.9 GB 内存下构建峰值 2.78 GB。
- 核对：与东方财富涨停/跌停/炸板池比对 09-10、09-14、09-15 三天，非 ST 涨停 121 只完全一致；东财股池不含 ST，且以封板为口径，是我们日线口径的子集。§6.2 补充口径说明。
- 发现：东财股池 `qdate` 不是数据日期，AR-3.4 合并时须按请求日期并做集合核对。
- 测试：新增 2 项、增强 1 项；Linux 隔离克隆全仓 1102/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-1.3～1.6、AR-3.1 进度，§6.2 口径，§8 新增 D-3，§10 验收记录。
- Git：独立提交 `feat: 回溯日线补齐与涨停事件库、情绪指标真实构建`；不 push。

### 2026-09-17 09:26｜[研究能力/成交模型] AR-3.2 打板成交可行性模型 v1 并接入事件研究

- 改动：
  - 新增 `quantlab.trading.limit_execution`：次日开盘/收盘买入、当日/次日涨停价排板（保守/乐观情景）；次日开盘或收盘卖出，跌停顺延。
  - 费用计入佣金、滑点及按日期的印花税与过户费；持有期内卖不出按最后收盘价计价，留在收益样本中；数据终点截断标为待定。
  - 事件研究规格新增 `execution`，结果增加分样本成交统计。
- 关键约束：当日排板研究只能用买入前已知的条件（`LOOKAHEAD_FOR_ENTRY`）；无逐笔队列，排板成交只是情景假设；资格 research_only。
- 真实烟测（非研究结论）：138,718 个收盘涨停事件，次日开盘买、再次日开盘卖。成交率 86.1%，净收益均值 −0.99%，与标签隔夜收益 +1.2%～+1.5% 方向相反。
- 测试：新增 9 项（含随机面板与参考实现逐值比对）；Linux 隔离克隆全仓 1111/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-3.2 进度与验收记录，回填 AR-1.3～1.5 提交号。
- Git：独立提交 `feat: 打板成交可行性模型并接入事件研究`；不 push。

### 2026-09-17 09:37｜[研究能力/事件研究] 首批 7 项预登记真实研究：可执行打板收益

- 研究族 `limit-board-exec-v1`：首板、连板、冰点、高潮、炸板、二板打板（保守/乐观）。样本 2019-01～2026-09，2024 年起为样本外，同族 Holm 校正。
- 结论：
  - 次日开盘买、再次日开盘卖的涨停类买法，样本外平均净收益全部为负。
  - 连板比平均涨停差 1.04 个百分点；首板略好 0.23 个百分点。两者都与预登记方向相反，如实标注。
  - 冰点买入、高潮回避在样本外不显著。
  - 二板打板保守情景 −9.67%、乐观情景 −2.22%：结论取决于封死时能否排到。
- 改动：family 报告增加检验量、样本内外取值、成交率、方向与结论字段；显著但反向的研究标为 significant_opposite_direction。
- 测试：增强 1 项；Linux 隔离克隆全仓 1111/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-3.1 完成与首批研究记录，回填 AR-3.2 提交号。
- Git：独立提交 `feat: 事件研究报告标注检验方向并记录首批真实研究`；不 push。

### 2026-09-17 09:47｜[公开证据/采集框架] AR-2.8 长抓取可续抓（板块成分等大批量来源）

- 改动：
  - 公开证据抓取支持 `max_seconds` 分段续抓：响应边抓边暂存，下次校验、重放后继续，完成后原子写入并删除暂存。
  - 抓取时点改为按开始与全部响应中最晚的一类判定。
  - 调度对进行中的成分任务不计失败、不冷却；CLI 增加 `--max-seconds`。
- 关键约束：暂存损坏、版本或请求序列不一致即重来；数据错误、越过收盘后窗口即丢弃；网络错误保留进度。
- 测试：新增 4 项；Linux 隔离克隆全仓 1115/0/0。
- 文档：规划文档新增 AR-2.8 步骤、进度与验收记录，回填 AR-3.1 提交号。
- Git：独立提交 `feat: 公开证据长抓取分段续抓`；不 push。

### 2026-09-17 10:06｜[打板研究/数据底座] AR-1.7 前瞻日线增量并入：事件库与情绪指标延伸到最新交易日

- 改动：
  - 新增 `quantlab.data.forward_daily`：Baostock stock_basic/交易日历参考快照；用 DailyMarket 每日快照把回溯数据延伸到指定交易日，缺日、参考过旧、日历不一致即拒绝。
  - 事件库、情绪指标、事件研究支持 `forward_through`；调度新增 `forward_reference` 任务。
  - 情绪指标成交额改为整数分求和，verify 允许浮点舍入误差；屏蔽 Baostock 登录输出对 CLI JSON 的污染。
- 真实数据：
  - DailyMarket 09-15 与回溯 09-15 逐值一致。
  - 延伸至 2026-09-16：事件 423,774 个，情绪 1,871 日。09-16 非 ST 涨停 89 家、跌停 4 家与东财股池完全一致，连板数全部一致；炸板比东财多 3 家（口径差异）。
  - 情绪周期 09-15 冰点 → 09-16 高潮。
- 测试：新增 4 项；Linux 隔离克隆全仓 1119/0/0。
- 文档：规划文档新增 AR-1.7 步骤、进度与验收记录，回填 AR-2.8 提交号。
- Git：独立提交 `feat: 前瞻日线增量并入事件库与情绪指标`；不 push。

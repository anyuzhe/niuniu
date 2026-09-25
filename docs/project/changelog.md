# 牛牛 AI 交易助手：开发历程与功能变更总档案

> 追加式开发史：历史快照不代表今日状态；当前完成度请看 [当前状态](status.md)。开发完成后继续在本文追加，原历史记录不删除。[文档导航](../README.md)

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

## 3. 历史产品快照（2026-09-15）

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

### 2026-09-17 10:19｜[研究能力/题材] AR-3.3 每日题材事实引擎 v1（代码）

- 改动：
  - 新增 `quantlab.trading.theme_engine` 与 CLI（pyproject 登记 `niuniu-theme-facts`）：由涨停/炸板/跌停池 + 当日或之前的板块成分快照 + 板块行情，按板块生成涨停数、连板梯队、龙头候选、封单资金、持续天数等事实。
  - 另存股池行业分布；通用篮子板块不参与排序；Theme Snapshot 发布须确认，状态一律 UNKNOWN。
  - 调度新增可刷新的 `theme_facts` 任务。
- 关键约束：事实不是判断；成分会被供应商事后调整；Theme Matrix SQLite 只在 Mac 上写入。
- 测试：新增 4 项；Linux 隔离克隆全仓 1123/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-3.3 进度与验收记录，回填 AR-1.7 提交号。
- Git：独立提交 `feat: 每日题材事实引擎`；不 push。

### 2026-09-17 10:27｜[研究能力/前瞻明细] AR-3.4 涨停事件前瞻明细并入与每日研究库自动重建

- 改动：
  - 新增 `quantlab.trading.event_details` 与 CLI（pyproject 登记 `niuniu-event-details`）：按交易日生成东方财富涨停/炸板/跌停池、强势池、人气榜、龙虎榜（含机构席位）明细，并与日线涨停状态核对。
  - 事件研究条件可用 `em_` 列，只采用核对一致的交易日。
  - 调度新增 `limit_research`（每日重建事件库与情绪指标到当天）与 `event_details`。
- 关键约束：明细是收盘后才完整可知的供应商口径，禁止用于当日打板筛选；只随归档逐日积累，不补历史。
- 真实数据：2026-09-16 明细 213 行，核对一致；首封时间分布、龙虎榜机构席位等可直接用于后续研究。
- 测试：新增 3 项；Linux 隔离克隆全仓 1126/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-3.4 进度与验收记录，回填 AR-3.3 提交号。
- Git：独立提交 `feat: 涨停事件前瞻明细与每日研究库自动重建`；不 push。

### 2026-09-17 10:37｜[AI/只读工具] AR-4.1 打板研究数据接入对话、MCP 与 AI Team

- 改动：
  - 新增 `quantlab.agent.limit_research_tools`，含 9 个只读工具：数据覆盖、情绪与周期、相似日、涨停梯队、事件条件查询、题材事实、龙虎榜、事件研究列表与详情。
  - 接入对话、MCP 与 AI Team 复核员；系统提示与 Agent Memory 新增打板研究使用规则。
- 关键约束：无构建/抓取/登记/写入工具；结果列只用于复盘；东方财富口径与 research_only 警告随每次返回；预登记方向相反的显著结果不算支持。
- 测试：新增 3 项；Linux 隔离克隆全仓 1129/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-4.1 进度与验收记录，回填 AR-3.4 提交号；新增 `agent_memory/architecture/limit_research.md`。
- Git：独立提交 `feat: 打板研究数据只读工具接入对话与MCP`；不 push。

### 2026-09-17 10:44｜[AI/复盘] AR-4.2 打板情绪收盘复盘（事实/机器状态/评论分层）

- 改动：
  - 新增 `quantlab.trading.daily_review` 与 CLI（pyproject 登记 `niuniu-daily-review`）：每日复盘冻结事实层（涨跌停与前日对照、连板梯队、题材、前瞻明细、龙虎榜、数据缺口）与机器状态层（情绪周期、相似日）；AI/宿主评论单独追加。
  - 生成中文摘要；接入手机简报、AI 只读工具 `get_daily_review` 与收盘后调度。
- 关键约束：评论是判断不是事实，不回写事实；机器状态是版本化规则与历史类比，不是预测或交易信号。
- 真实数据：2026-09-16 复盘——高潮（温度 83.2，前一日冰点），涨停 91（非 ST 89），炸板率 13.3%，最高 6 板，1进2 36%。
- 测试：新增 2 项；Linux 隔离克隆全仓 1131/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-4.2 进度与验收记录，回填 AR-4.1 提交号。
- Git：独立提交 `feat: 打板情绪收盘复盘`；不 push。

### 2026-09-17 10:53｜[AI/预测校准] AR-4.3 可验证打板预测与 Brier 记分

- 改动：
  - 新增 `quantlab.trading.limit_forecasts` 与 CLI（pyproject 登记 `niuniu-limit-forecast`）：6 个次日二元问题，开盘 09:15 前记录、不可修改，收盘后按情绪指标判定并计 Brier。
  - 机器基准为 250 日气候与相似日类比；记分卡给出相对气候基准的技能分与校准。
  - 接入 Agent Scorecard、AI 工具（唯一写工具 `record_limit_forecast`）、系统提示、Agent Memory 与收盘后调度。
- 关键约束：预测记录不是交易指令；复核员无写权限；样本不足不得宣称预测能力。
- 测试：新增 2 项；Linux 隔离克隆全仓 1133/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-4.3 进度与验收记录，回填 AR-4.2 提交号。
- Git：独立提交 `feat: 可验证打板预测与Brier记分`；不 push。

### 2026-09-17 14:37｜[AI/自主研究] AR-5.1/5.2 研究计划授权与夜间样本内筛选

- 改动：
  - 新增 `quantlab.trading.auto_research` 与 CLI（pyproject 登记 `niuniu-auto-research`）。
    - 宿主预览研究计划，并按摘要确认授权。
    - 计划至多 30 天，锁定样本内区间、结果列、成交模型和预算。
    - 自动计算隔离期与锁定样本外起点；确认族唯一。
  - Agent 只能用 `propose_auto_study` 把有预登记方向的提案放入队列；同一检验只运行一次。
  - 夜间任务按预算只在样本内区间登记运行事件研究，并用 10 项质疑清单筛选；通过、失败、出错全部永久保留。
  - 事件研究结果新增分年检验统计量 `by_year_tested`。
  - 接入 AI 工具、系统提示、Agent Memory 与收盘后调度（19:00）。
- 关键约束：
  - 筛选通过不是结论。
  - 样本外只经宿主晋级。
  - 无 shell、联网、写代码、交易。
  - 复核员没有提案工具。
- 真实数据：只读回放 7 项已登记研究，6 项未通过；S4 全样本通过但样本外 p=0.314，印证筛选不等于确认；据此修正了稀有状态的分年稳定性口径。
- 测试：新增 7 项；Linux 隔离克隆全仓 1140/0/0。
- 文档：
  - 更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》：AR-5.1/5.2 进度与验收记录，新增待决定事项 D-4，回填 AR-4.3 提交号。
- Git：独立提交 `feat: 自主研究计划授权与夜间样本内筛选`；不 push。

### 2026-09-17 14:51｜[AI/自主研究] AR-5.3 研究结论库与前瞻衰减监控

- 改动：
  - 新增 `quantlab.trading.research_conclusions`。
    - 宿主把通过筛选的提案晋级到锁定样本外区间确认，在计划唯一确认族内按 Holm 判定；族变大时重新评估。
    - 已确认规律按确认区间之后的新数据每日滚动监控：效果反向、缩水一半以上或成交检查不过即标为 `DECAYING`。
    - 退役只由宿主决定；账本汇总全部提案（含失败）与结论状态。
  - 事件研究引擎新增只读窗口复算 `measure`；已冻结规格的规范化保持幂等。
  - CLI 新增晋级、结论、监控、退役命令；AI 只读工具 `list_research_conclusions`；接入系统提示、Agent Memory 与收盘后调度（19:30）。
- 关键约束：
  - 只有 `MONITORING` 可称为仍有效的已确认规律。
  - 历史锁定区间确认是弱确认，前瞻监控才是主要检验。
  - AI 不能晋级或退役；结论不是交易信号。
- 真实数据：真实研究 S4 按样本内/样本外窗口复算，与登记结果逐项一致。
- 测试：新增 4 项；Linux 隔离克隆全仓 1144/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-5.3 进度与验收记录，回填 AR-5.1/5.2 提交号。
- Git：独立提交 `feat: 研究结论库与前瞻衰减监控`；不 push。

### 2026-09-17 15:04｜[AI/自主研究] AR-5.4 打板盘前简报

- 改动：
  - 新增 `quantlab.trading.premarket_brief` 与 CLI（pyproject 登记 `niuniu-premarket-brief`）。
    - 依据前一个收盘复盘，汇总情绪状态、连板梯队与题材、仍有效（MONITORING）的已确认规律及观察名单、衰减规律、已记录预测与记分卡、版本化风险提示和数据缺口。
    - 输入变化即生成新简报，旧简报保留。
  - 事件研究引擎新增 `matching_events`（剔除标签列）。
  - 接入 AI 只读工具 `get_premarket_brief`、手机简报、系统提示、Agent Memory 与收盘后调度（19:40）。
- 关键约束：观察名单不是买入建议；风险提示是阈值规则不是预测；当日打板类结论盘前不列名单。
- 真实数据：生成 2026-09-17 盘前简报（依据 09-16 收盘）。
- 测试：新增 2 项；Linux 隔离克隆全仓 1146/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-5.4 进度与验收记录，回填 AR-5.3 提交号。
- Git：独立提交 `feat: 打板盘前简报`；不 push。

### 2026-09-17 15:09｜[AI/自主研究] AR-5.4 补充：盘前简报须依据当天复盘

- 改动：收盘后调度生成盘前简报前检查当天复盘已生成，否则 `REVIEW_NOT_READY` 重试；简报依据日早于前一个工作日时在数据缺口中提示。
- 测试：调度与盘前简报用例补充；Linux 隔离克隆全仓 1146/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-5.4 进度与补充记录。
- Git：独立提交 `fix: 盘前简报须依据当天收盘复盘`；不 push。

### 2026-09-17 16:10｜[执行/模拟盘] AR-0.2 模拟盘补计法定印花税与过户费（D-2）

- 用户决定：印花税与过户费都要计入手续费。
- 改动：
  - 新增 `quantlab.execution.fees`：按成交日的法定印花税（卖出）与过户费（双向）。
  - `ExecutionConfig.statutory_fees`：开启后，费率在规则记录或配置与法定费率中取较高者；回测、资金预留、对账同一口径，默认关闭以保持已有研究可复现。
  - qimo 模拟盘升级 v3 并开启法定费用；原因是官方规则记录费用字段为 0，只改配置不会生效。
- 待办：宿主在 Mac 上重新授权 qimo v3（命令见规划文档 AR-0.2 记录）。
- 测试：新增 3 项；Linux 隔离克隆全仓 1149/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》：已确认决策、待决定事项、AR-0.2 进度与验收记录。
- Git：独立提交 `feat: 模拟盘按成交日计法定印花税与过户费`；不 push。

### 2026-09-17 16:22｜[数据/归档] AR-2.7 集合竞价与盘中快照（D-1）

- 用户决定：授权集合竞价与盘中定时采集。
- 改动：
  - 公开证据归档支持时段型来源：开始时刻与每个响应都必须在窗口内，不续抓、不补抓。
  - 新增 `em_auction_snapshot`（09:25:30–09:29:30，实时主机，撮合不足 80% 拒绝）。
  - 新增 4 个盘中时段各 3 个股池快照。
  - 调度新增独立的盘中开关、tick 与 LaunchAgent（`com.niuniu.evidence-intraday`）；`capture-all` 跳过时段型来源。
- 关键约束：盘中快照与收盘后口径分开存放，不能当作收盘结果；实时主机不可用即失败，不改用延时主机。
- 真实预演：全市场分页 56 页、5,560 只，46.7 秒；虚拟机访问 push2 时断时续，竞价快照需在 Mac 上抓。
- 测试：新增 3 项；Linux 隔离克隆全仓 1152/0/0。
- 文档：更新《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》AR-2.7 描述、进度与验收记录，回填 AR-0.2 提交号；同步 Agent Memory。
- Git：独立提交 `feat: 授权时段内的集合竞价与盘中快照`；不 push。

### 2026-09-17 16:35｜[数据/存储] AR-1.8 回溯日线合并为 pack（D-3）与收尾

- 用户决定：合并回溯日线小文件。
- 改动：
  - `RetroDailyStore.consolidate`：按证券分 8 片打包，字节与哈希不变，逐片复读校验，全部完成后才发布索引；删除原文件前再次全量复核；可续跑。
  - 读取、清单、深度校验自动走 pack；已合并的 capture 禁止写入。
- 真实数据：
  - 16 个 pack 共 646 MB；清单摘要与抽样逐行一致。
  - 用 pack 重建的事件库输出哈希与原来相同。
  - 删除 5,455 个证券目录；占用 11 GB → 639 MB，文件 16,368 → 37。
- 同步记录：
  - AR-3.3 题材引擎完成带板块成分的真实验证，并记下 v1 规则局限。
  - 2026-09-17 收盘后已归档与尚未执行的部分。
  - 新增规划文档 §11 使用与运维清单（Mac 上需执行的安装与重新授权命令）。
- 测试：新增 1 项；Linux 隔离克隆全仓 1153/0/0。
- Git：独立提交 `feat: 回溯日线合并为 pack 并删除原小文件`；不 push。

### 2026-09-17 17:22｜[AI/外部数据] 扶摇 MCP 安全聚合接入与宏景科技复测

- 改动：
  - 新增宿主侧 Streamable HTTP MCP 客户端，只允许扶摇 meta、A 股、A 股指数三个固定端点；本地工具白名单与远端 `tools/list` 双重校验。
  - 凭证只从 `HITHINK_FINANCE_API_KEY` 或 macOS 钥匙串读取；禁止跨域重定向，限制响应体，区分会话重建、限流和业务错误，并对远端文本递归脱敏。
  - AI 只新增 5 个聚合工具：标的消歧、个股行情/日 K、板块与当前成分、短线情绪、估值与财务指标；原始远端工具不进入模型 Schema。
  - 实时个股问答升级为扶摇主源，原腾讯/东方财富/新浪两源共识作为交叉校验和回退；冲突返回 `PARTIAL` 与 `consensus_issues`。
  - 保留既有 Research Skill、Playbook、Peer Review、Research Session Grant 和 Proposal 工具链；修复最外层包装器未透传 `proposals` 的兼容问题。
- 关键约束：扶摇数据是当前/回顾性外部证据，不写正式 `MarketSnapshotStore`，不具 Strict PIT、官方 MarketRules、交易所行情 SLA、Decision、信号或下单资格。
- 真实数据验证：
  - 宏景科技解析为 `301396.SZ`；收盘价 174.90 元、涨约 2.54%、成交量 14,841,823 股、成交额 2,608,405,000 元。
  - 扶摇、腾讯、东方财富、新浪一致，结果 `FULL`、无冲突。
  - 近期日 K、估值、`2026-2` 财务指标、竞价、热度/异动、涨跌停情绪、龙虎榜均调用成功。
  - 智慧城市、人工智能、东数西算（算力）、数字经济、算力租赁的当前成分均核验包含宏景科技。
- 测试：新增 6 项扶摇集成测试；扶摇、实时行情、Agent Chat、Research Skill 相关回归共 28/0/0；`py_compile`、`git diff --check`、仓库密钥扫描通过。
- 文档：新增《牛牛AI交易助手_扶摇MCP接入与验收说明》；补充《牛牛AI助手用户端实测与Bug记录_20260916》的 BUG-09～12、真实数据链路复测和限制说明。
- 部署：用户提供的凭证已进入当前 Mac 用户系统钥匙串，未写入仓库；应用重启后生效。
- Git：本次代码、测试与文档使用同一独立提交；不 push。


### 2026-09-17｜[文档/工程] 文档分层、当前说明归并与代码地图

- 类型与原因：维护；根目录 78 份 Markdown 混放当前指南、规划、验收和规则，部分说明已落后于代码。
- 内容：76 份旧文档按主题迁入 docs；根目录保留三个入口；集中维护六份当前说明，增加代码地图、迁移指纹清单和本地链接检查。
- 内容核对：更新扶摇/公开网页行情分工、StrategySource 与 AR 实施状态；历史测试和数据数字保持历史属性。
- 约束：源码、测试、示例、启动、依赖、许可证、Playbook/Research Skill 包及行情/实验数据不移动不改写；不增加模型权限。
- 验证：711 个原 Python 文件 AST 解析通过；修改前隔离回归 222 模块/1159 项通过/0 跳过；同进程 macOS Qt 原生崩溃单独保留，未修复。迁移后检查见 [整理验收](../development/documentation-cleanup.md)。
- Git：本条与文档整理形成同一独立本地提交；未 push。
- 后续：继续维护 docs/project/status.md 和主题指南，复杂阶段验收才另存 dated archive；不再新增竞争性的根目录总计划。


### 2026-09-17 19:07｜[测试/约定] 改用后台与接口验收，不直接操作客户端

- 原因：用户明确不再直接操作真实客户端测试；在 AGENTS 和开发规范中记录默认后台测试边界。
- 验证：18个后端模块/127项通过/0失败/0跳过；2只证券2024年本地行情副本的HTTP链路19项检查通过，包含执行、报告/分页、重复提交、失败留证、服务重新打开和归档复算。
- 证据：`artifacts/headless-validation-20260917-190049/`；完整观测484行，重复研究逐值相同，归档复算 numerically_matched。四份原行情文件SHA256保持一致。
- 首轮脚本问题：默认分页30行落在40个预热空值中；保留失败记录并修正为全分页逐值比对，未改产品源码以迎合测试。
- 边界：不启动可见GUI、不截图/输入、不修改日常数据/模拟账户/授权；无付费模型或真实订单。本轮没有验证可见窗口行为或修复旧Qt崩溃。
- Git：仅上述测试约定与本开发史形成独立本地文档提交，不push。原始运行产物留在Git忽略目录。


### 2026-09-17｜[后台研究/测试] 授权队列接线与真实模型三候选验收

- 原因：用户授权开始一次最多三个候选、无可见客户端、独立空间的真实模型自主因子测试。
- 实现：chat_cli 增加显式 --allow-granted-research 和 headless_chat_runtime；按需创建一条共享队列并安全关闭，原 Grant、预算、时限、输入冻结保持有效。
- 模型：现有 Codex CLI 的 GPT-5.5 medium；3轮/21次工具调用，自主生成三个价量DSL、预览、冻结、提交和读取结果；无宿主预填候选公式。
- 验证：新增6项测试通过，9模块相关回归共61/0/0；3个真实任务completed，3个输入冻结，3次归档复算numerically_matched。
- 限制：两证券工程样本不足引擎IC所需的每时点3只，Rank IC均null；不得宣称候选有效或无效，更不认证Alpha。正式授权/因子库未改变，测试授权已撤销。
- 验收修正：模型和研究执行后，日志对象流被误按JSONL解析；保留初始失败及原始字节，修正验收脚本后仅离线重核，未重新调用模型或追加候选。
- 证据与详情：[后台实测](../archive/testing/20260917-自主因子后台实测.md)，原始产物在 artifacts/autonomous-factor-test-20260917-193940/。
- Git：本实现、测试和说明形成独立本地提交，不push。后续应事前扩大样本和冻结验证设计；持续无人值守模型调度仍未部署。


### 2026-09-17 21:32｜[研究/验收] 冻结三候选扩大至100股并分割历史样本内外

- 用户要求：继续上一轮候选验证；新增约定为每次任务完成后普通推送代码。已同步AGENTS、开发规范和开发史规则，权限不外推到P10/实盘。
- 设计：100只（沪深主板/创业板/科创板各25），固定哈希排序和2019年底前上市；2020–2023样本内、2024已见诊断、2025至2026-09-04历史样本外，1/5根标签按阶段末日截断。
- 原输入：167,537行。标准MQC因23只/164行空成交量/额阻断；在结果计算前冻结研究专用空量处理，原空值/时点保留、相应信号排除，不填零、不换股、不改生产validate_bars。
- 结果：18个Rank IC检验统一Holm；振幅与日内实体负向候选通过预登记回顾性信号门槛，放量正向假设不支持，未反转方向或增加候选。候选仍未确认Alpha，未做费用/成交/历史中性化或前瞻验证。
- 代码：新增 frozen_candidate_validation 模块、capture/run/verify 脚本；复用既有计算和统计工具；原模型生成与交易权限不变。
- 测试：新增10项及7模块合计47项通过/0失败/0跳过；3套因子/观测、18组日度与统计全量独立重算一致；100个原行情文件SHA256一致。初次协议外层校验读取错误在计算前拒绝，日志保留并添加测试。
- 文档/产物：扩展原《20260917-自主因子后台实测》第二阶段，更新当前状态/运维/代码地图；数据与日志保存在 artifacts/frozen-candidate-validation-20260917-211359/。
- Git：本任务收尾提交后按用户授权普通推送 origin/main，远端SHA以推送回执核对；不上传artifacts、原行情和凭据。
- 后续：冻结两候选的控制因子、独立成交和成本验证；没有部署无限自主挖掘或实盘。


### 2026-09-17｜[助手功能] 由牛牛自主执行，开发者观察；补齐原生本地数据工具

- 原因：用户明确纠正外部开发者代研究的方向；正式CLI观察发现本地行情发现/检查工具未接入，之前演示依赖临时摘要。
- 改动：两个只读本地数据工具接入共同ResearchProposalAPI；DSL实际合同、local-data-only后台选项、Grant能力说明和参数错误反馈。原行情校验及因子/统计公式不变。
- 正式验证：修复前6次真实工具查询暴露缺口；修复后原生助手21次调用，自选10只证券与已有因子、记录假设、执行1个授权研究、保存结论；新进程新会话5次工具调用找回并核对记忆与归档。
- 异常：两次模型参数错误被拒绝并由模型自行修正，保留原记录；加强产品字段提示而非代填研究或放宽校验。
- 工程：新增12项，相关回归81/0/0。100份原行情及副本哈希一致；测试授权已撤销，无GUI、行情联网、正式因子注册或交易。
- 证据：artifacts/assistant-observation-20260917-214804/；同一验收文档第三阶段。不把单次流程通过当成原创因子、Alpha或无人值守已完成。
- Git：本任务代码、测试、说明形成独立提交，按用户要求普通推送origin/main并核对；实际成功状态见最终交付回执，不强推、不自动部署。


### 2026-09-17｜[助手/规格] QM50-SCLA v0.2原文件绑定与严格监督测试

- 任务：按用户Downloads中最新的qimo50_factors_v0.2.md及qimo50_factor_dictionary_v0.2.json，让牛牛自行测试；开发者只核对定义和实际产物。
- 改动：固定原始文件SHA和规格ID，60项MD/JSON定位匹配；原生助手分组读取、审计、版本绑定、禁止替代和一次性固定测试入口。未修改旧qimo-source-rules-v2或正式Playbook。
- 真实模型：第一轮14次调用读取global/全部11组/审计；第二轮7次调用运行合成组件检查、自选5只股票与区间执行P07原始诊断并读回结果。无外部代提交普通研究。
- 验收：34/34合成组件情景检查；P07原始成交额/排除昨日的20日中位数125行可计算，独立Polars移位路径逐值匹配(<1e-12)。60项定义均按原始哈希核对。
- 限制：59项尚无完整精确适配器，P07历史时点/候选池仍MISSING_SOURCE；全策略BLOCKED，无真实Q、收益、成交或Alpha认证。合成测试不是完整引擎验证。
- 回归：新增14项，12个相关模块107/0/0；原文件、行情及日历哈希不变，不操作可见GUI、不下载行情、不产生交易。
- 证据：artifacts/qimo50-supervised-20260917-231023/；详细说明见docs/archive/testing/20260917-QM50-SCLA-v0.2-严格规格验收.md。
- Git：代码/测试/说明形成独立提交，按用户要求普通push origin/main并核对远端SHA；原始下载说明及行情不上传Git，实际交付状态保存于delivery.json。


### 2026-09-18｜[QM50/助手] 基础规则依赖、真实回执覆盖与P01组件边界

- 来源：牛牛先读取原始global/P/N/E并提出优先补security_rules_asof/price_limits_asof/candidate_eligibility_asof；没有由开发者代选新因子或另跑收益研究。
- 功能：新增只读基础覆盖API，复用既有PIT/Universe/完整状态/规则/参考深验器，按真实日历绑定D/D-1/D-2；全局存量、请求缺口和现有规则字段合同分离。保存完整矩阵及来源哈希，不新增官方回执。
- 组件：25项基础资格/P01合成案例，包含首板、无高度上限、左截断、缺日、停牌/无涨跌幅限制中断、ST/UNKNOWN、raw/tick/参考价、板块/品种/制度显式输入；不能当作真实P01或候选产出。
- 实际模型：8次调用提出计划；12次调用选4股/9决策交易日并完成36行输入审计和22项初版组件；5次调用在新进程复核全局入口并执行25项最终组件。早期22项不与最终25项重复合计。
- 缺口：完整Universe/状态回执0；14条稀疏状态、7条正式规则和7条回顾性参考不覆盖本请求；MarketRules无reference_price/tick/board/instrument/delisting/new-listing/normal-regime字段；真实高度及候选均为null。
- 修复：仅把get_strict_pit_coverage放白名单未使真实ChatRuntime注册，牛牛主动报告后补显式工具与真实运行时回归。保留一次规格ID错误被拒绝并由模型自修记录，没有放松版本绑定。
- 验证：新增17项，14模块116通过/0失败/0跳过。独立核对36行原因汇总、受检归档指纹、四份原始行情/日历及原始MD/JSON未变。无GUI、市场下载、交易、策略注册或持续研究授权。
- 记录：原QM50严格验收文档第二阶段；artifacts/qm50-dependencies-20260917-235738/保存计划、原生事件、矩阵、回归与回执。
- Git：本次功能、测试和主题说明独立提交，按用户授权普通push origin/main并核对SHA，结果以delivery.json为准；不上传市场资料或原始用户文档。


### 2026-09-18｜[助手/数据] 既有packed回溯日线的真实输入接入与独立复算

- 用户目标：继续真实功能，不停留在资料缺口与合成检查。发现已有5,455证券capture含额外原字段，规格入口过去没有跨工作空间读取接线。
- 改动：宿主只读source-workspace绑定；来源/证券发现、原JSON与typed全值验证、按交易日D-1物化、原字节冻结、独立复算。支持旧逐证券目录与pack，不修改原数据/价格规则/PIT合同。
- 真实牛牛：自行选择capture及4只边界样本/244日，调用正式工具接入976行；历史供应商ST112、停牌1、非ST交易863。P07：955个数值、21空值；候选/Q/P01/P06没有伪造。
- 实际故障：牛牛报告首次replay=false；独立诊断为JSON字典键排序改变股票行序，修复保留原始request顺序。新会话无外部来源绑定重算同一test_id，976行equal=true。旧false记录与数据保留。
- 监督：11,712原字段值、955公式值和21空值逐项核对；源切片/冻结字节/原说明SHA不变。新增16项，相关151/0/0。
- 交付：docs/archive/testing/20260917-QM50-SCLA-v0.2-严格规格验收.md第三阶段；artifacts/qm50-data-integration-20260918-010358/记录完整模型轨迹、冻结源与监督结果。
- 限制：这是供应商回顾性输入层，不是完整60字段策略/历史PIT/Alpha。没有客户端下载/界面操作/新行情下载/长期授权/正式因子注册/订单。
- Git：本轮独立提交并普通push origin/main；最终成功状态与远端SHA以delivery.json及工具回执为准，不自动部署。


### 2026-09-18｜[数据源可行性] 实测截图中的eltdx与pytdx初始化建议

- 范围：用户要求核对截图是否能获得更多数据；本轮是有限源端探测，不是外部开发者代牛牛研究因子，也未接入主运行时。
- 实测：eltdx3.2.2在独立环境取得60根1m、历史成交、竞价过程和正式09:25撮合、五档、80条权息股本记录、9条个股题材，以及两个日期70/88条涨跌停炸板混合列表；北交实际股票3根日K返回。
- 兼容性：PyPI pytdx1.72在两个明确主站原setup取K线失败，仅测试子类跳过SetupCmd3后均成功；未测试QQ群1.72r2包，不做全局修改。
- 限制：2024-09-04竞价过程空，2025-09-17非空；初始正式撮合查询达到2页上限报错，后续明确8页查询成功，失败保留；不能混用竞价过程与撮合、分笔与L2订单、更新日期与财报修订链。
- 授权：上游ELTDX Research-Only License限制个人非商业研究，禁止生产/商业/自动交易服务等用途；不添加主依赖或部署。第三方资料使用权仍独立核验。
- 保留：探测程序和原始响应仅保存artifacts/tdx-source-probe-20260918-013455/；不上传上游包、二进制或行情。生产源码/数据未变，没有GUI或真实交易。
- 交付：维护一份主题实测报告和导航/当前状态/本日志；普通提交并推送origin/main，实际SHA以delivery.json为准。没有业务代码变更，未虚报新一轮全量业务回归。


### 2026-09-18｜[数据] TDX全部新增类型入原数据库并启动全市场计划

- 授权：用户要求把一分钟、竞价/正式撮合、历史成交、五档、财务股本、权息、题材、涨跌停列表及北交所等新增资料像原日线/5m一样保存。
- 实现：13个tdx_*视图加入现有catalog/mqc.duckdb；独立provider=tdx页归档、完整原响应、Parquet和哈希；SQLite仅作队列。原有两类视图和Baostock文件不替换。
- 真实执行：5,809个证券标识、初始58,091个任务；先前21个有效响应页带原始observed_at迁入。第一批496请求后主动暂停，验证字节恢复后继续同一计划；全历史未完成，尚未展开历史流与失败不算完成。
- 可靠性：分页直到空页、重复页停止、EMPTY与ERROR分离、STORED恢复使用原字节；快照date以观察日期解释，保留所有原字段/单位，不构造历史、PIT或交易。
- 验收：新增20项，相关114项通过/0失败/0跳过。测试中显式模拟磁盘空间，生产30GiB门槛不放宽；中间状态SQL错误已修复。正式模型只读验收已启动但最终回答未确认，不宣称模型已完成验收。
- 环境：eltdx3.2.2隔离放在数据根automation/tdx/runtime-3.2.2；不改主环境默认依赖、不注册每天任务或订单服务，遵守个人研究许可边界。
- 证据：artifacts/tdx-ingestion-20260918-015551/，原数据库备份、原文件清单、计划、页导入、测试和续采命令均保留；实际运行状态在数据根progress和队列。
- 交付：本任务按用户约定独立提交并普通推送，最终成功与SHA以Git回执为准；推送不代表采集已全部结束。


### 2026-09-18｜[数据可靠性] TDX断线有限重试、冷却恢复与Mac登录后自动续采

- 原因：全市场采集在64,338请求后因连续ConnectionClosedError停止；用户要求断线只影响速度，不能造成最终历史断层。
- 请求级：连接关闭/超时/502/503/504最多额外重试3次，失败即关闭旧连接并在两个已核验7709主站轮换；成功保存前绝不推进offset/日期。
- 运行级：连续8个瞬时任务失败后冷却60/120/240/300秒，最多6轮；仅瞬时ERROR可使用更高12次队列恢复预算。协议坏包仍ERROR，普通最多3次，不用无限重试掩盖数据问题。
- 停止门：恢复耗尽、访问限制、磁盘保护写AUTO_HALT；人工STOP和AUTO_HALT均阻止autoresume，明确resume才解除。状态API增加progress/stop/auto_halt。
- 部署：本机用户LaunchAgent `com.anyuzhe.niuniu.tdx-autoresume` 已加载，RunAtLoad+300秒间隔；登录后恢复同一active plan，writer lease防重复实例。不是交易/商业服务。
- 验证：新增4项恢复测试，TDX模块24项通过；原10个相关模块共118项通过。90秒真实恢复同一plan处理248请求、0恢复轮，按TIME_BUDGET正常退出；随后LaunchAgent实际进入running。
- 边界：自动恢复不改变full_history_complete=false，不把EMPTY/ERROR/PIT资格改成成功，不绕过ELTDX个人研究许可或服务端访问限制。

### 2026-09-18｜[TDX调度] 接续未提交优化、预览绑定与安全应用

- 保留基线82de01b上两个未提交文件，不重置、不覆盖。增加纯构建/只读预览、显式apply+snapshot_id、旧任务审计；补重复竞价锚点、反向生命周期、未验证北交floor拒绝；默认每节点0.35秒。
- 文件锁改为POSIX flock / Windows msvcrt分支；移除全量重试协议坏包的resume路径，只恢复瞬时错误。Windows原生验收尚未执行。
- 真实policy `7829c3c1dac7a38f8db9110070933025fcee9d04f6f1c232a221e04aa9beb4d6`：5,801生命周期已知、8未知，SH/SZ auction floor 2025-07-22，BJ无floor。理论逐日族63.42%裁剪不是下载完成率。
- 备份97,419,264字节队列后应用：237个原PENDING竞价任务SKIPPED_POLICY，26个有效frontier；240条原ERROR逐字段保持。真实60任务续采22.79秒、0恢复轮，REQUEST_BUDGET退出后恢复STOP，不恢复旧单机长跑。
- 验证：开工28项，完成后39项TDX专项及11模块133项相关回归通过，0失败/跳过。证据、候选policy、完整改动预览和队列备份在artifacts/tdx-distributed-20260918/。
- 工程：WebCodex结构化新建在Lexar卷返回OS45且未写入，改用同一WebCodex的Python独占创建测试文件，未切换远程工具。代码/文档独立提交并普通推送；回执以Git SHA为准。后续继续三机分片、最小checkpoint与校验汇总。

### 2026-09-18｜[TDX分布式] Tunnel恢复后接续核心、文件数据面与回执

- 接续ad15fac：保留两个已修改和三个新文件，不重置工作区；确认上次CLI未创建后独占新建。沿原数据合同实现固定分片、完整范围/策略绑定、最小checkpoint、SAVED/EMPTY与序列校验、乱序等待、冲突隔离和幂等合并。
- 原始/Parquet逐值比对、精确前驱和opening_match父页共同验收；STORED移至正常视图外，pending_promotions恢复同一字节。Bootstrap逐页核验后只保留manifest，避免16GiB机器常驻数百万原始字典。
- 新增loopback-only文件数据面、Range续传、.part+SHA原子接收、canonical MERGED确认及worker循环。上传成功不是合并成功；未确认包不丢，确认仅删除传输副本，原始页/错误不删除。STOP/AUTO_HALT优先，单次服务预算与30GiB保护保留。
- 安全/平台：Mac/601现有SSH登录验证通过，HomePc既有公钥未获中继认证；未新建密钥、未改变服务端授权。Windows路径测试使用真实junction而非放宽规则；完整应用fcntl移植不属于独立采集worker的验收范围，profile明确列出未纳入的单个应用接线测试，Mac仍执行该原测试。
- 验证：70项完整TDX专项，13模块164项相关回归均通过/0失败/0跳过。日志为resumed-tdx-tests.log和resumed-related-regression.log；真实队列另建queue-before-sharding.sqlite3与sharding-baseline.json，旧canonical保持STOP。新节点部署结果须另记，不据此声称三机上线。
- 交付：新增运行指南并更新当前状态/架构；本阶段代码测试文档独立提交、普通push并核对SHA。具体部署和长期采集仍以各节点实际回执为准。

### 2026-09-18｜[TDX部署] 三份正式断点包、Windows专项通过与Mac worker 0上线

- 版本：功能代码555ca6451f3cb167323709804293779a5b96061c已普通推送并核对远端，两台Windows fast-forward且工作区无业务修改。Mac70项完整TDX/164项相关回归通过；Windows两台分别69项独立采集profile通过、0失败/0跳过，明确不包含单个完整应用原生接线测试。
- 分片：cluster fbe957f355eb036c497981e5cb73e5be88743db715bb9c3ab2e9277092c42046，股票1951/1953/1905，frontier9424/9403/9136，checkpoint6872/6864/6629；tar字节910356480/910673920/876800000。完整SHA与绑定见cluster.json。构建前备份队列，237条现存ERROR逐字段不变。
- Mac实采：worker根独立于canonical，原offset续采60请求/21.592秒、网络错误0；首次66页MERGED，重复导入0新增/66重复，收到精确回执后清理传输副本，原始页和错误不删。安装时6872页原始/Parquet逐值验证，非重下历史。
- Mac持续运行：真实LaunchAgent带STOP启动返回USER_STOP且处理0请求，随后显式解除本次验收标志、启动仅shard0的120秒有限循环与本地校验汇总。旧unsharded LaunchAgent卸载、原plist留档，canonical STOP保留。进程状态须以实时文件与launchctl核对，不能据启动回执保证未来永远在线。
- 持续循环实证：第一轮264请求/120.615秒、0网络错误；sequence 2导出288页/29,358,080字节并自动MERGED/ACK，累计两包354页、冲突0；进入第二轮。采集速率2.19请求/秒不含导出和逐页汇总耗时，尚无三机实测速率。
- Windows阻塞：HomePc现有SSH身份Permission denied；601 Register-ScheduledTask拒绝访问，随后仅一次WebCodex detached SSH启动被平台安全检查拦截，无Job/PID产生、无替代调用。两台bootstrap均未安装、worker均未启动。Mac闲置reverse SSH已卸载并从登录目录移出，配置留档；文件服务只在loopback。
- 证据：Mac artifacts/tdx-distributed-20260918/ 下bootstrap-build.log、mac-worker-install.log、mac-shard-live-acceptance.json/log、mac-launchagent-stop-proof.json和deployment-progress.json；Windows的portable-worker-tests.log、deployment-checkpoint.json。运行配置放独立数据/tdx-control目录，不上传市场文件、运行凭据或机器plist到Git。
- 收尾：更新状态、指南和代码地图；文档独立提交并普通push后核对，Windows跟随文档SHA。未完成两节点传输/自启动，不宣称三机完成、3倍加速或全历史资格。

### 2026-09-18｜[TDX运维] 受限传输身份与Windows当前用户监督器

- 用户要求完成两节点并测试、给出全历史工期。只用对应WebCodex，Mac既有采集不中断。
- 服务器变更先备份、sshd -t与root/ollama-tunnel有效配置等值校验；新增独立非Shell传输身份，使用两台原有公钥，只允许127.0.0.1:18943本地转发，未添加公网行情监听或复制私钥。
- 601原生detached启动已返回Job并核对health cluster，正在使用原bootstrap与SHA接续传输；HomePc启动仍被平台安全检查拦截，未换工具/方式代启，提供操作员本机手动入口。
- 新Windows监督器以当前用户运行，先检查三种停止标志与bootstrap，固定分片/cluster，单实例、子进程归属、隧道重连预算和本地日志；HomePc明确禁止自动启动被拦截隧道。
- 验证：新增8项离线边界；Mac完整TDX78项、14模块相关回归172项均通过/0失败/0跳过，文档检查通过。首轮diff检查指出两处EOF空行，清理后复核；各Windows实际启动继续按真实回执记录。不以脚本、账号或连接health代替节点上线。

### 2026-09-18｜[TDX传输] 前驱校验凭据降低初始化传输量

- 两台Windows当前用户Interactive/Limited计划任务均已注册，真实带SUPERVISOR_STOP运行返回0且启动子进程数0；不需要管理员权限。两台77项独立worker测试通过。HomePc操作员启动的本地端口随后出现，实际health核对正确cluster；未由监督器代启被拒绝的SSH。
- 实际中继全包吞吐约0.2–0.3 MB/s，601原下载在Job报告lost后核查发现进程仍在写.part；没有重复启动或将目录缓存0字节误判断流。保留已下载部分，改用同源、小型、SHA固定的前驱校验凭据。
- 新模式从原bootstrap逐页核验raw/Parquet/manifest生成，冻结原frontier/assignment/policy和前驱行摘要；原始文件仍在canonical和原包中。worker凭据非行情、非SAVED；canonical导入仍用实际前驱原始页复核。HomePc 4,763,945字节、601 4,606,132字节，原全包不删除。
- 增加本地worker汇总writer-lock竞争转为BundleDeferred，保留精确outbox并等待；不改变内容冲突门槛。Mac完整TDX88项、15模块相关182项回归通过/0失败/0跳过；首次新单元测试发现临时目录/var与/private/var解析差异，统一根路径后通过。
- 容量审计发现Lexar每个受检小文件及页目录实际各占524,288字节，即约2MiB/页；不是按文件内容字节就能规划容量。原始数据未删除、未格式化磁盘；全历史ETA必须同时报告存储限制和剩余协议错误。

### 2026-09-18｜[TDX实机] Windows真实续采与HTTP回执响应修复

- HomePc/601小型断点安装成功，两台各87项独立worker测试通过。实际Windows任务分别带USER_STOP/AUTO_HALT启动，均返回0子进程，未提权。
- HomePc真实60请求/21.102秒、源端错误0，原76条ERROR逐字段不变；64页结果从原offset续采并在canonical校验MERGED，重复发送取得同一回执，无重复入库。
- 601真实60请求/21.071秒、源端错误0，结果包已保存；初次在查询回执时超时。定位到原transfer主循环串行accept/merge，慢速合并使新HTTP请求排队；随后临时SSH达到3600秒预算退出，同一outbox仍保留，未重新采集60页。
- HTTP主循环与单一合并线程分离，慢合并时health/receipt仍可响应，实际写入仍取canonical单写者锁；ACK仍只由成功校验合并产生。SYNC_STOP阻止启动，后台合并异常留证后退出，不伪造健康。
- 新增3项真实loopback并发/停止/异常测试，Mac完整TDX91项、15模块相关185项回归通过。部署和601回执恢复结果另按实际记录。

### 2026-09-18｜[TDX运行策略] Windows改为离线采完整分片后物理交接

- 原因：用户明确不需要Windows边采边传Mac，允许完成后用移动硬盘一次性交接。两机此前未长跑的直接原因是验收后STOP/SUPERVISOR_STOP仍保留，且监督器把传输health设为worker启动前置，不是WebCodex或采集源故障。
- 改动：监督器新增显式`offline_only`合同；该模式只启动固定worker的autoresume，不启动SSH/HTTP同步、不生成每轮网络回传，仍保留plan/policy/shard绑定、STOP/AUTO_HALT、瞬时重试、30GiB磁盘余量和单实例锁。
- 最终交接：worker停止后复制完整数据根/导出产物到移动硬盘，Mac仍按原bundle sequence、raw/Parquet/manifest SHA、source_id、前驱分页和冲突隔离规则导入，物理运输不等于绕过验收。
- 容量：601 D盘约1.57TiB可直接开始；HomePc现有E盘约381.76GiB，另两盘也无单盘更大空闲。历史成交随机样本33/36完整、平均2.394请求/完整股票日、约96,337逻辑字节/完整日；HomePc完整分片大概率超出现有单盘容量，保留磁盘门并在不足时AUTO_HALT，不关闭保护。
- 验证：监督器单测及完整TDX profile 91项通过；后续Windows实机切换、启动和持续心跳另按真实回执记录。

### 2026-09-18｜[TDX性能] Mac正式节流调整到0.25秒

- 基准：固定同100个真实trades请求、两并发、无写库、关闭请求级重试，0.35/0.30/0.25/0.20秒分别2.815/3.296/3.938/4.896 req/s，全部100/100成功、0错误。
- 正式队列验收：0.20秒在Mac shard实际推进300个任务，74.845秒、300网络请求、0网络错误、0恢复轮；SAVED增加282、EMPTY增加18，原69条分片ERROR逐字段不变。
- 实现：新增`runtime_request_interval`/worker-service `--request-interval`运行时覆盖，最小0.20秒；不重签scheduler policy，不改变policy_id、plan_id、shard assignment或历史边界。progress/result记录实际生效间隔。
- 决策：长期先用0.25秒，不直接常驻0.20；0.20只作为短测已验证档，需更长连续运行观察后再升级。新增2项覆盖测试后完整TDX profile 93项通过、0失败/跳过。

### 2026-09-18｜[TDX范围] 停止K线与历史逐笔成交，只保留非K线数据

- 用户明确K线从其他渠道取得，同时不需要与K线/成交量研究相关的逐笔成交历史。HomePc和601计划任务禁用，SUPERVISOR_STOP及worker STOP保留，实机无TDX采集进程；Windows不再参与长期采集。
- Mac沿用固定0/1/2三shard而不是重做计划：shard1/2由原witness bootstrap本机安装，先从canonical接续已合并成功的非K线结果；三片仍各自独立SQLite/page lake，避免共享writer。
- 新`collection-scope.json`独立于scheduler policy，当前排除bars_1m/bars_5m/bars_daily/trades/opening_match；已有数据和历史ERROR不删除。三片分别1882/1877/1813个PENDING trades变为SKIPPED_POLICY并写审计，K线先前已分别4515/5495/5314个待采任务停用。
- 运行时增加scope校验与恢复后重新应用：autoresume即使把可重试ERROR恢复成PENDING，也会在任何网络请求前再次跳过已排除family。专项测试覆盖“excluded retry不得触网”。
- 三个Mac LaunchAgent使用0.75秒/片、2 workers，实际各自100请求短观察均0网络错误；trades的SAVED/EMPTY计数保持不变而auction继续增长，证明范围切换已生效。旧0.25单worker属于此前阶段，不再描述当前三进程聚合配置。

### 2026-09-21｜[Playbook选择复盘 / 外部方法接入] 未入选对照组与AI产业雷达Research Skill

- 背景：用户要求把 AI 产业雷达（ai_industry_radar_pyqt）中三项可借鉴做法落到牛牛：未入选候选的影子对照组、产业上游+未来确认时刻、热度即拥挤度报警。第1项作为宿主工程能力实现；第2、3项只做外部方法入库和数据阻塞登记，检验必须由牛牛自行预注册完成，宿主没有代跑研究或代选因子。
- 选择结果复盘：新增 `trading/selection_outcomes.py`、CLI `niuniu-selection-outcomes` 和3个AI只读工具（`get_selection_outcome_summary / list_selection_outcome_reviews / get_selection_outcome_review`）。同一冻结CandidateSet内选中与未选中证券按D0（仅PREP）及D1/D2/D3/D5/D10计算close/preclose链式信号收益；停牌按因子1并单独计数，缺日线为DATA_MISSING，交易日历未覆盖为NOT_YET_OBSERVED，已冻结结果遇数据修订报REVIEW_CONFLICT而不覆盖。汇总按Playbook版本/kind/frame/窗口分组，给出样本数、NO_TRADE数、价差均值/中位数和正价差占比；少于3个样本标INSUFFICIENT_SAMPLES，不做显著性检验。
- 权限：结果只写 `_trading/selection_outcomes/`，不自动调权、不写Decision/Intent/Paper；新工具不进入Peer Review首轮SAFE_TOOLS，避免评审被结果锚定。研究聊天可用 `playbook_selection` 引用读取选择记录与复盘摘要。
- Research Skill：新增 `research_skills/ai_industry_radar/`（PUBLIC_METHOD / SOURCE_REQUIRED，control `44571065...37e48b`）和策展计划 `curation/ai_industry_radar-a245cef7.json`。按本轮要求从用户自有公开仓库 `https://github.com/anyuzhe/ai_industry_radar_pyqt.git` HTTPS clone，固定commit `a245cef7f2fd83fb9b9076a23b58f089e538db81`、tree `8dfabd2c33ab63c68d938fad8d0e78e17345da8d`，archive `b0535b7c...7bf11b`（164文件/935,231 bytes）。策展包 `18911b09...eb1051` 含视频二精校逐字稿1份statement、21个claim（13原话/3推演/5博主自述待核实）与2个DRAFT假设，Library只读授权该精确包。
- 阻塞如实登记：题材“热度年龄”只能用当前成分回看历史，存在前视偏差；牛牛没有PIT确认事件日历和PIT产业链映射；逐字稿不是原始音视频字节，发布时间与博主身份未验证，博主样本/胜率只作FACT_TO_VERIFY。未回填历史、未升级证据等级、未写StrategySource/Playbook。
- 归档器修正：Git archive原先把0字节tracked blob当预算错误，含 `__init__.py`、`.gitkeep` 的仓库无法归档。现允许0字节对象进入inventory，16MB上限不变；package资源仍须1字节以上，空文件不能成为策展证据。新增回归在旧代码上失败、新代码通过。
- 数据根：archive与curation先在隔离数据根生成，并完成list/get/search/excerpt端到端读取。写入 `/Volumes/Lexar/niuniu-data` 需要用户授权该目录，本次请求未得到响应；176个文件已打包为 `artifacts/claude-transfer/ai_industry_radar-data-root.tar.gz` 并附SHA256清单。解包前Library对该技能返回NOT_MATERIALIZED，郑希包不受影响。
- 验证：新增11项测试（选择复盘8、控制包/registry钉值2、0字节blob归档1）。云端容器Python 3.11按文件逐个运行全仓235个测试文件、1339项，并与e0d9050基线逐文件对照：除 `test_desktop.py` 3项因 `desktop/replay.py` 使用3.12 f-string语法无法在3.11导入（基线相同）外全部通过；15个桌面测试文件在断言全部通过后于Qt offscreen退出阶段段错误，基线同样出现且随机翻转。文档检查PASS，`git diff --check` 无问题。未在Mac真实桌面启动窗口或点击验证。
- Git：本条与代码、测试和文档同一提交；SHA以该提交Git历史为准。
- 后续：是否对热度反向假设做个股级预注册事件研究由牛牛自行决定；确认事件日历与产业链映射需要新的PIT数据接入，另行授权。选择结果复盘需宿主运行 `--auto-all` 或后续显式接入调度后才会产生样本。

### 2026-09-21｜[Research Skill数据根] AI产业雷达策展包写入niuniu-data

- 用户随后授权 `/Volumes/Lexar/niuniu-data`。写入内容：161个内容寻址对象、1个Git receipt和1个策展包目录（14个文件），共176个新文件；未覆盖、未删除任何已有文件。策展包先写到临时目录，全部核对后整体改名为 `packages/ai_industry_radar/`，避免Library看到半成品目录。
- 核验：176个文件逐一SHA256与隔离数据根一致；`research-skill-git-audit` 对 ai_industry_radar 与 zhengxi 均为1/1 verified、0 invalid；Library在真实数据根上两项技能均为VERIFIED，get/search/excerpt可读。核验在牛牛Cowork虚拟机中用Python 3.10兼容垫片运行、从已提交的 `research_skills/` 副本读取，未对真实仓库执行Git-clean检查。
- 事故与修正：经桌面应用文件写入通道写入的1个PNG对象（上游 `docs/examples/演示K线图.png`）被附加了C2PA元数据，大小由83,519变为89,289字节。SHA256核对当场发现后，已从本地副本按原字节就地重写，复核通过。今后向数据根传输图片等二进制对象后必须逐个核对SHA256，不能只看写入回执。
- Git：本条为文档补记，单独提交在前一提交之后。

### 2026-09-21｜[功能测试与修复] 选择复盘跨日、异常、并发和桌面引用

- 用户明确数据正在另行治理，本轮只测试并修复功能。所有业务样本为TemporaryDirectory合成夹具；没有访问/治理正式niuniu-data、修改TDX模块、运行采集、签发正式研究授权、调用业务模型或启停公共服务。原有数据治理工作区改动不包含在本次提交。
- 选择复盘：保留v1哈希算法与已有归档；重复生成时只排除全局calendar_reference_snapshot_id比较，实际窗口交易日/accepted日线及其他内容仍须完全一致。正常延长日历不重写旧记录，可继续生成新成熟窗口；每次build清理输入缓存，补日和真实修订可见。
- 完整性：get/list/summary统一核对checksum、review_hash、format、路径与selection/window身份、实际候选证券集合和分组统计。坏记录不进入数值汇总，但errors/incomplete必须披露并贯穿CLI、AI及桌面，不能悄悄缩小负样本。
- 并发：正式服务写入由POSIX进程锁保护并在锁内重检。支持时使用硬链接不覆盖发布；Lexar实测不支持硬链接(errno45)，改为同一锁内重检后原子rename，兼容该卷。此合同保护合作的服务调用，不宣称防止任意外部程序绕过锁篡写。
- CLI：auto-all逐窗口收集结果，部分成功后报错不丢计数；SUCCESS/PARTIAL_FAILURE/FAILED分别退出0/3/2，正常等待不算失败。只读get/list/summary遇不完整归档也返回非零。修正list --full并增加offset分页。
- 桌面：复盘引用列表补selection_id；真实引用打开保留errors/incomplete，并显示不完整提示。新增离屏测试先在旧代码复现空编号，再验证正常打开、不改写归档和坏记录提示；不启动可见窗口。
- 功能盘点：当前default_registry为441个因子/组件，16个组合模板逐个resolve成功。旧qimo-source-rules-v2/QimoPaperRunner是专门的规则代理流程，通用ExecutionStudy、理论组合研究和AR事件研究不只服务期末50分；严格QM50原始合同不是旧代理的同义词。未查看用户运行库中自建Playbook。
- 验证：18个原功能模块106项逐模块通过；首个总进程480秒超时停在headless模块，随后headless独立6项通过。最终新旧选择复盘15项、无硬链接2项、Playbook工具3项、headless6项共26项通过且4个产品文件测试前后SHA一致；文件系统/桌面4项也在Lexar卷临时目录通过。去重合计22模块131项，新增11项，不把重跑累计成更多测试。
- 限制：一次早期组合回归180秒超时；最终26项中60秒faulthandler输出定位到外置卷依赖导入，随后正常结束为OK(69.492秒)，不是测试失败。Pi实施任务有中断，独立Reviewer任务未产出结论；最终修改由主控逐处复核并补回归，不声称独立Reviewer PASS。不运行全仓重负载、真实桌面、付费模型或盈利验证。日志/结果保存在本轮新目录artifacts/functional-validation-20260921。
- Git：只将本轮4个产品文件、3个测试文件与3份现有说明形成独立提交；不包含TDX、行情或artifacts。普通推送及远端SHA核对以本轮实际回执为准，失败不得视为已推送。

### 2026-09-21｜[按序实施] 跨层生命周期、MCP接线与组合模板目录

- 顺序：先同步积压Git提交，再验证完整功能链，最后落地策略能力发现的首个增量。旧三笔提交已普通push到51b0fc4并取得成功回执；SSH 443连接间歇关闭，独立远端SHA复核与本轮新提交推送以最新回执为准，不修改网络配置或强推。
- 缺陷修复：标准MCP原先只组合MarketData链，缺少Playbook/来源/选择复盘读取层。新增MCPResearchAPI仅补既有get/list只读工具，重名MarketSnapshot仍保留原市场API合同。新增测试先复现缺失，再经真实进程内Client和stdio新进程查询同一选择/归档，验证工具唯一、只读注解、坏记录披露及执行权限不扩大。首轮Reviewer仍不读取复盘结果或Scorecard。
- 策略发现：在原ReadOnlyResearchAPI增加list_research_templates/get_research_template，直接读取16个原组合模板；分页、精确ID/版本、来源摘要哈希和原theory/theory_version提案字段均保留。逐一验证16个模板与resolve_template一致且可进入既有preview；不注册新因子、改公式、代定交易参数、把模板计为成品策略或放宽Grant/QM50绑定。
- 跨层研究测试：脚本化Provider驱动正式headless ChatRuntime发现工具、记录假设；临时宿主Grant允许一次真实JobQueue执行并冻结实际输入，随后读证据/保存finding；同turn/spec重试不新增job，新spawn进程读回相同run_id、source SHA和预算used=1/remaining=0。不是自主模型质量或策略有效性验证。
- 跨层模拟测试：通用非Qimo Playbook由SYSTEM_PREDICTION桥接WATCH，再经人工READY/PLAN_OPEN及宿主确认PaperPlan/执行，得到模拟fill、OPEN和D1复盘；新spawn进程重复交付不增加订单、成交、账户版本或决策。未确认与NO_TRADE分支不生成Paper账户、订单或虚假股票Decision。
- 验证：新增3个MCP场景、4个模板用例、3个生命周期场景，共10项。最终主控重跑14模块88项全部通过，4个产品文件及3个新增测试文件前后SHA一致；原MCP、聊天、记忆、选择复盘、核心、授权、Paper桥接回归均包含。Qt引用另做offscreen独立验证，结果见ui-regression.json，不称真实桌面验收。
- 复核：独立Pi只读审查4个产品文件及MCP/模板测试，未发现有证据支持的权限/版本/工具接线缺陷；主控另检查并改进生命周期测试的冷启动等待和子进程清理。实施worker早期夹具错误保留在日志，最后在测试内修正，未为通过测试改产品合同。
- 范围：未访问niuniu-data、运行正式研究/业务模型/行情采集、启停公共服务、修改TDX治理文件或原策略公式。新临时测试与日志位于artifacts/functional-lifecycle-20260921，artifacts不进Git。F3b资金/持有/退出/费用/执行的完整策略封装仍是下一阶段，不把本轮目录发现算成已完成。
- Git：本条与本轮4个产品文件、3个新测试及3份既有文档组成独立提交；仅普通push并核对回执，精确SHA在Git历史与本轮commit/push记录中，不自称已部署。

### 2026-09-21｜[F3b] 版本化策略配置包与人工审批执行

- 基线：开工独立读取远端main为8f7e23b，与本地一致，前轮推送核验收尾。用户继续授权功能推进，不涉及正式数据治理。
- 新增统一策略包niuniu-strategy-package-v1：固定策略标识/版本、精确信号或组合模板、证券日期范围、资金/费用/仓位及既有目标权重生命周期。compile_strategy纯编译展开既有默认配置；prepare逐字段核对包与普通spec，ExecutionStudy在运行前重解析并核对实际参数，父manifest和数值复算均保留包身份。不增加回测引擎、数据库或独立运行状态源。
- 操作入口：宿主CLI支持preview、独占文件导出和propose待批准提案；新增niuniu-strategy-package安装入口，当前也可python -m调用。原提案面板增加“导入完整策略包（不执行）”，清除旧选择与确认，只填草稿，保存/批准仍走原流程。示例JSON仅演示结构，非推荐资金/证券/日期。模型/MCP/Reviewer新增两个纯配置只读工具，超大结果明确拒绝，不交付截断spec；QM50绑定与Session Grant权限保持不变。
- 真实语义：v1仅接受research_only，严格资格或官方规则覆盖声明直接拒绝、不静默降级；旧严格研究入口未改。生命周期为每根完结bar重算目标、目标减少驱动退出、期末按市值计价不强平，不支持固定持有、独立止损止盈或自动Paper/实盘。16个原组合模板均能编译并进入原提案预检，但不是16个已验证成品策略。
- 缺陷复现与修复：主控构造重签包内股票范围、保留旧resolved_config的复算反例，初版错误接受；改为运行入口重新prepare完整声明后拒绝。另核对实际signal_snapshot价格口径，raw/qfq错配不能通过。初始失败日志保留，不只记录修复后的通过。
- 独立复核：首个Reviewer上游重试后无报告，不计审查。后续独立只读Reviewer提出MEDIUM资格声明缺少回执与LOW预览哈希未绑定源码两项；前者通过限定新包v1研究口径解决，后者新增compiled_spec_hash并要求CLI与package_hash同时核对。新增同配置源码改变/严格资格伪造反例通过；复核报告原文保留，修复由主控验收，不声称独立复核者另做了修后PASS。
- 验证：新增5个测试模块25项；本轮去重覆盖18模块107项。复核修订后的受影响后端10模块62项、其余7模块43项及Qt离屏2项均通过，共18模块107项、0失败/错误/跳过，源码前后指纹一致；合并统计及原始日志在artifacts/strategy-package-20260921内review-fixed/supplement/precommit结果中。16模板预检是同一批显式合成配置验证，不额外累计为策略或测试方法。文档检查122份、543个本地链接无错误。
- 过程限制：实现worker有测试导入/模板dataclass编码错误，均修复；一次Grant测试在并行开发期报告运行时身份变化，未据此放宽门禁，随后独立及本轮最终Grant12项通过。包端到端主要验收open后端，未独立验收带新包的vnpy_open/vnpy_rules运行；未运行真实模型、可见桌面或盈利验证。
- 范围与提交：9个产品Python文件、pyproject、5份测试、1份JSON示例及4份现有文档组成独立功能提交；不包含TDX治理文件或artifacts，不访问niuniu-data，不启动采集、常驻服务或重启WebCodex/Runner。仅普通push并独立读回远端，具体SHA和成功状态以本轮Git回执为准。

### 2026-09-21｜[F4] 策略可视化编辑、版本差异与归档结果对照

- 基线：开工实际本地与独立远端均为79ab8b5。用户继续授权功能开发，正式数据治理及TDX未提交工作保持独立；不访问正式niuniu-data、旧运行空间、业务模型或真实GUI，不启停公共进程。
- 原ProposalDialog新增策略工作台，复用compile_strategy及原人工批准链。表单覆盖身份/信号/范围/资金/费用/仓位，保留未展示高级字段；原包不变往返保留数值类型与配置身份。编辑立即失效预览，填入时及接收端均校验compiled_spec_hash；仅另存新文件、不覆盖原版，取消不回填、导入不执行，返回草稿清除旧批准勾选。
- 版本比较纯配置归一化后逐字段列左右值及存在性；同标识或同名同版本内容变化警告，不自动改版本。历史归档比较不使用当前模板重编译来替代历史事实。
- 结果对照只读两个明确UUID的完成execution父归档/信号子实验，文件树前后校验并核对包与真实配置、targets、行情和曲线。全部冻结输入（含背景）、Universe及其元信息/版本、价格/证券日期/运行环境/backend/初始资金/费用/规则须符合可比条件；不同口径delta=null。信号/目标仓位规则作为变量明确列出，不排序赢家、不声明Alpha。UI与compare-packages/compare-runs CLI共用服务，后者退出码0/3/2分别为可比/不可比/读取或核对失败。
- 已复现修复：Qt组合框Python tuple查找导致有效包无法导入，改为精确值逐项匹配。主控三个初始反例发现附加冻结输入被忽略、缺失零费用被填零、重复净值时钟被接受，均修复；补上重新签名后包内信号参数与实际配置不一致拒绝，证明仅snapshot ID不同但输入字节相同仍可比。
- 独立复核：UI只读审查未发现所审产品范围缺陷；后端只读审查指出Universe metadata忽略，主控构造真实合成listing归档复现后改用既有冻结加载合同校验版本、保留全部metadata。另复现有限但篡改的Sharpe被直接展示，现以已保存曲线核对绩效统计。上述为归档内部一致性，不是外部签名认证或重新回测。复核报告开头将文件SHA与Git HEAD混用，实际依据已读取源码和报告指出的明确位置核对，不把该文字当版本身份证据；修后回归由主控执行，未宣称独立修后PASS。
- 测试：新增4模块30项（对照10、边界7、CLI4、桌面9）；最终11个后端模块70项+2个桌面模块11项，去重合计13模块81项，0失败/错误/跳过，5个产品文件测试前后SHA一致。全部业务样本为TemporaryDirectory合成行情/归档，桌面明确offscreen。原始失败、测试夹具将0.3误当变更的修订、修复回归与最终源码指纹保存在artifacts/strategy-workspace-20260921；以review-fixed-backend/ui及precommit记录为准，不累计重跑数量，不声称全仓、真实桌面或策略有效性验收。
- 工程过程：新文件原子创建工具因Lexar不支持返回errno45且回滚，确认不存在后用独占创建落盘；UI Reviewer观察回执一度异常，随后对同一run取得completed终态及实际报告，未重启服务或替换远程系统。仅本轮5个产品Python文件、4个新增测试及指南/开发史形成独立提交；TDX及artifacts不暂存。共享status页出现数据治理并行增补，SHA保护拒绝过期写入后已重新读取并只更新本轮F4状态；为不夹带另一任务改动，混合status暂不整文件提交，本轮交付与验收在随提交的指南/开发史完整保留。普通推送与远端SHA以实际Git回执为准。

### 2026-09-21｜[TDX数据湖] 主库归并、大文件归档与worker安全退休

- 原因：ExFAT上数十万组三文件页及worker重复副本占用远大于逻辑数据量。用户要求先完成已采数据的归并/压缩，再安全清理冗余副本；不重新采集、不按外部数据源校验行情正确性。
- 实现：新增大文件归档和可查询物化表，原始响应gzip、原Parquet及manifest按原字节进入`tdx_page_archive.sqlite3`，13类标准`tdx_*`视图兼容已归档和未归档页；本地worker仍通过原结果包、MERGED回执、ack归并。分页前驱、重试和重复导入可从归档读原字节。归档中断残留目录仅在现存文件逐一匹配归档、且查询行数一致时清理，额外或不同文件保留并报错。
- 删除安全修复：旧退休路径会整目录递归删除，且未识别worker-1/2存于队列库的虚拟checkpoint witness。现先取得各库writer lease，预检全部worker的cluster、导出回执、publication/checkpoint、主库归档覆盖与实体页文件SHA；不认识的目录/文件、未发布页或不匹配字节即拒绝。`--dry-run`不写标记、不删除；正式操作仅逐页移除指定三文件和空目录，保留worker队列、错误记录和虚拟witness。
- 真实运行：三份worker已STOP，归并后的主库319,961 publication、62,915,859行；主库大文件归档于16:06记录COMPLETE。退休前dry-run核对通过，正式进程于19:29成功退出，macbook/homepc/601三份回执均为RETIRED；分别涉及92,548/74,474/74,649条publication及6,872/6,864/6,629个checkpoint。实体页目录按预检结果逐页删除，没有移动或删除主库唯一归档。
- 清理后只读复核：319,961 publication与319,961 archive页逐source_id核对0缺失/错配，13类标准查询逐类行数与publication求和一致，合计仍为62,915,859行。Lexar卷占用从本次清理前约838 GiB降至约353 GiB；约485 GiB是期间观察到的卷占用差，可能包含其他磁盘活动，不作精确净节省结论。
- 验证：TDX相关62项测试通过（含残留目录额外/改动文件、未登记worker页、虚拟witness和跨worker先预检后删除）；文档检查122份、543个本地链接为PASS。未运行全仓测试、可见客户端或重新调用供应商。此数据仍非全历史齐全或Strict PIT证据。
- Git：本条与TDX产品代码、相关测试、指南和当前状态形成独立提交；普通推送与远端SHA以实际回执为准。

### 2026-09-21｜[F5] 策略归档发现、结果选择与助手只读接线

- 基线为main@7f9f828，开工独立远端SHA一致；用户继续功能推进，正式数据治理/TDX/并行status保持独立，不启动常驻进程或真实GUI。
- 新增同源strategy_run_catalog：只枚举本工作空间直接UUID候选；列表按名称/版本/标识/问题检索，含失败execution，不把旧无包实验、factor子归档算成策略。元信息列表不读Parquet或返回未经核验的收益；每次最多检查100候选/返回20匹配，next_offset为真实扫描位置，错误、下一页与匹配数量分开。8MiB单记录及100000候选限额明确失败，不递归或建第二份索引数据库。
- get_strategy_run复用原compare_strategy_runs对指定归档及信号子实验核验，再把历史包读取与文件指纹绑定，不用当前模板重编译历史，不回读数据根或重新回测。目录metadata_only与详情archive_internal_consistency分开，不认证Alpha、Strict PIT或执行授权。
- 原策略工作台结果页增加手动查询/分页、选到左右侧及核验选中归档；失败记录保留但不可选作有效结果。查询代际变化忽略旧异步响应，异常解除忙状态并明确反馈，不把读取失败当空目录、不修改策略草稿。手填UUID和原比较仍兼容。
- 本地ChatRuntime和标准MCP接入list_strategy_runs/get_strategy_run/compare_strategy_runs，CLI加list-runs/get-run；同一后端、真实stdio验证。精确返回游标/错误/阻塞，超预算明确拒绝，不静默裁剪；模型详情不输出历史完整包作为可执行新spec。首轮Reviewer仍拒绝三工具并同步能力标记，QM50绑定不开放替代、无新批准/执行权限。
- 独立只读复核发现入口resolve先于符号链接根检查，主控在ReadOnlyResearchAPI/ChatRuntime/build_mcp_api/build_mcp_server四入口复现；现统一在解析和聊天日志初始化前检查原始output根，保持CLI/UI/模型边界一致。原报告与修前失败日志保留，修后验证由主控完成，不声称独立复核者另给修后PASS。
- 测试过程：首次并行开发期结果比较一次不可比断言失败且未记录blocker，后续固定源码比较通过，不能据此追认具体原因；后续失败是测试将既有ChatStore初始化目录误算作查询写入，改为先初始化再冻结查询前基线，未放宽产品无写入检查。实现worker默认时限结束为cancelled，已写文件由主控完整读取并重新测试，不拿worker终态或无报告当完成证明。
- 最终验收：新增3模块20项（目录6、工具/MCP/CLI8、选择器6）；固定修后源码11个后端模块74项、3个Qt离屏模块17项，共14模块91项，0失败/错误/跳过。覆盖真实临时execution归档list→get→compare、stdio新进程、费用口径不同比较阻断、损坏后核验拒绝、部分列表错误、扫描偏移分页、无自动扫描、查询代际防旧结果、四入口符号链接拒绝及原提案/聊天回归。所有产品源码测试前后指纹一致；不累计重跑次数，不把测试替身/合成样本当真实模型、真实客户端或策略收益验证。
- 最终测试、源码指纹、复核及Git回执位于artifacts/strategy-catalog-20260921；仅本轮代码、测试、指南及开发史独立提交，TDX、生产数据和artifacts不提交。共享status存在另一任务更新时只改本轮状态且不整文件提交，普通push后再核对远端，不表示部署。

### 2026-09-21｜[F6] 从历史策略归档载入可编辑副本

- 基线：开工main本地和独立远端均为045b62417bfccdd5fef4e6e952d942898c89fdc7，只有共享status未提交；此前TDX治理已由另一任务提交，本轮不修改其代码或读取正式数据。
- 功能：结果目录新增“载入为可编辑副本（不执行）”，默认取消的确认框提示替换未保存草稿；prepare_strategy_revision先get_strategy_run深验，再核对所选package_hash，单独按当前compile_strategy解释。历史包/run/证据指纹与当前编译指纹分列，当前UI应用前再次核对编译指纹；取消、损坏、过期选择或不可用信号均不覆盖原草稿。
- 版本：同strategy_key同version但完整编译指纹改变时，预览/另存/填入均拒绝，要求明确新版本或新标识；新版本不自动生成。普通独立导入清除来源，完整配置树修改保留来源。来源仅是本次工作台内存核对信息，不持久化为新包/实验父子谱系；原v1格式和模型工具集合不变。
- 人工门：回填沿原ProposalDialog再次核对compiled_spec_hash并清除旧批准勾选，保存为新pending提案；不继承旧批准、预算、Job或收益结论，不调用正式模型、数据根、回测、Paper或交易。测试中的临时合成归档由真实ExecutionStudy生成，不冒充自主研究。
- 缺陷与复核：独立只读审查在其锁定源码未发现高置信问题，但提示关闭后的迟到响应值得补测；主控实际复现reject后隐藏对象草稿仍被替换，现done时递增查询代际以拒绝迟到结果，保留修前失败与修后回归。复核报告属于修关闭问题之前的源码，未声称独立修后PASS。
- 验收：首轮目录10+离屏14共24项通过；新增关闭窗口反例后，固定修后源码8模块71项通过（后端45、Qt离屏26），0失败/错误/跳过，本轮新增13项包含在71项中。9个相关源码/测试文件测试前后指纹一致，完整统计见artifacts/strategy-revision-20260921/final-regression.json。测试数量不累计重跑，未做可见桌面、正式数据或策略盈利验收。
- 收尾：仅本轮2个产品文件、2个测试及指南/开发史形成独立提交；共享status仅更新本轮条目且不整文件夹带提交。普通push和远端SHA核对以本轮真实回执为准；不启停或重启公共服务。

### 2026-09-21｜[F7] 策略改版直接父来源跨会话保存

- 基线：main本地/独立远端均为df5093f，开工仅共享status未提交；不读取正式niuniu-data，不改TDX/交易算法/权限，不启停进程或可见GUI。
- 合同：v1六必填字段不变，增加可选revision_source（固定8字段、规范UUID及完整SHA）。正常包无字段时沿原身份；来源参与package/compiled哈希，另用排除直接父引用自身的content_hash判断配置/源码未改。同标识同版本内容修改在完整编译阶段拒绝，重开文件不绕过；纯编译标not_checked，不认证来源。
- 复用归档：get只深验当前execution和计算子实验，直接父来源另标not_checked；make/verify只核对一个直接父的完整当前归档指纹，不递归祖先。prepare改版不继承祖父引用，返回当前选中父和当前独立编译副本。来源随原提案spec/执行manifest/复算自然保留，不新增数据库或改变计算children图。
- 宿主门：ProposalService预检与批准冻结前后核对直接父；错误哈希即使语法正确也不能成为已批准来源，父缺失/损坏/变化即拒绝。原批准、输入冻结及队列权限不继承；已批准执行和数值复算使用自身冻结输入，不将父策略作为新的行情来源。
- 界面与CLI：F6载入后来源随JSON保存，重开显示未核验引用，按钮显式核验并先清除旧验证显示；普通独立无来源导入不伪造谱系。新增verify-revision-source只读命令及模型合同说明，不新加模型写入或执行工具。
- 独立复核指出批准前后来源变化时，虽拒绝批准但遗留冻结候选会被get作为approval_freeze显示，且重试可能沿用旧冻结。主控追加断言实际复现后修复：未批准状态不返回有效批准回执，明确unapproved_input_freeze；带改版来源的pending残留不能复用，须拒绝旧提案并重新生成。原始候选保留、不自动删除；修后验证由主控完成，不声称独立修后PASS。
- 验证：全部使用临时合成行情与真实ExecutionStudy/ProposalService/JobQueue，Qt离屏。首轮4模块40项通过；复核问题修正后最终14模块110项通过（后端81、离屏29），0失败/错误/跳过，含本轮新增17项（来源6、跨层生命周期8、界面3）。12个相关产品/测试文件前后SHA一致，完整统计见artifacts/strategy-lineage-20260921/final-regression.json；原失败日志保留，不累计重跑，不冒充真实模型、正式数据或策略有效性验收。
- 提交：仅本轮明确代码/测试/指南/开发史独立commit和普通push；共享status保留，不整文件夹带。远端状态以Git回执为准；旧历史开发记录不改写。

### 2026-09-21｜[数据治理交接] 只读盘点与Coverage数据根绑定修复

- 用户要求数据治理由另一模型继续，本窗口保留代码职责。基线main@6de1715；本轮只读观察正式niuniu-data、指定_market_data归档、回执、目录和数据库，不更新数据、SQL视图、采集scope或进程。观测时刻2026-09-21 13:03–13:14 UTC；只有共享status为既存未提交文件。
- 存储证据：319961 publication/319961 archive页、62915859行，逐source_id联接的缺失/族行数错配/额外均为0；13类视图真实行数一致，各取1页原字节SHA校验通过，不声称全部319961页再次深验。compaction=COMPLETE，3个worker=RETIRED且STOP保留；退休不代表历史计划完成。主库剩余pending/error均为已排除族，worker仍有5555个auction pending前沿、6个auction error和1个ladder前沿；前沿数不是剩余全部历史请求数。transfer及tunnel仍有进程，未停止。
- 覆盖区别：raw/qfq日线各5215文件17075243行，5m各5215文件360081759行，均截至9月4日（5m的15文件结束更早）；20865个Parquet footer可读不等于全量值质量通过。另有5455证券8644474行retro_daily pack（2019-01-02至2026-09-15，manifest统计）保存前收/换手/供应商状态；不因旧MQC缺字段而重复下载。TDX竞价14902776行、5565证券、42个实际日期，单位仍未确认；不能按日期最值声称全年覆盖。严格回执深验14条稀疏status、完整Universe与完整逐日status均0。数据后续计划按备份恢复、索引与全源清单、字段/单位/质量、有限研究快照、新鲜度和按需求补采分阶段交接。
- 已复现代码缺陷：复制后的catalog/mqc.duckdb两条旧行情视图仍引用MQC-DATA，Coverage此前会把foreign视图行数和当前根文件数混用；合成反例实际返回1行而当前根应为4行。现在以宿主根明确文件名单通过内存DuckDB读取，仅扫描证券/日期/抓取时点列，2线程/512MB/禁spill，不打开或修复正式catalog。原数据根SQL仍保持原样，由数据负责人单独治理；历史manifest旧路径不得批量替换。
- 独立只读复核指出同模块small-table/silver祖先链接也可能跨根；主控追加反例复现后统一祖先和文件路径检查，并限制silver遍历规模。测试证明取消持久catalog依赖、缺fetch_ts显式、链接拒绝及正常嵌套表计数；修后验证由主控执行，未声称独立修后PASS。
- 最终验收：test_pit_coverage 12项与test_mcp_server 3项共15项通过，0失败/错误/跳过；含7项新增，源码/测试/记忆合同/指南指纹稳定。修前失败和修后日志在artifacts/data-governance-handoff-20260921；observed-coverage.json是修复后对正式数据根的一次只读结果。测试使用合成样本，不声称数据已治理、全仓通过或策略有效。原始生产库未写入、服务未启停。
- 提交仅本轮产品文件、测试、对应指南/记忆合同与开发史；共享status不提交。用户交接计划单独交付，不新增另一份当前状态或让数据执行者并发改产品代码。普通推送及远端SHA以实际回执为准。

### 2026-09-21｜[F8] 通用归档行情只读入口与Chat/MCP接线

- 基线：main本地与独立远端均为53b5e6b，只有共享status既存未提交。用户确认另一模型执行数据治理，本轮只改产品代码并在TemporaryDirectory合成样本验收；不访问正式niuniu-data/历史业务artifacts，不修改SQL视图、TDX采集、迁移、单位、策略公式、可见客户端或公共服务。
- 新增ArchivedMarketDataAPI，复用原ArchivedDailyBridge和TdxLake；普通Chat与MCP均接list_archived_daily_sources/list_archived_daily_symbols/inspect_archived_daily及get_tdx_data_status/read_tdx_data。不建立第二个数据库或Provider；数据根和来源工作空间由宿主固定，模型参数不接受path/root/SQL。构造期不读源，source list在加载计划前限制候选，错误capture保留errors/incomplete；packed与原目录按相同原始/typed字节合同读取。
- 读取边界：TDX仅catalog_rows_only，不重新深验原始页、不把请求日期当实际覆盖；original_record、source_id、未知单位与observed_at原样保留。读取缺根、损坏/锁库或无效参数返回结构化失败；完整返回超过64KiB明确拒绝，错误包也有预算保护，不截断数据后返回成功。工具read_available表示接线，不认证资料已存在、PIT或可直接回测。
- 兼容：旧QM50命名的三个只读别名及TDX入口转同一实现，专用source_workspace继续有效；绑定规格仍屏蔽通用替代名称和未授权测试，首轮Reviewer白名单不扩大。修正普通ResearchSpecAPI外层能力清单漏列实际工具的问题，断言schemas与get_capabilities工具集合一致；内层失败不改成成功，原警告/证据保留。
- 验收：新增两个测试模块21项，最终12模块140项全部通过，0失败/错误/跳过；覆盖真实ChatRuntime分发与留痕、MCP进程内及stdio子进程、packed日线、TDX原单位、旧别名/原规格约束、根路径、坏capture、分页和输出预算。最终9个相关产品/测试/共享reader文件前后指纹一致，统计见artifacts/generic-archive-access-20260921/accepted-regression.json，初始失败日志保留。
- 测试边界：首次完整三步聊天及旧提案幂等测试因默认上下文触发TOOL_CONTEXT_BUDGET_EXHAUSTED；对HEAD原ChatRuntime和工作区分别实测，原版同样在第二次提案返回触发预算且均只生成1个提案。仅将这些功能测试显式设置100000字符测试预算，产品默认60000、权限和上下文保护未放宽；原预算拒绝测试继续通过。不是实际模型自主研究、正式数据或全仓验收。
- 独立Pi只读审查在其记录的4产品文件版本未发现有证据的阻断问题；之后主控补外层能力清单3行修复与测试预算设置，最终测试由主控执行，不把早期报告写成独立修后PASS。worker报告、审查、失败和最终回归均在同一新artifacts目录。新文件事务create在ExFAT报errno45并确认回滚后，以独占创建落盘；一次SHA参数抄写错误拒绝整批后，重读当前文件重新提交，未覆盖并行改动。
- 提交仅本轮4个产品文件、2个新测试、1个原测试预算设置与指南/开发史，artifacts和共享status不整文件提交。完成后普通push并独立核对远端；不表示部署，后续正式Provider适配以数据负责人交付的字段/单位/时点/快照合同为前提。

### 2026-09-21｜[F9] 已归档日线的显式有限研究输入

- 基线：main本地与独立远端fa57e72，既存共享status保留。用户要求继续代码线，另一模型负责G0–G6数据治理；本轮不访问正式niuniu-data、旧MQC、历史业务_market_data或真实模型，不启停采集/服务，不改TDX单位或原始QM50合同。
- 新增archived_daily_dataset编译器/只读Provider和宿主CLI（preview/export/inspect）。复用已有ArchivedDailyBridge真实raw/typed校验，仅接受明确1–10个沪深代码、最多371自然日、raw日线、research_only。完整覆盖请求所用capture日历；缺日、停牌或必需值异常拒绝，不填值、不删样本、不推断qfq/分钟或官方可交易资格。15:00 available_at明确为研究对齐时钟，historical_available_at_verified固定false。
- 输入包保留精确原始响应、typed日线、plan/basic/calendar与规范bars。预览哈希固定请求和来源语义，确认导出前重新核验。Provider每次完整核验固定文件树、内容/身份/原始与派生语义，修改bars再重签manifest不能冒充原版本；允许包范围内子请求，不读原数据根或网络、不建立永久数据库。源可离线，快照身份沿原批准冻结、JobQueue、ExecutionStudy与数值复算保留。
- 接线：local_data_provider明确识别archived-daily-dataset.json，混合marker/坏包/qfq/分钟拒绝而不fallback；旧路由保留。普通MQC发现对新管理包明确拒绝，助手/MCP新增只读get_archived_daily_dataset，宿主指定根且返回不暴露物理路径；模型无export、批准、切根或新增执行权，原规格/Reviewer白名单不扩大。
- 主控跨层测试实际复现祖先symlink根绕过检查，独立Pi静态复核也提出同点；修复读取/源预检祖先检查后回归通过。独立报告仅对应它记录的先前SHA，修后验收由主控完成，不称独立修后PASS。
- Lexar隔离样本实际复现RENAME_EXCL errno45不受支持；不放宽为覆盖rename，改为独占新目录、INCOMPLETE清单、最后原子发布有效marker。中断留不完整目标供宿主检查，不能作为有效包或覆盖重试；竞争失败不删除其他导出锁，原归档不变。文件系统不支持目录fsync时不声称断电耐久性；没有清理任何正式数据。
- 最终验收：两个新模块27项（后端15+跨层12），最终13模块136项全部通过、0失败/错误/跳过，8个产品/测试文件前后SHA一致。Lexar同卷2个选定场景复跑通过且临时目录清理；不将重复运行累计成新测试。测试含真实CLI子进程、Chat/MCP接线、原人工批准冻结后源/输入下线、原ExecutionStudy复算；只证明合成功能，不证明正式数据已交付、策略有效或真实自主研究。
- 证据在artifacts/archived-dataset-20260921：accepted-regression.json、lexar-compatibility.json、lifecycle-before.log、lexar-compatibility-before.log与独立报告。完成后仅本轮代码/测试/指南/开发史独立提交普通推送，核对远端；共享status不整份夹带，正式数据包未生成，公共服务未重启。

### 2026-09-21｜[治理交付复核] raw日线尾部读源修复与数据侧后续任务

- 用户提供另一模型G0–G6交付并要求评估和继续代码。开工main@3b0dd21469dfdbb7d07daadce56292daa03ea327，远端仍为32c91e4；3b0dd21是另一模型4文件raw-tail增量，本轮先审查修复该读源链，F10输入包界面继续待做。共享status原修改保留。无采集、正式库/指针写入、服务重启或可见GUI操作。
- 数据侧只读复核：两条bronze视图确已绑定niuniu-data；三个备份文件存在，未再次全量重哈21G。报告混用任务day与页内事件date，实际tdx_*事件聚合为daily 5781日、1m 28日、5m 123日、capital_changes 7991日；竞价实际42日，原报告282任务日期不可替代事件覆盖。范围不是逐证券连续性证明。竞价“手”仍是候选，14:59样本误标09:25、观测版本去重/冲突选择和G3源文件SHA未完成；G4不是完整增量发布，G5/G6仅计划。本机SDK没有query_valuation属性，不把它写成已验证接口。完整下一轮只读纠偏任务在artifacts/governance-review-20260921/data-next-actions.md。
- 原3b0dd21反例：请求仅尾部先被MQC空窗口拒绝；错误pack digest、coverage_end越界仍可加载；坏JSON指针被当作不存在；尾部过滤会静默丢掉停牌/无效行，来源身份只信声明。本轮按每证券完整主干截止仅追加后缀，支持只查尾巴和混合截止，不替换主干、不填内部洞。需要尾部时验证实际pointer、pack index、原始/typed字节及精确日历覆盖，明确缺证券/缺日/停牌/无效值；同实例读源变化拒绝，快照保留实际SHA和观察时间，资格仍非PIT。
- 延迟读源：raw日线确需扩展才加载指针及capture；qfq、分钟、主干历史不依赖未使用的raw尾部。保留合法written_by描述字段，拒绝重复JSON键、非有限常量、非法字段/路径；修复provider提前resolve掩盖数据根链接。捕获日历明确休市的尾部不制造缺交易日错误；全请求没有行情仍拒绝。源字节不写回，已有指针不重签。
- 独立Pi静态复核记录了当时版本的written_by与来源role接线问题；主控跨层测试复现并修复相关兼容性，同时自行补充qfq/分钟依赖、周末、重复键、根链接反例。worker完成核心实现及局部回归后由主控取消并确认终态，后续由主控收尾；不宣称独立修后PASS。修前失败日志保留，工具观察复核run曾返回invalid_runner_response，后续同run取消调用确认原run已completed；未重启公共服务。
- 最终验收：14模块144项通过，0失败/错误/跳过；其中新增两个测试模块20项，旧fallback 7项按真实合同修订；最终6个产品/测试文件指纹稳定。覆盖旧MQC/资格/原QM50/有限数据包/Grant/批准冻结/策略复算。批准后源和指针下线的合成任务仍从冻结输入完成，重复批准不重复执行。真实指针另做sh.600000在2026-09-07..15的一次只读smoke，7行成功且pointer SHA未变；不等于全量正式数据或策略有效性验收。
- 本轮测试与事件日期查询、真实只读smoke、复核和提交回执均保存在artifacts/governance-review-20260921。仅提交本轮代码/测试/指南和开发史；普通推送将同时带上已经审查并修复的3b0dd21祖先，远端SHA以交付回执为准。数据治理模型下一步只做事件时间覆盖勘误、单位/版本合同及有真实字节身份的有限交付，不再并行改src/tests或单独推送旧增量。

### 2026-09-22｜[F10] 归档研究输入数据工作台与宿主选择

- 基线main@4286f9a，既存共享status保留；本轮仅代码、合成数据与Qt离屏验收，不读取/修改正式niuniu-data、旧MQC或历史业务归档，不采集、不治理、不启停公共服务、不调用真实模型或可见GUI。
- 数据中心和Baostock菜单加入归档输入面板，手动发现capture元信息、明确证券/日期、原F9预检、完整preview_hash确认导出、已有包深验及人工选择分开。初始范围为空，来源只绑定宿主output；生成不自动切根、不创建提案/授权。沿用raw/1d/research_only及原规模/缺失规则，未新增Provider、数据库或后台调度。
- 宿主后台深验后核对dataset_id、marker及包文件树/元数据变化，再在Qt线程应用当前会话数据根。队列、有效Grant、跟踪守护进程/授权和损坏回执阻断切换；旧未冻结失败/取消/中断任务仍可能恢复，因此也阻断跨根使用，提示保留旧工作空间或另建研究空间。关闭旧对话、清原确认和缓存，不修改历史归档或授权。文件状态检查不是永久租约/不可变文件认证，每次Provider/审批仍重验字节。
- 修复DataResearchChatDialog替换标准ChatRuntime.api导致归档读取等工具丢失，改为只补缺少的已存在只读数据工具，同名接口保留原实现；工具集合与能力清单一致。锁定原始规格时不增加工具或改变原能力响应，模型没有导出/批准/切根工具。
- 独立宿主静态复核提出旧可恢复任务与payload-only晚变化风险，主控均构造失败场景后修复。自行补齐已撤销且synced跟踪状态误阻断、绑定规格工具扩张、空完成回执假成功、关闭导出后短暂重开动作，以及关闭只读对话遗留busy等边界。只读迟到回调失效；已开始导出只延后关闭并记录实际成败，不伪称取消写入。UI worker终态cancelled且未交最终报告，主控接手已落地代码并完成阅读、修复和最终验收；独立报告对应它记录的修前SHA，不称独立修后PASS。
- 最终12模块111项通过，0失败/错误/跳过；新增UI13+工作台集成21共34项，重复运行不累计。6个Qt离屏模块47项、6个后端模块64项；包括实际面板→F9导出→深验→宿主选择、真实Proposal/JobQueue执行同一包以及旧入口回归。最终8个相关产品/测试/依赖文件指纹稳定；不等于正式数据已交付、真实模型自主研究或全仓正确性认证。
- 原始证据在artifacts/archived-dataset-workbench-20260922，包括accepted-regression.json、独立复核、修前失败和逐模块日志；使用说明更新原user-guide。提交仅两个产品文件、两个新测试、指南和本开发史；共享status不整份提交。普通推送及独立远端SHA以交付回执为准；不自动部署或保存跨启动默认数据根。

### 2026-09-22｜[F11] 归档输入与研究草稿只读兼容核对

- 基线main@17435bd，本地与独立远端一致；保留既有共享status修改。代码侧继续F10后的研究衔接，数据治理仍由另一模型负责；本轮不读取/修改正式行情或历史业务_market_data，不调用真实业务模型、采集、实盘或可见客户端，不启停公共服务。
- 合成复现确认原ProposalService.preview对research_only只做配置/预算与资格检查：qfq或包外证券可通过配置预检，但实际F9 Provider拒绝。保留原预检/提案/批准合同，不把新诊断强行加入审批门。新增archived_research_check，按原parse/preview/prepare及F9实际字节读器核对明确spec的主输入、背景和raw执行价格角色，汇总周期/复权/证券/日期及资格或外部依赖阻塞；不改参数、不填样本、不运行因子或返回统计充分性/Alpha证明。
- 普通ChatRuntime/标准MCP同源只读check_archived_daily_research，固定宿主data_root，精确spec_json且不接收任意路径/SQL。valid-but-incompatible为工具ok=true、compatible=false与完整blockers；坏配置/损坏包为ok=false，超响应预算拒绝不裁剪为成功。原QM50规格和Reviewer白名单不扩展。
- F10面板成功显式选择后提供“进入研究提案（不执行）”，打开空的原ProposalDialog，不代选股票、日期、因子、资金或策略。原提案面板新增“核对草稿与归档输入（只读）”，结果含精确输入/草稿身份；与原“仅预检配置与预算”分层，保存和批准继续由宿主明确操作。
- 自测复现关闭但未销毁对话仍接受迟到核对结果，已修复close/reject/generation保护；补数据根和原service上下文检查、调度异常恢复。独立Pi只读复核提出“选择B提案仍显示A草稿输入匹配”，主控构造失败回归后清除旧报告/文案并重新核对；报告对应其记录的修前版本，最终修后验收由主控完成。
- 最终13模块142项通过，0失败/错误/跳过；新增后端16+桌面9共25项，重复执行不累计。5个Qt离屏模块49项、8个后端/接口模块93项；覆盖真实MCP进程内及stdio子进程、锁定规格拒绝、同源策略包核对、F10选择→空提案→检查→人工批准→原队列，及既有提案/冻结/Grant/策略复算。最终6个产品/测试文件指纹前后一致，不等于正式数据已验收或真实模型自主研究已验证。
- 只覆盖F9有限raw/1d/research_only及明确子范围，不证明所有滚动/留出子窗口、因子预热或样本功效；账户/可选后端/外部规则依赖不在检查范围时明确阻塞。Campaign不整包认证，不创建输入副本或新的持久任务状态。结果为观察，不是文件租约，批准与读取仍重验冻结。
- 原始日志、baseline反例、独立报告、修前失败和最终accepted-regression.json在artifacts/input-research-check-20260922；只提交4产品/2新测试/指南/开发史。共享status不整份提交，普通推送及远端SHA以交付回执为准。新文件事务create在Lexar报errno45并确认完整回滚后改用独占创建；一次空insert工具参数被schema拒绝，无文件改动，纠正后按SHA整批应用。

### 2026-09-22｜[F12] 提案任务进度与结果只读回查

- 基线main@9680583，本地/远端开工一致；保留共享status原有修改。用户继续代码线，数据治理由另一模型负责。本轮只读项目源码与隔离合成测试，不访问正式行情/历史业务_market_data，不采集、启停服务、打开可见GUI或调用真实业务模型。
- 原提案面板新增“跟踪选中提案任务与结果（只读）”。固定proposal_id和所选proposal_digest，共享progress投影连接既有ProposalStore、_jobs、approval manifest及结果头部；不建新状态库，不调用JobQueue构造/提交/取消/恢复。提案数据库使用mode=ro/query_only及稳定读事务，复用原row decoder与checksum合同，坏记录明确errors/incomplete。
- 状态区分等待批准、批准未入队、queued/running、cancel_requested、completed/failed/cancelled/interrupted以及缺失/冲突。running仅表示持久日志，不确认进程在线；attempt和stage计数保持原值，不推算总体百分比或ETA。批准事务与队列回执更新间的approved+job可明确展示；submitted缺job显示LOST_JOB，不重建。结果只在任务/提案/冻结清单与结果身份一致时提供链接，点击再读，不把元数据核验当payload深验或数值复算。
- 窗口初次读取一次，默认不持续刷新；显式勾选后5秒最多120次、不叠加请求，终态/错误/关闭/工作空间改变停止。同路径目录被替换也失效。旧提案窗口不能在新output打开回查，配置身份不符拒绝；关闭后迟到结果丢弃、控件恢复。运行中日志变化会明确要求刷新而非合成原子快照。
- 普通Chat/标准MCP同源get_proposal_progress，仅完整proposal UUID；真实MCP进程内和stdio回归，不扩大首轮Reviewer/原始QM50白名单。exact响应保留错误及限制，超预算拒绝，不裁剪为成功；找不到提案时不生成虚假证据引用。
- 主控额外复现并修复冻结manifest在回查末尾变化仍显示成功、旧提案窗口跨output，以及同路径目录置换/结果重复status/提案重复question被默认JSON覆盖的问题。严格JSON只在本投影生效；结果文件限制64MiB，语法校验后只返回头部字段，不认证指标。首次测试因macOS /var临时别名违反路径合同而失败，fixture改用规范真实路径，未放宽产品链接保护。旧catalog测试硬编码6工具，在原HEAD实际13工具上也复现失败，现改为明确14名工具合同和副本/唯一性检查，不删除权限断言。
- Pi独立只读审查run终态cancelled且未产出报告，不计独立PASS；最终由主控源码复核和实际回归验收。原始修前失败、两轮回归及交付证据保存在artifacts/proposal-progress-20260922。提交只包含本轮4产品/2新测试/1旧测试/指南/开发史，不整份提交共享status；普通推送和远端SHA以delivery.json为准。
- 最终12模块137项通过，0失败/错误/跳过；新增后端21+桌面13共34项，重复执行不累计。4个Qt离屏模块47项、8个后端/接口模块90项；包含真实Proposal/JobQueue执行、新进程回查、真实MCP进程内/stdio和旧研究/授权/复算回归。最终7个代码/测试文件指纹稳定；不代表正式数据、真实模型自主研究或全项目已经验收。

### 2026-09-22｜[F13] 旧结果入口回查与异步工作空间一致性

- 基线main@8cc356b，本地与独立远端一致；发现F5–F12已经落地，未重复创建策略目录或进度模块。用户继续功能线；不访问或修改正式niuniu-data/TDX，不运行采集、业务模型、可见窗口或公共服务控制。共享status原有改动保留，不整份纳入提交。
- 旧ProposalDialog.job_status此前仅从get_job取run_id，open_result直接打开旧缓存。现复用已有read_proposal_progress，固定所选提案摘要；每次点击重新关联提案/任务/spec/冻结清单/结果头部，不一致或缺失使旧链接失效。关闭、改草稿/选择以及输出目录路径或实体身份更换均拒绝旧回执，打开策略工作台及返回草稿也复核原宿主空间。仍为头部身份检查，不声称完整数据/归档深验，不修改任务/批准/恢复权限。
- 策略工作台结果对照改用已有统一_archive_read，增加关闭标记、目录身份和回调代际检查；左右run_id改变使旧对照失效，回复需绑定实际两个ID。调度/读取/格式错误清旧结果、恢复控件，不当作空目录或零差。已有目录、详情、改版来源读取共用空间检查。进度面板发现空间失效时同步清除旧明细，不仅禁用打开按钮。
- 新增19项离屏反例/正例：首批15项在原代码13失败+1异常+1通过；另补两个预检/输入核对清链接反例，修前均失败。覆盖真实合成Proposal/JobQueue、无写入哈希对照、延迟回调、关闭未销毁、同路径目录置换、坏任务关联/结果缺失及异常回复。基线数字不是全产品缺陷总数。最终11模块127项及F11输入核对桌面9项，共12模块136项通过，0失败/错误/跳过，源码指纹一致，测试ID去重保存，不累计重复执行。
- 独立Pi报告指出预检/输入核对仅setCurrentRow(-1)无法清除已空选区的旧结果链接，以及测试假回执ID不匹配会掩盖关闭/inode保护退化。前者新增两项失败复现后显式清绑定；后者修正回执为请求原ID，并补正确上下文接受/错误ID拒绝两个控制例。报告对应修前SHA，Run在时限内已落盘报告但最终为cancelled；报告内容已核实和处理，不称独立修后PASS。原始日志、accepted-regression、补充测试及审查证据位于artifacts/result-navigation-20260922；全为TemporaryDirectory合成资料、Qt offscreen和真实既有接口，不等于真实业务模型或可见桌面验收。
- 交付只包含3个产品文件、1个新增测试、使用指南和开发史。普通push当前upstream并独立核对SHA，实际提交/远端状态以交付回执为准。一次编辑请求含空insert被schema拒绝且无写入，纠正后按当前SHA事务应用；未削弱并发编辑保护。

### 2026-09-22｜[F14] 完整策略链与结果详情、导出、恢复和复算验收

- 基线main@f565402、工作区干净；远端dc08122尚缺状态文档提交，本轮普通推送将包含该已检查祖先。用户要求本轮验证、修复和收尾；不读取/修改正式niuniu-data、旧MQC/业务归档，不参与TDX治理、调用真实模型、可见GUI或启停公共服务。
- 新增两条跨层验收，复用F9合成raw输入、真实compile/ProposalService/JobQueue、冻结、进度、目录、历史改版、同口径比较、bundle恢复与新进程复算。检查重复请求/批准不重复任务、改版重新批准且仅直接父引用持久化，子包不自动包含父策略。批准后原capture和输入包离线，真实任务及复算仍使用批准冻结；不是测试替身代跑自主研究或盈利验证。
- ResultDialog仅提取并保护原结果窗口宿主逻辑，复用原record_widget、ReplayWidget、观测与账本，不重写计算引擎。每次异步读写绑定原output/目录/记录及所用伴随文件身份，关闭/空间置换/文件变化拒绝迟到内容；统计文件身份不冒充SHA深验。原观测筛选两项反例修复为清空旧行并使旧请求代际失效。导出/复算在单窗口互斥，文件选择后和排队实际执行前重核，写入后关闭保留实际回执；未知复算状态和来源不符不显示成功。
- export_bundle在发布前核对ZIP内实际序列化字节与清单、源文件及源码稳定性；恢复在最终发布时独占创建目录，不使用可替换同名空目录的rename。中断保留无效目标/restore-incomplete标识，失败不覆盖重试、不删除原归档，也不声称文件系统断电耐久性。
- 修前证据：结果窗口首批11项为5失败/5异常/1通过，其中spy被不应发生的跨空间调用触发类型错误；额外观测两项均失败。独立Pi只读审查提出恢复目录并发覆盖、伴随文件漂移，主控三个反例均复现后修复。报告锁定修前SHA，修后验证由主控执行，不声称独立修后PASS。观测补丁曾被平台拒绝写入，后同一受保护工具以更小的仅清界面行改动完成；未改权限或借其他执行通道写该补丁。
- 初轮广泛回归211项在源码修改期间出现2项待修观测失败和1项批准runtime漂移拒绝；该轮源码不稳定，不作最终验收。导出中断测试的首次mock过宽、worker首次unittest导入路径错误均保留原日志，后修正测试定位而未放宽产品合同。新增3个测试模块28项（结果窗口21、发布/恢复5、端到端2）；最终统计以artifacts/f14-validation-20260922/accepted-regression.json为准，不累计重跑。
- 最终固定源码逐模块独立进程回归23模块218项通过，0失败/错误/跳过，测试ID唯一、6个代码/测试文件指纹一致。含9个Qt离屏模块123项、14个后端/业务模块95项，以及全部新28项；旧Qimo、原助手/Grant/记忆、新进程、可选vnpy_rules与各类复算在相应原测试内通过，不代表所有组合均已验收。Lexar同卷临时目录3场景复跑通过并清理，仅为兼容性补验，不累计为新测试。122份文档与545个本地链接检查通过。
- 交付范围为3个产品文件、3个新增测试与指南/状态/开发史；原始日志和两份Pi报告保留在本轮artifacts，不提交。最终检查源码指纹、文档链接与Git diff，独立commit、普通push后读回远端SHA；准确结果以delivery.json为准，推送不等于自动部署或真实客户端/模型验收。

### 2026-09-22｜[F15] 治理资料只读消费第一批：覆盖、日期轴和公司行动候选

- 基线main@3f65b3a，开工工作区干净；依据上一轮交付复核继续代码侧第一批，不执行治理模型R1–R16全部需求。正式niuniu-data、数据库/视图/指针、治理artifact、产品依赖、采集/业务模型与公共服务均不操作；全部测试使用隔离合成资料和内存函数。没有新的正式复权数据或最终缺陷名单。
- TDX read增加13族date_axis和非事件日期警告，保留原行/顺序/资格；coverage提供COUNT行/不同code/来源、UTC观察时刻、异常计数与逐证券日期分位。资源受限的内存协调连接只读ATTACH，避免与已有普通DuckDB连接配置冲突；不改视图或其他连接设置，不认证源页字节、版本完整性、PIT或连续交易日。
- 新增公司行动候选服务：固定单证券窗口读取TDX catalog、EM/THS Parquet和可选qfq，保留源定位及实际Parquet内容SHA。有限全文方案解析、显式每股基数、未知/税后/差异化分红/缺字段阻断；东财税基未声明，不以null当零。源内独立方案候选合计、重复保留定位、修订冲突不累加；供应商之间不相加，不按票数或吻合率认证真值和血缘。qfq仅已存因子变化诊断，无修正价/重建执行路径。
- 沿原ArchivedMarketDataAPI接3个只读工具，标准MCP和普通Chat自动共享；模型不能传入路径/SQL，不增加首轮Reviewer或锁定原QM50权限。新增只读CLI；原qfq目录/载入检查增加未认证提醒，不改变Provider数值、批准冻结或复算口径。known_issue_list_status保持not_bound，数据侧最终事件清单未交付，不把旧数字硬编码为认证结果。
- 主控两项入口反例首先复现普通DuckDB连接配置冲突及coverage缺日期警告，随后修复。独立Pi报告完成，指出空字段转零/默认税前、公告日使修订误加、qfq错code等问题；主控修复并新增内存语义测试。第四项关于TDX原页未核验，保留明确catalog_rows_only和candidate_not_adjudicated边界，不把候选agreement声称最终一致性；本轮不扩展为正式原始页审计。报告对应修前代码，修后回归由主控完成，不声称独立修后PASS。
- 两个实现Pi Run在时限内结束为cancelled，留下代码但没有完整交付报告；主控继续接管、阅读、修复和验证，不把中间实现当验收。新增测试分别为覆盖7、公司行动15、入口13，共35。首轮入口3项因macOS /var临时目录别名被正确拒绝，修复测试夹具为真实路径，未放宽产品路径规则；专项复跑35/35通过。一个补充测试文件创建请求被平台拦截且未落地，未将其计入测试；后续用普通受保护工具完成独立的内存语义测试与小范围夹具修正，未借其他远程通道。
- 最终固定源码逐模块回归14模块162项通过，0失败/错误/跳过，测试ID去重，全部产品源码及受测测试文件指纹稳定；新增35项已包含其中。包含真实MCP进程内/stdio、脚本化模型通过正式ChatRuntime工具、原TDX留存、旧数据读取、锁定QM50、有限Grant、提案批准、策略归档复算及F14跨层流程。不能据此认证正式数据质量、大库性能、真实业务模型或全项目正确。文档检查122份/545本地链接通过。
- 验收日志、独立审查和交付回执在artifacts/governance-consumption-20260922；最终统计以accepted-regression.json为准，不重复累计。仅本批产品/测试/指南/状态/开发史进入独立提交；普通push并独立核对远端SHA，不自动部署。剩余R3、R7/R8增量、最终缺陷清单与R12/R13发布前重建继续按纠正后的合同处理，R16采集不在授权内。

### 2026-09-22｜[F16] 显式日历、完整日期差集与MCP参数合同

- 基线main@6ea3eb0，工作区干净。用户要求计划后直接执行；本轮限定R7/R8有界代码消费，不读写正式数据或治理产物，不采集、不重建qfq、不启动可见客户端/真实模型，不启停公共服务。
- session_coverage抽出calendar_window，沿原calendar_sessions严格自然日覆盖检查返回全部缺日及规范摘要；有效旧接口行为保留，非规范日期明确拒绝。新增calendar_review固定三类来源：bronze、精确retro capture、已有F9包；参考内容/文件/规范化摘要分开，禁止换源补洞、默认日历或越过已冻结范围。F9/retro复用现有真实字节读取与校验，不造第二套导出/回测引擎。
- 逐证券日期核对保留全部missing/unexpected/duplicate集合，期望范围与明确上市/退市闭区间相交；缺生命周期不假定在市，停牌/未知状态与日期存在分列。complete仅日期存在，F9兼容/行情值/可交易/PIT均未认证。CLI及Chat/MCP读同一服务；初轮18项源码测试通过，后追加完整缺日列表和明确多日历选择两项。
- 入口初轮8项出现1项异常：SDK会丢弃多余path后正常查询，直接API却拒绝。只读复现确认未换读路径，但调用合同不一致。新增ContractMCPServer在SDK解析前验证宿主required/additionalProperties并公布闭合schema，不改SDK文件或工具权限；补前置拒绝及进程内/stdio回归。此前实际查询是正常宿主路径，不宣称发生越权读取。
- 独立Pi只读复核已完成，范围内未发现阻断性缺陷；它未覆盖随后新增MCP适配修复和source_calendar_content_hash展示，修后验证由主控完成，不声称独立全仓或修后PASS。新文件事务创建首次因Lexar文件系统os error45回滚，确认文件不存在后用本机结构化进程exclusive create，现有文件继续SHA保护编辑；无权限放宽或更换远程系统。
- 最终固定源码按模块独立进程回归21模块224项全部通过，0失败/错误/跳过，测试ID无重复，全部产品Python文件及所测模块指纹前后一致。新增后端20项、入口9项共29项，含真实MCP进程内/stdio、脚本化模型经正式ChatRuntime、CLI同源、显式多日历、完整差集、旧日历/retro尾部/F9/原QM50/Grant/提案/策略复算/F14链路；不是正式行情质量、全市场覆盖、真实模型或可见客户端验收。122份文档/545个本地链接检查通过。
- 原始日志、复核和最终回执位于artifacts/calendar-review-20260922/；accepted-regression.json固定测试ID与源码摘要，delivery.json固定提交、文件匹配与远端结果。仅本轮6个产品文件、2个新测试和3份说明独立提交，普通推送后核对远端，不自动部署；复权重建、未定R3版本合同、正式数据治理及R16采集未执行。

### 2026-09-22｜[F17] 配股候选交付的版本绑定与只读查询

- 基线main@21577e6且工作区干净。用户要求继续代码并给数据侧下一步，限定已接受候选资料的只读消费。只核对对方交付CSV/摘要两份artifact，不重跑治理生成器，不访问正式niuniu-data/数据库/指针，不抓取、调用真实模型、开可见GUI或启停公共服务。数据侧转入独立追加的事件取证，接受版不再重复返工。
- 新增rights_candidates：宿主显式绝对文件路径和双SHA绑定，摘要必须引用CSV实际SHA；每次 bounded read/recheck，不缓存旧成功。全表CSV结构、配股键唯一、来源字段分类与Decimal候选公式对照，独立核对互斥计数/摘要。只有已知其它事件类可旁置并明确not_evaluated；没有全市场完整/官方/因子未变认证。
- get_rights_candidate_manifest/query_rights_candidates沿原ArchivedMarketDataAPI供普通Chat和MCP共享；CLI rights-manifest/rights-query同源，MCP支持四个宿主绑定参数，ChatRuntime可显式注入绑定。未配置不猜文件、不默认绑定artifacts；未增加GUI绑定或长期配置。按证券日期分桶分页仍带全包未决数；原文与数据侧标签不作为授权，空结果不作为没有缺口的证据。不自动选源、不运行修正因子，不改旧Provider、F9/Grant/审批/复算。
- 初始25后端+10入口测试通过；有界独立Pi只读审查完成，发现未知事件类可漏掉、未参与公式的数字列漏检、超长单行无法通过limit=1取回。主控构造三个反例（review-counterexamples-before.json）后修复：明确兄弟类且拒绝带配股字段的伪装，所有数字声明非有限值拒绝，新增24KiB单行预算使不支持的输入在整包校验时明确失败、不默默裁剪。补5项测试，独立报告只覆盖其记录的修前SHA，修后回归由主控完成。
- 实际交付第一次只读smoke验证878行746/88/19/25，sh.600626只在conflicts，两个源artifact字节及mtime未变；不是正式行情或公告验收。最终受影响模块回归与修后同一smoke继续按accepted-regression.json、handoff-smoke-final.json记录；不把固定CSV身份当上游真值认证。
- 最终固定源码逐模块独立进程回归14模块148项，0失败/错误/跳过；新增29后端+11入口共40项，ID去重且全部产品/受测文件SHA前后一致。包含真实MCP进程内/stdio重开、脚本化模型走正式ChatRuntime、旧F15/F16/规格/Grant/提案/策略复算及F14。修后实际交付全量分页只读878个唯一事件通过，桶与已验收版一致，两个源文件字节及mtime不变；不等于完整重建或真实助手研究验收。
- 原始测试、复核、反例、数据侧下一步说明与交付回执存放artifacts/rights-candidate-consumption-20260922/。仅本轮5个产品文件、2个新测试及3份现有文档纳入独立提交，普通推送后核对远端；无自动部署。正式重建、待决事件来源选择和F9停牌新合同仍为后续范围。

### 2026-09-22｜[数据侧S1] 19条未决配股事件的本地证据包

- 基线main@20fc254、工作区干净。按任务书第一优先级执行：父交付artifacts/data-governance-20260922-D1D3的per-event-status.csv与rights-final-v2.json双SHA逐字节核验一致后原样保留，新结论全部写入独立补充目录artifacts/data-governance-20260922-S1-rights19。本轮不采集、不联网、不改正式niuniu-data或数据库、不发布复权因子，父CSV的final_status=NEEDS_DECISION保持不变。
- 对象为父CSV中event_class=rights_issue_missing且final_status=NEEDS_DECISION的19条，与父摘要buckets.conflicts=19一致；处理顺序按任务书指定，先sh.600626/1993-06-21的零值与槽位疑问，再sh.600624、sh.600633、sh.600628、sh.600820的股份基数线索。只读取本地既有资料：巨潮配股Parquet的15个字段、tdx_capital_changes除权日±60日全部15个类目、EM/THS股息库覆盖情况。
- 三个可复核判据全部不使用价格。判据一以TDX股本变动扣除c3蕴含送转量求出不含任何巨潮数字的配股量：10/19可求出，其中8条与巨潮实际配股数量相对差<1e-4，2条（sh.600601、sh.600686）不一致；其余9条在−5~+20日窗口内无TDX股本变动记录。判据二只比较两家各自上报的配股前总股本之比与(1+c3/10)，得一致6条、恰好相差送转因子4条、缺一侧上报值9条；该判据不使用任何比例数字，因此不触犯禁止的乘1.1推理。判据三的蕴含基数分子取自巨潮实际配股数量，已在交付中明确标注其非完全独立。
- 争点定位显示分歧集中且互斥：仅比例分歧11条、仅配股价分歧6条、TDX配股价槽为0导致不可比1条、两者皆分歧1条；阈值1e-4，TDX价格为float32的约1e-8差异记为表示误差而非分歧。sh.600626两家配股比例同为6.0，争议仅在价格槽，其TDX派息2.5与巨潮配股价2.5数值相同但本轮未据此交换槽位。
- 19条verdict全部为UNRESOLVED，摘要中adjudications_made=0、price_evidence_used=false、parent_files_modified=false。逐条给出缺什么证据，主要缺口为配股说明书/实施公告原文的配股基准股本口径、分股东类别实配拆分、方案修订序列。独立股息旁证只覆盖5/19，EM与THS股息库最早止于1993年报（实施于1994年），1992–1993年除权事件在本地无任何独立股息旁证。巨潮自身存在缺陷：多条配股前流通股本报0，sh.600633与sz.000513的配股后减配股前不等于实际配股数量，均已记入缺证据项而非静默采用。
- 同时发现父CSV首列带UTF-8 BOM（表头第0列实为﻿event_class）且ths_raw列含内嵌换行，须用utf-8-sig读取且不能按行切分，已写入交付供代码侧解析参考。parent_event_digest定义为该行各字段按表头顺序用csv.writer(lineterminator="\n")规范化重序列化后的UTF-8文本sha256，代码侧可复现；action_or_plan_id一律为显式unknown，因巨潮stock_allotment_cninfo与tdx_capital_changes均不返回方案编号。
- 交付为README、S1-19条未决配股事件证据包.md、evidence下JSONL/CSV/确定性摘要与logs下两个只读脚本，摘要不含墙钟时间并以summarises_jsonl_sha256绑定JSONL；采集器连续两次重跑JSONL的SHA稳定为a34c869d…。artifacts/在.gitignore内不进版本库，本次提交仅含本条开发史。不认证供应商正确性、上游独立性、历史可得时点或因子完整性，也未裁决任何一条事件。

### 2026-09-22｜[F18] 有界候选重建预览及来源草案

- 基线main@20fc254，开工工作区干净。用户要求继续代码维护；只推进F17绑定候选的纯预览，不访问正式niuniu-data，不改治理材料/指针，不采集、安装依赖、真实模型研究、可见GUI或启停公共服务。
- rights_rebuild_preview复用F17完整校验快照：固定bundle_id与证券日期范围，自动枚举全部列内配股事件（不允许status/page/exclude）；有界20事件、10证券、3660日、32KiB请求。每项来源草案须精确event_digest，成对选择配股价/比例，派息/送转和交付前收来源明确；未知/冲突即使已选源仍blocked，不支持人工裁决伪字段或覆盖数值。
- 预览只计算每事件候选参考价/因子比/理论raw百分数，40位固定Decimal输出字符串，不累计因子、不生成价格/归一化曲线，不写任何候选状态、任务、因子或批准。scope_digest与preview_digest固定完整范围和来源；ready_for_review不构成官方/完整历史/PIT或执行许可。get_rights_rebuild_contract/preview_rights_rebuild沿现有Chat/MCP，CLI新增rights-preview-contract/rights-preview并区分0/3/2退出码；未新增桌面绑定或默认部署。
- 初轮30项后端、10项入口测试通过，包含缺项、重复、陈旧身份、来源差异、未决不可绕过、空范围、全部20事件输出、真实MCP/stdio重开、脚本化模型经ChatRuntime及原QM50/Reviewer边界。独立Pi只读复核完成，覆盖5个产品文件和2个新增测试的同一源码SHA，未发现范围内可利用绕过或权限扩大；它未运行测试或核验原始市场材料，不等于全仓或官方事件认证。
- Lexar新文件事务创建遇到os error45并完整回滚；核实文件不存在后改用结构化Python exclusive create，新文件未覆盖任何已有改动；其余编辑继续使用SHA保护。共享changelog被数据侧S1并行追加并独立提交为b78cdd2，SHA冲突拒绝了旧编辑；重新读取后保留对方提交，仅追加本轮内容。过程、审查和回归证据保存在artifacts/rights-rebuild-preview-20260922/。
- 最终固定源码逐模块独立进程回归16模块188项，0失败/错误/跳过，新增40项包含在总数内；测试ID去重，全部产品Python及受测文件SHA前后一致。涵盖F17、F15/F16入口、原Chat/MCP、QM50、Grant、提案及策略复算/F14链路；accepted-regression.json保留真实ID和明细，不是可见客户端或真实模型自主研究验收。
- 仅对已接受的候选CSV/摘要做正式服务只读smoke：sh.600626零值冲突及sz.000759未匹配事件，分别提出TDX/巨潮假设仍blocked；sz.000589小差异两套假设各得独立ready_for_review预览，但未选择赢家或保存裁决。3事件×2假设不重复计入单元测试数；两个候选文件字节与mtime不变，未访问正式行情根。记录见handoff-preview-smoke.json。
- 仅本轮5个产品文件、2个新测试、3份现有文档纳入独立提交；提交前后按to-be-committed.json和delivery.json核对验证文件、普通推送及远端SHA。数据侧b78cdd2的S1记录保留为既有祖先，未将新S1证据自动接入裁决。F9停牌合同、持续因子曲线、实际重建发布仍是后续独立范围。

### 2026-09-22｜[数据侧S2] 采集脚本整改并入版本库

- 用户明确"数据采集都应该写成脚本，助手只监控脚本运行"，随后要求检查并整改现有采集脚本。清点 artifacts/data-governance-20260922-D1D3/logs/ 下 47 个 .py，真正触网的只有 5 个：ths-collect.py、ths-pilot.py、cninfo-collect.py、cninfo-pilot.py、d4-min5-backfill.py，其余为离线分析一次性脚本。全部位于 .gitignore 的 artifacts/ 内，代码维护侧无法复核。
- 结构性结论：baostock 采集产品 CLI 已有 fetch-bars/fetch-status/fetch-reference/dividend-import，d4-min5-backfill.py 属重复实现，标注应改用产品 CLI，本轮不迁移其逻辑；akshare 下的同花顺分红与巨潮配股则在产品内无任何入口，确属新增能力，故整改为版本库内的 scripts/collect/。
- 新增 scripts/collect/envelope.py 共用采集信封：目标目录非空即拒绝（除非显式 --resume）、--dry-run 不发起任何供应商请求、临时文件加 os.replace 原子写入、逐符号回读校验行数与列名、ok/empty/failed/schema_issue 四态分明（失败不写文件，空结果写零行文件）、运行前后按列签名分组稽核并写入回执 column_signatures/schema_is_uniform。退出码 0/1/2 分别对应成功、有失败、拒绝执行。
- 新增 scripts/collect/universe.py，清单只能来自具名预设或 --universe 显式文件。旧 cninfo 脚本清单取自分析产物 d4/rights-issue-adjustment-gaps.csv，是其比目标总体少 114 只的根因；预设 tdx-rights 由 TDX 除权除息 c4>0 解析得 706 只，stocks 由 baostock stock_basic type=1 得 5552 只，并显式声明退市股仅 337 只、1990 年代摘牌标的多半不在内这一已知局限。
- ths_dividend.py 取代 ths-collect.py/ths-pilot.py：去掉全表 astype(str)（旧版把缺失值写成字符串 'nan'），改为仅对 parquet 写不下的列逐列降级并在回执 coerced_to_string 点名；schema_issue 证券不再是既无文件也不进失败名单的黑洞。cninfo_allotment.py 取代 cninfo-collect.py/cninfo-pilot.py：删除 15 列 KEEP 白名单投影，原样保留供应商全部列，REQUIRED 仅作存在性门槛；回执不再错写进 ths/ 目录；去掉 python -O 下会被优化掉的裸 assert。
- 新增 tests/test_collect_envelope.py 共 15 项，注入假 fetcher，全程离线、只写临时目录，覆盖非空拒绝先于任何请求发生、dry-run 零请求零写入、四态互不混淆、重试次数、全列保留与数值 dtype 保持、续采跳过已校验文件且已有文件 SHA 不变、续采重采损坏文件、混合列签名被标记、fail-fast、limit 与路径分隔符拒绝。本机 .venv 全部通过，用时 0.2s；scripts/check_docs.py 122 文档 545 本地链接 PASS 0 错误。
- 仅以 --dry-run 对真实湖目录做只读计划核对，未发起任何采集：cninfo 目标目录无 --resume 时按预期拒绝执行；加 --resume 后精确报出 114 只缺口，与此前诊断的口径缺陷数一致。列签名稽核当场查出既有 592 个文件并非同一 schema——588 个 16 列、4 个 15 列（旧脚本写空结果用 pd.DataFrame(columns=KEEP) 漏掉 plan_symbol），且 16 列版已丢弃供应商另约 40 列，其中含停牌起始日、缴款日期、大股东认购数量等判定 19 条未决配股事件所需证据。因此明确记录：该目录不得用 --resume 补齐，正确做法是全宽采到新目录重来，由代码维护侧决定指针替换。核实运行后真实湖内未产生 _receipts 或 .tmp 文件。
- 本轮不运行任何采集，真正发起采集仍需用户单独授权。artifacts/.../logs/README.md 已把四个旧采集器标注 ⛔ 作废并写明各自缺陷，指向 scripts/collect/README.md。提交只纳入 scripts/collect/ 与 tests/test_collect_envelope.py；同时段 src/quantlab/ 下 5 个文件与 rights_conflict_evidence.py 属代码维护侧并行未提交工作，未暂存、未改动。

### 2026-09-22｜[数据侧S3] 缺口感知增量采集与逐次授权闸门

- 用户进一步明确：采集脚本须自行判断缺失证券与缺失交易日，例如历史止于9月20日而当前为9月22日时，只补交易日范围；退市股不处理；先展示缺口规模，每次真实采集仍须单独授权。S2所称“baostock产品CLI已有采集、无需再写调度”过宽：现有CLI能按显式证券/日期取数，但没有全市场覆盖扫描、缺口计划与授权范围绑定，本轮补齐这层而不替换旧Provider。
- 新增coverage.py与scan_gaps.py。交易日使用既有只读baostock归档日历（13,070行，1990-12-19至2026-09-30）；本地TDX日线实际不含sh.000001/sz.399001等指数行情，故不伪造“指数已验证”结论。证券总体固定为stock_basic中type=1且status=1的5,215只在市A股，退市文件只统计为排除项、不采集。扫描同时识别整只未采full与末尾落后tail；5分钟目标末日不足48根时列refresh_last；中间无bar日期可能是停牌，仅报告、不自动补。2020-01-02前的5分钟供应商硬边界单列，不反复重试。
- 默认目标日期按北京时间判断：交易日18:00前追至上一交易日，18:00后含当日。计划JSON无墙钟时间，绑定日历与stock_basic SHA、每个既有文件SHA、证券和日期区间，并生成确定性plan_sha256；--limit可以先形成有限计划供人审阅。真实只读扫描在2026-09-22 18:00后得：日线5,215只全部末日落后，统一目标2026-09-22，典型区间2026-09-04..09-22共13个交易日；5分钟5,215只全部末日落后，最长样本2026-08-28..09-22共18个交易日。该结果只说明本地覆盖落后，不是采集授权。
- 新增bars_incremental.py，只消费已审阅计划。真实运行必须同时给--apply、--plan和与计划完全一致的--approve-sha256；计划被改、日历/证券表改变、既有目标文件SHA变化、路径越界或动作重复均在供应商登录前拒绝。每只写入前备份并核SHA，供应商返回不得越过批准日期；按返回日期整日替换后校验schema和主键，临时parquet回读通过才原子替换。未加--apply时仅打印计划，不初始化供应商或写长期库。
- 同花顺与巨潮脚本也改成默认只展示计划，必须显式--apply才构造真实fetcher；默认清单分别改为stocks-listed与tdx-rights-listed（后者实际644只），退市股排除。历史tdx-rights仍保留为显式可选项，不再作为默认。
- 新增tests/test_collect_gaps.py并扩充采集信封测试，合计27项离线回归通过：周末过滤、18:00截止、退市排除、full/tail/refresh_last、供应商硬边界、计划确定性和限额哈希、无授权零请求、防篡改、防陈旧文件、整日替换及既有15项信封行为。真实湖只运行只读扫描与无--apply审阅模式；未登录供应商、未发请求、未创建回执/备份/临时文件、未修改任何行情或公司行动数据。


### 2026-09-22｜[F19] 未决配股补充证据只读消费

- 在 F17/F18 上增加宿主显式绑定的 S1 补充证据层：JSONL+summary 双文件/双SHA，每次读取重核字节；summary 必须绑定 JSONL 及父 F17 CSV/summary，19 条事件必须与父候选 conflicts 全集一一对应，parent_event_digest 按父CSV字段顺序规范化重序列化后复算。
- 新增 rights_conflict_evidence 只读读取器，以及 Chat/MCP/CLI 的 get_rights_conflict_evidence_manifest / query_rights_conflict_evidence。模型工具无 path/hash/approve/execute 参数；未配置 fail closed；Reviewer 和 QM50 锁定会话不扩权限。S1 文本一律按不可信来源声明处理。
- F18 在宿主额外绑定 S1 时仅给 conflict 事件附加 supplemental_evidence；EVENT_REQUIRES_SEPARATE_ADJUDICATION 永久保留，calculation 仍为 null，reconstruction_authorized/publication_authorized 仍 false。未绑定 S1 时 F18 保持原输出结构。
- 实际 S1 只读 smoke 验证 19/19 verdict=UNRESOLVED、adjudications_made=0、price_evidence_used=false；sh.600626/1993-06-21 即使显式提出 TDX 来源仍 blocked，父候选与 S1 四个文件内容 SHA/mtime 未变化。未读取正式行情/公告、未执行治理脚本或写数据。
- 首轮独立只读复核未发现权限绕过，但指出两项非阻断正确性问题：参与汇总的 diagnostics 非空值可被 bool/string 伪装，以及查询接受无连字符 ISO 日期。已改为有限 int/float（排除 bool）或 null，并严格 YYYY-MM-DD，补反例回归。
- 修后专项配股链 101 项通过；联合回归 19 模块 209 项全部通过，0 失败/错误。覆盖 F17/F18/F19、Chat/MCP、日历/治理工具、QM50权限、Grant、审批、策略包复算和 F14 生命周期。第二轮独立只读复核对 R1/R2 修复返回 PASS，并确认 S1 仍不解除 conflict blocker、calculation 仍 null、重建/发布权限仍 false；不是官方公司行动认证、真实模型自主研究或正式因子发布验收。
- 本轮只提交 F19 的 6 个产品文件、2 个新增测试和 3 份现有文档；并行数据侧 S2/S3 提交均作为现有祖先保留，没有把采集逻辑纳入 F19。

### 2026-09-22｜[F20] F9 停牌状态输入合同 v2

- 保留原 `tradable_only_v1` 默认行为：请求中出现 `tradestatus!=1` 仍拒绝，旧v1包的format/request/summary与冻结snapshot算法不迁移。新增显式 `preserve_suspension_state_v2`，CLI与桌面均需主动选择；合同进入preview hash、manifest、dataset_id和normalized bars的 `input_contract`，切换合同清除旧预检。
- v2保留完整证券×session网格和raw/typed源字节；停牌行保留 `bs_trade_status=0`，OHLC必须null，volume/turnover仅接受来源null或有限非负值，`vendor_previous_close`必须有限正数但只作估值证据，不生成K线或成交价。缺/混合合同、未知状态或缺估值参考fail-closed；没有v2 `input_contract` 的旧数据继续走原OHLCV验证。
- 研究侧仅对显式v2启用状态mask：停牌session不删行，当日强制ineligible，shift/horizon仍基于完整session网格，落在停牌价格端点的forward label为null；不forward-fill、不将复牌价压缩成下一行。v1研究身份不新增停牌policy字段。
- 执行侧把成交price与valuation mark分开：停牌证券不进入open价格表，目标变化记录 `vendor_suspended` 且0 fill；持仓优先沿用最后真实可交易close，无历史mark时才可用vendor_previous_close估值。`vnpy_open`明确拒绝含停牌v2行；open/vnpy_rules继续走显式状态路径。
- 独立Reviewer指出停牌除权日若沿用除权前mark同时计应收现金/送股会重复估值，已改为持仓在停牌除权现金/送股时要求显式post-action valuation，缺失直接阻断；股票拆分等原有缺真实估值bar路径继续fail-closed，不从preclose推导除权后fill。
- 批准冻结对v2的DataSnapshot身份新增冻结parquet SHA、原source snapshot_id和input_contract；冻结file evidence也保留input_contract。相同请求的v1/v2或不同冻结字节不能共享snapshot_id；v1无contract时沿用旧身份算法。验证了批准后源包离线仍从冻结字节运行并numerically_matched复算。
- 新增 `tests/test_archived_suspension_contract.py` 8项并扩桌面1项，共新增9项；新增的第8项固定 `vnpy_open` 对保留停牌行必须明确拒绝。提交后按不重复测试用例统计：F20/公司行动26项PASS；F9/桌面/审批冻结组48项中47项直接PASS，唯一旧v1冻结生命周期因组合压力等待超时后单独PASS；纸面账户与限价37项PASS；执行/研究复算轻量9项PASS；`native_vnpy_rules_reproduction` 慢单项独立PASS；策略包/F14/提案/日历40项PASS，合计161项明确PASS。既有 `test_parent_studies_rebuild_all_descendants_and_training_pipeline` 单独运行超过300秒被超时终止，期间无断言失败，未计入通过数；更早的大组资源争用/超时也不作为验收证据。
- 本轮不读取或修改正式行情、TDX、治理产物、数据库或指针，不执行采集，不扩大研究/交易授权，不启动真实模型或可见GUI；并行 `scripts/collect/*` 数据侧改动保持独立，不纳入F20提交。

### 2026-09-23｜[数据侧S4] 在市A股全量基线采集与独立交验

- 用户逐批授权后，版本化脚本在后台完成全部已定义核心采集；总体固定为Baostock `stock_basic` 中 `type=1 AND status=1` 的5,215只当前在市A股，退市股排除。日K和5分钟目标为2026-09-22；公司行动写同花顺/巨潮/Baostock独立v2目录，参考数据写不可变日期批次。没有续写旧混合目录、刷新catalog、切换Provider/产品指针、裁决公司行动或发布复权因子。
- 日K最终17,137,682行、5分钟363,380,939行、日状态/ST 17,137,823行，各5,215文件且单一schema；三个主键分别为`(code,date)`、`(code,date,time)`、`(code,date)`，全量相邻键扫描均0重复/0空值。目标日5,202只交易、13只停牌；5分钟目标日每只精确48根。日K/5分钟复扫仍列13条tail，但状态表逐只证明最后行情之后全部为`tradestatus=0`、无任何交易状态行，不能再作为普通采集失败重试。
- 行情运行期两次暴露Baostock底层解析卡死，进程内`SIGALRM`不能可靠中断；改为可杀并重启的provider worker、请求硬超时和逐证券原子回执。停牌空值不填零，全区间停牌显式记`suspended`。10,427个行情备份及各证券最后成功目标文件SHA256全部复核一致。历史bronze仍保留供应商早期停牌表示，完整状态中473,485条停牌；消费者必须连接状态表，不能把“有K线行”直接视为可交易。
- 公司行动完成：同花顺5,209有数据+6个HTTP 200正确证券页面零表证据，146,457行；巨潮639+5，988行、58列且`记录标识`唯一；Baostock分红5,090+125，50,210行、15列。旧零行占位Parquet共130个均先备份核SHA再迁为`_empty/*.json`，覆盖总体无缺失/额外/重叠。同花顺保留5,028个`分红总额`和181个`AH分红总额`的具名12列变体；Baostock分红保留83条供应商精确重复，未在bronze层静默删除，正式事件层须另定可追溯去重合同。
- 新增`baostock_reference_snapshot.py`、`baostock_dividend.py`、`baostock_daily_status.py`及`migrate_empty_parquet.py`；通用信封增加持久检查点、空结果marker及页面证据，THS仅在HTTP 200、标题代码匹配且0表时分类empty。参考快照7/7成功：日历13,062、证券8,971、行业5,555、全市场7,393、上证50/沪深300/中证500分别50/300/500，manifest文件SHA全部复核一致。
- 采集专项离线回归最终40项通过；真实数据另做文件数、行数、schema、证券身份、主键、目标日48根、空marker、迁移备份、行情备份和manifest SHA交验，不能以单元测试替代。本次真实结果与限制归档于[2026-09-22/23 全量数据采集与交验](../archive/data-evidence/20260923-全量数据采集与交验.md)。行情扫描/计划SHA/逐次批准可每日重复，参考快照可按日期重建；公司行动与状态脚本当前仍是全量基线/中断续采，不冒充每日事件修订维护器或Strict PIT。
- 提交仅纳入本批`scripts/collect`、两份采集测试和文档；并行`src/quantlab/agent/*`、`src/quantlab/data/version_ledger.py`不纳入。普通push及远端SHA以本条所在提交为准，不自动部署或变更正式数据指针。

### 2026-09-23｜[数据侧S5] 每日智能重复计划与独立批准脚本

- 用户要求将全量基线脚本改为每日智能重复使用。本轮只改版本化脚本、离线测试和说明，实际执行**仅只读扫描与计划生成**；没有启动新的供应商采集、修改bronze、catalog/Provider、正式公司行动或复权发布。保留S4按原旧`stock_basic`定义的5,215只历史验收，不覆盖回执。
- 新增`daily_plan.py`两阶段只读编排：当日参考快照缺失时只生成其不可变计划；完成且七文件SHA复核后，分别生成行情、状态、三家公司行动计划与独立SHA。总索引不构成一揽子批准，真实采集仍逐计划要求`--apply --plan --approve-sha256`（参考快照按原脚本的日期/目录/审批SHA合同）。截止日遵守北京时间18:00，旧日历不伪装成今日覆盖。
- `scan_gaps.py`改为选择不晚于目标日的最新已完成、manifest与原文件SHA一致的参考日历和证券快照；`bars_incremental.py`联网前复核所选快照未变化。状态表逐交易日证明尾部全为停牌时列`suspended_tail`、绑定状态Parquet SHA，不再生成重复采集动作；内部缺日仍不自动补。`status_incremental.py`自动识别全缺证券和尾部交易日，完整交易日校验、旧文件备份/原子更新/逐证券回执，内部缺日单列；失败按原批准计划显式续跑，不补空价或生成假交易。
- `corporate_actions_daily.py`对同花顺与巨潮每日重新请求全供应商历史、对Baostock分红默认重查近3个报告年（可显式放宽至60），按全字段顺序无关且保留重复的摘要判断unchanged/new/updated/empty/failed。已存在事件不能被供应商临时空响应擦除；变化先备份旧字节和空marker再原子替换，逐证券观察时间、响应摘要及可续跑回执，未变化文件保持原SHA。Baostock超出回看窗口的早年修订仍为已知未覆盖；不在bronze自动裁决、去重或发布。
- 只读真实扫描发现2026-09-22已完成参考快照的在市总体为**5,222**，较S4所用旧`stock_basic`多7只（均有9月IPO日期）。在新总体下，日K、5分钟及状态各有7只`full`待采，另13只状态证据支持`suspended_tail`；并没有补采或宣称新总体完成。2026-09-23当日参考快照尚未采集，`artifacts/data-collection-plans-20260923-daily/index.json`只给出`reference_required`及参考计划SHA `c1417216e991836b16a5d094c640fc0d94dcd486dcb9c4a02e2eab66becae230`，不联网。
- 离线采集专项最终58项通过；文档链接检查与Git差异检查以提交前实跑为准。本批不做真实每日运行成功、历史修订检出率、PIT或客户端验收。仅提交`scripts/collect`、三份采集测试和相应文档；并行`src/quantlab`/version_ledger改动不纳入。普通push并核对远端SHA后记录实际状态。

### 2026-09-23｜[F21] 通用 Observation / Revision / Event 版本合同

- 新增 `src/quantlab/data/version_ledger.py` 与 `niuniu-observation-version-ledger-v1`，把经济事件 `event_id`、来源修订 `revision_id`、内容 `content_hash`、抓取观察 `observation_id` 四个身份拆开。重复抓取相同修订只增加 observation；同 revision key 若内容或 publication/effective/supersedes 等修订级元数据不一致直接拒绝，避免把来源修订误计成多个经济事件。
- 同一 event/source 的 `supersedes_revision_id` 只允许线性链；缺父、跨 event/source、自环/环、同父分叉、子修订首次观察早于父修订均 fail-closed。跨来源始终是平行证据，不自动 merge/SUM/vote/择优。summary 的 records/events/revisions/sources、策略和限制全部从 JSONL 重算，不信任自报统计。
- 宿主以 JSONL + summary + 双 SHA256 显式绑定。逐行闭合字段、重复 JSON key、NaN/Infinity、超预算、错误 hash、读取中变更和用户 symlink 均拒绝；兼容 macOS 固定 `/tmp`/`/var` 系统别名。`observed_at/published_at` 要求 aware canonical ISO8601，publication 不得晚于 observation，effective 必须为 canonical date/aware timestamp。
- 版本选择只允许 `explicit_revision_v1` 与 `latest_observed_revision_as_of_v1`。后者必须显式 `as_of`，只在同 source 且 `observed_at <= as_of` 的修订链中选唯一 tail；没有当时版本或存在断开的多根/歧义则 blocked，不回退到当前最新。返回 `ready_for_review` 仅表示该版本唯一，`official_verified/strict_pit/merge/reconstruction/publication` 均固定 false。
- 接入普通 Chat/MCP/CLI 的 `get_version_ledger_manifest`、`query_version_ledger`、`get_version_selection_contract`、`preview_version_selection`。模型 schema 无 path/hash/approve/execute，未配置不扫描目录；QM50 宿主绑定规格和 Peer Reviewer 不获得 F21 工具。event_key/payload 标记为不可信来源数据，不能作为命令或授权。F17–F20 不自动消费账本，不改变配股状态或重建 blocker。
- 新增 `tests/test_version_ledger.py` 与 `tests/test_version_ledger_tools.py`，修后专项 23/23 通过（含 direct API、CLI、正式 Chat、MCP in-process + stdio、重复观察、修订链/as_of、跨来源、路径/hash/mutation/预算、QM50/Reviewer 权限）。相关回归另确认旧候选核心29项、相关非stdio/权限链93个真实用例、标准 MCP/归档集成9项；大组里出现的旧 MCP stdio 初始化超时与 AgentMemory Git 状态错误均按单项/小组复核，不作为 F21 功能失败。未访问正式数据、未采集、未执行重建/发布。

### 2026-09-23｜[路线治理] F22–F27 CODE / DATA 双轨责任边界

- 用户重新确认此前既定顺序：F21统一版本/修订选择合同 → F22公司行动正式人工决策包 → 等待数据侧19条/88条进一步证据 → F23 candidate factor/qfq重建 → F24影响审计+publish gate+rollback → F25 Auction版本/单位治理 → F26 Strict PIT Universe/状态/规则正式化 → F27治理后真实AI自主研究最终验收。本条只澄清owner和gate，不宣称F22–F27已实现。
- 责任边界正式拆开：DATA负责采集、证据闭合、规范化、candidate factor/qfq重建、影响审计、publish/rollback、Auction治理和Strict PIT正式数据；CODE负责闭合合同、身份/SHA/父引用校验、只读查询/消费、人工决策入口和fail-closed权限边界；HUMAN负责公司行动来源/版本裁决及正式发布批准。Research Agent/Chat/MCP不得从“可读取”推导出重建或发布权限。
- F22为三方协作：数据侧准备按F21 `event_id/source_id/revision_id`绑定的证据与缺口，人作正式决定，代码侧只保存/校验可审计决策包。19条conflict已由S1证明19/19 UNRESOLVED，继续作为F22 blocker；既有878条的`746/88/19/25`桶保持父治理语义，88条不由代码文档重命名，数据侧只需确认其中哪些仍缺证据且会影响F23。
- F23/F24明确为DATA主责：F23生成candidate factor timeline、candidate qfq、rebuild manifest/lineage和current-vs-candidate差异，但不覆盖正式版本；F24负责影响审计、人工publish gate、active pointer/receipt和可验证rollback。CODE最多增加只读consumer/verifier，产品运行时不得扫描bronze、自动择源、运行全库qfq重建、切正式指针、publish或rollback。
- F25/F26同样DATA主责：Auction先闭合来源vintage、字段版本、单位/精度/转换规则；Strict PIT再形成带publication/effective时间与coverage的Universe、Security Status、Market Rules正式receipt/版本链。F27才重新以牛牛AI为主角，在数据侧提供的已发布冻结基线上做真实自主研究工程验收，外部开发者不得用手工研究或注入答案代替。
- 目录协作同步定为“代码仓 + 数据根 + 版本化共享合同 + manifest/SHA handoff”：现有`src/quantlab/data`继续只放产品 reader/verifier/consumer，`scripts/collect`只负责采集；目标新增中立的`contracts/data_governance`、DATA离线`scripts/governance`与人工门控`scripts/publish`。数据根沿已有bronze/silver/gold/catalog/staging/quarantine/backups结构补`governance`控制面，并把未发布候选与active正式数据严格分开。当前仅写规划，禁止为整理目录批量移动既有历史数据或切指针。
- 本次只更新`docs/guide/data-and-evidence.md`、`docs/project/status.md`和本开发史，不修改`src/quantlab`、采集脚本、正式数据、catalog/Provider、候选状态或发布状态；后续由数据侧审查上述owner、目录/handoff、artifact/gate与19/88口径。
- 随后用户进一步收紧协作模型：不需要CODE与DATA共同维护复杂治理合同/目录，也不要求CODE复核DATA正确性。最终口径改为 **DATA对数据本身全责，CODE只按统一数据清单读取**。DATA在清单中维护“有哪些数据、绝对路径、格式/覆盖、是否READY”；一旦标READY即代表正确性、来源/版本、单位、完整性和适用范围由DATA确认。CODE仅处理路径不存在、不可读或reader无法解析等技术错误，不扫描数据根找替代来源、不自动回退、不做第二套数据认证。
- 规划新增`docs/reference/data-catalog.md`作为唯一日常DATA→CODE协作文档。当前仓库/数据根中已发现的主要路径先标`REVIEW_REQUIRED`供数据侧审查，不因路径存在就声明可用于产品；F22–F26完成后由DATA更新对应行到`READY`，CODE再接入。前一版关于新增`contracts/data_governance`、`governance/*`等目录仅作为未实施草案撤回，本轮不创建这些目录、不移动历史数据。
- 数据侧随后完成审查并认可该协作边界，同时直接维护`docs/reference/data-catalog.md`：已把确认可供CODE使用的数据列为`READY`，其后又继续独立扩充qfq、公开来源文件与研究查询API；这些状态、覆盖和交付方式均属于DATA结论，CODE沿清单消费，不重复做数据正确性认证。

### 2026-09-23｜[CODE] 统一 DATA catalog 消费入口

- 新增 `src/quantlab/data/dataset_catalog.py`，把 DATA 维护的 `docs/reference/data-catalog.md` 作为产品交接边界。解析 `READY/NOT_READY/REVIEW_REQUIRED/DEPRECATED` 与 `FILE/DATABASE/API/STREAM`，重复ID、表格结构/状态分区错误、清单缺失/过大等均 fail-closed；不读取 `dataset_registry.json` 的 `current` 来冒充 READY，不扫描数据根寻找替代项。
- 普通 Chat、标准 MCP 和 `data_review_cli` 接入 `list_data_catalog` / `get_ready_data_source`。模型schema不暴露path/root/approve/execute；host可显式指定catalog路径用于测试/部署。FILE/DATABASE只检查DATA公布路径是否存在可读，返回 `data_correctness_revalidated_by_code=false`、`fallback_performed=false`；API/STREAM只返回DATA公布入口，不由CODE直连第三方供应商。
- Chat系统边界明确先查DATA清单，再消费READY入口；NOT_READY/REVIEW_REQUIRED/DEPRECATED不作为正式输入。锁定QM50研究规格会话仍过滤这两个通用工具，不因统一清单扩大原规格权限。
- 新增 `tests/test_data_catalog_tools.py` 7项，覆盖核心解析、非READY/未知/不可读拒绝、无fallback、CLI、Chat权限、MCP进程内+真实stdio及额外参数拒绝。相关回归另确认 `test_data_review_tools` 13项、标准MCP 3项、archived integration 6项、F21工具类7项、原Chat 13项，合计49项明确通过；真实DATA清单smoke可列出当前READY集合并读取`qfq_published_f24`两个已发布路径，CODE未复核其业务正确性。
- 本轮不修改任何 `/Volumes/Lexar/niuniu-data` 数据、采集/治理脚本或DATA清单内容；`docs/reference/data-catalog.md` 当前由数据侧并行维护，本CODE提交明确不暂存它。现有 `MQCParquetProvider` 等历史业务路径仍有旧qfq硬编码，后续按功能独立迁移并处理每证券`valid_from`，不夹进本次入口提交。

### 2026-09-23｜[CODE] 再对齐 DATA 当前交付：qfq v2 + 研究查询 API

- 重新读取数据侧当前 `data-catalog.md` 与 `/Volumes/Lexar/niuniu-data/catalog/dataset_registry.json`：当前清单共48项，DATA声明 `READY=29`（23 FILE + 6 API）、`REVIEW_REQUIRED=4`、`NOT_READY=13`、`DEPRECATED=2`；23个READY文件路径均实际存在。机器registry共50项，`current=39/superseded=7/legacy=4`。这只是CODE侧交接核对，不重新证明数据正确性。
- 发现主线两个真实错位：其一 `MQCParquetProvider` 仍硬编码旧 `qfq_kline_daily/min5`，而DATA已在`4c9212c`发布v2并把registry切到`bars.daily.qfq/bars.min5.qfq`；其二catalog已把6个研究API标READY，但main还没有DATA定义的`ResearchDataProvider`，产品无法实际调用。
- 精确复用 data-remediation 已提交的 `src/quantlab/data/dataset_registry.py` 与 `research_provider.py`，工作区blob与DATA分支blob完全一致，不在CODE侧修改供应商、字段、凭证、限频或registry语义。`requests>=2.31,<3`补为正式运行依赖。
- `MQCParquetProvider` 对日线/5分钟raw/qfq优先按DATA registry解析current路径；registry不存在时仅为历史测试/旧显式数据根保留旧布局，registry存在但条目/路径无效时绝不fallback。qfq v2同时执行 `_meta/coverage.parquet` 的逐证券`valid_from`，并检查实际qfq文件首日，避免5分钟等请求静默缺头；早于DATA覆盖一律拒绝，不回旧qfq、不用raw补。
- 新增 `ResearchDataAPI`：只暴露catalog当前READY的 `research_search / stock_research_reports / stock_news / stock_announcements / financial_statements / investor_qa`，每次调用先重新检查同名catalog状态，再调用DATA统一Provider。错误不变成空结果、不自动换源；返回明确 `data_authority=DATA`、`data_correctness_revalidated_by_code=false`、`fallback_performed=false`、非Strict PIT/非MarketSnapshot/无交易授权。`stock_fund_flow_daily`及原实时行情/MarketSnapshot/扶摇入口仍按DATA的REVIEW_REQUIRED状态不升级。
- 普通Chat、标准MCP和新增`niuniu-research-data` CLI共用上述API；MCP标记这些工具`readOnlyHint=true/openWorldHint=true`。`local_data_only`与锁定QM50规格不获得联网研究工具。17类新增公开来源FILE数据本轮只通过统一catalog发现，不新增任意路径/任意SQL/任意Parquet模型查询工具，后续按具体产品功能逐项接入。
- 对齐时又发现3条旧联网旁路：Chat 的扶摇聚合/自动实时报价，以及 MarketSnapshot public-web provider/Daily Orchestrator，虽然DATA已把 `fuyao_context` / `realtime_quote` / `market_snapshot` 标为 `REVIEW_REQUIRED`，旧代码仍可能因实现或凭证存在而联网。现已统一按 DATA catalog gate：非READY不注册Fuyao工具、不预取实时报价，MarketSnapshot readiness为BLOCKED，live CLI和Orchestrator在联网前拒绝；DATA日后改READY才自动解锁。`stock_fund_flow_daily`继续不暴露正式工具。
- 最终当前代码明确通过121项：catalog 7、qfq registry 5、研究API 8、MarketSnapshot provider 4、public-web 9、Daily Orchestrator 20、live quote 5、Fuyao 6、原Chat 13、标准MCP 3、core 12、Baostock 10、retro-tail 7、Data Review工具层11、Data Review stdio单项1。另在DATA独立worktree对其原样 `dataset_registry.py` 跑12/12通过。Data Review另1个stdio用例及archived integration本轮外层调用超时，未取得新结果且不计入121；DATA的`research_provider.py`原pytest测试因当前`.venv`未安装pytest未复跑。真实DATA smoke确认READY总数29、6个READY研究API可见、4个REVIEW_REQUIRED旧入口均blocked，`sh.600000` qfq实际读取`qfq_kline_daily_v2`，`sh.600009`在DATA `valid_from=2003-08-11`之前明确阻断。数据正确性仍完全沿用DATA结论。

### 2026-09-24｜[CODE] 代码侧修复：助手上下文预算、qfq后上市证券、回测成本提示、测试与3.11兼容

- 起因：2026-09-23 对 `4195ad2` 的全仓审阅与全量测试（292个模块逐一独立进程、离屏Qt、装vnpy 4.4.0）发现3项真实失败及若干缺陷。本次只改代码侧（`src/quantlab`、`tests`、`examples`、文档），不修改 `/Volumes/Lexar/niuniu-data`、DATA清单状态、采集脚本或 `data-remediation` 分支。
- 助手上下文预算：系统说明（约6.5k）+ agent_memory（约39.6k）+ 附加说明已约5.2万字符，旧默认 `max_context_chars=60000` 扣除最终回答预留后只剩约5.18万，第一次工具结果就触发 `TOOL_CONTEXT_BUDGET_EXHAUSTED`。默认值改为120000（与本机已保存配置一致，已保存的 `model.json` 不被改写）；新增 `MIN_TOOL_CONTEXT_CHARS=16000`，系统说明加本条消息留给工具结果的空间不足时，在调用模型前明确报错并给出建议预算，不写入失败轮次。`turn_started` 事件新增 `context_usage`（系统说明、工具schema字符数、工具上限、预算）供排查；工具schema（约4.8万字符）只记录不计入预算，以免缩小现有120000配置下的实际工具空间。
- qfq v2：`MQCParquetProvider` 原先只要请求起始日早于 `valid_from` 或文件首日就整批报错，一批证券里只要有一只后上市就失败。现按 DATA coverage 自带的 `history_truncated` 区分：`true` 仍严格阻断且不回退；`false` 时 `valid_from` 即上市起点，与 raw 一样按窗口截取；coverage 缺该列时全部按截断处理。真实 coverage（只读查看）为452只 `true`、4,770只 `false`，与DATA清单描述一致。
- 回测成本（用户选定A方案，不改引擎默认值和已归档结果）：新增 `cost_model_warnings`，未收卖出印花税/过户费、未模拟涨跌停、或仅用固定 `limit_pct` 近似时，写入执行记录 `cost_model_warnings`、`limitations` 首部（⚠）和 report.md 提示段，CLI在stderr提示；成交、费用、`execution` 汇总与复算比较字段不变。新增 `examples/execution_statutory.json`，使用指南回测示例改为开启 `statutory_fees`。
- 测试：更新过时的Reviewer白名单测试（F3b有意开放 `get_strategy_package_contract`/`preview_strategy_package` 两个纯配置工具，其余 propose/record/preview 仍禁止）；新增 `tests/_optional.py`，26个依赖原生vn.py的用例在未装vnpy时显式跳过；Dev Studio测试不再依赖当前目录。`desktop/replay.py` 一处f-string改为Python 3.11可解析，全部源码/测试已按3.11语法解析通过。
- 文档：README中英文改正“实时报价已支持”的说法（当前被DATA门控关闭）；数据与证据§15.2、状态页qfq描述同步；代码地图包行数更新到当前并补 `niuniu-strategy-package` 入口（逐文件JSON清单仍为09-17快照）。
- 新增测试：`test_chat_context_budget.py` 2项、`test_cost_model_warnings.py` 3项、`test_qfq_registry_consumer.py` 新增4项；验证结果见下一条补记。
- 验证（云端隔离副本，Python 3.12、离屏Qt、vnpy 4.4.0）：293个测试模块逐一独立进程全部通过，共1,980项、0失败；其中21个Qt模块打印OK后在解释器退出时段错误（既有Qt退出问题，与本次改动无关）。另卸载vnpy复跑11个相关模块，全部通过并显式跳过26项；从 `tests/` 目录运行Dev Studio测试通过。`scripts/check_docs.py` 与 `git diff --check` 通过。未在Mac本机 `.venv`（Python 3.13）复跑，未调用真实模型或读取行情数据。

### 2026-09-24｜[CODE] 产品化改造阶段0–1：日常工作台导航、今日市场与主线方向

- 起因：用户对比 easy-stock 后决定先做产品化收口（继续用 PyQt、只给自己用、大V复盘放最后）。核实发现原首页“今日交易”只读手工 Decision/Theme 记录（工作空间内为0），每日复盘/简报最后产出停在2026-09-16/17，打开软件基本看不到当天内容。方案见 Project 文档 `claude/niuniu-productization-plan.md`。easy-stock 为 PolyForm Noncommercial 许可，本次只参考产品设计，未使用其代码。
- 阶段0：左侧导航改为7个日常工作台（今日市场、主线方向、今日候选、个股报告、我的股票、复盘验证、AI 助手）；原9个页面全部保留，收进“专业模式”开关（按工作空间保存在 `_desktop/ui.json`），标题改为交易台、主题矩阵、股票决策档案、持仓计划、决策复盘等；顶栏常驻“问 AI”，研究议程/新建实验/＋Decision 等按钮只在专业模式显示；导航改为按 key 跳转（`navigate_page`），不再依赖页面序号。今日候选、个股报告、我的股票暂为“即将上线”说明页，不伪造内容。
- 阶段1：新增 `trading/market_overview.py` 与 `niuniu-market-overview` CLI，只经 DATA 清单读取 READY 的前复权日线、日状态/ST、同花顺涨停池、交易所两融和 Baostock 参考快照，生成当日市场事实（涨跌家数、涨跌停、炸板、最高连板、成交额及变化、昨日涨停溢价、连板晋级率、两融）与近一年分位、近60日走势、连板梯队（附涨停原因），以及领涨行业（中位涨幅、5日中位涨幅、涨停数、成交额占比、连续进前五天数、领涨股）和涨停原因集中度。涨跌按复权收盘，涨跌停复用既有 `limit_states` 与板块规则，前收用“前一日前复权收盘÷当日因子”推算。桌面两页读取 `_home/market/<交易日>.json`，结果过期时后台自动重算。
- 真实数据冒烟（本机隔离VM，只读挂载数据湖，Python 3.10 + polars 1.44）：2026-09-23 上涨1,757/下跌3,366、涨停51/跌停14、最高4连板、成交额17,648亿元；计算出的51家涨停与同花顺涨停池当日51条一致。单次计算约45–75秒（读取5,222只证券近一年日线与状态）。冒烟中发现并修复两融日变动方向写反的问题，并补测试覆盖。
- 测试：新增 `test_market_overview.py`（合成数据湖按真实文件格式：涨跌停/连板/除权日不算下跌/昨日涨停溢价/两融变动/行业与涨停原因/超出数据日期拒绝/NOT_READY 不替代/CLI/桌面渲染）6项；导航相关的7个桌面测试改为按 key 跳转并覆盖专业模式显隐与保存。全量结果见下一条补记。
- 限制：只有盘后数据；指数行情、概念板块成分、盘中实时尚未由数据侧提供；行业是参考快照当天的证监会分类；尚无定时任务，靠打开页面或 CLI 触发。
- 验证（云端隔离副本，Python 3.12、离屏Qt、vnpy 4.4.0）：294个测试模块逐一独立进程运行，共1,986项；首轮仅 `test_trading_cockpit_desktop` 3项因原首页变为“今日市场”失败，测试改为先进入专业模式“交易台”后通过，其余全部通过（10个Qt模块打印OK后退出时段错误，为既有Qt退出问题）。`scripts/check_docs.py` 与 `git diff --check` 通过。未在Mac本机 `.venv`（Python 3.13）打开真实窗口验收。

### 2026-09-23｜[数据侧整改 第一批] 阶段0只读盘点与阶段1数据集注册表

- 按用户批准的《牛牛数据侧整改方案》（D1–D7 全部按建议采纳）开始第一批。工作在独立 git worktree `.worktrees/data-remediation`（分支 `data-remediation`）进行，未触碰另一会话中未提交的 F21 版本账本文件。
- 阶段0：新增只读 `scripts/collect/inventory.py`，按数据集目录输出文件数、字节、Parquet 行数、列签名分组、页脚统计日期范围、空结果标记、回执与 listing fingerprint；`--deep-hash` 才计算逐文件内容清单。报告只能写在数据根外。真实盘点结果在 `artifacts/data-remediation-20260923/stage0-inventory.json`（分段运行后合并），0 个不可读文件。主要发现：silver qfq 日/5 分钟截止 2026-09-04 而 raw 截止 2026-09-22；巨潮配股 v2 有 67 种供应商列签名、同花顺 v2 有 4 种；`src/quantlab/data/dividends.py` 仍读仅 3 只证券的 Baostock 旧分红目录，`corporate_action_review.py` 仍读同花顺 v1 与东财旧分红；12 个 silver 目录中 9 个为空；`backups/` 约 30.8 GB。
- 阶段1：新增 `src/quantlab/data/dataset_registry.py`（`catalog/dataset_registry.json` 的读取、校验与 `resolve`）。注册表缺失时保持调用方原默认路径；存在时即为权威，格式错误、未知字段、越出数据根、符号链接路径、current 目录缺失、未注册或非 current 名称均报错，不静默回退。listing fingerprint 漂移只由 `verify` 报告，不阻断 resolve；注册表不提升任何数据资格。可选 `version_ledger` 字段只引用 F21 账本，二者职责分开。
- 新增 `scripts/collect/registry.py`（draft/verify/apply/views）与人工审阅的 `registry_spec.json`（25 个逻辑数据集：15 current、6 superseded、4 legacy）。apply 必须给出草稿完整 SHA，且草稿后目录未漂移；旧注册表先复制到 `catalog/registry_history/`。已在真实数据根安装注册表，SHA `98a227f94b3fbd409c143b84d31d8afaf888d5168e462c82d1bdaa23f1b1daa8`；产品代码暂未改为按注册表读取，行为不变。
- `reg_*` catalog 视图生成器只 CREATE OR REPLACE `reg_` 前缀视图，拒绝与表同名，写前记录原 `reg_` 视图。14 个视图的 SQL 已在内存 DuckDB 中对真实数据逐一建视图并计数，行数与盘点一致；**尚未写入 `catalog/mqc.duckdb`**，需确认并行会话不在读取 catalog 后再按计划 SHA 应用。
- 路径统一：新增 `scripts/collect/paths.py`，全部采集脚本经它取数据根（`NIUNIU_DATA_ROOT` 或历史默认路径），脚本中不再出现硬编码数据根。`ths_dividend.py`、`cninfo_allotment.py` 取消指向 v1 旧目录的默认 `--dest`，必须显式给出。偏离方案之处：未设环境变量时仍回退到历史路径而非报错，原因是每日脚本在导入时绑定路径常量且既有 58 项测试依赖此行为；强制显式数据根留待后续。
- 测试：新增 `tests/test_collect_inventory.py` 5 项、`tests/test_dataset_registry.py` 12 项；与既有采集测试合计 75 项全部通过（Linux VM，Python 3.10，离线临时目录）。未运行全仓回归，因为本批未修改被其他产品模块导入的代码。

### 2026-09-23｜[数据侧整改 第二批] catalog 视图、当日增量、捕获包迁入数据根

- catalog：14 个 `reg_*` 视图已按计划 SHA `8785586044e0…` 写入 `catalog/mqc.duckdb`，只新增 `reg_` 前缀视图，未改表和原有视图；逐个核对行数与盘点一致。写入须在 Mac 路径下进行（DuckDB 创建视图时即解析文件路径），本次在 Linux 工作区用用户命名空间把数据根挂到 `/Volumes/Lexar/niuniu-data` 后执行。
- 当日增量（用户已批准）：2026-09-23 参考快照 7/7 文件完成，在市 A 股 5,222 只。`daily_plan.py` 重新生成计划（`artifacts/data-collection-plans-20260923-daily-r2/`），7 只新股的日 K、5 分钟、日状态全部 ok（计划 SHA `b96b0d8d…`、`e2ab6c47…`、`16fd0e77…`）。日 K/5 分钟目标日仍为 2026-09-22（北京时间 18:00 前）。
- 公司行动每日再观察：巨潮配股 644/644 完成（601 unchanged、43 updated、0 failed）。**这 43 条 updated 全部是误报**：`daily_common._stable_value` 把供应商返回的 `pandas.NaT` 记为字符串 `"NaT"`，而同一单元格从 Parquet 读回是 `None`，导致内容未变的文件被判为修订并重写。已修复（`cdaa2fc`，NA 先于日期分支判断）并补回归测试；43 个被重写文件与备份的逻辑内容逐一核对相同，更正记录在 `artifacts/data-remediation-20260923/stage3-cninfo-false-revision-audit.json`，原回执不改写，备份保留在 `backups/corporate-daily-e043b14436741eb5/`。修复后的 401 只没有再出现误报。
- 捕获包迁移（阶段 2）：新增 `src/quantlab/data/capture_root.py` 与 `scripts/collect/migrate_captures.py`。`artifacts/_market_data` 的 1,800 个文件（673,750,558 字节）按计划 SHA `36fa879d…` 先整体核对、再复制到 `/Volumes/Lexar/niuniu-data/lake/_market_data` 并逐文件核对，源文件一个未动。随后写入 `artifacts/_market_data.redirect.json`（capture_root_id `66a590b0…`），所有捕获读写模块（回溯日线、DailyMarket、公开证据、前瞻参考、Baostock 导入/series、证据调度、打板研究工具、行情工具）改为经 `capture_root()` 定位；无重定向时行为不变，重定向无效时报错。`catalog/retro_daily_tail.json` 改指迁移后的 capture，pack index digest 不变，旧指针备份在 `catalog/retro_daily_tail.history/`。真实数据上已验证：工作空间解析到新根、回溯尾部读取 sh.600000 2026-09-07..15 共 7 行成功。
- 新目录名为 `lake/_market_data` 而非方案中的 `captures/`，因为 `baostock_series`、`retro_tail` 的校验按目录名 `_market_data` 判断。
- 注册表更新为 SHA `807ddb62f592…`，新增 `capture_tree` 类型及 5 个 `captures.*` 条目（旧版在 `catalog/registry_history/`）。
- 测试：新增 8 项（capture root/迁移）与 1 项（NaT 回归）。在 Python 3.11 隔离环境中跑通受影响模块：采集 76 项及 retro_daily、retro_pack、retro_tail 三组、daily_market_archive、public_evidence、forward_daily、baostock_series、baostock_data、evidence_scheduler、limit_research_tools、archived_daily_dataset、archived_data_tools、archived_dataset_lifecycle、archived_research_check 全部通过；`archived_suspension_contract` 中依赖 vnpy 的 1 项因未安装 vnpy 未运行，其余 7 项通过。未跑桌面（PyQt）测试。

### 2026-09-23｜[数据侧] 公司行动全量再观察结论：不再每日复查历史

- 巨潮配股 644/644、同花顺分红 4,478/5,222、Baostock 分红 1,329/5,222，真实修订均为 0；巨潮 43 条 updated 为 NaT 比较 bug 误报（`cdaa2fc` 已修，逐一核对内容相同）。同花顺在用户确认无需继续后停止，回执可续跑；Baostock 因请求间隔被调到 0.3 秒且频繁重新登录，IP 被封禁后中止。
- 决定：历史记录不再每日全量复查，全量复查只在发布新版 qfq 前做（平时最多每季度一次）；每日只采新事件与新上市证券，`corporate_actions_daily.py` 的子集模式待实现，之前每周一次。Baostock 请求间隔不低于 1 秒、单次登录。详见[再观察结果与采集频率](../archive/data-evidence/20260923-公司行动再观察结果与采集频率.md)。

### 2026-09-23｜[数据侧整改 第三批] qfq v2 发布、公开来源数据 17 项、研究查询 API

- qfq v2（`d1fd5e3`、`4c9212c`）：`scripts/derive/build_qfq.py` 从三家原始公司行动重建复权因子，事件须至少两个可用来源一致才采用（共 54,712 个），TDX 单源事件忽略，无法确认的事件不猜。发布到 `lake/silver/qfq_kline_daily_v2` 与 `qfq_kline_min5_v2`（5,222 只，至 2026-09-22；`date` 为 date32）；452 只只从最后一个未确认事件日起提供，起点见 `_meta/coverage.parquet`。按用户“不管这些历史”的决定，截断部分不补。旧 qfq 两项标为 DEPRECATED。
- 公开来源采集（`fb8e0ca`）：`scripts/collect/public_sources.py` 按 plan→SHA 批准→apply 的同一合同采集 17 项公开数据（涨停池、交易所融资融券、大宗交易、巨潮公告目录、机构调研、股东增减持、限售解禁、业绩预告、股东户数、回购、质押、新股、指数权重、申万行业历史、东财异动监控/异常波动、北向分钟），首采均已完成，覆盖见数据清单 §3.1。数据源代码取自 a-stock-data（Apache-2.0，commit `2e0ae63`），按用户决定直接引用、未逐行审查，来源与哈希记在 `scripts/collect/vendor/a_stock_data/PROVENANCE.json`。东财串行且间隔不低于 1.5 秒。
- 采集中修掉的问题：申万站点缺中间证书（固定 GeoTrust 中间证书并加 UA）、上交所融资融券分页上限 2,000（改分页并核对总数）、巨潮 502 与无效栏目循环（重试 4 次、单栏目、核对公告总数）、业绩预告按报告期分别拉取并在 5,000 行上限处报错、回购/新股只返回最新 5,000 条（回执写 `truncated_to_latest`）。
- 研究查询 API：新增 `quantlab.data.research_provider.ResearchDataProvider`，给 CODE 的按需接口 7 项（问财语义搜索、个股研报、个股新闻、个股公告、三大报表、互动易问答、个股资金流）。出错一律抛异常，不以空结果冒充无数据；按供应商限频；问财密钥只从环境变量或 git 忽略的 `.env` 读取。实网冒烟测试 6 项通过；资金流接口当晚被东财拒绝连接，标为 REVIEW_REQUIRED。
- 注册表更新为 SHA `41d5887a…`，新增 17 个 `public.*` 条目（`dated_snapshots` 类型，旧版在 `catalog/registry_history/`）。`docs/reference/data-catalog.md` 同步新增 §3.1 文件数据与 §3.2 API。
- 测试：新增 `tests/test_research_provider.py` 10 项、`tests/test_collect_public_sources.py` 4 项；连同 `test_collect_daily`、`test_build_qfq` 共 43 项通过。
- 每日增量：2026-09-23 的日 K、5 分钟、日状态 r3 计划已生成（目标日 2026-09-23，各 5,222 个动作），需在 Mac 上单进程运行。
- 每日增量完成（2026-09-23 夜在 Mac 上单进程运行）：日状态 5,221/5,222 ok，sz.002107 超时后于 09-24 用单独计划 `27dc70a8…` 补齐；日K 5,219 ok、3 只当日停牌；5 分钟 5,222 ok（每只 48 根）。日K/5 分钟/日状态三项截止推进到 2026-09-23，数据清单已更新；qfq v2 仍截止 2026-09-22。
- qfq v2 按新计划 `cf7f1ba8…` 重建至 2026-09-23（日线与 5 分钟各 5,222 只，TDX 快照与公司行动输入未变，截断仍为 452 只），coverage 已重新生成。09-23 巨潮公告 1,507 条、融资融券 4,108 条已补采；资金流接口复测仍被拒绝连接，维持 REVIEW_REQUIRED。

### 2026-09-24｜[CODE] 产品化改造阶段2：个股报告、我的股票、AI 日常模式

- 市场总览计算时同时保存逐股快照 `_home/market/<交易日>.stocks.parquet`（收盘、近5/20/60日涨幅、全市场及行业内近20日强弱分位、20/60日均线距离、距60日高点、成交额/20日均值、20日波动、连板、10日涨停次数、ST/停牌），个股页和我的股票不再扫描全市场。
- 新增 `trading/stock_report.py`：代码或名称（6位代码、sh./sz.前缀、.SH后缀、唯一名称）生成一页报告，含摘要、指标、120日前复权日K、同行业近20日最强、以及读取 DATA READY 的业绩预告、未来30天解禁、近30天股东增减持文件形成的“需要留意”事实；公告和研报经 DATA `ResearchDataProvider` 在线读取，各自独立失败并说明原因，不换源。新增 `trading/my_stocks.py`：本地自选/持仓列表（仓位、成本可选），逐只巡检与行业集中度。
- AI：新增 `agent/home_tools.py`，助手可读 `get_market_overview`、`get_stock_report`、`get_my_stocks`（只读已生成结果）。`ChatRuntime(tool_profile='everyday')` 只开放上述3个和6个 DATA 研究接口（共约9个），系统说明换成简短的日常提示加 `rules/core.md`，不再附带研究/治理合同；研究模式行为不变（增加上述3个只读工具）；锁定研究规格的会话不加这些工具、也不允许日常模式。对话窗口增加“日常/研究”模式选择（普通模式默认日常，专业模式默认研究，数据工作台内的助手固定研究）；各页“问 AI”把当前页面数据预填进输入框，用户确认后发送。
- 真实数据冒烟（本机VM只读）：重算 2026-09-23 总览含逐股快照约55秒；贵州茅台、大亚圣象、凯撒旅业报告各约0.2–0.3秒，大亚圣象正确标出4倍放量、4连板和半年度每股收益首亏预告；三只股票的我的股票巡检正确给出仓位合计与行业集中提示。冒烟中发现同行列表包含自身，已排除。
- 测试：新增 `test_stock_report.py` 10项（代码格式、按名称查找、解禁/减持/业绩预告提示、未生成总览时的提示、在线段独立失败与未开放说明、我的股票增删与仓位上限、日常模式工具白名单与短系统说明、研究模式不变、桌面个股页/我的股票/问AI预填）。
- 限制：今日候选、历史验证标签（阶段3）和复盘验证闭环（阶段4）尚未做；个股页没有盘中实时价；“需要留意”的阈值是经验设定的提示，不是经过验证的信号。
- 验证（云端隔离副本，Python 3.12、离屏Qt、vnpy 4.4.0）：295个测试模块逐一独立进程运行，共1,996项全部通过。首轮3个既有模块因默认进入日常模式而失败（研究对话往返测试、选择复盘引用测试的构造替身、能力列表一致性），已让研究测试显式切到研究模式、替身接受新参数、能力列表包含新工具。部分Qt/线程模块打印OK后在退出时崩溃，为既有问题。未在Mac本机真实窗口验收。

### 2026-09-24｜[CODE] 产品化改造阶段3：今日候选与历史验证

- 市场总览的逐股特征改为在整个加载窗口（多加载60个交易日预热）上逐日计算，当天快照、今日候选和历史验证共用同一套数字；前向结果为“次日开盘买、第5个交易日收盘卖”，并标记次日一字涨停（买不进）。
- 新增 `trading/candidates.py`：5 条固定规则（强势趋势、放量创新高、首板、强势股回调、超跌，均排除 ST/停牌）。每条规则在近一年每个交易日回放，与当日全部可交易股票等权同法对比，取不重叠的5日样本，扣约0.2%往返成本，给出平均超额、扣成本后超额、跑赢比例、平均入选数、样本数和 t 值，结论分“较稳定跑赢/跑输/没有稳定优势/样本不足”。页面 `今日候选` 显示各规则今天的股票、入选理由和验证结论；个股报告显示该股今天入选的规则及其结论；助手 `get_market_overview` 同时返回候选与验证文字。旧版结果（无候选）打开页面时自动重算。
- 真实数据（本机VM只读，2025-08-08 至 2026-09-10 信号日，53–54 个不重叠样本）：强势趋势扣成本后 −0.34%（t=−0.8），放量创新高 −1.15%（t=−1.8），首板 −1.29%（t=−2.7，稳定跑输），强势股回调 −0.52%，超跌 −0.56%；没有一条规则显示出扣成本后的稳定优势。重算总览（含候选与验证）约38秒。
- 测试：新增 `test_candidates.py` 5项（规则说明、已知正超额被识别且扣成本和不重叠样本数正确、单日入选不足为样本不足、次日一字涨停剔除、ST/停牌不入选），既有市场总览与个股报告测试通过。
- 局限：验证只含当前在市股票（幸存者偏差）；约一年、单一市场环境；成本为固定估计，未考虑容量和冲击。规则本身是常见经验规则，验证结果只说明它们在这段时间的表现，不是对规则的最终评价。
- 验证（云端隔离副本，Python 3.12、离屏Qt、vnpy 4.4.0）：全量测试2,043项通过；唯一未运行的是数据侧 `test_research_provider`（依赖未安装的 pytest，非本次改动）。未在Mac本机真实窗口验收。

### 2026-09-24｜[CODE] 产品化改造阶段4：复盘验证闭环

- 新增 `trading/judgments.py`：判断存 `artifacts/_home/judgments.json`（看多/观望/看空、5/10/20个交易日、我的判断/AI 的判断、可选失效价和目标价、理由；按方向校验失效价/目标价位置）。核对只读 DATA READY 前复权日线：收益从判断日收盘算到第 N 个交易日收盘；失效价/目标价按实际收盘价（前复权收盘 ÷ 复权因子）逐日核对，先触发者结束；否则到期按顺向收益 ±1% 判正确/错误/持平，观望不计对错；同期全市场等权平均取自市场总览新增的 `market_returns`（每个交易日可交易股票等权平均涨跌），并给出超额。完成的核对写回记录并冻结。统计按总体、来源、方向、周期给出准确率、平均顺向收益、平均顺向超额，已完成少于10条时提示参考意义有限。
- 市场总览：`_daily_stats` 增加等权平均涨跌 `mean_pct`，结果增加 `market_returns`（统计窗口内逐日）；缺少该字段的旧结果打开页面时自动重算。
- 页面：个股报告增加“保存判断（之后自动核对）”；复盘验证页改为读取这些判断：准确率、平均顺向收益/超额、分组表、逐条结果（进行中显示进度，触发失效价/目标价的注明日期），可删除、双击打开个股报告、“问 AI 复盘”。交易台的旧决策记录仍在专业模式“决策复盘”。助手新增只读工具 `get_judgments`（日常与研究模式都有）。
- 真实数据冒烟（本机VM只读）：重算 2026-09-23 总览约37秒，`market_returns` 255 个交易日；按 09-02 至 09-18 保存5条判断后核对约0.03秒：茅台 09-09 看多5日到 09-16 −2.5%（全市场 −2.6%）判错误；凯撒旅业看多设失效价 4.17，09-14 收盘 4.08 触发，第8个交易日结束；东易日盛看空10日 +10.6% 判错误；工商银行观望不计对错；宁德时代20日进行中 3/20。第二次核对直接读取冻结结果。
- 测试：新增 `test_judgments.py` 9项（到期判正确及超额、失效价按实际收盘提前结束、看空目标价/观望/持平、进行中/等待数据/停牌日计入交易日、统计只计已完成的看多看空、保存校验、核对冻结与删除、日常模式 `get_judgments`、桌面从个股报告保存到复盘页显示）。
- 局限：准确率只看涨跌方向，不含交易成本；判断基准是判断日收盘价，实际能成交的价格可能不同；全市场基准是等权平均，不是指数；样本少时准确率没有统计意义。
- 验证（云端隔离副本，Python 3.12、离屏Qt、vnpy 4.4.0）：全量测试2,052项通过；唯一未运行的仍是数据侧 `test_research_provider`（依赖未安装的 pytest，非本次改动）。未在Mac本机真实窗口验收。

### 2026-09-24｜[CODE] 产品化改造阶段5：大V复盘

- 新增 `trading/kol.py` 与页面“大V复盘”（日常导航第7项，AI 助手移到第8项）：手动粘贴复盘文章（作者、平台、发布日期、标题、链接、正文，存 `artifacts/_home/kol/posts.json`）；“AI 提炼观点”用模型设置里的模型一次性提取固定格式观点（大盘/个股/方向、看多/观望/看空、1/3/5/10/20日、原话），不给模型任何工具，正文声明为外部数据；原话去标点后须在正文中出现，否则标“未在原文找到”，格式不符的丢弃并计数；可手动增删观点。“保存为待核对”把大盘/个股观点转成来源“大V观点”、带作者的判断（起点为发布日及之前最后一个交易日收盘；同一篇重复保存替换旧判断），方向观点不自动核对。作者表现表、“问 AI 汇总最新观点”。
- 复盘验证扩展：核对周期增加 1 和 3 个交易日（个股报告默认仍为5）；支持大盘判断（按市场总览的全市场等权平均序列构成的指数核对，不设失效价/目标价，无超额）；判断记录增加作者和文章编号，统计增加按作者分组；助手 `get_judgments` 返回作者字段。复盘页大盘判断行双击不跳转个股报告。
- 不做的事：不登录、不订阅、不抓取雪球/淘股吧/公众号；自动采集需数据侧按合规方式交付后再接入。
- 测试：新增 `test_kol.py` 7项（观点解析/原话核对/丢弃计数、观点校验、文章校验与去重、提炼→保存→核对全链路含大盘判断与按作者统计、周末文章从周五收盘起算、API 模型缺少密钥时的提示、桌面导入/手动加观点/保存/作者表）；导航测试更新为8个日常页。
- 局限：模型提炼可能漏提或误提，需人工核对后再保存；本次没有用真实模型跑提炼（云端与本机VM都没有可用的 Codex 登录），真实调用需在Mac上验收；准确率只看涨跌方向；样本少时没有统计意义。
- 真实数据冒烟（本机VM只读，观点手动填入）：一篇 2026-09-12（周六）的文章，大盘/个股起点正确落在 09-11 周五收盘；茅台看空5日 −1.4% 判正确，宁德时代看多5日 −8.6% 判错误，大盘看多1日 +0.6% 基本持平，方向观点跳过；保存约0.2秒。
- 验证（云端隔离副本，Python 3.12、离屏Qt、vnpy 4.4.0）：全量测试2,059项通过；`test_mobile_workbench` 在8进程并行时本地HTTP超时一次，单独重跑通过；数据侧 `test_research_provider` 仍因缺 pytest 未运行。未在Mac本机真实窗口验收。

### 2026-09-24｜[DATA] 实时行情接口审查并开放

- 审查 `PublicWebConsensusProvider`（腾讯/东方财富/新浪、至少两源一致）、`LiveStockQuoteService` 与 `MarketSnapshotProviderRegistry`。收盘后实网测试普通股、科创板、北交所、停牌股与 200 只批量：三源价格、成交量（股）、成交额（元）逐项一致；昨收与 09-23 入库日K一致，唯一差异 sh.600160 为 09-24 除息（10派2.2元，35.05→34.83），符合交易所除权参考价。
- 修复：东方财富改为 `ulist.np` 批量接口（每批 100 只、间隔 1.5 秒串行、失败重试一次），替代逐只并发请求；原逐只接口的买一/卖一字段取错（f19/f31，收盘后缺失），批量接口用 f31/f32 实测与腾讯一致。停牌/当日零成交不再报成“两源不一致”，改为 `no_trade_today`、`tradable=false`。实测东财对同一 IP 过密请求会断开连接，此时腾讯+新浪两源仍能形成一致结果。
- 数据清单：`realtime_quote`、`market_snapshot` 改为 `READY`（新 §3.3，写明单位、一致规则、停牌与除权语义、限制）；盘中（竞价、连续竞价、涨跌停封单）待下一交易日开盘补测。`fuyao_context` 维持 `REVIEW_REQUIRED`：DATA 环境无扶摇凭证无法实测；它未开放前，`chat_runtime` 的实时报价只走公开网页三源共识。
- 测试：`test_public_web_market_snapshot` 新增 3 项（东财批量解析与北交所前缀、批量请求数、停牌原因），相关 12 + 5（live quote）+ market snapshot/orchestrator/fuyao 共 57 项通过。
- 同日续：用户提供扶摇凭证（写入 git 忽略的项目 `.env`，`HITHINK_FINANCE_API_KEY`）。实测扶摇报价与五个聚合查询（证券解析、个股快照+日K、板块、短线、基本面）：成交量为股、现价/昨收与三家公开行情一致，日K成交量与 09-23 入库日K一致；成交额只有约 8 位有效数字。修复 `FuyaoAugmentedQuoteProvider`：与公开行情不一致的扶摇报价不再输出（全部不一致时报错）；通过校验时补上扶摇缺的证券名称、改用公开行情的精确成交额和盘口画像；停牌股标 `no_trade_today`。`fuyao_context` 改为 `READY`（清单写明板块为当前成分、K线为扶摇自有复权不可用于回测）。更新 `test_fuyao_integration` 的不一致用例；`test_market_snapshot_provider` 两项改为固定测试用清单，不再依赖线上清单状态。相关 50 个测试模块中仅 3 项 stdio 子进程用例因本地环境缺包失败，与本次改动无关。

### 2026-09-24｜[CODE] 日常模式接入扶摇与实时报价

- 数据侧开放 `realtime_quote`、`market_snapshot`（6693fea）和 `fuyao_context`（666d26a）。对话本来就按清单开关：问到具体股票时宿主自动附上实时报价（扶摇为主、公开行情校验，对不上的不输出），研究模式出现5个扶摇工具；扶摇不在清单 READY 时两者都不启用。
- AI 助手“日常”模式的工具白名单加入5个扶摇工具（清单未开放或无密钥时不会出现）；日常系统说明补充用法和口径：板块成分是当前成分，扶摇K线不用于统计/回测，与牛牛数据有出入时说明两边口径，引用实时报价写明时间。
- `test_market_snapshot_provider` 两项原先读取仓库真实清单、假定盘中快照未开放，改为固定一份“待审查”清单（9a40b7b；数据侧随后在 setUp 做了同样处理，两者兼容）。
- 验证：本机VM用项目 `.env` 的扶摇密钥连通，证券消歧“贵州茅台”返回 600519.SH；未在Mac真实窗口里跑完整对话。测试：扶摇集成测试增加日常模式开放/未开放两种情况；全量回归见本节末。
- 全量回归（云端副本，Python 3.12、离屏Qt）：2,062项通过；数据侧 `test_research_provider` 仍因缺 pytest 未运行。

### 2026-09-24｜[DATA] 盘中板块接口（响应 CODE 需求“盘中板块榜与板块成分行情”）

- 评估刷新频率：CODE 原提 60 秒，看盘偏慢。实测扶摇：710 个概念/行业板块 3 次批量请求约 3–4 秒；1,065 只成分股 4 次批量约 2 秒；15 秒内约 40 次请求后出现一次网络错误，歇 20 秒恢复。经用户确认：板块榜 10 秒、打开的板块成分股 5 秒。
- 新增 `src/quantlab/data/sector_intraday.py`（`SectorIntradayProvider.board_snapshot / board_members / board_series`）：最小间隔内返回缓存（带年龄），失败重试一次、再失败返回上次结果标 `stale`；成分股用腾讯+新浪轮流核对（每只 ≤30 秒一次、每次 ≤300 只），核对时不一致的不输出价格；涨跌停/炸板由 DATA 按板块规则推算并与扶摇涨停/跌停/炸板池对照；上市前 5 个交易日标无涨跌停。
- 新增 `scripts/collect/sector_intraday_recorder.py` 与 `artifacts/run-sector-recorder.command`：交易时间每分钟把全部板块写入 `lake/bronze/provider=fuyao/sector_board_intraday/`。
- 收盘后实测：710 个板块全部返回；新能源汽车 1,065 只首次 7 秒、之后 2–5 秒，1,061 只与公开行情一致、4 只零成交；涨停/炸板与扶摇池一致。数据清单新增 §3.4，两个接口先标 `REVIEW_REQUIRED`，下一交易日（2026-09-28，09-25 中秋休市）盘中实测后开放；记录器数据集 `NOT_READY`。
- 测试：`tests/test_sector_intraday.py` 5 项。
- 同日续：经用户同意，`sector_board_snapshot`、`sector_board_members` 先改为 `READY`，清单写明盘中延迟、竞价时段、全天限流、封板判断尚未实测；2026-09-28 盘中实测，问题严重时改回 `REVIEW_REQUIRED`。`sector_board_intraday` 仍为 `NOT_READY`。

### 2026-09-24｜[CODE] 盘中板块页

- 新增日常页“盘中板块”（导航第3项）：左侧同花顺概念/行业板块排行（涨幅榜/跌幅榜/成交额，可筛概念或行业），单击板块在右侧列出成分股现价、涨跌幅、成交额和状态（涨停/炸板/跌停/停牌/来源不一致暂不显示），双击打开个股报告；页面打开期间的板块涨跌幅采样走势；“问 AI 解读”。交易时间板块 10 秒、成分股 5 秒原地刷新（不重建页面，保留选择），午休/收盘后每分钟检查；顶部显示交易状态、数据时间、年龄、刷新失败时的上次结果。
- 只通过数据侧 `SectorIntradayProvider`（进程内共享一个实例）取数；`trading/intraday_sectors.py` 先查数据清单，`sector_board_snapshot`、`sector_board_members` 都为 `READY` 才调用，否则页面说明原因（专业模式下有“开发预览”供核对）。数据侧同日已把两个接口改为 READY（9ac3276），页面按清单要求始终显示 `as_of`、离现在秒数和 `stale`。
- AI 助手新增只读工具 `get_intraday_sectors`（板块涨跌前列，可选一个板块的成分股概况），同样只在接口 READY 时出现在工具列表里。
- 取数失败只在本页显示（如“没有配置扶摇密钥”），不写窗口全局状态栏。
- 测试：新增 `test_intraday_sectors.py` 6 项（清单开关与说明、排行/成分状态/提示词、工具开放前后、页面未开放说明、排行与选中板块成分股、取数失败留在本页），使用数据侧测试里的扶摇替身；导航测试更新为 9 个日常页；`test_desktop`、`test_trading_desk_desktop` 遍历所有页面时关闭盘中板块的开关，避免测试访问真实行情。
- 全量回归（云端副本）：2,073 项通过（`test_mobile_workbench` 并行时本地 HTTP 超时一次，单独重跑通过）；数据侧 `test_research_provider` 缺 pytest 未运行。

### 2026-09-24｜[CODE] 盘中板块：过滤全市场标签和小板块

- 盘中板块页和 AI 的板块摘要默认隐藏不代表题材的全市场标签：融资融券、沪股通、深股通、证金持股、国家大基金持股、高股息精选、中国AI50、ST板块、摘帽、新股与次新股、注册制次新股、科创次新股、“同花顺”开头的指数、“2026中报预增”这类业绩标签（`trading/intraday_sectors.py` 的 `MARKET_LABELS`），并隐藏成分股少于 10 只的板块；页面有“过滤全市场标签和小板块”开关，关掉显示全部。
- 成分股只数需要数据侧在板块榜里提供 `constituent_count`（已提需求）；字段出现前只按名称过滤，页面写明原因。
- 真实数据（2026-09-24 收盘）：隐藏 19 个标签后，成交额榜前列由“融资融券/深股通/沪股通”变为芯片概念、华为概念、国企改革等。
- 测试：`test_intraday_sectors.py` 增加 2 项（标签隐藏与开关、提供只数时隐藏小板块），页面测试覆盖开关。

### 2026-09-24｜[DATA] 盘中板块接口追加：成分股只数与板块分类（响应 CODE 追加需求）

- `sector_board_snapshot` 每个板块新增 `constituent_count`（来自新增的每日成分快照 `sector_board_constituents`，`scripts/collect/sector_constituents.py`；首份 2026-09-24，710 个板块、80,701 行）和 `board_class` / `label_reason`（DATA 维护的 `industry` / `theme` / `market_label` 分类，版本 `board-class-v1`；2026-09-24 的 19 个 `market_label` 与 CODE 原按名称隐藏的 19 个一致）。盘中记录器开盘前自动刷新成分快照。数据清单 §3.4 更新字段说明并新增 `sector_board_constituents`（READY）。测试新增 2 项，共 7 项通过。
- 当晚另完成：2026-09-24 参考快照（在市 5,222 只）；公开数据 13 项（当天观察 9 项 + 涨停池、大宗交易、机构调研、股东增减持）；18:30 原定采集因连不上 Mac 延到 22:40 前后完成。日K/5分钟/日状态计划已生成（`artifacts/data-collection-plans-20260924-daily/`），需在 Mac 上运行。

### 2026-09-24｜[CODE] 盘中板块改用数据侧的板块分类与成分数

- 数据侧在板块榜里加了 `constituent_count`、`board_class`、`label_reason`（f816f48）。页面与 AI 摘要改为隐藏 `board_class=market_label` 的板块，删除 CODE 自己的名称清单；成分股少于 10 只的板块按 `constituent_count` 隐藏（为空时视为未知，不当成 0）。页面说明写明隐藏的类别和成分统计日期；没有分类字段时不按名称猜，照实说明。
- 真实数据（2026-09-24 收盘）：隐藏 19 个全市场标签和 76 个成分股少于 10 只的板块，710 个板块里显示 615 个；涨幅榜前列由林业（5 只）等小板块变为风电零部件、风电设备、纺织制造等。
- 测试：`test_intraday_sectors.py` 过滤测试改为 3 项（按分类隐藏与开关、只数已知才隐藏、无分类不按名称隐藏）。
- 全量回归（云端副本）：2,078 项通过；数据侧 `test_research_provider` 缺 pytest 未运行。

### 2026-09-24｜[CODE] 数据中心（第一部分：数据目录）

- 新增日常页“数据中心”（导航最后一项）：读取数据清单，显示可用/待审查/未就绪/已停用数量和最近一次审查日期；全部数据集按状态、类型排序，可按状态、类型筛选和按名称/内容/说明搜索；列出类型、内容、覆盖（从清单文字读出的截止或观察日期，页面注明不是实际检查结果）、状态；单击显示位置/接口、格式、覆盖与用途、使用说明。
- 更新状态、预览与试查询、更新与归档三部分等数据侧接口：向数据侧提需求（Project 文档 `claude/niuniu-data-request-data-center.md`，建议清单 ID `data_status_service`、`data_preview_service`、`data_update_jobs`），页面按清单状态显示“尚未提供/待审查/已开放”。
- 旧“数据中心”（实验存档的行情快照与股票池、Baostock 参考数据获取、归档日线研究输入）暂留在专业模式，新页面底部可打开；其中由 CODE 直接获取 Baostock 数据的按钮与“外部数据接口归数据侧”的约定冲突，待数据侧更新任务接口到位后移除。
- 测试：新增 `test_data_center.py` 3 项（覆盖日期解析 6 种写法、目录行/筛选/排序/服务状态、页面列表/搜索/详情）；导航测试更新为 10 个日常页。
- 全量回归（云端副本）：2,083 项通过；数据侧 `test_research_provider` 缺 pytest 未运行。

### 2026-09-25｜[DATA] 数据中心接口（状态、预览、更新与封存）与封存机制

- 新增 `src/quantlab/data/data_services.py`：`DataStatusService`（只读状态索引、封存清单和当天回执，0.4 秒返回）、`DataPreviewService`（READY 文件预览、9 个查询接口试查）、`DataUpdateJobs`（7 个任务：收盘后日常更新、盘中记录器启停、补某一天、封存、核对、撤销封存；先计划后执行，后台独立进程，运行记录在 `catalog/jobs/runs/`）。新增 `scripts/collect/job_runner.py`。
- 新增 `src/quantlab/data/day_seals.py`：按日封存清单 `catalog/seals/YYYY-MM-DD.json`（文件、字节、SHA-256、行数、采集时间、来源），次日发布与可补采的数据标待封存、补采后追加为新版本，当天观察未采到的标无法补回；核对与撤销（整份移到 `_revoked/`，不删除）。公开数据采集器遇已封存的分区拒绝写入。2026-09-24 已封存（第 1 版，24 个文件，核对无误）。
- 新增全市场个股盘中快照（`src/quantlab/data/stock_intraday.py`，并入盘中记录器，09:25/10:00/11:30/14:00/14:57/15:00）：约 5,570 只一次约 10 秒，收盘后实测 200 只抽样与腾讯一致。新增同花顺、东财人气榜两项当天观察数据（首采 2026-09-25）。
- 数据清单新增 §3.5：三个接口 `READY`，另有 `day_seals`、`hot_rank_ths`、`hot_rank_em`（READY）与 `stock_intraday_snapshot`（首个交易日有数据后改 READY）。
- **事故与修复**：状态索引首版有变量重名 bug，逐证券统计时把索引 JSON 写进了 4 个数据文件（日状态 sz.301699、日K与 5 分钟 sz.301686、前复权日线 sz.302132）。发现后立即修复代码并加回归测试；4 个文件逐个从更新前备份恢复、用 Baostock 重取缺的日子（日K/5 分钟补 09-23、日状态补 09-24），前复权按原计划单独重建；被覆盖的内容与修复记录留在 `artifacts/data-remediation-20260924/overwritten-files/`。复查五个目录全部文件头正常。受影响的是用户正在运行的 09-24 增量：日K不受影响（开跑前已校验），5 分钟原计划记录的是旧校验码会拒绝执行，已生成替换计划 `0d079771…` 和 `run-20260924-min5-r2.command`。
- 测试：`tests/test_data_services.py` 7 项（封存/待封存/核对/篡改/撤销、计划与阻止条件、后台运行、状态索引不写数据文件）。
- 同日续：经用户授权，盘中记录器改为打开牛牛时自动启动（`DataUpdateJobs.autostart`，只允许这一个任务；非交易日、已收盘、已在运行、今天手动停止过或已结束时不启动）。两个启动脚本增加一行后台调用 `scripts/collect/autostart.py`，日志写 `artifacts/autostart.log`。后台任务的记录器和 5 分钟更新用 `caffeinate` 防止 Mac 睡眠。测试新增 1 项，共 8 项。

### 2026-09-25｜[CODE] 数据中心接入数据侧的状态、预览、更新与封存接口

- 数据中心页上方分四个分区：数据目录、更新状态、预览与试查询、更新与封存；后三个在清单里对应接口（`data_status_service`、`data_preview_service`、`data_update_jobs`）为 READY 时才可点（新文件 `desktop/data_services_ui.py`）。
- 更新状态：各数据集最新日期、最近更新、行数、文件数、健康（正常/落后/异常/未知，颜色区分）与原因、已封存到；盘中记录器显示今天记录与失败次数；汇总数字；最近 30 天封存（版本、文件、行数、待封存、核对结果、问题数）；可只看有问题的。
- 预览与试查询：READY 的文件数据按 code/date 过滤看前 N 行（列类型与说明放在表头提示）；READY 且数据侧开放试查的接口按 `query_schema` 生成参数表单（必填、枚举下拉、示例），试查一次并显示来源、数据时间和提示。
- 更新与封存：任务下拉与参数表单来自 `list_jobs`；“生成计划”显示步骤（采集/跳过/封存/核对/启动/停止、数据、日期、是否覆盖）、预计耗时、有效期、提示；`blocked_reason` 不为空时不能执行；“确认执行”调用 `run`；运行记录（手动/自动启动、状态、进度、步骤）每 3 秒刷新，单击看结果、错误和增量日志，运行中可取消。所有调用在后台线程，错误只显示在本分区。
- 旧数据中心里由 CODE 直接获取 Baostock 行业/股本/交易状态的按钮移除（改由数据侧任务采集），对话框代码与其测试保留。
- 测试：新增 `test_data_center_services.py` 4 项（接口未 READY 时分区不可点、状态与封存表、文件预览、任务计划被阻止/确认执行/运行记录/日志/取消，任务用替身不起后台进程）；状态和预览用数据侧测试里的临时数据湖。
- 未验证：本机 VM 只挂了数据湖目录、没有 `catalog/`，无法用真实数据根跑状态接口；Mac 真实窗口未验收。
- 全量回归（云端副本）：2,095 项通过（含数据侧新增的 `test_data_services`）；数据侧 `test_research_provider` 缺 pytest 未运行。

### 2026-09-25｜[DATA] 代码检查缺陷修复（宿主按用户授权修改）

- 用户授权修复 2026-09-24 对 `85ab2e9` 检查发现的问题，本条是其中 DATA 侧的 15 项，逐项现象、原因、改动和测试见[缺陷修复记录](../archive/testing/20260925-代码检查缺陷修复记录.md)。改动由宿主开发者完成，未经数据侧另行复核；没有碰数据盘上的数据文件，也没有重新采集。
- `data_services.py`：“补某一天”改用覆盖该日的最新参考快照日历，没有覆盖时计划直接阻止（此前执行时找不到当日快照而失败）；交易日补采上一交易日到前一天每个自然日的公告目录，以及其中周末、节假日的机构调研、股东增减持（此前每周五、周六的公告目录会漏）；任务启动在 `catalog/jobs/.lock` 下串行、计划和状态原子写，两个启动脚本同时打开只起一个记录器；以 `runner.lock` 判断后台任务存活，只对确认活着的任务进程组发信号；启动失败记 `failed`；`cancel()` 返回实际结束状态；预览的总行数、`date`/`code` 校验、920 代码归属北交所，必填日期可填 `today`；日志句柄不再泄漏。
- `day_seals.py`：撤销后重封的版本号接着编，不再覆盖 `_history` 里的旧版本；撤销时核对结果一并移走。
- `sector_intraday.py`：涨跌停按交易日取 `trading/price_limit_regime.py`（主板 ST 自 2026-07-06 起 10%，302 开头 20%），规则表未覆盖的板块不推算。
- 采集脚本：记录器单实例（`catalog/jobs/sector_recorder.lock`），成分刷新分段、不再阻塞开盘，个股快照只在各时点截止前拍、过期记 `missed` 并记录迟到秒数（`stock_intraday.SNAPSHOT_DEADLINES`）；成分快照断点文件坏行跳过重取；收盘更新里成分快照失败只记失败项，前复权未完成时其余步骤照常执行、运行最后记失败。
- 数据清单同步更新涨跌停比例、记录器、个股快照截止、任务锁与补采范围、封存版本号的说明。
- 测试：`test_data_services.py` 新增 10 项，新文件 `test_collect_intraday.py` 8 项，`test_sector_intraday.py` 新增 1 项、改 1 项；这些测试放回修复前的代码全部失败。全量结果见下条。提交 `c6fcf30`。

### 2026-09-25｜[CODE] 代码检查缺陷修复

- `pyproject.toml` 声明 `numpy>=1.24,<3`、`pandas>=2.0,<4`，离线环境导出的基础包加入二者（此前干净安装后 `niuniu-sentiment-cycle` 报缺 numpy）。
- `README.md`、`README.en.md`、`docs/guide/data-and-evidence.md` 改为按数据清单描述：`realtime_quote`、`fuyao_context`、`market_snapshot` 已于 2026-09-24 `READY`，`stock_fund_flow_daily` 仍待审查。
- 数据中心“更新与封存”：取消后按实际结束状态提示；运行日志只接受最新一次读取的结果，重复选中或读取较慢时不再重复追加。
- 测试：`test_data_center_services.py`、`test_offline_environment.py` 各新增 1 项。
- 全量回归（云端副本，装齐全部依赖，Qt 离屏）：2,125 项全部通过，0 失败、0 跳过（修复前 2,104 项，两侧共新增 21 项）；新增和改动的 22 项放回修复前的代码全部失败，同文件原有 22 项修复前后都通过。`scripts/check_docs.py`、`git diff --check` 通过；新虚拟环境 `pip install .` 后相关模块导入正常。
- 未验证：真实数据盘、Mac 真实窗口、交易日盘中记录器与供应商请求。
- 提交：`c6fcf30`（DATA）、`3d3e338`（CODE），以及包含本条、缺陷修复记录、状态页和归档索引的文档提交；先普通推送到 `origin/claude/lucid-dirac-xhls8w`，用户确认后快进推送到 `origin/main`（`85ab2e9..0fa2ff3`，远端 SHA 已核对）。

### 2026-09-25｜[CODE] 开发工作台六职责协作

- 用户批准直接在牛牛工作台提出需求，由系统按 LEAD / DATA / CORE / AI / APP / QA 开发；在 `85ab2e9` 基线上创建独立 feature worktree 实施，不在运行中的主目录改代码，不触正式数据、采集、可见客户端或用户服务。
- 保留 P10 四种过程权限与 Human Merge，新增专业领域、精确文件归属及 DATA 跨目录例外；六角色完整模型配置由宿主设置并随任务冻结，模型不能自选配置或扩写范围。LEAD/QA 无写入权，四个实施域按需要调度。
- 新增只读自然语言规划及计划确认：原始需求、基线分支/SHA、文件负责人、测试、接口依赖和模型绑定；30 分钟过期，需求/基线变化需重做。桌面确认后自动运行，显示专业角色/过程角色/状态/模型/次数及事件；保留高级入口，同源 CLI 增加规划、审批和角色配置。
- 实施默认最多两人并行，QA 与写入互斥；失败依赖、依赖环、重复执行、三次子任务上限和有限协调轮次均受程序约束。重开原任务使下游 QA 失效，不能跳过失败或另建同路径写入者规避预算。增加 Git common-dir 的受管执行锁；外部宿主编辑不受该锁强制控制。
- 大文件支持分段读取和 SHA 保护的唯一文本替换；已有文件写入必须 CAS。测试强制从当前 worktree 导入源码并留证，使用离屏 Qt、临时数据根、去掉常见凭据环境变量；零测试或全部跳过拒绝。人工合并重新校验最终测试/审核/验收指纹，关闭了验收后改动仍沿用旧结果的间隙。
- **验证边界**：新测试使用脚本化模型传输调用正式角色工具、临时 Git 仓库、真实 Python 测试和实际本地提交；有四实施域闭环与故意失败后返工场景。不是实际付费模型开发，不声称全项目回归或真实桌面验收。测试进程不是 OS 沙箱，主分支前进时仍需宿主处理并重新验收，不自动 rebase/push/部署或扩大数据/研究授权。
- 首轮后端 16 项中唯一失败是测试误假定零测试必然 exit=0；本机 Python 返回 5。修正测试为核对实际测试数量与拒绝结果，未放松生产验收门槛。扩展后 23 项后端已全部通过，界面初轮 7 项通过，最终统计以下方收尾回归为准。
- 工具限制：Lexar 卷不支持 MCP 事务式新建所需操作，失败已完整回滚；新文件改为只在本任务工作区排他创建，已有文件仍用 SHA 保护的精确编辑。无第三方密钥或行情提交。
- 最终回归：先在独立提交 `58a1a30` 完成 10 模块 70 项，再基于并行任务已推送的 `origin/main=46b2539` 整合为 `4db5572`，同样 10 模块 **70 项全部通过，0 失败、0 错误、0 跳过**（旧 Dev Studio 14、六职责后端 23、离屏界面 8、HTTP/Codex 协议 15、聊天预算 2、研究 AI Team 8）。所有 Python/Agent Memory 指纹在回归期间稳定，127 份文档/654 个本地链接检查通过，`git diff --check` 通过。另在实际 Lexar 卷创建临时 Git 仓库，四实施域、真实测试进程、独立 QA 到本地合并的整条路径通过；临时样本已清理，未触正式数据。
- 并行整合：只在独立工作区处理 `status.md` / `changelog.md` 两处追加位置冲突，双方章节完整保留；其他 DATA/CODE 修复按其原提交继承，本补丁未再次修改其数据口径。主目录当时有两份未跟踪的缺陷修复文档/测试，经逐字节 SHA 校验与远端已提交版本完全一致；同步前须再次核对无独有内容，保留原字节与回执后才允许快进，不 reset、不 force push。
- 可复核证据位于 `artifacts/devstudio-six-roles-20260925/`：`precommit-results.json`、`final-results.json`、`integrated-results.json`、逐模块日志、`lexar-smoke.json`。功能代码以 `4db5572` 为标识；最终主分支同步/推送的 SHA 以本轮工具回执和交付回复为准，不将测试通过冒充远端推送成功。

### 2026-09-25｜[CODE] 六角色本地 Pi 模型接入

- 用户要求六角色统一使用本地 Pi 的 GPT-6 Luna，并明确授权真实用户端操作及模型调用。在独立 worktree 增量增加 `pi_sdk`、自定义 `provider/model` 和 `pi_path`，配置页新增复制当前配置到全部角色。
- 新 `devstudio/pi_provider.py` 与打包的 `pi_bridge.mjs` 经 Node 调用本机已安装 Pi ModelRuntime，复用 Pi 登录，不提取/展示密钥；不启动 Pi AgentSession、不加载插件、skills、项目指令或内置读写/shell。精确模型身份、工具白名单、调用/轮次/上下文/超时与停止受宿主约束，无自动模型回退。
- 本机 Pi 0.85.1 已发现 `openai-codex/gpt-6-luna` 且可用，真实一次宿主工具调用往返成功（返回指定 nonce）。离线回归 10 模块75项通过（新Pi协议/配置13项、原开发工作台与六职责45项、HTTP/Codex15项、聊天预算2项）。真实传输与日志在 `artifacts/pi-luna-validation/`，不是股票功能验收。
- 真实牛牛窗口已打开；原生辅助功能操作被macOS以未授权拒绝，已告知用户开启WebCodex/Runner辅助功能。未用其他渠道绕过OS界面控制权限，后续先通过同源正式工作台服务继续验证。搜索功能将由正式六职责流程实际模型实施，不由宿主代写。

### 2026-09-24｜我的股票添加框本地候选提示

- 我的股票输入框消费当天已有本地股票快照，名称/代码片段不区分大小写匹配，固定最多显示12项并稳定排序；提示同时展示名称与代码。清空、无结果或异常时关闭并清空提示。
- 候选选择只填入规范代码，不自动提交自选；添加仍需显式点击既有“添加”动作，原持仓/成本和添加校验保持不变。不访问网络、不扫描大行情数据、不改 DATA 事实或用户自选存储合同。
- 使用指南同步说明候选与显式添加的边界。离屏Qt合成数据回归新增键盘选择后检查代码填入及点击添加提交；本记录不代表测试已执行，冻结回归由独立 TESTER 报告。

### 2026-09-25｜[CODE] 日内做T：底仓做T 回测与分时回放；数据清单解析修复

- 用户要求基于数据侧新开放的 `gst_intraday`（清单 §3.6，16 只股票 2019-05-29 至 2024-10-24 的 3 秒成交与 1 分钟K）做日内板块和日内策略，交易方式选“底仓做T”，策略思路来自用户提供的文章《日内交易策略——当天收盘前必须走人》（PDF）。
- 新包 `quantlab.intraday`：`gst.py` 只读打开 DuckDB，只按 symbol/date 读 `bars_1m`、`stock_days`、`stocks`、`ticks`，不读 `*_all`、不写库；涨跌停由 `stock_days.prev_close` 按 `price_limit_regime` 推算，ST 取 `security_status_baostock_v2`。`t0.py` 底仓做T 引擎：下一根开盘价成交加滑点、每分钟最多 20% 成交量、整分钟封涨停不能买/封跌停不能卖、开仓单 3 分钟撤单、14:50 强平、15:00 收盘集合竞价、未回补部分按收盘估值单列、日亏 1% 停手、每天最多 20 笔；佣金最低 5 元、过户费、卖出印花税 2023-08-28 前 0.1% 后 0.05%；同时记录不计滑点和费用的“信号本身”收益。`strategies.py` 把文章三种策略改写为底仓做T；`backtest.py` 分训练期/检验期、分年、分股汇总并保存到 `_intraday/runs/`。
- 新页面“日内做T”（日常工作台第 4 个）：策略回测（参数、三档费用预设、底仓规模、股票范围、训练期截止日，后台运行可停止、显示进度）与分时回放（价格、VWAP、昨收、涨跌停、主动买卖量、买卖点标记，交易明细双击直达、可对单日模拟）。
- **全量实测**（Cowork 虚拟机读取同一份数据盘上的库，16 只股票 20,063 个股票日，默认参数、普通佣金、0.1% 滑点；训练期 ≤2022-12-31）：开盘突破训练期 −14.71 bp/天（t=−16.6）、检验期 −11.23（t=−8.2），每笔不计成本 −1.2 / +1.9 bp；VWAP 回归 −46.33（t=−57.3）/ −43.54（t=−39.4），每笔 −0.8 / −0.7 bp；尾盘动量 −0.71（t=−7.5）/ −0.42（t=−2.9），每笔 +2.6 / +3.5 bp。三种策略的信号本身几乎没有优势，来回约 35 bp 的滑点和费用决定了结果。16 只全量回测每种策略约 18–35 秒（虚拟机）。抽查一笔开盘突破交易，区间、成交价、滑点与分钟数据一致；涨跌停规则分布：主板 10% 17,396 天、创业板 20% 1,980 天、创业板改革前 10% 533 天、ST 5% 154 天。
- **数据清单解析修复**：数据侧在 §3.6 增加了表结构说明表（`| `ticks` | 视图 | …`），旧解析器把 §3 里所有以反引号开头的表格行都当数据条目，于是整份清单报“列数不对”，所有 READY 判断（盘中板块、数据中心、实时行情等）都会失败。改为只把首列表头为“数据 ID”的表当数据条目，真正数据表里的坏行仍然拒绝。新增回归测试。
- 测试：新增 `test_intraday_t0.py`（24 项：成交、滑点与费用、最低佣金、成交量上限、涨跌停阻断、未回补、强平与收盘竞价、交易时段、日亏停手、笔数上限与 T+1、三种策略、不看未来、统计；临时 DuckDB 上的只读、可用日、创业板 2020-08-24 涨跌幅切换、ST、逐笔顺序、回测与保存）、`test_intraday_page.py`（3 项离屏 Qt）、清单解析 1 项；导航测试更新为 11 个日常页。全量回归（云端副本，Qt 离屏，4 路并行）：315 个测试模块共 2,191 项通过；唯一例外是一直需要 pytest 的 DATA 侧 `test_research_provider`（本环境未装 pytest，未运行）。部分桌面测试模块在全部通过后解释器退出时返回 139（离屏 Qt 退出时崩溃），单独运行正常。
- 未验证：Mac 真实窗口（按约定不操作真实客户端）、Mac 上经数据清单路径打开数据库（逻辑与测试相同，路径由清单给出）。

### 2026-09-25｜[CODE] 日内做T：找到两个检验期为正的尾盘先卖后买策略

- 用户要求“找到合适的日内策略”。研究记录见[日内做T 策略研究](../archive/intraday/20260925-日内做T策略研究.md)，复算脚本 `scripts/research/gst_intraday_t0/`（开发者一次性研究，只用于人工复算）。
- 成本校准：用 `gst_intraday` 五档盘口量出这 16 只股票的买卖价差多数时间为 1 个价位；引擎新增 `Costs.slippage_ticks`（按价位计滑点），页面默认改为“普通佣金 + 每边 1 个价位”，原 0.1% 口径保留为可选项。
- 训练期（≤2022-12-31）约 650 种组合筛选，唯一稳定的规律是“下午弱且大盘也弱时尾盘继续弱”；据此新增两个只做先卖后买的策略：`weak_close` 尾盘弱势（14:00 个股跌 ≥3% 且 16 只平均跌 ≥1%）、`close_score` 尾盘打分（14:00 七指标线性打分，系数只用训练期拟合后固定，预计跌 ≥20 bp）。卖出为 14:01 开盘价减 1 个价位，收盘集合竞价按收盘价买回（引擎新增 `T0Config.close_in_auction`）；股价 <8 元不做。
- 读取层新增 `GstIntraday.market()`：在 DuckDB 里按日期范围算 16 只股票每分钟的等权平均涨跌（每只取当时最后成交价，少于 8 只时为空），随 `Day.market` 提供；仍只读、按日期和股票过滤。
- **检验期只跑一次**（普通佣金、每边 1 个价位）：尾盘弱势 176 笔，每笔扣费后 +28.5 bp（训练期 +13.9），按日期聚类 t=1.6；尾盘打分 210 笔，+38.0 bp（训练期 +16.6），t=2.1。万 1 免五、0.1% 滑点、每边 2 个价位下检验期仍为正（+23～+42 bp）。对整笔底仓的年化贡献约 +0.9%～+1.4%，证据中等；“大盘”为 16 只平均而非指数。文章三种策略在新口径下仍大幅亏损。
- 测试：`test_intraday_t0.py` 增至 30 项（价位滑点、集合竞价买回、涨停收盘买不回、两个新策略的触发条件与打分手算核对、市场平均只用当时已知价格）；页面、导航与清单解析测试通过。全量回归（云端副本，Qt 离屏）：2,197 项通过，唯一例外仍是需要 pytest 的 DATA 侧 `test_research_provider`（未运行）。

### 2026-09-25｜[CODE] 日内做T 第二轮：上午打分（逐年滚动）

- 用户认为上一版策略不行，要求继续实验。第二轮约 800 种组合（两头集合竞价、挂单网格、突破、收盘竞价扫描、多时点打分、逐年滚动比较变体），过程见[日内做T 策略研究 §7](../archive/intraday/20260925-日内做T策略研究.md)。挂单网格和突破全部亏损；低开回补检验期不稳。
- 新策略 `morning_score` 上午打分（逐年滚动）：10:00、10:30 用 10 个指标（个股与 16 只平均的涨跌、偏离均价、主动买卖差、当天位置、跳空等）预测到收盘的涨跌，每年只用之前年份拟合的系数（`intraday/morning_models.py`），预计跌 ≥20 bp 先卖后买、收盘集合竞价买回。正式引擎：2021–2022 每笔扣费后 +71.0 bp（t=3.5），2023–2024 +36.0 bp（456 笔，胜率 62%，t=2.1），2023 年持平；动用一半/全部底仓年化约 +3% / +6%，最大回撤约 2%。另加入 `intraday_score` 全天打分（检验期 +23.9 bp，t=1.7）和 `gap_rebound` 低开回补（对照，不推荐）。
- 引擎：允许策略在 09:25 集合竞价上决策、开盘第一笔成交；读取层的大盘数据增加“比开盘涨跌”和平均跳空，按“截至该分钟”取值；新增 `slot_grid` 与研究网格对齐。回测 16 只全量约 25 秒（虚拟机）。
- 测试：`test_intraday_t0.py` 35 项（新增逐年模型选择、低开回补竞价决策、分钟网格、全天打分手算核对、大盘截至取值）；全量回归（云端副本，Qt 离屏）2,202 项通过，唯一例外仍是需要 pytest 的 DATA 侧 `test_research_provider`（未运行）。

### 2026-09-25｜[CODE] 日内做T 第三轮：趋势突破

- 用户问有没有趋势突破策略。训练期约 150 组（开盘区间、昨日高低点、唐奇安通道 × 方向 × 放量/大盘/均价线/主动买卖 × 收盘竞价/跟踪止损/均价线出场 × 多日趋势），见[日内做T 策略研究 §8](../archive/intraday/20260925-日内做T策略研究.md)。不加过滤的突破全部亏损（约等于成本），向上突破没有一组稳定为正，止损类出场更差。唯一接近可用的“30 分钟区间跌破 + 16 只平均跌 ≥1% + 放量 3 倍”训练期每笔 +18 bp、检验期 +10 bp（t=0.7），不显著。
- 产品：新增可调的 `range_breakout` 趋势突破（开盘区间）策略作对照（区间分钟、方向、大盘门槛、放量倍数、跟踪止损、最低股价）；读取层给每天加上前一可用日成交量 `Day.prev_volume`。
- 测试：`test_intraday_t0.py` 36 项（新增突破的首次突破、大盘与放量过滤、方向、前一日成交量）；全量回归（云端副本，Qt 离屏）2,203 项通过，唯一例外仍是需要 pytest 的 DATA 侧 `test_research_provider`（未运行）。

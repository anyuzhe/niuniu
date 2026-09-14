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

## 3. 当前产品快照（2026-09-14）

当前牛牛已经从“因子实验平台”演进为三层体系：

- **Trading Desk**：今日交易、主线市场、股票中心、持仓计划、复盘、Decision Frame、Strategy Intent。
- **AI / Playbook 层**：AI Team、Peer Review、Git-first Agent Memory、Expert Playbook Lab、前瞻预测冻结。
- **Research Lab**：因子、理论、PIT、Campaign、Alpha Factory、Watch、统计验证、执行回测、数据归档。

当前正式代码全仓基线：**763 passed / 0 failed / 0 skipped**。
当前已完成阶段：P1～P8；P8.5 已进入 C 阶段的真实前瞻验证。
尚未正式完成：P9 Agent Scorecard、P10 Dev Studio、P11 System Health、P12 移动端、P13 Paper→Real 完整交易闭环。
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

仍未正式完成：P9 Agent Scorecard；P10 Dev Studio + Dynamic Agent Orchestrator 的产品化落地。

### 7.3 Research Lab

已完成：数据/PIT、Factor、理论、结构事件、组合评分、Holdout、Walk-forward、Bootstrap、多重检验、独立成交回测、Campaign、Alpha Factory、Watch、复算归档。

仍需加强：approval-time actual-byte freeze、Research Session Grant、更多 Strict PIT 历史原始资料、Watch 序贯统计。

### 7.4 Expert Playbook Lab

已完成：来源归档、候选全集、selected/unselected、规则版本、历史回放、前瞻冻结、防回填、Selection/Execution Access 分离。

当前阶段：P8.5-C 前瞻验证刚开始，需要积累连续真实样本后才能评价稳定性。

## 8. 尚未完成的正式阶段

- **P9 Agent Scorecard**：按任务类型评价 Coverage、证据正确性、计划完整性、及时性、约束违规、Playbook 候选覆盖与风险识别；第一阶段只展示，不自动调模型权重。
- **P10 Dev Studio + Dynamic Agent Orchestrator**：DevTask、隔离 worktree、Main Agent 动态拆 Subagent、path lease、Tester、Reviewer、Human Merge。
- **P11 System Health**：统一展示数据新鲜度、PIT blocker、JobQueue、daemon、MCP、日志、通知、磁盘与最近错误。
- **P12 移动端 / 机器人**：复用同一 MCP/API/Decision/Stock Dossier，不建立第二份交易状态。
- **P13 Paper → Real**：先长期 Paper / Shadow，再单独立项真实券商接入；自动实盘不是当前默认能力。

## 9. 当前推荐的后续主线

1. 连续运行 P8.5-C，积累真正“先预测、后揭晓”的样本。
2. 建立正式 Real-time Market Snapshot 服务，统一竞价、盘口、分钟行情时间戳与哈希。
3. 建 Daily Playbook Scanner：市场节点 → 目标身位 → 全候选 → AUCTION/R1 相对选择。
4. 把 Playbook 输出接入 Trading Cockpit、Strategy Intent 和 Paper Account，形成每日自动闭环。
5. 样本足够后再做 P9 Agent Scorecard。
6. 随后推进 P10 / P11 / P12；P13 真实账户最后单独评审。
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

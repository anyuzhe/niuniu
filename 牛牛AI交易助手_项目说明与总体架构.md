# 牛牛 AI 交易助手：项目说明与总体架构

- 文档性质：当前项目定位、总体架构和长期边界的权威说明
- 架构口径更新：2026-09-14
- 适用仓库：`github.com:anyuzhe/niuniu`
- 当前稳定基线：P8.8-A/B/C 核心长期 Paper 闭环已完成，全仓 `842 passed / 0 failed / 0 skipped`

## 1. 一句话定位

牛牛不是“研究某一个高手”的软件，也不是单纯的因子回测平台。

> **牛牛是一个把多来源交易知识持续形式化、结构化验证，并通过 Daily Scanner、AI Team、Decision Ledger 和复盘机制形成可追溯交易研究闭环的个人 A 股 AI 交易研究系统。**

系统真正长期积累的对象是**可版本化、可验证、可前瞻检验的 Playbook**，而不是某一个交易者的名字。

“期末50分”只是首个 `TRADER` 类型来源试点；未来 92科比、炒股养家、Zarili、用户自己的经验、公开方法、历史统计和牛牛自身复盘结论都应进入同一来源框架。
## 2. 两个架构视角

牛牛同时有两个互补的架构视角，不能混为一张图。

### 2.1 产品模块架构

```text
牛牛 AI
├─ Trading Desk
│  ├─ 今日交易
│  ├─ 主线市场 / Theme Matrix
│  ├─ 股票中心 / Stock Dossier
│  ├─ 持仓计划 / Strategy Intent
│  └─ 复盘中心 / Decision Timeline
├─ AI Team
├─ Research Lab
│  ├─ Factor / Experiment / PIT / Campaign / Factory / Watch
│  └─ Trading Knowledge / Playbook Lab
├─ Dev Studio（P10，尚未产品化完成）
└─ System Center
```

产品模块架构回答“软件怎么组织”。
### 2.2 交易知识与决策循环

```text
交易知识 / 策略来源
        ↓
经验提炼 / Playbook Hypothesis
        ↓
规则化 / 状态化 / 指标化
        ↓
Git Markdown + Structured Evidence 双轨存储
        ↓
历史数据 / Strict PIT / 执行验证
        ↓
Daily Scanner：PREP → AUCTION → R1/R2/R3
        ↓
AI Team 独立研究 + Chief 综合
        ↓
Decision Ledger / Strategy Intent
        ↓
Paper / Execution
        ↓
D1 / D2 / D3+ 结果评价与复盘
        ↓
新经验 / 新反例 / 新规则版本
        └──────────────→ 回到知识提炼
```

这个循环回答“知识和证据怎样流动并形成交易决策”。
## 3. 交易知识 / 策略来源层

最上层不再是“期末50分”，而是通用 `StrategySource` 概念。

```text
StrategySource
├─ TRADER                实盘交易者 / 高手
├─ USER_EXPERIENCE       用户自己的长期经验
├─ PUBLIC_METHOD         公开课程 / 书籍 / 文章 / 方法
├─ HISTORICAL_CASE       历史行情案例
├─ STATISTICAL_DISCOVERY 市场统计规律 / 量化发现
└─ SYSTEM_REVIEW         牛牛长期前瞻与复盘产生的新经验
```

一个来源可以支持多个 Playbook；一个 Playbook 也可以由多个来源共同支持或反对。

因此未来关系应是多对多，而不是“一位高手 = 一套策略”。例如高低切 Playbook 可以同时引用多个交易者案例、用户经验和统计证据。

### 当前兼容状态

当前代码已经有 `ExpertSource`，它是最早为实盘高手试点建立的正式对象。现阶段**不强行破坏性重命名**；在兼容迁移前，将它视为 `StrategySource(type=TRADER)` 的现有具体实现。

后续引入通用 `StrategySource` 时，必须保留已有 `ExpertSource` ID、来源哈希、Case 和 Validation 的可追溯性。
## 4. 知识提炼与 Playbook 层

来源不是规则本身。任何外部经验进入牛牛后，先作为假设而不是生产真理。

提炼对象包括：

- 市场节点：主升、分歧、修复、退潮、极端风险等；
- 主线、龙头、身位、主动性、带动性、拥挤度；
- eligibility：谁进入候选全集；
- selection：为什么在候选中选择 A 而不选择 B；
- veto：什么条件下明确不做；
- entry / confirm / invalidation / hold / add / reduce / exit；
- execution profile：`STANDARD_ACCESS / QUEUE_DEPENDENT / UNKNOWN`。

第一状态必须是 `DRAFT`。冻结规则前要保留失败样本、未选样本、不可交易样本和来源完整性限制。

“规则能重建高手选择”与“规则有可交易 Alpha”是两件不同的事；`Selection Alpha`、`Execution Access` 和最终账户收益必须分开验证。

## 5. 双轨知识与证据存储

牛牛不把所有知识塞进 Markdown，也不把结构化证据塞进聊天记忆。
### 5.1 Git + Markdown：人类可读规则与 Agent Operating Memory

Git 中保存：

- Playbook 人类可读定义、概念、适用条件和版本理由；
- 开发规范、Agent 规则、工作流和权限边界；
- 已验证工程经验、故障复盘和架构决策；
- 用户明确确认的长期项目约定；
- 研究结论的摘要和局限说明。

这些内容要求可 diff、可 review、可回滚。向量索引未来只能作为可重建检索层，不是权威事实库。

### 5.2 Structured Evidence：数值与时点事实的权威源

结构化存储继续保存：

- `ExpertSource / StrategySource` 来源身份与哈希；
- `PlaybookDefinition / PlaybookCase / CandidateSet / SelectionDecision / Validation`；
- `MarketSnapshot / Decision Ledger / Theme Snapshot / Watch`；
- PIT 资格、实验 run、统计检验、成交、持仓、收益和执行审计。

Markdown 可以解释这些对象，但不能覆盖或替换原始结构化事实。
## 6. 数据与验证层

Playbook 不能只靠文字经验进入当天交易。任何规则都必须经过与目标口径匹配的数据验证。

验证层包括：

- 历史行情、DailyMarket 增量与 MarketSnapshot；
- `research_only / retrospective_reference / strict_pit / official_rule_covered` 数据资格；
- 候选全集重建，保留 selected / unselected / no-trade / 失败样本；
- Holdout / Walk-forward / Campaign / Bootstrap / 多重检验；
- T+1、停牌、涨跌停、费用、滑点、资金占用与成交可达性；
- 前瞻 `SYSTEM_PREDICTION` 与历史 `HUMAN_RECONSTRUCTION` 严格分离。

验证目标至少拆成三件事：

1. **Eligibility**：谁应该进入候选全集；
2. **Selection**：为什么在候选中选择某些股票；
3. **Execution / P&L**：普通账户能否成交，以及成本后结果如何。

其中任何一层成立，都不能自动推出下一层成立。
## 7. Daily Scanner 与当天决策链

已经形成的当天运行主线是：

```text
前一交易日收盘 / PREP
  ↓ 全市场事实、市场节点、目标身位、CandidateSet
09:25 AUCTION
  ↓ 竞价强弱、拥挤度、可成交性
09:35 R1
  ↓ 首个完整5分钟的主动性、相对强度、执行访问
R2 / R3
  ↓ 盘中复核与收盘定稿
Decision Ledger
  ↓
Strategy Intent
```

`Daily Scanner` 是规则运行器，不是模型自由选股器。它读取冻结事实和冻结规则；证据不足时输出 `UNKNOWN / NO_TRADE / PARTIAL`，不得为了每天有结果而强行推荐股票。

当前已完成 PREP 全市场扫描、MarketSnapshot、AUCTION/R1 Scanner 和 DailyMarket 增量归档；受控每日编排仍是下一阶段。
## 8. AI Team：独立研究，不做投票系统

当前正式角色包括 Chief Researcher、Market Scanner、Skeptic / Risk Reviewer、Quant Researcher；Developer 只属于未来 Dev Studio。

AI Team 的正确流程是：

```text
Frozen Evidence
   ↓
Independent Agent Opinions
   ↓
Conflict / Missing Evidence
   ↓
Chief Synthesis
   ↓
Decision
```

多 Agent 一致不能当作独立市场证据，也不采用“多数票=正确”。高风险任务才按需 Peer Review；第一轮互盲，Chief 负责综合证据和保留分歧。

未来 P10 的 Main Agent + Dynamic Subagents 是通用任务编排层，不等于当前 P8 已完成能力。Research Profile 共享只读 evidence；Dev Profile 才允许隔离 worktree 内受 path lease 约束的写入。
## 9. Decision、Strategy Intent 与执行层

牛牛必须区分四类状态：

- `Research Opinion`：研究结论或假设；
- `Decision`：某个真实 Frame 下冻结的判断；
- `Strategy Intent`：WATCH / READY / PLAN_OPEN / OPEN / ADD / HOLD / REDUCE / EXIT；
- `Paper Position / Real Position`：只有真实模拟成交或券商回报才改变持仓。

Playbook 命中只能产生候选和条件化计划，不能直接等同于“已买入”。

执行层继续区分 `STANDARD_ACCESS / QUEUE_DEPENDENT / UNKNOWN`。排队能力可以改变成交集合，但不能被包装成 Selection Alpha。

短期路线先接长期 Paper / Shadow，真实券商和自动实盘最后单独立项。
## 10. 结果评价、复盘与系统学习

复盘不是“看涨跌后解释为什么”，而是把原判和后续结果并排保存。

评价至少包括：

- D1 / D2 / D3+ 的后续兑现；
- 候选覆盖、漏选、误选、正确 NO_TRADE；
- 规则版本的适用区间、失败模式和执行限制；
- Agent 的证据完整性、风险识别和修订纪律；
- Selection、Execution Access 与账户收益的分层表现。

系统复盘产生的新经验只能回到 `SYSTEM_REVIEW` 来源，再形成新的 DRAFT 或新版本；不能直接覆盖旧 Playbook。旧版本、失败预测和反例必须永久可追溯。
## 11. 当前实现状态（2026-09-14）

| 层 | 当前状态 |
|---|---|
| Trading Desk / Decision / Dossier / Theme / Frame / Strategy Intent | 已完成主体 |
| AI Team / Peer Review / Git-first Memory | 已完成主体 |
| Research Lab / Strict PIT / Campaign / Factory / Watch | 已有成熟基础 |
| Playbook Lab 六类结构化对象 | 已完成 |
| `ExpertSource` 作为交易者来源 | 已完成，并兼容投影为 StrategySource(TRADER) |
| PREP 全市场扫描 / MarketSnapshot / AUCTION / R1 Scanner | 已完成 |
| DailyMarket 全市场日增量归档 | 已完成 |
| 真实前瞻冻结与防历史回填 | 已完成并已启动样本积累 |
| 通用 StrategySource 多来源对象 | **已完成 P8.6**：六类来源 + 多对多 PlaybookSourceLink |
| 受控每日自动编排 PREP→AUCTION→R1 | **已完成 P8.7 v1**：持久计划、幂等 tick、恢复、错过窗口不回填 |
| Agent Scorecard | P9，尚未完成 |
| Dynamic Agent Orchestrator / Dev Studio | P10，尚未完成 |
| System Health | P11，尚未完成 |
| 移动端 | P12，尚未完成 |
| Prediction→Decision/Intent + PaperPlan | **P8.8-A/B 已完成** |
| 动态跨日 Paper / fill→Intent / Rebalance / D1-D3+ Review | **P8.8-C v1 已完成**；仍需真实前瞻运行样本积累 |
| Real Broker | P13，尚未开始 |

当前生产代码最近完整回归基线：**842 tests / 0 failed / 0 skipped**。
## 12. 后续开发主线

新版路线按“先让知识来源通用化，再让每日闭环自动运行”的顺序推进：

1. **P9 Agent Scorecard**：开始按任务类型评价 Coverage、证据正确性、计划完整性、及时性、约束违规和后续跟踪；先展示，不自动调模型权重。
2. **P10 Dev Studio + Dynamic Agent Orchestrator**：Main Agent、动态 Subagents、隔离 worktree、path lease、Tester、Reviewer、Human Merge。
3. **P11 System Health → P12 移动端 → P13 Paper→Real**。
4. 并行积累真实前瞻 Paper 日志，并继续补 R2/R3 Orchestrator、正式实时 MarketSnapshot provider 与 Strict PIT 原始资料。

并行继续补 Strict PIT 原始资料、approval-time actual-byte freeze、Research Session Grant 与 Watch 序贯统计。

### P8.7 当前边界

Daily Orchestrator v1 是**单交易日、宿主先建计划**的持久状态机：DailyMarket 可显式授权 capture；PREP 使用正式全市场扫描；AUCTION/R1 只消费已经存在的 `LIVE_NEAR_REALTIME MarketSnapshot`。它不会自己选择一个未经审计的实时行情网站，也不会在错过时间窗后生成 SYSTEM_PREDICTION。R2/R3 仍标记为 unsupported，等对应 Scanner/Forward 合同完成后再扩展。

### P8.8 当前边界

P8.8-A/B/C 的核心链路已经完成：`SYSTEM_PREDICTION → Decision/Strategy Intent → PLAN_OPEN → PaperPlan → DynamicPaperAccount → fill receipt → OPEN/HOLD/REDUCE/EXIT → D1/D2/D3+ PaperOutcomeReview`。动态账户允许跨日增加证券，但过去 target 会确定性补 0，且历史 NAV/fill/order 前缀必须保持不变；ADD/REDUCE/EXIT 必须由对应当前 Strategy Intent Decision 驱动，不能借 rebalance 偷偷开新股票。

P8.8-C 的“自动复盘”只生成因果 outcome evidence，不替用户事后自动做 HOLD/REDUCE/EXIT 决策；真实券商、真实资金和自动实盘仍全部留在 P13。当前还需要通过后续真实前瞻运行积累足够长期 Paper 样本，才能评价规则/Agent/账户表现。

## 13. 一句话定义

> **牛牛是一个把多来源交易知识持续形式化、结构化留证、数据验证化，并通过 Daily Scanner 与多 Agent 研究形成可追溯交易决策，再通过长期复盘把新经验沉淀回规则库的个人 A 股交易研究系统。**

它的核心不是复制某位高手，而是建立一个可以不断吸收、反驳、验证和迭代交易经验的长期研究闭环。

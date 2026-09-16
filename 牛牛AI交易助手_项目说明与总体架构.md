# 牛牛 AI 交易助手：项目说明与总体架构

- 文档性质：当前项目定位、总体架构和长期边界的权威说明
- 架构口径更新：2026-09-16
- 当前开发机独立数据根：`/Volumes/Lexar/niuniu-data`；`/Volumes/Lexar/MQC-DATA` 仅保留旧数据副本和历史来源引用。
- 适用仓库：`github.com:anyuzhe/niuniu`
- 当前稳定基线：PIT Universe Receipt v1 与连续 SecurityStatus v2 工程合同已完成（两者真实完整 snapshot 均仍为0）；SecurityStatus 现有真实资料仍为7只证券/14条稀疏 verified statement；2026-09-17 前瞻取证已有三所5,563只review基线与规范addendum，但目标日刷新和归档确认仍未完成；MarketRules v2 首批7个停牌 session及全局深度审计；7个复牌日 exact 算术参考已隔离留证但不具 Strict PIT 资格；External Research Skill v3 已固定真实Git archive/策展包并接入只读Library；AI个股问答已支持明确证券的三源临时只读实时报价；2026-09-16 前瞻 PREP 以 `COMPLETE_NO_TRADE` 留证；全仓基线 **1006 tests / 0 failed / 0 skipped**

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
├─ Dev Studio（P10 v1 已完成）
├─ System Center（P11 v1 已完成）
├─ Mobile / Bot（P12 v1 已完成；同源只读轻客户端）
├─ Broker Shadow（P13-A v1 已完成；只读账户证据 / Dynamic Paper 对账）
└─ RealTrade Readiness（P13-B0 v1 已完成；无券商通道时 fail-closed）
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

### External Research Skill 边界适配

外部专家知识库先进入独立 `research_skills/`，而不是复制到 Daily Scanner 或 execution。包固定由 `skill.yml / SKILL.md / references / method.md / scorecard.md / scripts` 构成；只读审计核资源字节、publication/availability、DIRECT_QUOTE 逐字存在性、原话/推演/待核实事实及“公开观点/披露行为/后续结果”关系。

v2 增加 Git archive/curation 两层：宿主先自行授权并完成 clone；归档器本身禁用 lazy fetch、固定 HTTPS origin/完整 commit/tree、拒绝 dirty checkout/symlink/submodule，把全部 tracked blobs 转为独立数据根中的SHA256对象和append-only receipt。策展器只读取已验证对象和显式 plan，生成内容寻址 DRAFT 包，不把整个上游或其脚本装进牛牛。

审计最多输出宿主可复核的 `PENDING/PARTIAL StrategySource` 预览，绝不执行外部脚本、联网或写 Playbook Lab。外部评分仅代表来源风格相似度；季度机构数据只进入 Theme Matrix / Stock Dossier 中期辅助证据。之后仍必须经过 Playbook DRAFT、牛牛自己的 PIT CandidateSet、Holdout/Walk-forward 与执行验证。

v3 增加只读 Research Skill Library：`research_skills/library.json` 是 Git-clean 宿主授权表，同时固定 control/archive/package snapshot 和 curation plan。服务在每次读取时重新核验 Git archive对象、策展资源及lineage；桌面Research Lab、日常AI助手、AI Team Peer Review和MCP共用精确snapshot的list/get/search/excerpt。来源片段上限6000 UTF-8 bytes并拒绝SCRIPT，所有正文都标为不可信外部数据而非指令。Library没有下载、脚本执行、结构化写入、Decision/Paper或订单接口。

首个 `research_skills/zhengxi` 在 Git 中仍是 source-free `SOURCE_REQUIRED` 控制包；上游已固定到 `304ac3e4...bebb536`，独立数据根 archive 为143文件/11,367,050 bytes。首个 `f9e72ecd...74bf10` 策展包含1份上游访谈、001513持仓/结果、10条claim和1个“说做结果”alignment，现已获只读Library授权，可用于受控检索和假设生成；但上游二次整理不是官方原始字节，source identity需宿主复核且publication time未验证，不能称为已验证 Alpha。

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
- 前瞻 `SYSTEM_PREDICTION` 与历史 `HUMAN_RECONSTRUCTION` 严格分离；
- Official MarketRules 按 snapshot append-only 保存实际 records、官方原文 SHA256 与宿主确认的 publication time，`published_at > available_at` 时 fail-closed；
- PIT Universe 按 effective session append-only 固定完整声明 scope、全部 members、逐来源官方字节和 `published_at / available_at / created_at / cutoff_at`，零散 eligibility statement 或当前股票列表不能证明全集；
- SecurityStatus v2 精确绑定同 session PIT Universe，对全部 members 固定 `TRADABILITY + RISK_WARNING`；只有显式 previous snapshot 与相邻 session 宿主确认才能证明进入、持续、撤销，稀疏事件不跨日传播。

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

当前已完成 PREP 全市场扫描、MarketSnapshot、AUCTION/R1/R2/R3 Scanner、DailyMarket 增量归档与 P8.7 受控 Daily Orchestrator。实时层已接入 `public-web-consensus-v1`：腾讯主源、东方财富第二源、新浪备用校验，至少两源一致才形成可用快照。R2 为 11:30 午间复核、R3 为 15:00 收盘定稿，均必须引用前一阶段真实冻结的 SYSTEM_PREDICTION，只延续其中已选标的。PREP CandidateSet 为空时直接保存前瞻 NO_TRADE 并进入 `COMPLETE_NO_TRADE`，后续 Frame 标记跳过；非空 CandidateSet 下 PREP 暂未选股仍继续等待 AUCTION。2026-09-15 已用5,219行 accepted DailyMarket 为 2026-09-16 冻结首条此类真实时钟 NO_TRADE 样本。公开网页源适合当前研发/个人自用，但不认证 Strict PIT，也不具备交易所级 SLA。

个股信息问答与上述正式交易链分离：用户当前轮次明确 A 股代码或本地正式名称，即授权宿主针对这些明确股票执行一次最多10只的三源只读报价；唯一股票上下文的明确追问可沿用，多股票歧义不猜。报价在模型推理前注入价格、时点与市场状态，并在聊天工具事件中留证，但固定不写 MarketSnapshotStore、不创建Decision/信号/订单。于是“没有已冻结MarketSnapshot”只阻断正式交易证据，不再阻断普通个股情况回答。
## 8. AI Team：独立研究，不做投票系统

AI Team 当前正式研究角色包括 Chief Researcher、Market Scanner、Skeptic / Risk Reviewer、Quant Researcher；Developer 属于已落地的 P10 Dev Studio 开发 profile，不进入交易研究投票或判断链。

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

P10 已落地 Main Developer Agent + Dynamic Subagents 开发编排层，并与 AI Team 研究链保持权限分离：Research Profile 继续只读 evidence；Dev Profile 只允许在隔离 worktree 内按 path-scoped lease 受控写入，最终发布仍停在人工 Merge Gate。
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
## 11. 当前实现状态（2026-09-16）

| 层 | 当前状态 |
|---|---|
| Trading Desk / Decision / Dossier / Theme / Frame / Strategy Intent | 已完成主体 |
| AI Team / Peer Review / Git-first Memory | 已完成主体 |
| Research Lab / Strict PIT / Campaign / Factory / Watch | 已有成熟基础；Watch Sequential Monitor v1 已完成，支持冻结经验基线后的 Rank IC 在线衰减证据 |
| Approval-time Actual-byte Freeze | **已完成 v1**：人工批准时冻结实际规范化研究输入、qfq/raw/context 与 Universe mask；执行/恢复不再读取变化后的源数据 |
| Research Session Grant | **已完成 v1**：宿主显式授权证券/日期/周期/因子/模式/有效期与总计算预算；AI 可在范围内提交有限研究，使用同一 JobQueue 和逐任务 input freeze，可撤销 |
| Watch Sequential Monitor | **已完成 v1**：新 Watch 冻结 family alpha / min_effect / min_new_dates / block_sessions，新增成熟日进入非重叠 block + mixture e-process；legacy Watch 不静默升级，越界只触发人工复核 |
| Strict PIT Evidence Archive | **已完成 v1 基础设施**：支持 Universe eligibility / SecurityStatus / Industry / Daily Market Cap 四类 statement；当前 `niuniu-data` 已有 SecurityStatus 14条/7只股票，其它三类仍为0 |
| PIT Universe Receipt | **v1 工程完成、真实数据待前瞻获取**：目标 session 完整 scope/member、官方原文 SHA256、三项宿主确认、cutoff 防回填、append-only audit；Qualification/PREP/Orchestrator/approval freeze 已接线。真实 `niuniu-data` snapshot=0 |
| Strict PIT Coverage | **已完成 v1**：深度验证 receipt 后按年份/证券/字段展示 evidence presence，并分开展示回顾性 inventory 与 gap；不生成数据集总覆盖率；当前 SecurityStatus 有14条 verified evidence，其它三类仍缺 |
| Strict PIT SecurityStatus | **v2 工程完成、真实完整数据待获取**：累计7份深交所公告→14条稀疏状态事件；v2 新增全Universe逐日状态、显式相邻session链、进入/持续/撤销、append-only audit、silver/PREP/Coverage/System Health接线。真实v2 receipt=0，稀疏事件不跨日外推 |
| 2026-09-17 前瞻官方取证 | **staging/runbook 已完成，归档门保持关闭**：2026-09-16 review-only A_SHARE 基线为 SSE 2,318 + SZSE 2,901 + BSE 344 = 5,563；追加式语义包固定三所规范、SZSE 3次站内检索与10个公开静态路径探测。目标日刷新、publication time、公共字段映射和全状态完整性未确认，Universe/v2 status receipt仍均为0 |
| Official MarketRules Receipt | **v2、首批真实资料与全局审计已完成**：按 snapshot append-only 保存 records/官方原文/`published_at`；CLI/System Health 深度核验1个 receipt、7条停牌规则、7份原文。7个复牌日已另核出 exact 算术参考值，但历史行情 byte vintage 只在事后取得，reference audit 固定 Strict PIT eligible=0、MarketRules appended=0；全市场覆盖仍缺 |
| Playbook Lab 六类结构化对象 | 已完成 |
| `ExpertSource` 作为交易者来源 | 已完成，并兼容投影为 StrategySource(TRADER) |
| PREP 全市场扫描 / MarketSnapshot / AUCTION / R1 Scanner | 已完成 |
| DailyMarket 全市场日增量归档 | 已完成 |
| 真实前瞻冻结与防历史回填 | 已完成并已启动样本积累 |
| 通用 StrategySource 多来源对象 | **已完成 P8.6**：六类来源 + 多对多 PlaybookSourceLink |
| External Research Skill Adapter | **已完成 v3**：v1包审计 + v2 Git archive/选择性策展 + v3 Git-clean只读Library；Research Lab、日常助手、AI Team、MCP可检索精确策展snapshot，不执行脚本/联网/自动写库。郑希DRAFT包仍仅为PARTIAL预览 |
| 受控每日自动编排 PREP→AUCTION→R1→R2→R3 | **已完成**：持久计划、幂等恢复、R2/R3 continuation review、错过窗口不回填；空 PREP CandidateSet 进入 `COMPLETE_NO_TRADE` 且不抓无标的行情；实时三源抓取需宿主显式授权 |
| Live MarketSnapshot Provider | **已完成 v1**：腾讯主源 + 东财第二源 + 新浪备用校验；至少两源一致、异常源剔除、时间戳防脏数据、公开网页源不升级 Strict PIT |
| 个股问答自动实时行情 | **v1 已完成**：当前轮明确代码/正式名称或唯一股票追问即触发一次三源只读报价，自动注入模型上下文；最多10只、多股歧义不猜、不写正式MarketSnapshot/Decision/订单 |
| Agent Scorecard | **P9 v1 已完成**：按任务类型只读评价，样本不足 UNKNOWN，无总分/自动调权 |
| Dynamic Agent Orchestrator / Dev Studio | **P10 v1 已完成**：隔离 worktree + depth-1 动态 Subagent + path lease + Reviewer + Human Merge Gate |
| System Health | **P11 v1 已完成**：Runtime / Research Readiness 双轴，只读聚合服务、任务、数据新鲜度、PIT、通知、Dev 与日志；MarketRules v2 显示全局完整性 inventory 但不冒充 case coverage；无健康总分/自动修复 |
| Mobile / Bot | **P12 v1 已完成**：同一 Workbench `/mobile` + 只读 JSON API + MCP/CLI Mobile Brief；复用 Decision/Dossier/Paper/Health，无第二状态源 |
| Broker Read-only / Shadow | **P13-A v1 已完成**：脱敏账户快照 append-only 保存、Dynamic Paper 持仓/现金对账、MCP/System Health 只读查询；无实时券商连接 |
| RealTrade Readiness | **P13-B0 v1 已完成**：Broker capability + disabled safety policy + fail-closed blocker；当前无 live channel 时固定不可连接/不可下单 |
| Prediction→Decision/Intent + PaperPlan | **P8.8-A/B 已完成** |
| 动态跨日 Paper / fill→Intent / Rebalance / D1-D3+ Review | **P8.8-C v1 已完成**；仍需真实前瞻运行样本积累 |
| Real Broker / Order Submission | **P13-B1+ 尚未开始**；B1 先做具体券商实时只读，B2/B3 的认证/风险门/订单继续单独评审 |

当前生产代码最近完整回归基线：**1006 tests / 0 failed / 0 skipped**。PIT Universe v1 / SecurityStatus v2 工程通过不代表真实数据资格已自动升级。
## 12. 后续开发主线

P13-B0 已把“当前没有具体券商通道”做成 fail-closed 安全门，后续不再用假 Gateway 推进：

1. **P13-B1 Live Read-only Broker Adapter**：只有出现明确可用的具体券商实时只读通道后才开始；目标是账户/持仓/资金/回执只读连接，不默认包含订单权限。
2. **P13-B2/B3**：实时 Shadow、kill switch、风险限额、逐单确认、订单预检与最终真实订单必须继续分层单独评审。
3. 无 B1 通道期间，并行积累真实前瞻 Paper 日志；低成本实时 MarketSnapshot、Watch Sequential Monitor、Strict PIT Evidence Archive 与 Coverage v1 均已补齐。后续外部数据升级目标是券商/QMT/交易所级行情；内部 Research Lab 下一主线转为**真实官方历史资料归档与 receipt coverage 提升**，而不是再改 Strict PIT/Coverage 引擎。

Approval-time actual-byte freeze、Research Session Grant、Watch Sequential Monitor、Strict PIT Evidence Archive/Coverage、PIT Universe v1 与连续 SecurityStatus v2 工程合同均已完成；真实状态资料仍只有 7 只证券、14 条稀疏 statement，v2 完整逐日 receipt 为0。Official MarketRules publication receipt v2 已把同7份公告映射为7个明确停牌 session；7个复牌日 exact 算术值因缺开盘前 publication receipt 仍只作回顾性 reference。External Research Skill v3 仍只形成 PARTIAL StrategySource 预览和 Playbook DRAFT 候选。

2026-09-16 已在独立数据根完成 2026-09-17 的前瞻准备：父 capture 保存5,563只三所 review-only A_SHARE 基线；独立 addendum 保存 SSE/SZSE/BSE 规范语义和SZSE有界公开源排查。官方规范只证明字段与私有分发机制，不能替代目标日逐证券值；SZSE公开批量完整状态源尚未找到，BSE公开 `xxtpbz/xxzrzt` 字典也未闭合。故四项确认均为false、archive未调用、正式receipt仍为0。现已根据用户明确授权安装一次性条件式LaunchAgent：目标日08:00启动、09:10安全停止，先固定官方字节与机器审计，只有publication time、语义映射、完整性全部成立才自动归档；已知证据缺口不会因定时执行而消失，错过不得历史补档。

当前内部主线是：在未来 session 09:15 cutoff 前同步归档首个真实 Universe，并仅在三所完整状态均成立时归档 SecurityStatus；同时继续寻找历史静态参数文件，随后补历史行业与每日真实市值。任何 staging、稀疏 receipt、回顾性参考或外部知识评分均不视为完整覆盖/Alpha。

**P14 / AR 自主研究与打板情绪研究线（2026-09-16 建立规划）**：目标是让牛牛围绕行情、市场情绪和打板规律持续做可复现、可证伪的研究。先补正确的涨停事实（按日期生效的涨跌幅制度、触板/炸板/连板、回溯全市场 ST/停牌数据）和日度情绪指标，再做收盘后公开证据归档、事件研究与保守成交模型，最后接入 AI 复盘、可验证预测与有限授权的夜间研究循环。所有新数据默认 research_only 或前瞻抓取留证，AI 不获得交易权限。详见《牛牛AI交易助手_自主研究与打板情绪研究_规划与进度》。

### P8.7 当前边界

Daily Orchestrator v2 是**单交易日、宿主先建计划**的持久状态机：DailyMarket 可显式授权 capture；PREP 使用正式全市场扫描；AUCTION/R1/R2/R3 只消费已经存在的 `LIVE_NEAR_REALTIME MarketSnapshot`。R2 在 11:30、R3 在 15:00 做 continuation review，必须引用前一阶段真实冻结的 SYSTEM_PREDICTION，只能延续其中已选标的。若冻结的 PREP CandidateSet 为空，状态机以 `COMPLETE_NO_TRADE` 正常终止并将后续阶段写成 `SKIPPED_NO_TRADE`；若 CandidateSet 非空，即使 PREP `selected_symbols=[]` 也仍等待 AUCTION。它不会自己选择未经审计的实时行情网站，也不会在错过时间窗后生成 SYSTEM_PREDICTION。Provider Registry 当前同时有离线 `manual-import-v1` 与 live `public-web-consensus-v1`。实时 Provider 必须至少两源一致；Orchestrator 默认不联网，只有宿主计划显式 `allow_market_snapshot_capture=true` 才自动抓取；每 Frame 失败冷却30秒、最多3次。公开网页源固定不认证 Strict PIT。

### P8.8 当前边界

P8.8-A/B/C 的核心链路已经完成：`SYSTEM_PREDICTION → Decision/Strategy Intent → PLAN_OPEN → PaperPlan → DynamicPaperAccount → fill receipt → OPEN/HOLD/REDUCE/EXIT → D1/D2/D3+ PaperOutcomeReview`。动态账户允许跨日增加证券，但过去 target 会确定性补 0，且历史 NAV/fill/order 前缀必须保持不变；ADD/REDUCE/EXIT 必须由对应当前 Strategy Intent Decision 驱动，不能借 rebalance 偷偷开新股票。

P8.8-C 的“自动复盘”只生成因果 outcome evidence，不替用户事后自动做 HOLD/REDUCE/EXIT 决策；真实券商、真实资金和自动实盘仍全部留在 P13。当前还需要通过后续真实前瞻运行积累足够长期 Paper 样本，才能评价规则/Agent/账户表现。

## 13. 一句话定义

> **牛牛是一个把多来源交易知识持续形式化、结构化留证、数据验证化，并通过 Daily Scanner 与多 Agent 研究形成可追溯交易决策，再通过长期复盘把新经验沉淀回规则库的个人 A 股交易研究系统。**

它的核心不是复制某位高手，而是建立一个可以不断吸收、反驳、验证和迭代交易经验的长期研究闭环。

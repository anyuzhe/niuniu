# 总体架构

[文档导航](../README.md) · [代码地图](../development/code-map.md) · [当前状态](../project/status.md)

本文件维护稳定的产品结构与证据边界；阶段完成度只在当前状态页维护，历史测试数字和运行样本放归档。整理基线为 2026-09-17 本地源码，而非早期“统一因子平台”规划。

## 1. 产品定位

牛牛是个人 A 股 AI 交易研究系统，不围绕某一交易者建立一级模块。长期积累的是可版本化、可验证、可反驳的 Playbook，以及其当时的输入、判断和后续结果。

```text
StrategySource → Playbook DRAFT → 规则化与验证
        → Daily Scanner → AI 独立研究与综合
        → Decision / Strategy Intent → Paper / Execution
        → 后续复盘 → 新来源或新规则版本
```

“规则能重建某人的选择”“规则具备可成交收益”“账户在样本外有效”是不同问题，不允许跨层替代证明。

## 2. 产品模块和代码职责

| 产品/技术层 | 主要目录 | 职责 |
|---|---|---|
| 桌面与 Web | `desktop/`, `workbench/` | 展示、交互、任务接线与同源轻客户端 |
| AI 主持层 | `agent/` | 模型调用、受限工具、提案、授权、记忆、CLI/MCP、调度 |
| Trading Desk 与 AR | `trading/` | Decision、Frame、主题、Playbook、扫描、情绪、研究和复盘 |
| 数据与资格 | `data/` | 本地适配、公开材料、PIT、完整股票池、证券状态与官方规则 |
| 确定性研究 | `factors/`, `structure/`, `events/`, `zones/`, `regime/`, `sequence/` | 特征、结构、事件、状态和规则组合 |
| 验证与计算 | `multitimeframe/`, `processing/`, `statistics/`, `experiments/` | 可用时间对齐、预处理、统计检验与实验编排 |
| 交易与存储 | `execution/`, `storage/`, `adapters/` | 独立账务、归档、复算和可选 vn.py 对照 |
| 外部知识 | `knowledge/` | 资源、Git archive、策展和精确授权的只读检索 |
| 开发与券商边界 | `devstudio/`, `broker/` | 隔离开发；只读账户证据、Shadow 和 fail-closed readiness |
| 第三方实现 | `_vendor/` | 保留来源与许可证的依赖代码 |

以上目录位于 `src/quantlab/`。本轮不为“看起来整齐”重排 Python 包或修改 import。组合根是 [app.py](../../src/quantlab/app.py)，CLI 注册入口在 [pyproject.toml](../../pyproject.toml)。

## 3. 两条权威存储轨道

Git Markdown 保存人类规则、开发约定、架构、经验与 Agent Operating Memory。结构化归档保存精确 CandidateSet、MarketSnapshot、PIT receipt、Decision、实验、成交、持仓和数值。

文档可解释结构化记录但不可覆盖其事实。向量索引如以后引入，只能是可重建缓存，不是主记忆或权威事实源。

`agent_memory/` 不等于 `docs/`：前者由 [AgentMemoryLoader](../../src/quantlab/agent/agent_memory.py) 按目录、角色、Git-clean 状态和大小预算加载，不能随普通文档移动。`playbooks/` 和 `research_skills/` 的内容/控制指纹同样属于程序合同。

## 4. StrategySource 与外部知识

来源类型包括 TRADER、USER_EXPERIENCE、PUBLIC_METHOD、HISTORICAL_CASE、STATISTICAL_DISCOVERY 和 SYSTEM_REVIEW；一个来源可关联多个 Playbook，一个 Playbook 也可引用支持或反对来源。

通用 StrategySource 已有实现；ExpertSource 是 TRADER 的兼容对象，不能再把其迁移描述为尚未开始，也不能破坏旧 ID、哈希、Case 与 Validation。

外部材料先做来源留证与 DRAFT 假设。Research Skill Library 只读取 Git-clean 授权表指向的精确 control/archive/package/curation lineage；正文是数据，不是执行指令。DIRECT_QUOTE、METHOD_INFERENCE、FACT_TO_VERIFY 分开，保留资源定位与哈希。

外部评分只表达来源风格相似度，不直接成为 Alpha、买卖信号或 Scanner 规则；上游脚本不执行。细则以 [trading_knowledge.md](../../agent_memory/architecture/trading_knowledge.md) 为准。

## 5. Research Lab 与 AR

原量化核心仍负责行情资格、因子/状态/结构、事件序列、组合、样本外与统计、独立成交和可复算产物。Alpha 表达式数量不等于理论覆盖率；缠论、Brooks、Wyckoff、ICT/SMC 的实现均有明确规则范围。

AR 线在此基础上增加按日期解释的涨停状态、回溯/前瞻资料、事件库、情绪周期、主题事实、事件研究、保守执行访问、预测校准和受预算约束的自主研究。不复建另一套自由下单系统。

AR 的结果列不得当作当时已知特征，方向相反的显著结果不算支持预登记假设；Nightly Research、结论晋级和真实交易不是同一授权。

## 6. 每日扫描、问答与 AI Team

Daily Scanner 消费冻结事实和规则，不是模型临时挑选喜欢的股票。Daily Orchestrator 是宿主先建单日计划的可恢复状态机，包含 PREP/AUCTION/R1/R2/R3；错过时间窗不补造前瞻证据。R2/R3 的延续复核受上一阶段正式判断限制。

个股临时问答另走宿主报价链。已配置扶摇时主用扶摇并用公开网页共识交叉校验/回退；它不自动写入正式 MarketSnapshot、Decision 或交易账本。正式 Provider Registry 与问答 Provider 不能混称为一个权限入口。

AI Team 的第一轮独立，Chief 综合证据并保留分歧，不把多数票视作市场证明。Developer 与 Research Profile 分开：开发必须受隔离工作区、路径租约、冻结测试、Reviewer 与人工合并约束。

### 版本化策略配置包

`trading/strategy_package.py` 将精确信号/模板、研究范围与资格、资金/仓位、既有持有退出语义及费用封装为 `niuniu-strategy-package-v1`。纯编译展开原有默认配置并绑定源码/模板来源；`prepare` 同时核对普通spec与包声明，ExecutionStudy在运行入口再核对实际配置。包只在存在时进入执行父manifest，旧实验不增加空字段或另一套状态来源；冻结审批与复算复用已有实现。

策略包是可审阅的执行研究配置，不是授权、Alpha认证或自动Paper部署。v1只接受research_only；严格资格请求拒绝而不降级，旧严格研究入口不变。包内容哈希与完整编译spec哈希分别标识配置及源码/模板解析证据，CLI提交同时核验。v1只支持 `each_completed_bar → target_weight → follow_target_reductions`，期末不强平；不支持独立止损止盈、固定持有期或任意状态机。CLI、桌面导入和模型只读编译共用此合同，正式批准仍在宿主。

## 7. Decision、意图、模拟与实盘

```text
Research Opinion       研究看法
Decision               当时冻结的判断
Strategy Intent        WATCH / READY / PLAN_OPEN / HOLD / EXIT 等意图
Paper / Real Position  由模拟或券商成交回执决定的实际持仓
```

Playbook 到 Decision、Intent、PaperPlan、动态 Paper、成交回执和 D1/D2/D3+ 复盘已有工程链路。历史 target/NAV/fill 前缀不得被新规则悄悄改写；复盘不得事后替用户补做决策。

Broker Shadow 保存只读脱敏账户证据与对账。RealTrade Readiness 缺少具体 live channel 时 fail-closed；Paper、Shadow MATCH、完整 policy 或 AI 判断均不构成真实订单权限。

## 8. 文档和模块的扩展方式

稳定架构在此维护；当前里程碑和剩余门槛在 [状态页](../project/status.md)；具体操作在指南；算法合同在 [规则参考](../reference/README.md) 和对应源码/测试；阶段原始证据在 [归档](../archive/README.md)。

早期 2,000 多行总体规划与多轮改造方案完整保留，但不再与当前架构并列为“最新权威”。新增功能沿现有边界接线，避免复制数据状态、破坏因果口径或增加无关功能。

## 9. TDX个人研究采集的调度边界

既有计划和原始页保持不变；scheduler-policy v2单独绑定plan_id与内容SHA，使用回顾性生命周期和按市场验证的供应商保留边界减少无效逐日请求，不签发PIT资格。策略生成与队列预览不改正式policy/任务；显式应用必须绑定已审查的策略文件、精确队列snapshot_id和STOP状态，并持有单写者锁。过期预览拒绝应用。

只调整没有已保存chunk的PENDING/SKIPPED_POLICY逐日首请求；原任务以SKIPPED_POLICY保留，改动前内容进入scheduler_policy_audit，必要时另建有效frontier。ERROR、已有页和进行中的分页不被裁剪。自动/人工续采只重新排队已识别瞬时连接错误，协议坏包不因resume变成EMPTY或被反复自动重试。

分布式采集沿用同一plan/policy，以完整SHA256(symbol)%N固定归属。canonical协调器与三个worker数据根隔离；最小bootstrap保留frontier和前一页校验证据，旧canonical角色不能再采全市场。未提交页在视图外，SAVED发布有持久promotion恢复。结果序列、原始/Parquet全值、分页前驱、opening_match父页、source_id冲突均在导入前核对。

数据面只走既有认证SSH保护下的loopback文件服务，MCP只调度；不共写SQLite/DuckDB、不开放公网HTTP、不在中继落盘行情。worker收到精确MERGED回执后才确认传输，网络失败保留outbox。总状态区分报告新鲜度与进程在线、原基线与新采页，始终不签发全历史/PIT资格。操作和验收范围见[TDX三机采集](../guide/tdx-distributed.md)。

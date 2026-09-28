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

### 8.1 版本化计算身份与研究关联（2026-09-27）

`experiments/computation.py` 为因子缓存和 Factory 基准比较提供 `computation-runtime-v1`：覆盖除 `desktop/` 外的保守 Python 集合、计算 JSON 资源、Python 及 numpy/polars/pyarrow/duckdb 版本。缓存键同时绑定上述身份，不仅绑定源文件；新档即便完整应用指纹相同也必须核对计算资源/依赖。`runtime_fingerprint()` 原合同不变，审批、Grant、JobQueue 和默认精确复算仍绑定全应用。计算兼容不签发授权，不代表跨应用版本可以精确复算；旧档缺计算身份时仍按旧完整运行环境处理。

Factory 保留旧 DSL `candidate_ids` 合同；普通注册因子明确采用 `alpha-factory-plan-v2` / `candidate_refs`，输出 `alpha-factory-v2`。参数规范化后固定因子 ID、版本、参数和定义/代码指纹，语义重复候选拒绝；只接受现有评价器支持的收盘可用 scalar/boolean。沿用原审批、队列、固定检验族、失败槽位、结果归档和人工观察池晋级。旧冻结计划不自动升级，新代码变动须重新提案。

`agent/research_links.py` 只读现有 run、工作空间 `_trial_registries`、已归档检验族及 ResearchMemory。关联依赖精确 ID、registry/binding 指纹、源实验字节和显式父假设，不按名称或相似参数合并。查询有界分页，部分/错误结果为 UNKNOWN；本地 REGISTERED 不等于可信事前登记、统计充分性或 Alpha。返回本地血缘而非重算 p 值，不新建权威数据库。原生 Chat/MCP 和因子证据页共用这一入口。

### 8.2 有限对话收尾与证据恢复

Pi传输在已有总轮次内保留最后一轮无工具收尾，宿主停止信号在同批工具间立即生效。预算停止携带非空文本、termination/needs_followup/reason；ChatRuntime仅将明确PiBudgetStopped转成追加式partial，Developer直接调用仍失败。协议异常、取消、未知工具和授权校验不因收尾放宽。

`agent/chat_recovery.py`从原会话日志提取有界历史引用，不是第二状态库或可执行检查点。显式recovery_only只开放已有任务/研究/记忆查询和原finding保存；不能新建/批准/重跑研究、恢复Grant或触发行情联网。引用先重读真实来源，超限/缺失明确保留；长期会话仍受原上下文与事件预算限制。桌面预填和CLI共用同一模式。

### 8.3 原生研究选择器与 Factory 表单

`desktop/research_picker.py`只选择现有注册定义或本工作空间归档；`trading/research_evidence.find_research_archives`使用有界UUID目录/原始头部查询，不创建索引数据库。目录身份、头部SHA核对与计算兼容/数值复算分层表达；分页/搜索/换根/关闭后旧结果不得继续被使用。

`desktop/factory_builder.py`把显式表单编译为原alpha-factory-plan-v2，经原normalize_plan/preview/propose保存pending。宿主可传expected_digest绑定预览；写提案前重建prepared并核对，不绕过原审批/队列/冻结/固定测试族。界面候选副本与正式登记分开，不制造第二因子池。AlphaFactoryDialog的摘要只投影保存的预设槽位/结果/decision，不重算、择优或自动晋级。

### 8.4 Factory报告与只读解读

`agent/factory_report.py`将已有Factory状态与完成父归档投影为有界report-v1，SHA/manifest/prepared及固定槽位一致性校验和返回前复查不读取或重算源行情。report_digest绑定状态和父归档字节，与分页/时钟无关；成本计划与实际取得证据分开，重复/未计划结果拒绝，缺失槽位不删除。完整UI最多12候选，正式get_alpha_factory_report工具最多6；工具不再二次compact破坏该已受限报告。

`agent/evidence_review.py`定义独立只读profile，ChatRuntime在初始化禁用行情与queue_factory，并在API层和派发schema层执行白名单。页面只提供来源ID/hash，不自动调用模型；现有研究profile、Grant和P10权限未改变。桌面factory_report和CLI的--evidence-only消费同一读取服务；导出只创建新文件，不覆盖权威状态或承诺可搬迁复算。对话日志与研究事实分开。

### 8.5 原生观察池快照与人工刷新

WatchService.inspect_snapshot只接受原Watch历史中已发布的精确snapshot_id，读取时核对所选快照自己的来源树，而非复用最新快照的完整性。视图指纹绑定definition/state/snapshot及观察到的来源指纹，不持久化新状态、不重算统计。WatchStore.set_active增加可选expected_state_digest，在原锁内比较后写入；无参数旧调用保留兼容，不产生自动停用权限。

FactorWatchDialog复用原归档选择器和提案进度窗口，字段与按钮按明确选择/忙状态/工作空间身份控制，历史和来源变化不自动替换。watch_snapshot_view仅投影已保存指标。ResearchAgenda保留Watch内部快照错误、标记100项扫描上限，并只按原watch_id导航。未新增模型历史快照工具；此次服务只为原生界面，原统计、刷新审批/输入冻结、跟踪授权与交易边界未变。

### 8.6 研究议程的类型化证据导航

`desktop/agenda_navigation.py`从实际agenda evidence生成按原顺序保留的显式选项，仅接受固定类型及规范ID；名称、说明、外部路径或action文字不得选择可执行函数。打开前按对应原服务重新读取精确对象，不建立第二结果库。原Factory/增量包/DSL/普通提案仍在自己的人工操作窗口，job和已注册DSL只读展示；普通factor保持版本及参数，不自动触发查询。

研究议程按冻结candidate_kind/旧candidate_ids区分普通因子与DSL；增量包使用独立引用类型，旧agenda的proposal仅在明确incremental待办种类下兼容转换。最多200条记忆扫描未完时不把缺失于本页解释为无结论。原统计、模型工具、权限和任务状态未改变。原生路由以选择代次及工作空间身份拒绝过期回执，新增接入页面补充关窗/换根保护。

### 8.7 首个待审批研究的配置边界

`desktop/experiment.py`明确区分既有直接研究和`draft_only`配置模式。后者即使直接调用submit也只校验配置并返回独立副本，不读行情资格、不获取队列；缺数据根时保留表单而不转入依赖数据根的ProposalService。因子选择复用FactorPicker，因子ID/版本不按名称替代，原参数与模式合同保持。

`desktop/agent_proposals.open_research_draft`将配置交给原ProposalDialog；表单编辑保留原草稿，输出/数据根的路径与目录身份、父编辑代次变化时拒绝迟到覆盖。保存、资格核验、批准时实际输入冻结及执行仍由原服务处理。本轮没有新增模型工具、执行授权或计算引擎；Factory入口只打开这个配置流程，完成的基准仍需人工通过原归档选择器选择。

### 8.8 本地数据可加载性与配置预检分离

`desktop/local_data_readiness.py`只在用户明确点击时将表单的证券/日期/周期/复权传给既有LocalMarketDataTools。返回内容按原证券顺序和范围重新核对，状态/记录不一致、关闭/换根/表单编辑后的回执拒绝；仅显示原加载器检查，不建立状态数据库或资格回执。MQC的缺量校验、管理数据包的入口选择、审批冻结和研究授权均不改变；空值原因未知时不能推断停牌或自动填补。

### 8.9 回溯停牌占位价的版本化适配

`archived_daily_dataset.py`新增显式format/contract v3，不改v1/v2默认语义。只有原始与typed数据逐值一致、同一日tradestatus=0、OHLC全空或精确等于有限正preclose且volume/amount/turn/pctChg无非零值时，派生OHLC才置null；原字节和完整session网格保留。新包绑定normalization_contract/policy、masked计数和资源上限，深验必须从原字节重建后与保存标准化表逐值匹配。运行层继续使用既有v2状态契约，不改MQC生产校验、标签、研究mask、成交引擎或审批/Grant。

显式宿主v3范围20只/1100自然日/22000行/44数据文件；模型桥接单次10只/371日不变。宿主读取两个不重叠的原始symbol组，比较计划/参考字节一致性，然后核对完整目标范围的每个calendar session；不存在按首年或首10只截断。旧合同、模型工具、总体字节预算与独占新目录发布均保持。已有失败验收必须保留为原输入版本的失败，不因新版本能加载而改写历史。

## 9. TDX个人研究采集的调度边界

既有计划和原始页保持不变；scheduler-policy v2单独绑定plan_id与内容SHA，使用回顾性生命周期和按市场验证的供应商保留边界减少无效逐日请求，不签发PIT资格。策略生成与队列预览不改正式policy/任务；显式应用必须绑定已审查的策略文件、精确队列snapshot_id和STOP状态，并持有单写者锁。过期预览拒绝应用。

只调整没有已保存chunk的PENDING/SKIPPED_POLICY逐日首请求；原任务以SKIPPED_POLICY保留，改动前内容进入scheduler_policy_audit，必要时另建有效frontier。ERROR、已有页和进行中的分页不被裁剪。自动/人工续采只重新排队已识别瞬时连接错误，协议坏包不因resume变成EMPTY或被反复自动重试。

分布式采集沿用同一plan/policy，以完整SHA256(symbol)%N固定归属。canonical协调器与三个worker数据根隔离；最小bootstrap保留frontier和前一页校验证据，旧canonical角色不能再采全市场。未提交页在视图外，SAVED发布有持久promotion恢复。结果序列、原始/Parquet全值、分页前驱、opening_match父页、source_id冲突均在导入前核对。

数据面只走既有认证SSH保护下的loopback文件服务，MCP只调度；不共写SQLite/DuckDB、不开放公网HTTP、不在中继落盘行情。worker收到精确MERGED回执后才确认传输，网络失败保留outbox。总状态区分报告新鲜度与进程在线、原基线与新采页，始终不签发全历史/PIT资格。操作和验收范围见[TDX三机采集](../guide/tdx-distributed.md)。

# 数据与证据说明

[文档导航](../README.md) · [使用指南](user-guide.md) · [当前状态](../project/status.md)

本文件解释代码采用的数据合同，不签发资料资格证书。某天、某只证券是否具备合格数据，必须检查对应 snapshot、receipt、publication time 和实际字节。

## 1. 三种位置不要混用

| 位置 | 保存内容 | 整理原则 |
|---|---|---|
| `/Volumes/Lexar/niuniu` | 源码、受版本控制的规则、说明 | Git 管理 |
| `/Volumes/Lexar/niuniu-data` | 牛牛独立行情及证据数据根 | 本轮不移动、不重写 |
| 项目 `artifacts/` | 实验、工作空间、Decision、任务与验收日志 | 不入 Git，不当普通文档搬家 |

`/Volumes/Lexar/MQC-DATA` 保留为旧 MQC 来源。历史实验中的旧绝对路径是来源证据，不做批量替换。备份、归档和当前运行根也不能仅凭名称相似而互相覆盖。

## 2. 本地行情适配

[local_data_provider](../../src/quantlab/data/provider.py) 可识别宿主明确建立的 `archived-daily-dataset.json` 输入包；该标记不得与 approval freeze、Baostock series 或 dataset 标记混用。没有新标记时保留原 approval freeze → Baostock series → Baostock dataset → MQC 路由。新标记损坏或口径不符必须报错，不扫描原 capture 并自动注册、不改供应商标签、不静默回退。

原 MQC 布局示意：

```text
niuniu-data/lake/
├── bronze/provider=baostock/
│   ├── stock_kline_daily/sh_600000.parquet
│   └── stock_kline_min5/sh_600000.parquet
└── silver/
    ├── qfq_kline_daily/sh_600000.parquet
    └── qfq_kline_min5/sh_600000.parquet
```

该布局不是任意 Parquet/CSV 的自动识别规则。字段与编码以 [mqc.py](../../src/quantlab/data/mqc.py)、[validation.py](../../src/quantlab/data/validation.py) 为准。内部证券编码例如 `sh.600000`；高周期数据须按真实交易时段和 available_at 对齐，不能从 5m 反推真实 1m。

Coverage 的日线库存从宿主根内实际文件名单读取，返回 `inventory_source=root_bound_parquet_scan`、`catalog_views_used=false`；不使用持久catalog中的旧SQL视图，不修改数据库。复制数据目录不保证复制来的视图已改指新根；当前索引引用的治理与历史manifest路径保留是不同任务，不能批量替换历史证据。库存小表和silver同样拒绝指向根外的链接，读取失败不当作空库；库存存在仍不证明逐日完整性、正确复权或严格时点资格。


AR 回溯日线还有独立的 pack 合并与读取实现，见 [retro_daily.py](../../src/quantlab/data/retro_daily.py)。历史小文件到 pack 的迁移已记录在 AR 验收中；本轮只整理文档，不重复执行合并或删除数据。前瞻日增量见 [forward_daily.py](../../src/quantlab/data/forward_daily.py)。

### 已归档日线的有限研究输入包

[archived_daily_dataset.py](../../src/quantlab/data/archived_daily_dataset.py) 复用现有 retro 原始/typed 校验，支持宿主先预检，再确认创建全新独立目录。不是直接让助手写数据治理库，也不是审批冻结。原 capture 不改变；包保存原始字节、固定日历、规范行情及源证据，Provider 每次读取重新核对文件与原始/typed/派生语义，原源下线后仍可读取。

v1仅提供1–10个明确沪深代码、最多371自然日内的raw日线；每个请求证券必须逐日覆盖所选capture日历的全部交易session。缺日、停牌行和必需数值无效时拒绝，不填值、不删行、不自动挑替代样本；保留有效ST供应商行不等于确认可交易。日线15:00 Asia/Shanghai的 `available_at` 仅为显式研究对齐时钟，`historical_available_at_verified=false`。原始前收、换手和状态保留供应商字段语义；不提供qfq、分钟合成、官方股池/规则或PIT升级。

把新包目录显式设为研究宿主 `--data-root` 并选择raw后，沿原Proposal/JobQueue/策略包执行和输入冻结路径使用；创建数据包不批准研究，不继承任何旧Grant，跨根授权仍由宿主另行处理。操作见[使用指南](user-guide.md)。

### 宿主显式选择的 raw 日线尾部来源

`catalog/retro_daily_tail.json` 是数据负责人明确建立的可选指针，不是自动数据治理或新增授权。它绑定精确capture、pack index摘要和coverage_end；代码不创建、不改签该指针。无指针保持原MQC行为；只有raw日线请求超过相应证券主干完整文件的截止日，才校验并读取尾部。qfq、分钟、主干范围内的查询不依赖未使用的raw尾部来源，也不因此自动补全它们的日期。

需要尾部时，坏JSON、非法路径、缺失归档、错误指纹、越过coverage_end、缺证券、缺交易日、停牌或无效行情均明确拒绝；不能当成指针不存在、悄悄丢行或换回旧数据。不同证券分别确定截止日，只有严格后缀追加，不覆盖已有主干，也不补主干内部洞。快照保留真实指针、pack index、源计划/日历/原始与typed记录指纹和观察时间；它仍是research_only，不证明历史发布时点。批准后继续由原approval freeze保存并使用实际规范化输入，已批准任务不因源归档下线而回读别的数据。

## 3. 研究价格和账户价格

客户端及研究 CLI 默认 qfq；底层 `build_runner` / MQC API 默认值不同，直接调用 Python 时须显式指定 adjustment。默认 `execution.price_mode=research` 使用研究价格，不重复记入已体现在复权中的公司行动。

`execution.price_mode=account` 才进入 raw 价格和显式公司行动账户口径。执行费用、交易日规则、T+1、整手、滑点及拒单应由独立执行模块处理，不能拿未来标签收益当作实际账户收益。

| 执行后端 | 作用 |
|---|---|
| `open` | 默认独立成交回测 |
| `vnpy_open` | vn.py 受限共同模型的对照路径 |
| `vnpy_rules` | 与本平台规则及账务适配的离线路径 |

后两者需要可选依赖，不是实盘券商通道。qimo 模拟盘费用合同已在 AR 线升级，既有授权的兼容/重新授权要求以对应控制和验收记录为准，不能擅改历史成交账本。

## 4. 四类资格逐请求判断

| 资格 | 可以表达什么 | 不能据此推出什么 |
|---|---|---|
| `research_only` | 当前材料可用于明确限制下的研究 | 历史当时可得、可成交、Alpha |
| `retrospective_reference` | 事后取得的历史参考 | 当时已存在的完整信息集合 |
| `strict_pit` | 本次请求所用资料通过相应时点证据门 | 所有证券、所有日期都已覆盖 |
| `official_rule_covered` | 本次范围的官方交易规则证据通过要求 | 全市场总资格或真实订单可达性 |

PIT Universe receipt 证明的是 exact session 的声明全集。SecurityStatus v2 要绑定同日全集全部成员；零散 ST/停复牌 statement 不能跨日传播。连续状态变化须有显式相邻 snapshot 链。MarketRules 和历史行业/市值各有独立证据要求。

官方 URL、文件哈希、Git 时间、HTTP Date、事后取得的官方历史价格，都不能单独证明某信息在当时可得。即使价格边界算术正确，也可能只能作为回顾性参考。Coverage 是 presence/inventory，不是可拼出的“数据集总完成率”。

## 5. 问答实时行情与正式快照

| 链路 | 当前实现 | 边界 |
|---|---|---|
| 个股临时问答 | 配置扶摇后主用扶摇，腾讯/东财/新浪两源共识交叉校验或回退 | 不写正式 MarketSnapshot、Decision 或订单 |
| Daily Orchestrator 的正式快照 | Provider Registry、明确 capture 授权、Frame/时钟与冻结合同 | 不是凭一次问答或供应商响应就合格 |
| AR 股池、龙虎榜、主题和盘中材料 | 供应商公开证据归档与研究派生 | 与 Strict PIT/官方规则区分，结果列不得前置使用 |

扶摇能力与实际只读接线见 [fuyao_tools.py](../../src/quantlab/agent/fuyao_tools.py)、[fuyao_market_snapshot.py](../../src/quantlab/trading/fuyao_market_snapshot.py)。没有凭证时仍可使用既有公开网页链路；两侧价格冲突要保留 PARTIAL/consensus_issues，不挑有利数据。

问答层的自动查询范围不等于底层 Provider 最大批量，也不授权持续刷新、全市场下载或真实交易。凭证由环境/钥匙串读取，不写进 Markdown、Git、测试输出或模型提示词。

## 6. 哪份记录说了算

Git Markdown 保存规则、说明、工程经验与架构；结构化归档保存数值、时点、候选集、预测、Decision、成交和持仓。Markdown 可以链接与解释，但不能覆盖后者。

实验常见产物有 `experiment.json`、`observations.parquet`、`report.md`、按需的 `bars.parquet` 与成交/持仓明细；本地索引常用 DuckDB。具体文件以实验类型为准。跨环境复算需匹配配置、源数据和依赖，不能仅凭源码指纹认定所有行情已复制。

原始数量、历史研究结果和当时的证据缺口保留在 [数据验收归档](../archive/README.md) 和 [开发史](../project/changelog.md)。这些数字附属于记录日期；本轮未重新审计外部数据根，不把旧数值换个标题写成最新覆盖率。


## 7. TDX个人研究数据分区

2026-09-18新增13类TDX数据的独立原始归档及Parquet，统一注册在现有 `catalog/mqc.duckdb` 的tdx_*视图中，旧Baostock日线/5m视图和文件不替换。每行带source_id、plan_id、observed_at、单位和qualification，全部供应商字段保留在record_json；同一事件的不同观察版本不能未经选择直接相加。

快照类date按观察日期解释，不能冒充历史可用时间或财报修订链。EMPTY只说明某个请求当时返回空；PENDING/ERROR/尚未展开的历史流不算已完成。采集计划从旧日历最早日追溯并不证明上游保留这些历史。原始来源性质保持vendor_observation_personal_research_not_pit，不自动放入QM50官方规则或真实交易入口。入口和暂停/恢复见 [运行与运维](operations.md)。

盘点时须分别使用任务日期、事件日期和观察时间：`jobs.day`/publication 的请求日期不是页内全部行情日期。K线的实际历史范围应从 `tdx_bars_*` 的 `date/event_time` 统计；公司行动也按记录的生效日期分析，未来生效记录不得提前应用。每日证券深度须 `COUNT(DISTINCT code)`，页数、行数和证券数不能互换；全表日期最值不证明每只证券连续覆盖。观察日期快照可以包含历史事件，但不因此获得历史发布时点认证。

竞价不同观测版本须区分完全相同副本与数值冲突，明确事件键、早/晚盘阶段、来源选择与同时间并列规则；仅写 `DISTINCT(date,code,event_time)` 不能决定冲突的价格和数量。跨来源比值只能提供单位候选，不得覆盖原单位未核验标记；同一供应商两个接口也不是独立规格证明。指示性可匹配量、累计快照和最终成交量要分别解释，不把观测版本或累计快照求和当成交量。金额缺失保持缺失；任何经验证的推导金额须另列字段、公式及输入证据。

覆盖清单的哈希只固定清单自身；`path+bytes+mtime`、文件数量或日期数量相等不等于冻结行情字节或精确交易日集合完整。可执行研究交付需明确每个输入文件/切片的SHA256、选择规则和实际证券×日期范围；完整历史固定队列也不等于无幸存者偏差的PIT股票池。Universe/状态/交易规则是部分资格组件，不代替该研究实际需要的行情版本、行业、市值和发布时间证据。

## 8. 治理资料的只读消费入口（F15 第一批）

普通本地研究聊天与标准MCP新增 `get_tdx_data_coverage`、`get_adjustment_review_contract`、`inspect_corporate_action_sources`。它们不创建研究任务、不采集、不修改库/指针、不重建或发布复权因子；首轮Reviewer和锁定QM50原始规格会话不增加这三项权限。读取合同不需要数据根，另两项仅使用宿主已配置的data_root，不接受模型传入路径或SQL。

### TDX覆盖与日期轴

`read_tdx_data` 保留原始行、排序与qualification，新增date_axis：bars_daily/bars_5m/bars_1m/trades/opening_match/auction/capital_changes为event_date；depth/finance/quotes/securities/topics为observed_date；limit_ladder为batch_date，且明确部分行源自trading_date_value，不是统一事件日认证。非事件族的读取与覆盖结果均附date_filter_is_not_event_date警告，不制造不存在的event_time。

`get_tdx_data_coverage(family,symbol,start,end)` 聚合一个族全部符合过滤条件的行，而非取一页推算。返回rows、COUNT(DISTINCT code)、source_ids、日期范围/不同日期数，以及逐code日期数min/p25/median/p75/max。codes遵循SQL定义，空字符串纳入distinct、NULL排除，两者行数另列；非事件族的event_date与per_symbol_event_days字段为null，改用date_min/date_max/distinct_dates/per_symbol_dates。明确时区的observed_at按UTC时刻比较，坏值、空值和缺时区分别计数，不按电脑时区补齐。

覆盖查询由独立内存DuckDB连接只读附加原catalog，资源为2线程/512MB/30秒查询上限、禁临时落盘；不改变其他现有连接的设置。缺表、不可读、查询预算或检测到文件变化时失败，不当空集。结果固定catalog_rows_only、source_bytes_verified=false、history_complete=false、strict_pit=false；不认证源页字节、去重、连续行情或全市场覆盖。本轮没有在正式大库上做性能或全量对账验收。

### 公司行动候选与qfq诊断

先调用get_adjustment_review_contract，再以一个规范证券和明确日期窗口调用inspect_corporate_action_sources；上限3660自然日、每页1–20个除权日、offset≤20000。只读固定TDX资本变动视图，以及东财/同花顺分红Parquet和可选已存qfq文件；逐源披露缺失、错误、字节哈希和定位。TDX部分仅是catalog行观察，不宣称原始协议页已深验。来源文本作为不可信数据，不是工具指令。

只解析少量明确、完整方案语法，保留原文、每股/每10股基数和税基。未知/待定文案不能变成三个零；税后、现金缺税基、限售/流通不同分配、残余复杂语法均阻断候选归并。东财比例字段在本合同下没有显式税基，原值保留但不按默认税前参与总额。TDX c槽仅标统计反解候选，非协议认证；未支持类目不命名。

同一来源内，精确重复保留全部定位而不重复计值；有可区分方案身份时才形成候选合计。公告日变化不创建新方案身份；同报告期修订冲突、身份不清或同文本不同身份均不自动相加。不同供应商描述永不求和；agreement/disagreement仅是候选值关系，不通过2:1、匹配率或零偏差认证真值/独立上游。

qfq只显示指定证券已存相邻因子的变化方向与比值，不计算修正因子或“正确收益”。比值上升、下降或不变都不能单独证明欠调/完整；不存在已认证差异清单时保持known_issue_list_status=not_bound。此前治理报告的46/64/272等分类数字不写入产品真值表。已有本地qfq盘点和载入检查增加supplier_adjustment_not_verified提示，但不改变原始raw/qfq价格、研究参数、批准冻结或复算身份。

顶层ok表示接口读取是否成功；data.incomplete、errors、每个来源blockers和pagination仍须同时展示。解析/来源阻断不能被描述为“没有差异”或“已修好”；未知税基下部分源不能比较，并不证明该供应商数据错误。MCP/CLI沿现有64KiB完整响应上限，超限明确要求缩小页量，不截掉错误生成成功回复。

宿主CLI与模型工具同源：

```bash
# 纯合同读取，不接触数据
.venv/bin/python -B -m quantlab.agent.data_review_cli contract
# 下列两个子命令需显式传入宿主选择的数据根；不会采集或写入
# tdx-coverage --data-root <root> --family <family> [--symbol <code>] [--start YYYY-MM-DD] [--end YYYY-MM-DD]
# corporate-actions --data-root <root> --symbol <code> --start YYYY-MM-DD --end YYYY-MM-DD [--offset 0] [--limit 20]
```

CLI退出码0=读取完成，3=读取完成但资料/候选不完整，2=参数/读取/接口失败；0不是数据正确或PIT认证。R3事件版本合同、R12/R13正式因子重建、最终逐事件差异清单、R16第三源采集仍是后续范围，不由本批只读查询暗中执行。

## 9. 显式日历来源与日线日期集合核对（F16）

普通Chat/MCP新增只读 `get_trading_calendar(source,capture_id,start,end)` 和 `check_daily_date_coverage(source,capture_id,symbols,start,end)`；CLI仍用 `quantlab.agent.data_review_cli`。两项均要求明确来源及1–371自然日，日期检查限1–10个不同沪深代码；不接受模型路径/SQL，不修改数据、Provider、授权或F9限制。

| source | 宿主绑定位置 | capture_id |
|---|---|---|
| baostock_bronze | data_root下的Baostock raw日线、trade_calendar/calendar.parquet及stock_basic/stock_basic.parquet | 空字符串 |
| retro_capture | source_workspace下指定的原始retro capture，复用原raw/typed验证与pack读取 | 已发现的精确UUID |
| archived_dataset | data_root下已生成的F9输入包，复用完整包核验及包内参考日历，不回读原来源 | 空字符串 |

不扫描最新capture或选择更晚日历；bronze根遇到受管理标记拒绝回退，不自动接raw尾部。F9包和capture窗口仍受各自冻结范围限制。日历先检查全部请求自然日，末端过期、中间缺日（包括未知周末）返回blocked和完整missing_calendar_dates，trading_dates为null；不根据已有短日历宣称完整。空交易日窗口不形成完整研究日期验收。

`calendar_content_hash` 是排序后的日期/开市标记对之规范化摘要，含明确content_hash_semantics；`source_calendar_content_hash` 单独保留capture原始参考JSON内容摘要（bronze为null）；evidence另给实际所读文件SHA256/字节数。三种身份不互相替代。读取后重核已追踪的文件；retro行情仍由原Bridge固定实际源字节，F9仍从自己的保存字节核验。

日期检查返回完整missing_dates、unexpected_dates、duplicate_dates，不仅前几个示例。期望集合按所选日历与同来源ipoDate/outDate闭区间相交；outDate为空字符串仅表示来源未报告结束，不认证历史状态。生命周期缺失/歧义或文件不可读时相关集合为null并保留error，而不是空缺口；来源本身损坏按原读取合同拒绝，不尝试修复或补值。

`status=complete` 仅表示本次日期存在且唯一：停牌行仍计入存在，suspended_dates与unknown_state_dates另列。f9_blockers是已知不兼容原因，不是完整F9预检；固定f9_export_verified=false、price_values_verified=false、tradability_verified=false、strict_pit=false。日期齐全不能把含停牌的候选直接导出F9，也不证明复权或价格正确。

```bash
# 仅示意参数；先明确选择已交付的源和窗口，不替用户选样本。
.venv/bin/python -B -m quantlab.agent.data_review_cli calendar \
  --source baostock_bronze --data-root <明确数据根> --start YYYY-MM-DD --end YYYY-MM-DD
.venv/bin/python -B -m quantlab.agent.data_review_cli daily-coverage \
  --source retro_capture --source-workspace <明确来源工作空间> --capture-id <精确UUID> \
  --symbols '<沪深代码，最多10个>' --start YYYY-MM-DD --end YYYY-MM-DD
```

CLI仍以0/3/2区分读取完成、已读但日期不完整或blocked、接口错误。Chat/MCP沿64KiB完整响应预算，超限拒绝并要求缩小范围，不能截断日期集后显示成功。首轮Reviewer和原QM50锁定会话不增加这两项权限。标准MCP在SDK过滤前验证宿主required/extra字段，并公布additionalProperties=false，避免与直接API校验不同；不改变研究批准权限。

## 10. 版本绑定的配股候选清单（F17）

`get_rights_candidate_manifest` 与 `query_rights_candidates(symbol,start,end,status,offset,limit)` 只读取宿主显式选择的两份交付文件，不扫描最新目录、不运行治理生成器、不打开正式行情或数据库。绑定是 `RightsCandidateBinding(csv_path,summary_path,csv_sha256,summary_sha256)`：两个绝对普通文件路径与两个完整SHA256均由宿主提供，模型没有路径、指纹、切换版本或写入参数。未配置返回CANDIDATE_NOT_CONFIGURED；不会从data_root猜测交付位置。

CSV最多8MiB、10000行，摘要JSON最多64KiB；单格最多8192字符，配股单行编码最多24KiB，确保可用limit=1完整取回。每次读取前后核对文件类型、祖先链接与实际字节SHA，JSON还必须绑定CSV摘要；不缓存“曾通过”结果。不匹配、重复字段/事件、错汇总、未知事件类、伪装成其它类型的配股、非法数值或候选公式量纲错误均拒绝。只有已知的现金/送股/因子欠调兄弟类允许留在同一文件中，但计入other_rows_not_evaluated，明确不作它们的数值验收。

配股分桶从字段重新验证，和JSON的buckets、status及consistency_check核对；不能只相信disjoint=true或CONFIRMED_GAP标签。数值校验使用Decimal，百分数与比值分开，旧混用列必须为空。精确来源字符串保持，不以格式化小数覆盖原文；事件引用含bundle_id、CSV SHA、source_row、source_line_end和event_digest。仅证明交付内参数/算术一致，未深验公告、原始行情或因子文件；factor_no_change_verified、official_verified、lineage_verified、strict_pit、reconstruction_authorized和publication_authorized固定false。

查询status为all/exact/small/conflicts/cninfo_none，证券可留空表示本清单全部证券，起止日期必须明确；offset≤10000、limit为1–10，排序固定为证券与除权日。分页保留整包unresolved_rows，查询零条不代表没有公司行动或没有复权缺口。返回的incomplete=false仅表示这份候选交付验证完成，不表示未决事件被解决。source_choice始终为空：small不能默认采用巨潮，conflicts不自动裁决，cninfo_none不能静默跳过后宣称完整复权。原文/备注为UNTRUSTED_SOURCE_CLAIM_NOT_INSTRUCTIONS。cninfo候选公式混用了巨潮配股价/比例与TDX派息/送转，价格相容性不是官方事件证明。

### 宿主用法与入口覆盖

```bash
# 将占位符替换为宿主明确选择的绝对路径和审核过的完整SHA；命令只读。
.venv/bin/python -B -m quantlab.agent.data_review_cli rights-manifest \
  --rights-csv <CSV绝对路径> --rights-summary <JSON绝对路径> \
  --rights-csv-sha256 <完整CSV_SHA256> --rights-summary-sha256 <完整JSON_SHA256>
# rights-query 使用相同四个绑定参数，另加：
# --symbol sh.600626 --start 1993-06-21 --end 1993-06-21 --status all --offset 0 --limit 10
```

CLI返回0表示候选交付读取验证成功（可以仍有未决记录），2表示参数或读取失败；多行响应超过原64KiB预算时明确拒绝，应减小limit，不截断成成功结果。标准MCP启动支持同一组四个可选参数，必须全给或全不给；这里只是启动配置能力，不自动部署。普通ChatRuntime可由宿主以rights_candidate_binding关键字注入同一绑定；本轮未新增桌面选包按钮或永久默认绑定，普通客户端不因此自动读到开发artifacts。锁定QM50和首轮Reviewer权限不扩展；F9导出、Provider、Grant、审批冻结与研究执行均不变。

### 与数据治理侧的下一阶段分工

已接受的候选CSV及摘要保留原字节，新取证只做独立补充包并引用父CSV/JSON SHA，不覆写原分类、不重跑整批分类为目标。数据侧优先为待决事件提供事件/方案身份、股份基数、实施与除权日期、各字段原值和逐字段来源、原文文件SHA及locator。零值冲突不得擅自移动c1/c2；送转前后基数是待查线索，不按价格相近或乘1.1直接裁决。小差异来源选择应提出有证据的建议，不以小数位多或供应商名气自动选边。未匹配记录保留查找范围和缺失原因，零成交不当市场反应，找不到不等于事件不存在。

F9停牌支持属于代码合同/执行语义范围；数据侧只交原始状态、量额空值/零值、停复牌边界及内容身份样本，不删停牌或填量来适配旧F9。前向逐日Universe和新的公开源抓取不自动开始：需要新请求列明目标、用途、预算与授权；缺原始证据可交缺口清单，不为“全收口”编造决策。后续代码的有限重建预览与正式发布仍需分别评审，不由F17读取自动放行。

## 11. 有界配股事件重建预览（F18）

`get_rights_rebuild_contract` 纯读合同；`preview_rights_rebuild(request_json)` 复用F17宿主双文件/双SHA绑定，只有内存中的事件草案和候选算术。没有发布、保存因子、研究批准、人工裁决或订单接口，不读取正式行情/公告，不执行治理脚本。普通Chat与标准MCP共用原工具层；未新增GUI按钮或默认绑定，QM50锁定和首轮Reviewer权限不扩展。

请求严格包含 `contract=niuniu-rights-rebuild-preview-v1`、已验证的 `bundle_id`、`scope` 和 `choices`。scope为1–10个不重复规范证券代码及1–3660自然日的start/end；自动纳入该范围在绑定CSV里的全部配股事件，整范围最多20条，不支持status过滤、分页、exclude或skip_unknown。其它公司行动类仍明确not_evaluated，清单本身不是全市场事件全集。选择空窗口或含无候选证券，返回blocked，不能解释为没有公司行动。

`choices=[]` 可先盘点该范围的全部事件引用及阻断原因。随后每项选择必须带 `code/ex_date/event_digest/rights_source`，rights_source只能明确为tdx或cninfo，配股价和比例成对取同源。精确组同样要求明确数值来源，不隐式采用舍入后值；小差异不默认选边。重复、范围外、旧事件引用、错误bundle或请求中携带approve/execute/path等字段拒绝；原源文件变化由F17读源校验拒绝，不能靠同路径重绑。

| 返回状态 | 含义 |
|---|---|
| blocked | 请求已解析并读取绑定资料，但全范围仍有未选源、待决、未匹配、缺少前收/所选字段等；每条和顶层均保留阻断 |
| ready_for_review | 本范围清单内全部配股事件已给出可计算的草案，**仅供人工审阅**，不代表全公司行动齐全或允许重建 |

conflicts/cninfo_none即使带来源选择仍阻断，计算值为null；不支持自签approved或新参数覆盖。已有明确事件可展示自身的候选计算，但只要范围内其它事件未解决，整份仍blocked。缺值不填0，空选择不自动补默认源。零成交只令价格诊断不可用，不据此认定行动真假；此处也未核实前一交易日、停复牌和股份基数。

每个草案列出实际使用的交付原字符串、单位、字段和provider_claim：派息/送转固定来自TDX c1/c3，配股价/比例来自所选供应商，前收来自交付prev_raw_close。公式沿已接受的候选合同 `(P-c1/10+(ratio/10)*price)/(1+c3/10+ratio/10)`，**假设旧股基数一致且行动并存，未经认证**。巨潮方案是混合来源，不是官方参考价。仅给理论价、单事件因子比、理论raw变动百分数，使用40位固定Decimal上下文和十进制字符串；不按实际价格挑选来源、不累计事件因子、不生成base_date归一化曲线。

规范化请求、事件键/内容、范围、来源、计算及阻断一起进入preview_digest；scope_digest单独绑定范围和完整列内事件集。请求JSON空白/键顺序、choices与symbols排列不改变同语义预览；换范围、来源或候选版本会改变身份。无墙钟时间戳、无持久成功缓存；单次响应仍受64KiB完整输出预算，超限拒绝而不是截掉后半部分。official_verified、factor_no_change_verified、strict_pit、reconstruction_authorized、publication_authorized始终false；factor_series与adjusted_prices始终null。

```bash
# 先看精确请求字段；不需任何数据根。
.venv/bin/python -B -m quantlab.agent.data_review_cli rights-preview-contract
# 复用第10节四个宿主绑定参数，再给完整JSON字符串。JSON从已验证bundle_id和事件引用生成。
.venv/bin/python -B -m quantlab.agent.data_review_cli rights-preview \
  --rights-csv <CSV绝对路径> --rights-summary <JSON绝对路径> \
  --rights-csv-sha256 <完整CSV_SHA256> --rights-summary-sha256 <完整JSON_SHA256> \
  --request-json '<完整预览请求JSON>'
```

CLI 0=ready_for_review，3=blocked，2=请求/绑定/交付/预算错误；合同查询成功也是0。read-only工具响应ok仅指调用完成，必须再看data.status/incomplete，不将blocked解释为通过。F9停牌合同及实际因子重建发布继续单独推进，F18不修改Provider、原审批冻结、Grant或复算。

## 12. 未决配股补充证据只读绑定（F19）

F19在F17候选与F18预览之上增加**可选的第二层宿主绑定**，用于读取数据侧S1的19条未决配股本地证据。宿主必须同时给出JSONL、summary及各自完整SHA256；summary必须绑定JSONL SHA和父F17 CSV/summary SHA。工具不会扫描“最新文件”，模型也不能传路径或hash。未配置时F18保持原输出结构，不因为代码里存在S1能力就自动发现或加载资料。

`get_rights_conflict_evidence_manifest` 会重新校验父候选全部conflict事件、S1事件全集、`parent_event_digest`、TDX c1-c4与巨潮价/比例等父字段以及摘要计数；S1必须恰好覆盖父候选的全部conflicts，且19条 `verdict` 全部保持 `UNRESOLVED`、`action_or_plan_id=unknown`。参与股数汇总的diagnostics只允许有限数值或null，布尔/字符串/非有限值拒绝。`query_rights_conflict_evidence` 只接受规范 `YYYY-MM-DD` 日期，单页最多5条；空结果只表示该固定补充包中无匹配记录，不表示事件不存在或已解决。

`preview_rights_rebuild` 只有在宿主同时绑定S1时，才给对应conflict事件附加 `supplemental_evidence`。该信息包括股份基数发现、争点、股息旁证、缺失证据和待答问题，文本始终视为不可信来源声明。**它不会删除 `EVENT_REQUIRES_SEPARATE_ADJUDICATION`，不会生成calculation，也不会把 `UNRESOLVED` 改为来源选择、裁决或重建许可。** `reconstruction_authorized` 与 `publication_authorized` 继续为false；Reviewer与QM50锁定会话不新增这些工具。

CLI增加 `rights-evidence-manifest` 与 `rights-evidence-query`；`rights-preview` 可额外带四个 `--rights-evidence-*` 宿主参数。普通Chat/MCP只看到无路径的只读工具。当前已验收S1只读smoke读取19条、`adjudications_made=0`、`price_evidence_used=false`，并验证 `sh.600626/1993-06-21` 即使显式提出TDX来源仍保持blocked；父候选与S1四个文件的内容SHA和mtime均未变化。F19仍不读取正式行情/公告，不执行治理脚本，不修改候选状态、因子、审批或授权。

## 13. F9 停牌状态输入合同 v2

F9 原 `tradable_only_v1` 保持默认：请求范围内出现 `tradestatus!=1` 仍拒绝，不静默改变既有包格式、preview/request/manifest或旧研究身份。需要保留停牌时，CLI `preview/export` 或桌面工作台必须显式选择 `preserve_suspension_state_v2`；v2 使用独立包格式，合同版本进入preview hash、manifest、dataset_id和冻结后的数据身份，切换合同会使旧预检/确认失效。

v2 保留固定交易日历中的完整证券×session网格以及原始raw/typed字节。`tradestatus=1` 行继续要求完整有限OHLCV；`tradestatus=0` 行必须显式保留 `bs_trade_status=0`，normalized OHLC保持null，禁止用前收或其它价格填成K线。停牌volume/turnover只保留来源已有的null/非负有限值；`vendor_previous_close`必须为有限正数，但它只是在没有历史mark时可用的估值参考，绝不是open/close/fill价格。缺状态、混合/未知contract、缺少估值参考、非有限值均fail-closed。

研究侧只有带显式v2 `input_contract` 的bars才启用停牌语义。停牌session仍留在完整网格中，因子shift/horizon不会因删行跳到复牌日；当日universe mask强制 `eligible=false`，停牌OHLC为null，因此以停牌日作为价格终点的forward label保持null。因子或处理器若不能处理null，应显式失败，不做隐藏forward-fill或删行。没有v2 contract的旧数据即使含 `bs_trade_status` 字段，也继续按旧OHLCV验证规则处理。

执行侧将可成交价格和估值mark分开。v2停牌行不进入open价格表，不产生fill；目标变化记录 `vendor_suspended` 拒绝并在后续可交易session继续由既有目标语义处理。持仓估值优先沿用最后一个真实可交易close；若账户在没有历史mark时遇停牌，仅可使用来源 `vendor_previous_close` 建立估值mark。`vnpy_open` 明确拒绝含停牌v2行，避免将null OHLC交给原生撮合；open/vnpy_rules沿状态感知路径处理。

停牌日如果同时发生会改变经济价值的公司行动，不能一边沿用除权前mark、一边又计应收现金/新增股份，否则会重复估值。当前对持仓的停牌除权现金/送股场景直接阻断并要求显式的行动后估值证据；股票拆分等原有流程缺少真实估值bar时继续按既有规则fail-closed，不从 `vendor_previous_close` 推导除权后成交价。

人工批准仍冻结实际normalized parquet。对v2，冻结后的 `DataSnapshot.snapshot_id` 额外绑定冻结parquet SHA、原source snapshot id和 `preserve_suspension_state_v2`；文件证据同时保留 `input_contract`。因此原数据包/来源在批准后离线仍可从冻结字节运行和复算，但不能把相同请求的v1/v2或不同冻结字节视为同一snapshot。v1没有contract字段时沿用原snapshot算法，不做无关身份迁移。

F9 v2仍然只是 `research_only/raw/1d` 的有限归档输入合同，不证明历史停牌状态官方完整、价格正确、Strict PIT、可交易性或全市场覆盖，也不改变权限、采集、正式数据或自动交易边界。

## 14. F21 通用 Observation / Revision / Event 版本合同

F21 新增 `niuniu-observation-version-ledger-v1`，把过去混在一起的“经济事件、来源修订、内容、抓取观察”拆成四个独立身份：`event_id = digest(domain,event_type,event_key)`；`revision_id = digest(event_id,source_id,source_revision_key)`；`content_hash = digest(payload)`；`observation_id = digest(revision_id,observed_at,content_hash)`。因此同一个来源修订被重复抓取，只增加 observation，不会制造第二个经济事件或第二个 revision；同一个 revision key 若内容、publication/effective/supersedes 等修订级语义发生冲突则直接拒绝。

账本由宿主显式绑定 `observations.jsonl + summary.json + 双 SHA256`。summary 的 records/events/revisions/sources、选择策略和限制全部从 JSONL 重新计算，不信任自报计数；JSONL 逐行采用闭合字段、重复 JSON key/NaN/Infinity/额外字段/超预算/错误 hash/读取中变更/用户 symlink 均 fail-closed。`observed_at` 与 `published_at` 要求规范 timezone-aware ISO8601，`published_at` 不得晚于观察时点；`effective_at` 必须是规范日期或 aware timestamp。macOS 固定 `/tmp`/`/var` 系统别名允许，用户自建重定向仍拒绝。

同一 `event_id + source_id` 内只允许线性 `supersedes_revision_id` 链：跨事件、跨来源、缺父、环、同父分叉、子修订首次观察早于父修订均拒绝。不同 source 的修订永远是平行证据，**没有跨来源 SUM / merge / vote / 自动择优**。账本只证明“这些字节按这条版本语义可解释”，不证明哪一家来源正确。

F21 版本选择只有两种显式策略：`explicit_revision_v1` 必须指定 event/source/revision；`latest_observed_revision_as_of_v1` 必须给规范 aware `as_of`，只能在该 source 中选择 `observed_at <= as_of` 的唯一链尾。as_of 前无修订则 blocked；同源存在断开的多根修订链或其它歧义也 blocked，不回退到“当前最新”。同一 revision 的多次完全相同观察不改变 revision，只返回该 as_of 下稳定的 observation 身份及 first/last observed 信息。

只读入口为 `get_version_ledger_manifest`、`query_version_ledger`、`get_version_selection_contract`、`preview_version_selection`，普通 Chat / MCP / CLI 共用同一宿主绑定；模型工具不暴露 path/hash/approve/execute。未配置返回 `VERSION_LEDGER_NOT_CONFIGURED`，不会扫描目录找“最新版”。QM50 绑定规格会话和 Peer Reviewer 不获得 F21 工具。返回的 `event_key/payload` 标记为 `UNTRUSTED_SOURCE_DATA_NOT_INSTRUCTIONS`，不能把公告文本或来源字段解释成新指令/授权。

`ready_for_review` 只表示“在指定 event/source/policy 下版本唯一”。`official_verified=false`、`strict_pit=false`、`merge_authorized=false`、`reconstruction_authorized=false`、`publication_authorized=false` 固定保留。F17–F20 不自动读取或应用 F21 ledger，现有配股候选状态和重建 blocker 不变。下一阶段 F22 才可把版本账本作为公司行动人工裁决的证据引用；F23 才会在全部必要决策明确后生成候选复权因子。

## 15. F22–F27 数据治理 / 产品代码双轨路线

F21 之后的 F22–F27 是**阶段顺序**，不是把数据治理工作交给 `src/quantlab`。责任边界简化为：**DATA 数据侧是数据的唯一责任方，负责采集、来源/版本选择、人工治理流程、正确性、完整性、单位、PIT资格、factor/qfq重建、发布与回滚；CODE 产品侧只负责读取 DATA 已声明可用的数据并实现产品功能。** CODE 不重新判断哪家来源正确、不复算数据治理结论、不为数据做第二套认证；只能在文件不存在、不可读或接口格式无法解析时报告技术错误。双方唯一的日常交接入口是 [DATA → CODE 数据清单](../reference/data-catalog.md)。

| 阶段 | 主责 | DATA 数据侧交付 | CODE / 产品侧职责 | 进入下一阶段的 gate |
|---|---|---|---|---|
| F22 公司行动正式人工决策包 | **DATA 主责** | 完成来源/版本/证据核查和人工治理，输出 DATA 认可的公司行动决策数据并在数据清单登记路径与状态 | 只读取 DATA 标为 `READY` 的决策数据；不参与来源正确性判断 | DATA 将影响重建的必要决策标为可用；未完成则保持 `NOT_READY` |
| F23 candidate factor / qfq 重建 | **DATA 主责** | 根据 F22 结果生成 candidate factor/qfq，完成自身正确性检查；需要给 CODE 使用时发布成 DATA 认可的可用数据并登记路径 | 不运行全库 factor/qfq 重建，不比较来源，不审核因子正确性；只读取 DATA 最终公布的路径 | DATA 确认重建结果满足其质量要求并更新数据清单 |
| F24 影响审计 + publish gate + rollback | **DATA 主责** | 数据侧自行完成影响审计、publish gate、发布和 rollback；决定哪个版本是当前正式版本 | 只读取数据清单中 DATA 标记为 `READY`/当前正式的数据；不承担 publish/rollback 审核 | DATA 更新正式数据路径/版本/状态后，CODE 才切换消费 |
| F25 Auction 版本 / 单位治理接入 | **DATA 主责** | 数据侧完成 Auction 版本、单位、精度、历史口径治理并输出统一可用数据 | 按数据清单读取统一 Auction 数据，不自行猜单位或复核来源 | DATA 标记 Auction 数据 `READY` |
| F26 Strict PIT Universe / 状态 / 规则正式化 | **DATA 主责** | 数据侧保证 Universe、Security Status、Market Rules 的 Strict PIT 资格并输出正式数据 | CODE 只按数据清单消费 DATA 声明为 strict-ready 的数据，不独立认证 PIT 正确性 | DATA 在清单中明确目标数据 `READY` 及覆盖范围 |
| F27 治理后真实 AI 自主研究最终验收 | **CODE / AI 主责** | DATA 提供并维持验收所需的最终 `READY` 数据清单 | 牛牛从正式入口自主读取这些数据、形成假设、调用正式研究工具、保存证据/失败反馈/记忆并可重开复核；外部开发者只观察与修功能缺口 | 验收的是产品自主研究闭环；数据正确性结论沿用 DATA 的交付，不在 F27 重做数据审计 |

既有 F17 交付的 878 条候选曾以 `746/88/19/25` 四桶记录。仓库已明确其中 **19 条**为 `conflicts/NEEDS_DECISION`，S1 补充证据仍为 19/19 `UNRESOLVED`；因此它们在 F22 没有人工闭合前不能进入 F23 正式候选重建。**88 条的精确分类名称与处置语义继续以父治理包为准，本文不重新命名数据侧状态**；数据侧应在 F22 复核其中哪些条目仍需新增证据或会实际影响 factor/qfq，只有这些未闭合且影响重建的项目才构成 F23 gate。

跨轨原则只有两条：**DATA 对数据负责，CODE 对使用数据的产品行为负责。** CODE 不扫描数据根寻找替代来源，不因某份数据缺失就自动换另一来源，也不把自己的测试结果解释成数据正确；DATA 只需在统一数据清单中维护“有什么数据、数据在哪里、覆盖什么、当前是否可供 CODE 使用”。若 DATA 标记 `NOT_READY`，CODE 应把对应能力视为数据未就绪，而不是自行修数据。

### 15.1 CODE / DATA 协作方式

协作只保留两个物理根：`/Volumes/Lexar/niuniu` 是代码仓，`/Volumes/Lexar/niuniu-data` 是 DATA 自己管理的数据根。**数据根内部怎么分 bronze/silver/gold、receipt、backup、staging，是 DATA 的内部实现；CODE 不依赖这些内部约定。** CODE 只依赖一份稳定的 [DATA → CODE 数据清单](../reference/data-catalog.md)。

数据清单由 DATA 维护，每个可交付数据只需要写清：**数据名称/ID、数据内容、绝对路径、格式、覆盖范围或粒度、状态（`READY` / `NOT_READY` / `REVIEW_REQUIRED`）以及必要的使用说明。** DATA 一旦把某项标成 `READY`，就表示该项的数据正确性、来源选择、单位、版本、完整性以及适用范围已经由 DATA 负责确认；CODE 不再重复审核这些结论。

CODE 的读取规则也保持简单：只使用清单中明确标为 `READY` 的路径；不扫描 `/Volumes/Lexar/niuniu-data` 找“看起来更新”的文件，不在多个来源之间自动回退，不比较哪家供应商更正确，不重算 qfq/factor 来验证 DATA，也不读取 `NOT_READY`/`REVIEW_REQUIRED` 项冒充正式数据。运行时最多检查目标文件/目录是否实际存在、能否读取、格式是否能被当前 reader 解析；这些失败属于接口/运行错误，不是数据正确性审计。

DATA 如果新增、移动、替换或停用数据，应先更新数据清单，再通知 CODE 适配；CODE 如果需要一种尚未在清单中的数据，只向 DATA 提“需要什么数据/字段/范围”，不规定 DATA 必须如何采集和证明正确。这样 F22–F26 都由 DATA 自己完成治理和质量保证，CODE 只在对应数据变为 `READY` 后接入；F27 才验收牛牛是否能正确使用这些已交付数据。

代码侧已经实现统一读取层：`list_data_catalog` 分页读取 DATA 清单，`get_ready_data_source` 按 `dataset_id` 取得 `READY` 的 FILE/DATABASE/API/STREAM 入口；普通 Chat、标准 MCP 和只读 CLI 共用该边界。CODE 仅对 FILE/DATABASE 做“路径实际存在且可读”这一技术检查，明确返回 `data_correctness_revalidated_by_code=false` 与 `fallback_performed=false`；`NOT_READY`、`REVIEW_REQUIRED`、`DEPRECATED`、未登记数据均不会自动换源。锁定研究规格会话不新增这两个通用入口。

### 15.2 当前 DATA 交付的机器消费边界（2026-09-23 晚）

DATA 的文件型版本路由另有机器清单 `/Volumes/Lexar/niuniu-data/catalog/dataset_registry.json`。它解决“当前物理版本在哪”，而 `data-catalog.md` 解决“是否已经交付给 CODE 使用”；两者均由 DATA 维护。CODE 不根据目录修改时间找最新版。当前 qfq 已由 DATA 发布为 `qfq_published_f24=READY`，registry 的 `bars.daily.qfq` / `bars.min5.qfq` 指向 `qfq_kline_daily_v2` / `qfq_kline_min5_v2`，因此核心 `MQCParquetProvider` 按 registry 读取 v2。若 registry 存在但 current 条目缺失、路径逃逸/链接、目标不存在或状态不是 current，直接失败，不回退旧目录。

qfq v2 的覆盖不是“所有历史都已裁决”：DATA 对未确认事件不猜，452只证券从最后一个未确认事件之后才提供历史，逐证券起点在日线 v2 的 `_meta/coverage.parquet`。CODE 按 coverage 里 DATA 给出的 `history_truncated` 区分两种情况：为 `true`（历史因未确认事件被截断）时，请求早于 `valid_from`，或5分钟请求早于该证券实际发布文件首日，直接阻断，不得改读旧 qfq、用 raw 伪造前复权或静默只返回后半段；为 `false` 时 `valid_from` 只是该证券历史的起点（上市日），请求起始日更早也和 raw 一样从有数据的日期开始截取，不会因为一批股票里有一只后上市而整批失败。coverage 缺少该列时一律按截断处理。这个行为只执行 DATA 已公布的覆盖字段，不重新判断复权因子是否正确。

DATA 当前还交付6个 `READY` 按需研究API：`research_search`、`stock_research_reports`、`stock_news`、`stock_announcements`、`financial_statements`、`investor_qa`。其统一实现由 DATA 提供的 `quantlab.data.research_provider.ResearchDataProvider` 负责供应商、凭证、限频、字段映射和错误语义；CODE 只通过 `ResearchDataAPI` 暴露给普通 Chat/MCP/CLI。每次调用先查 DATA catalog 的同名项仍为 `READY`，否则在联网前拒绝；供应商错误只报告不可用，不换源。

`stock_fund_flow_daily`、`realtime_quote`、`market_snapshot`、`fuyao_context` 当前均为 `REVIEW_REQUIRED`。这一状态现在不仅体现在新统一工具里，也已经约束旧入口：普通 Chat 不注册 Fuyao 聚合工具、不做自动实时报价预取；MarketSnapshot readiness/live CLI/Daily Orchestrator 不允许公开网页实时 capture。即使旧 provider 类、网络代码或凭证仍存在，也不能绕开 DATA 状态。DATA 日后把对应项改为 `READY` 后，这些 gate 才允许 CODE 使用；CODE 不自行改变状态。

其余17类新增公开来源文件数据已经由 DATA 标 `READY` 并可通过 catalog 发现。它们的 schema/日期语义差异较大，CODE 不建立“任意 dataset_id + 任意列/SQL”的模型工具；后续只有具体产品功能需要时，才按清单的字段和覆盖合同增加有界 reader。这样既能消费 DATA 现有资产，也不会把数据湖浏览权限重新交给模型。

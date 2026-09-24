# 使用指南

[文档导航](../README.md) · [当前状态](../project/status.md) · [运行与运维](operations.md)

本指南说明当前程序的入口与典型流程。数据覆盖、任务状态和研究结论以实际工作空间为准；历史验收中的测试数量和数据量不作为今日实时状态。

## 1. 启动与安装

当前 Mac 可直接双击仓库根目录的 `启动牛牛平台.command` 或 `启动牛牛AI研究助手.command`。前者打开完整工作台，后者打开对话助手；它们共享项目 `artifacts/` 和独立数据根 `/Volumes/Lexar/niuniu-data`。

新环境在仓库根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[desktop]"
quantlab desktop --data-root /path/to/niuniu-data --output ./artifacts
```

Python 至少为 3.11。Windows PowerShell 激活命令为 `.venv\Scripts\Activate.ps1`。只使用 CLI 可安装 `python -m pip install -e .`。按实际需要安装额外功能：

```bash
python -m pip install -e ".[market_data]"
python -m pip install -e ".[vnpy]"
python -m pip install -e ".[mcp]"
```

这些安装命令不配置券商账户、不授权下载，也不自动开启任何交易通道。依赖版本以 [pyproject.toml](../../pyproject.toml) 为准。

无行情也可以先查看注册项和界面：

```bash
quantlab factors
quantlab theories
quantlab desktop --output ./artifacts
```

## 2. 页面怎么用

打开后左侧是 7 个日常工作台，每个回答一个问题；研究、治理和开发工具收在左下角“专业模式”开关里（设置按工作空间保存在 `artifacts/_desktop/ui.json`）。

| 页面 | 回答的问题 | 当前状态 |
|---|---|---|
| 今日市场 | 市场整体怎么样：涨跌家数、涨停跌停、连板高度、成交额、昨日涨停溢价、两融，并给出近一年分位 | 已上线（盘后） |
| 主线方向 | 什么方向最强：领涨行业、连续进前五天数、涨停原因集中度 | 已上线（盘后） |
| 今日候选 | 5 条固定选股规则今天各选出哪些股票、入选理由，以及每条规则过去一年的实际表现（扣成本后是否跑赢全市场） | 已上线 |
| 个股报告 | 一只股票怎么样：涨幅、相对全市场和行业的强弱、均线与放量、日K、需要留意的事项（ST、解禁、减持、业绩预告等）、最新公告和研报；可一键交给 AI 分析 | 已上线 |
| 我的股票 | 自选/持仓列表（仓位和成本可不填），每只的当日状态和需要留意的事项、整体集中度；可一键交给 AI 巡检 | 已上线 |
| 复盘验证 | 过去的判断和后来的结果 | 已可查看已保存判断 |
| AI 助手 | 自然语言提问；默认“日常”模式只带约10个工具（市场、个股、我的股票、公告/研报/新闻/财报），专业模式下默认“研究”模式（全部研究工具）；各页“问 AI”会把当前页面数据填进输入框，确认后再发送 | 已上线 |

专业模式下的页面：交易台（原“今日交易”）、主题矩阵（原“主线市场”）、股票决策档案（原“股票中心”）、持仓计划、决策复盘（原“复盘中心”）、AI 团队、研究实验室、开发工作台、系统中心，功能与原来一致。菜单接线见 [app.py](../../src/quantlab/desktop/app.py) 的 `PAGES`。

### 今日市场与主线方向的数据

两个页面读取同一份每日结果 `artifacts/_home/market/<交易日>.json`，由 [market_overview.py](../../src/quantlab/trading/market_overview.py) 生成，只使用 [DATA → CODE 数据清单](../reference/data-catalog.md) 中标为 `READY` 的前复权日线、日状态/ST、同花顺涨停池、交易所两融和 Baostock 参考快照（行业、名称、交易日历），不联网、不写数据根。打开页面时若结果早于应有的交易日（北京时间 18:00 后为当天，否则为上一交易日），会在后台自动重算，约 1–2 分钟；也可点“立即更新”。

也可以在命令行生成（适合以后接定时任务）：

```bash
.venv/bin/python -m quantlab.agent.market_overview_cli --output ./artifacts
.venv/bin/python -m quantlab.agent.market_overview_cli --output ./artifacts --show
```

### 今日候选与历史验证

规则写在 [candidates.py](../../src/quantlab/trading/candidates.py)：强势趋势、放量创新高、首板、强势股回调、超跌，都排除 ST 和停牌。规则固定写在代码里，不按结果调参数。每次生成今日市场时，用同一套特征把每条规则放回最近约一年的每个交易日：次日开盘买入（次日一字涨停买不进的剔除）、第5个交易日收盘卖出、等权，与当天全部可交易股票做同样操作相比，每5天取一个不重叠样本，扣约0.2%往返成本。结论分三档：扣成本后跑赢且 t≥2 为“较稳定”，跑输且 t≤−2 为“跑输”，其余为“没有显示出稳定优势”。

2026-09-23 的实际结果：5 条规则都没有显示出扣成本后的稳定优势，其中“首板”次日开盘买入持有5天平均跑输全市场约1.3%（t≈−2.7）。局限：只含当前在市股票（幸存者偏差）、只有约一年、只代表这一段市场环境。个股报告里如果该股今天入选了某条规则，也会显示这条规则的验证结论。

### 个股报告与我的股票

个股报告读取当天市场总览附带的逐股快照 `artifacts/_home/market/<交易日>.stocks.parquet`（近5/20/60日涨幅、全市场与行业内强弱分位、均线距离、距60日高点、成交额/20日均值、连板等），再读该股的前复权日线和数据侧已交付的业绩预告、未来30天解禁、近30天股东增减持文件，所以打开很快（不再扫描全市场）。公告和研报经 DATA 的研究接口在线查询，接口未开放或失败时分别说明，不换数据源。“需要留意”是客观事实提示（ST、停牌、距高点回撤25%以上、跌破20/60日线、放量2.5倍以上、3连板以上、解禁、减持、业绩预减/亏损），不是买卖信号。

我的股票保存在 `artifacts/_home/my_stocks.json`，最多50只；仓位合计不超过100%，未填的部分视为现金。

口径：涨跌按前复权收盘计算（除权日不算下跌）；涨跌停按板块规则和“前一日前复权收盘 ÷ 当日复权因子”推算的前收判断，不是逐日官方涨跌停价，新股上市初期和退市整理期不计；分位是与近一年同一统计量相比；行业用参考快照当天的证监会行业分类。指数行情和盘中实时数据侧尚未提供，所以暂不显示指数。结果是描述性统计，不是买卖信号。

## 3. 先走通一次小研究

先确认数据根正确、所选证券确有对应区间数据，再在数据中心检查覆盖和资格。小样本用于测试流程，不用于判断策略有效。

```bash
quantlab run \
  --data-root /path/to/niuniu-data --output ./artifacts \
  --symbols sh.600000 sz.000001 sh.600519 \
  --timeframe 1d --start 2024-01-01 --end 2024-12-31 \
  --factor BASE.MOMENTUM --lookback 20 \
  --horizons 1 5 20 --adjustment qfq --replay
```

完成后查看本次 experiment/run 的状态、报告、观测和回放；不要只看一项收益或“完成”标记。已有配置可在客户端编辑，也可用 `quantlab run --help` 查询参数。

评分与执行示例使用仓库 [examples/score.json](../../examples/score.json)：

```bash
quantlab run \
  --data-root /path/to/niuniu-data --output ./artifacts \
  --symbols sh.600000 sz.000001 sh.600519 \
  --timeframe 1d --start 2024-01-01 --end 2024-12-31 \
  --factor COMB.SCORE --params-json examples/score.json \
  --adjustment qfq --backtest --execution-backend open --replay \
  --execution-json examples/execution_statutory.json
```

[examples/execution_statutory.json](../../examples/execution_statutory.json) 开启 `statutory_fees`，按成交日计卖出印花税和过户费（只支持 2008-09-19 及以后的日期）。不带 `--execution-json` 时引擎默认不收印花税、过户费，也不挡涨跌停；这种情况下回测结果、报告和客户端“模型边界”会以 ⚠ 明确提示，命令行也会在标准错误输出提示。要模拟涨跌停，需提供逐时点 `--market-rules`，或用 `limit_pct` 作固定比例近似。

日期与股票只是参数示例，不能据此假设你的资料齐全。原 `examples/verify_*.py` 等历史验收脚本可能依赖开发机数据、特定实验 ID 或可选组件，不能把它们当作无前置条件的一键演示。

### 因子、组合研究和策略的区别

2026-09-21 按当前注册代码核对：`default_registry()` 含 **441 个因子/组件注册项**，`quantlab theories` 含 **16 个组合研究模板**。这是本次代码快照的数量，不是已验证策略数；ALPHA101 等名称也不代表该家族全部表达式已实现。

| 层次 | 当前内容 | 边界 |
|---|---|---|
| 因子与组件 | 基础指标、Alpha 表达式、结构、事件、状态、序列与 DSL | 输出特征/信号，不自动定义资金与买卖流程 |
| 组合研究模板 | 缠论二类买点、Brooks 二次入场/突破回踩、Wyckoff 阶段链、ICT/SMC 等明确规则组合 | 不只是单因子；可以跑组合、消融、留出、滚动和敏感性研究，但不等于完整主观理论或独立成品策略 |
| 通用成交研究 | `ExecutionStudy` 将信号接到目标权重、成交、费用与账户归档 | 不限于期末50分；仍需明确阈值、选股数、仓位和执行配置 |
| 专门的策略流程 | `qimo-source-rules-v2` + `QimoPaperRunner`，包含日内选择、条件持有/退出和模拟结算 | 当前专门封装的规则流程主要围绕期末50分；是显式工程近似的 DRAFT，不是原作者完整复刻或盈利证明 |
| 事件与方法研究 | AR 事件研究/自主研究框架，以及郑希、AI产业雷达 Research Skill 假设 | 框架或知识假设不能按名称当作已经完成的交易策略 |

旧 Qimo 规则代理与 **QM50-SCLA v0.2 原始规格**是不同合同，后者不能用前者或同名通用因子替代。这里只盘点随代码提供的能力；不据此推断当前工作空间中用户创建的 Playbook、批准记录或运行状态。

实现入口：[组合模板](../../src/quantlab/theory/templates.py)、[理论研究](../../src/quantlab/experiments/theory_study.py)、[成交研究](../../src/quantlab/experiments/execution.py)、[Qimo 模拟流程](../../src/quantlab/trading/qimo_paper.py)。

### 通过助手发现组合研究模板

本地聊天和标准 MCP 均支持 `list_research_templates(query, offset, limit)` 与 `get_research_template(template_id, version)`；首轮 Reviewer 也能读取这些事前规则定义。目录直接来自同一 `theory/templates.py`，不维护另一套手写清单。可以要求助手“列出现有组合研究模板，区分研究信号和完整交易策略”，然后按返回的精确 ID/版本读取规则、组件和来源哈希；不接受 `latest` 或猜测版本。

模板详情返回 `submission_fields={theory, theory_version}`，用于原有 `preview_experiment/propose_experiment`。证券、日期、周期、模式等仍需按实际宿主范围固定；固定模板不能同时覆盖 `factor/version/parameters/grid`。读取模板不会启动研究，Research Session Grant v1 仍拒绝 theory/context/execution；宿主锁定 QM50 原始规格时也不会开放通用模板作为替代。

策略统一封装的 v1 已接入下述版本化策略包：固定信号、范围、资金、目标持仓/退出、费用和成交合同，经原 Proposal/JobQueue/ExecutionStudy 审批执行。它不是将16个模板自动登记为成品策略，也没有替用户指定实际交易参数、验证Alpha或部署常驻执行。

### 完整策略配置包 v1

本版明确只接受 `qualification=research_only`；尚未把严格资格回执封装进策略包，所以请求 `strict_pit / official_rule_covered / retrospective_reference` 会直接拒绝，不会静默降级。原有严格研究入口保持不变，不能用包哈希代替资格证据。

[语法示例](../../examples/strategy_package.example.json) 只演示结构，代码、日期和金额不是推荐参数，也不能据此假定本地行情齐全。包有 `format / strategy_key / name / version / lifecycle / spec` 六个必填字段，可选 `revision_source` 固定直接父实验来源；策略版本为非空固定版本标签（例如1.0.0或draft-1，不接受latest），信号必须明确选择 `factor + version + parameters` 或 `theory + theory_version`，两者不可混用。`spec` 须显式固定研究范围、价格/资格口径、`mode=execution`、`replay=true`、资金/成交及仓位配置。

v1 使用原引擎的固定生命周期：每根完结 K 线按信号和约束重算目标权重；目标减少或归零驱动减仓/退出，实际成交仍受T+1、换手、停牌、价格限制和费用影响；样本末仅按市值计价，不强制平仓。它不支持独立止损止盈、固定持有期或任意自定义状态机。目标上限不是保证实际持仓永远不超限；缺逐日交易规则时也不能声称已验证真实交易可达性。

先在本机预览，不读行情、不生成任务：

```bash
.venv/bin/python -B -m quantlab.agent.strategy_package_cli preview \
  --package examples/strategy_package.example.json
```

`preview --export-spec /path/to/new-spec.json` 可导出完整绑定配置，目标已存在时拒绝覆盖。输出 `package` 为规范化配置，`package_hash` 为该配置指纹；`spec.strategy_package` 另固定实际解析配置及信号源码/模板来源。`compiled_spec_hash` 额外绑定完整展开spec、信号源码与模板解析证据，CLI保存提案时必须同时核对两个指纹。哈希不是批准；同名同版本的配置修改会改变配置哈希，编辑后应重新编译原包，不能只改展开spec的一侧。

桌面可在“AI研究助手 → 打开人工提案审批”面板点击“导入完整策略包（不执行）”，核对草稿，再保存待批准提案。导入会取消旧提案选择/勾选，不自动保存或批准；批准继续使用原数据资格、预算、实际输入冻结和任务队列。也可使用宿主CLI保存待批准提案：

```bash
.venv/bin/python -B -m quantlab.agent.strategy_package_cli propose \
  --package /path/to/your-strategy.json \
  --expected-package-hash <preview返回的package_hash> \
  --expected-compiled-spec-hash <preview返回的compiled_spec_hash> \
  --output /path/to/workspace --data-root /path/to/data \
  --request-id <本次请求的规范UUID>
```

同一请求重试须复用UUID；保存后仍在原审批面板批准，CLI没有批准或执行命令。安装更新后等价短命令为 `niuniu-strategy-package`。归档及 `reproduce_artifact` 都保留策略包身份，复算只用原冻结输入，不回读变化后的数据根。

助手/MCP可用 `get_strategy_package_contract` 读取真实字段合同，再用 `preview_strategy_package(package_json)` 纯配置校验。模型工具只返回完整可用的spec；超出输出预算会明确拒绝并提示宿主CLI，不交付被截断的可执行配置。策略包不扩大Session Grant，QM50绑定会话仍禁止通用包替代原始规格。v1不创建独立策略数据库，也不自动连接Daily Scanner、Paper常驻账户或真实券商。

### 策略工作台：编辑、版本差异与结果对照

在原“人工提案审批”面板打开“策略工作台：可视化编辑 / 版本差异 / 结果对照”。工作台不创建第二个策略库，不自动保存提案或执行实验；关闭/取消不会改变原草稿。已有绑定策略草稿会载入副本，也可导入普通策略包 JSON 或明确填写新配置。

“配置编辑”包含身份、精确信号、证券日期、周期、价格、资金、费用与仓位字段。导入的高级字段保留，可用“编辑完整配置树”调整；模板选择不开放因子参数覆盖。新包的证券、日期、资金不自动填写。无改动往返保留数值类型和配置哈希；修改会清除预览，必须重新校验后才能另存或填入原待审批草稿。另存只创建新文件，不覆盖旧版本；填入草稿仍会清除旧提案选择和确认勾选。

“版本差异”比较载入基线（或另一份明确选择的策略包）与当前草稿，列出逐字段左右值。相同标识/版本而内容不同会提示，不自动升级版本或认定新版本更好。比较按当前编译器解释配置；历史结果另走归档对照，不把重新编译后的配置当历史事实。

“结果对照”可先按名称、版本、标识或研究问题查找策略归档，再选到左侧/右侧；也保留手填完整 run_id 的方式。后端只读取这两个实际归档和其信号子实验，不回读源数据目录或重跑因子/回测；先核对身份、全部冻结输入（包括高周期背景）、股票池原始元信息及版本、运行环境和可比口径，再按已保存净值曲线校验描述性统计。净值日期须唯一并与行情对齐，成交费用缺项不能当零。不可比时保留原因而不产生数值差值，损坏或缺失归档明确失败；即便可比也不给赢家、显著性或Alpha认证。

宿主CLI沿同一服务提供只读对照：

```bash
.venv/bin/python -B -m quantlab.agent.strategy_package_cli compare-packages \\
  --left-package /path/to/v1.json --right-package /path/to/v2.json
.venv/bin/python -B -m quantlab.agent.strategy_package_cli compare-runs \\
  --output /path/to/workspace --left-run <左侧run_id> --right-run <右侧run_id>
```

退出码0表示比较完成且结果口径可比（或配置差异已列出）；3表示归档可读取但结果不可直接比较；2表示请求、归档或核对失败。版本差异和结果对照均不扩大模型、Grant、Paper或真实交易权限。

### 策略归档目录与助手只读查询

输出工作空间根须指向实际目录，不能使用符号链接本身。聊天与MCP在解析路径或初始化聊天存储之前检查原始入口，和宿主CLI/工作台执行相同边界；此检查不认证历史归档内容。

结果页点击“查找 / 刷新归档”才开始读取本工作空间目录，不自动扫描或执行研究。列表包括带策略包的失败 execution；失败记录可见，但不能选作有效结果。旧的不带策略包实验和普通因子子实验不计入该目录；这不是系统内所有策略、Playbook或因子的总清单。

目录返回 `verification=metadata_only`，只核对归档元信息、身份与包合同，不读 Parquet 或展示未经深验的收益。“核验选中归档”及结果比较会重新走同源完整归档一致性检查；发现之后被改坏的记录不会继续当有效结果。修改查询会清除旧列表并忽略已过期的异步响应，不改当前策略草稿或原批准状态。

每次最多扫描100个直接UUID候选，返回最多20个匹配；空匹配页仍可能有下一页。`offset / next_offset` 是候选扫描位置，不是匹配序号；必须使用返回的 `next_offset`。`total_candidates` 不是策略数量。`has_more` 与当前页 `errors / incomplete` 分开披露。目录是动态发现，跨页期间有新建/删除时应刷新重查，不声称整个列表是冻结快照。单个experiment.json超过8MiB或候选超过100000时明确报告限额，不作为无数据或已全部读完。

宿主CLI：`python -m quantlab.agent.strategy_package_cli list-runs --output /path/to/workspace --query 关键词 --offset 0 --limit 20`；核验指定结果：`python -m quantlab.agent.strategy_package_cli get-run --output /path/to/workspace --run-id <run_id>`。列表部分读取失败退出3，参数/整体读取失败退出2，正常完成退出0；还有下一页本身不是失败。

本地助手与标准MCP增加 `list_strategy_runs / get_strategy_run / compare_strategy_runs` 三个只读入口，共用相同目录及比较代码。助手详情只返回策略身份、绩效、限制和证据，不把历史原包自动作为可执行新草稿；输出过大明确拒绝，不删除错误/阻塞/游标以伪装完整。首轮Reviewer不开放这三个结果入口；QM50绑定会话继续拒绝通用策略替代。不扩大提案批准、Session Grant、Paper或真实交易权限。

### 从历史策略继续改版

在“策略工作台 → 结果对照”查找并选中已完成归档，点击“载入为可编辑副本（不执行）”。确认框默认取消；确认后先深验归档、核对目录条目的package_hash，再按当前代码编译配置副本。成功才替换当前工作台草稿；取消、坏归档、选择过期或当前信号版本不可用时，原草稿保留。载入期间再次发生源码变化会拒绝应用，关闭工作台也会使迟到响应失效。

载入后转到“配置编辑”，仍须手动重新预览。版本差异页另显示历史run_id、原包、历史编译指纹及读取时的归档证据，与当前载入时编译指纹分开；当前编译通过不是历史结果复现证明。普通版本差异仍按当前编译器解释两份配置，不能拿它替代历史来源面板。相同strategy_key和版本但配置或信号实现变了，本次改版预览、另存和填入会拒绝，须明确新版本，或显式使用另一策略标识；系统不自动替你起版本号。完全相同配置与编译指纹可保留版本重新发起提案，但不是复用旧任务。

改版来源现在保存为策略包可选 `revision_source`，包含直接父run_id、策略标识/版本及包、编译、内容和证据指纹；随另存JSON、完整提案、执行归档和数值复算保存。只记录直接父，不复制祖先包、不新建数据库、不把策略父关系混入计算子实验children。无来源的旧v1包仍保持原结构和身份，不能推断或自动回填旧来源。再次从历史归档改版时，记录当前选中的实验为直接父，而不是继续沿用祖父。详细来源展示仍为会话内信息，保存的是最小引用而非整条历史链。

重新导入带来源包后，窗口显示已保存的父引用，但标明本次尚未核验。点击“核验已保存的改版来源（只读）”才读取当前工作空间内的直接父归档；失败保留草稿并清除旧核验显示。纯编译及助手预览返回 `revision_source_verification=not_checked`，包哈希不能自行认证来源。CLI可用 `python -m quantlab.agent.strategy_package_cli verify-revision-source --package /path/to/revision.json --output /path/to/workspace`，通过退出0，缺失来源、坏归档或指纹不符退出2；不读取行情、不编译新策略或创建任务。

完整提案预检会核验父来源，正式批准又在冻结实际输入前后核验；父归档缺失、损坏或与保存指纹不符时拒绝批准，不继承旧批准、预算或任务。新提案的核验记录表示保存/批准时的事实，不代表父归档永久有效。若父来源在输入冻结期间变化，提案保持未批准；可能留存的冻结候选以 `unapproved_input_freeze/status=not_approved` 显示，不能当作批准回执。此类改版提案需拒绝后重新生成，不自动删除候选或复用旧冻结输入。来源不携带绝对路径、授权或收益承诺。同标识同版本修改配置/信号时，带来源包即使另存后重开也须明确新版本；内容身份仅排除父引用自身，不排除因子源码或参数。

子实验自身读取和数值复算仍按冻结的计算输入进行，不自动遍历父策略，也不会因为存在一个来源引用就复制其行情或继承其结果。单独移交子实验不自动附带父归档：可读自身结果，但来源核验可能不可用，应恢复精确父归档，而不是静默删除来源。另行导入没有来源的普通包表示无来源草稿，不构成已验证版本谱系。人工审批、有限研究授权、Paper和真实交易边界不变。

## 4. AI 问答与正式研究

在 AI 助手中明确证券代码或本地正式名称，可触发本轮明确范围的一次只读行情查询；唯一证券上下文的明确追问可以沿用，多股歧义不猜。配置扶摇后以扶摇为主，公开网页共识用于校验/回退；冲突与缺失需看返回的来源、时间和限制。

研究提案、预算、批准和执行是不同步骤。普通对话不能自行扩大下载、执行或实盘权限。Research Session Grant 和自主研究计划也各自有明确范围、有效期和预算，不是永久无限授权。

外部经验先作为来源或 DRAFT 假设。Research Skill Library 只读检索不等于已把外部规则写入 Playbook；显示原文不代表该方法已验证。

Playbook 选择结果复盘由宿主运行 `niuniu-selection-outcomes --output artifacts --auto-all` 生成（重新安装本项目前可用 `python -m quantlab.agent.selection_outcomes_cli`）。它比较同一冻结候选集内选中与未选中证券的后续信号收益，用来发现错杀或过度保守；不是可成交收益或 Alpha，不会自动修改 Playbook 或权重。AI 助手只能读取已生成的结果。

标准 MCP 已补齐同源只读 Playbook/来源/选择复盘工具；既有同名 MarketSnapshot 工具保持原实现与参数合同。可通过三个 `get/list_selection_outcome_*` 工具读取宿主已生成的结果和不完整提示，不产生第二份归档。首轮 Reviewer 仍不开放选择结果复盘及 Scorecard，MCP 不开放研究批准、Grant 提交、Paper 执行、下载或交易权限。

同一窗口重复运行会核对实际使用的交易日和 accepted 日线：日历仅正常延长时保留原始 v1 记录、哈希和创建时间，同时补齐新的成熟窗口；窗口内交易日或日线发生实质修订仍报告 `REVIEW_CONFLICT`。每次 build 重新观察输入，不沿用上次缺日或旧修订缓存。多个正式服务写入由进程锁串行化；兼容不支持硬链接的文件系统，不会因为两个服务同时运行而覆盖不同结果。

批量 `--auto-all` 的退出码：`0` 表示没有执行错误，`3` 表示部分窗口失败，`2` 表示全部尝试失败或请求无效。尚未成熟或不适用的窗口是 pending，不是执行错误；JSON 中另列 attempted/frozen/created/pending/failed 数量和逐窗口错误，调度器应同时读取这些字段。

读取归档时，坏记录、符号链接、路径身份或校验不一致会在 `errors` 中披露，并标记 `incomplete=true`，不能把剩余结果当作完整样本。AI 工具及桌面复盘引用保留该提示。只读 `--get/--list/--summary` 遇不完整归档同样返回非零：有有效结果时为3、没有有效结果时为2，不把不完整读取报告为SUCCESS。`--list --full --offset 0 --limit 20` 可分页查看逐证券明细；`--get SELECTION_ID --full` 查看单次选择全部窗口。

### 已有行情归档的通用只读查询

普通本地聊天与标准 MCP 共用 `list_archived_daily_sources → list_archived_daily_symbols → inspect_archived_daily`。来源固定为宿主 `--output` 工作空间内的 `_market_data/retro_daily`，使用真实返回的 capture_id；模型不能传文件路径或切换根。前两步是计划/证券元信息发现，错误 capture 在 `errors/incomplete` 中披露，不认证日历完整或原始值；第三步才对指定1–10只证券、最多371自然日按既有桥校验原始响应与typed Parquet，packed与原目录使用同一字段合同。`has_st/has_suspension`过滤只便于诊断，不可据此制造历史股票池。目录最多50个capture，并在读计划之前检查候选上限；规模超限明确失败，不伪装已经扫描完整。

TDX 使用 `get_tdx_data_status / read_tdx_data`，数据根来自宿主 `--data-root`，不从output或cwd猜测。未配置根、锁占用、损坏库和无效参数以结构化错误返回；显式根尚无TDX队列时状态可表示configured=false。read只查询既存catalog，`verification=catalog_rows_only / source_bytes_verified=false`，不是重新核验每页原始字节。保留`original_record、source_id、volume_unit、observed_at`和资格，未知竞价量单位不变成股，观察日不变成历史发布时间。状态中的请求日期范围不是实际数据日期覆盖。

可以向普通助手问“列出当前工作空间已有的回溯日线归档，核对字段和可读取范围，不生成研究”，或“查看已存TDX数据族和单位，说明哪些仍未核验”。工具只读取，不创建数据、提案、授权或任务。返回超过64KiB时明确RESULT_TOO_LARGE，不能靠删除错误或只返回半份数据来宣称成功；缩小limit/证券/日期再查。能力查询中的read_available仅代表接线存在，不证明资料已经就绪。

旧`list_qm50_archived_sources/list_qm50_archived_symbols/inspect_qm50_archived_daily`保留名称和宿主指定source_workspace，底层转同一只读实现。锁定原始规格会话仍用旧专用入口，不能借通用名称调用替代研究；固定测试仍须单独许可。首轮Reviewer的工具白名单不扩大。`preclose/turn/isST/tradestatus`保留供应商原意，不替代官方reference_price/float_shares/完整状态。

上述通用读取不把TDX或retro归档自动注册为通用策略Provider，不修改供应商标签、SQL视图或数据布局。TDX消费仍待字段/单位/时点/版本合同明确；retro日线可由宿主按下节显式生成有限研究输入。数据已读取、数据包已创建、研究已批准和研究执行成功是不同状态。

### 显式建立归档日线研究输入（不自动研究）

对已有 `list_archived_daily_sources` 返回的精确capture，宿主可使用 `python -m quantlab.agent.archived_daily_dataset_cli`。所有命令从项目根目录执行，下面参数只示意输入位置，不代选证券或日期：

```bash
# 只读预检；不会创建新目录或启动研究
.venv/bin/python -B -m quantlab.agent.archived_daily_dataset_cli preview \
  --source-workspace /path/to/source-workspace --capture-id CAPTURE_UUID \
  --symbols sh.XXXXXX sz.XXXXXX --start YYYY-MM-DD --end YYYY-MM-DD

# 用刚才返回的完整preview_hash确认；destination必须全新且父目录已存在
.venv/bin/python -B -m quantlab.agent.archived_daily_dataset_cli export \
  --source-workspace /path/to/source-workspace --capture-id CAPTURE_UUID \
  --symbols sh.XXXXXX sz.XXXXXX --start YYYY-MM-DD --end YYYY-MM-DD \
  --destination /path/to/new-input --expected-preview-hash FULL_PREVIEW_SHA256 --confirm-create

# 脱离原capture后仍可核验；读取不修改包
.venv/bin/python -B -m quantlab.agent.archived_daily_dataset_cli inspect --data-root /path/to/new-input
```

预检成功不保存或批准研究。导出前重新核对同一预览指纹，来源变了必须重新预检；已有目标（含空目录）拒绝覆盖。数据包只用于明确有限范围的 `research_only`、raw、1d输入，不能请求qfq或分钟；源日历内缺行、停牌或必需值异常不会被自动删除或补齐。当前上限1–10只证券、371自然日；不是全市场固定股票池，也不是自动日增量通道。

在支持no-replace目录重命名的文件系统使用整目录发布；Lexar/exFAT等不支持时先独占创建新目录，写入明确无效的 `publication_state=INCOMPLETE` 清单，再移入全部文件，最后原子发布有效清单。中断可能留下未完成目标，读器必须拒绝，后续导出不得覆盖或复用；原来源保持完整。主控可检查后另选新目标，不自动删除残留。目录fsync不受支持时为有限的文件系统耐久性，不声称断电后必然完整，重开仍须深验。

在新建研究会话/宿主配置中把 `--data-root` 显式选为新包目录，并在研究spec或策略包中设置 `adjustment=raw`，即可复用原人工提案、批准、JobQueue和复算路径。普通助手/MCP通过只读 `get_archived_daily_dataset` 查询当前宿主选中的包及其范围，不传路径、不创建包、不切根；旧MQC发现会明确拒绝把这种受管目录当成散文件。现有会话的旧数据根、Grant和批准不会被导出命令修改。

每次Provider读取会核验包内字节及原始/typed/规范行情一致性；15:00时间是研究对齐假设，不是历史当时可得证明。有效供应商ST行保留供研究，不变成已确认交易资格；未知状态不填正常。输入包没有独立交易权限，原始QM50规格会话和首轮Reviewer白名单不扩张。正式数据根、TDX采集和治理流程不因本功能自动改变。

### 在数据工作台操作归档输入包

入口：**研究实验室 → 数据中心 → 归档日线研究输入：预检 / 生成 / 选择**，也可从顶部 **Baostock 数据 → 归档日线研究输入（预检 / 生成 / 选择）** 打开。打开面板不读取来源、不导出、不运行研究；来源只绑定当前工作空间的 `output`，不会自动寻找别的工作空间。

先点击“手动发现 capture（仅读元信息）”，查看实际来源编号与错误，再明确填写 capture_id、证券和起止日期。点击“预检范围与源字节”后显示真实行数、日历范围、来源与完整指纹。范围或新目录改变会使旧预检和确认失效；只有重新核对、勾选确认后，“确认后生成全新目录”才可执行。目标必须不存在，不能覆盖旧包。导出成功不自动选择新根；已有原始归档保持不变。

在“已有包目录”选择生成的包或另一已保存包，点击“深验已有包”，然后“人工选择为研究输入”。宿主重新核对同一 dataset_id、包清单和核验期间文件状态，再更改当前工作台的数据根。有效 Research Session Grant、跟踪授权、运行/排队任务、坏回执，或可恢复但没有审批冻结的旧任务会阻断切换。不要删除旧任务绕过检查：保留旧工作空间处理原任务，或通过研究设置创建独立工作空间后再选新包。已撤销授权且完成同步的跟踪记录不会被误当成运行中。

切换不会自动撤销、复制或新建授权，也不会修改旧实验。旧对话和确认选择关闭，之后研究仍需明确设置 raw、1d、范围及参数，保存新提案、人工批准；包选择不是批准。原有限授权/锁定 QM50 规格的工具边界保持不变，数据版聊天保留标准 ChatRuntime 的归档读取工具。

只读操作中关闭面板会使迟到结果失效。导出开始后关闭会延后至实际完成或失败，不能把已开始的写入称为取消；中断残留沿 F9 合同明确为无效包且不覆盖重试。选择完成后每次 Provider/审批仍须深验实际字节，文件状态检查不是永久文件锁或 Strict PIT 认证。本入口不新增后台调度、跨启动的自动选根配置、正式采集或 TDX 适配。

### 选定归档输入后核对研究草稿

F10面板成功“人工选择为研究输入”后，可点击 **进入研究提案（不执行）** 打开原提案面板。这里保持空草稿，不自动选择因子、证券、研究日期、资金或版本；已有策略可继续从原导入/策略工作台入口填写。工作空间或当前输入根变化时，旧面板不得切回旧根或沿用旧选择打开研究。

原 **仅预检配置与预算** 仍是配置及资格/预算检查，不能把它当作已读取行情。新增 **核对草稿与归档输入（只读）** 是另一项显式操作：使用当前宿主选定的F9包，验证实际包字节，再对照草稿按原prepare解析的证券、起止日期、周期、复权及背景输入。一次列出多个不匹配原因；省略adjustment时仍按原qfq默认值核对，不为了匹配raw包修改配置。结果包含精确dataset_id、spec_digest、输入角色/行数和check_hash，不建立第二份任务或批准记录。

只检查F9有限raw日线包，不扫描或改写MQC、TDX、原始归档。正确的子范围会读取真实Provider；没有交易日、超范围、分钟/qfq、历史Universe或严格资格请求都不能被包装成匹配。账户公司行动、可选执行后端和外部规则依赖未在此验证时明确列为阻塞，不能以行情存在认证完整账户可执行性。Campaign一次整包检查不支持，需按节点分别核对；即使匹配，也不证明滚动/留出子窗口、因子预热或统计检验有足够有效样本。

草稿、显示的提案、数据根改变或关闭窗口会使旧检查结果失效；坏包或读取失败清除旧成功状态。核对的是明确草稿，不是另一个已保存提案，更不是授权。该检查为可选只读诊断，不新增强制批准门；保存提案和实际批准仍走原流程，批准时重验并冻结字节，已批准任务依旧不回读后来变化的输入。

普通助手和标准MCP可调用同源只读工具 `check_archived_daily_research(spec_json)`。模型不能传路径、生成数据包、改配置或批准研究。工具执行成功`ok=true`仍可能返回`compatible=false`和完整blockers；调用或数据损坏则为`ok=false`。超过响应预算明确拒绝而非截断成成功；锁定QM50原始规格和首轮Reviewer白名单不扩大。此工具的结果不是Strict PIT、Alpha或策略有效性证明。

### 跟踪提案任务与打开实际结果

入口：**AI研究助手 → 人工提案审批 → 选中已保存提案 → 跟踪选中提案任务与结果（只读）**。打开时读取一次，固定提案编号和配置身份；不使用上方未保存草稿，不继承批准勾选，也不自动提交、取消、恢复或重新运行任务。原“查看选中提案任务状态”和“运行任务”入口继续保留，取消/恢复仍需在原任务页明确操作。

面板区分等待批准、已批准尚无入队记录、排队、运行、取消已请求、完成、失败、取消和中断。显示真实job_id、attempt、当前阶段、阶段内计数和记录更新时间；日志中的running不认证进程在线，更新时间不是心跳，completed/total不是整体百分比，不估计剩余时间。已提交但任务日志缺失显示LOST_JOB，不把它当作新待执行任务，不修复或补造记录。

默认不持续刷新。人工勾选“持续查看”后每5秒最多120次自动读取；同一窗口不叠加读取，终态、错误、次数用尽、工作空间改变或关闭即停止。重开后重新读取既有记录，不启动后台守护进程或恢复授权。定时读取只是当前窗口行为，不会在关闭后继续通知。

完成任务还须关联相同run_id/experiment_id的结果头部，才启用“核对后打开实际结果”；点击时再次核对。原行情根不可用不妨碍读取已保存进度。冻结清单、提案或任务变化，以及结果缺失/身份不符均明确披露errors/incomplete，旧成功链接失效。这里核对冻结清单与结果头部身份，不重算行情文件SHA、完整结果或策略收益；完整归档深验和数值复算仍是独立操作。任务/冻结JSON上限4MiB，结果JSON上限64MiB，超限明确要求改用原归档检查，不静默省略成成功。

原“查看选中提案任务状态 → 在原工作台打开实际结果”也使用同一提案进度回查，不再只凭job日志中的run_id启用旧结果链接。每次点击打开会重核提案配置、任务、冻结清单和结果头部；缺失、错配、失败或读取异常会取消旧链接。改变草稿/选择、切换到配置预检或输入核对、关闭面板或工作空间路径及目录身份改变后，旧读取不能重新启用打开按钮；即使列表原本已无选中行，预检/输入核对也会显式清除旧结果链接。它不新增完整归档深验，也不启动、恢复或重建任务。

策略工作台的目录、详情和结果对照共用有界异步回调检查：关闭窗口、改变查询/左右实验编号、切换工作空间或同路径目录被替换时，旧回执不再显示为当前结果；错误和格式不完整的回复会清除结果、解除读取占用并说明失败，不当作空目录或零差异。任务跟踪发现工作空间失效时也会清除旧详情。工作台返回策略草稿前再次核对原提案工作空间，不能把旧窗口草稿填入另一个空间。

普通助手与标准MCP可使用同源只读 `get_proposal_progress(proposal_id)`，只接受真实完整提案UUID，来源固定宿主output，不接受任意路径或SQL。工具ok=true也可能返回incomplete=true；必须报告errors，不能仅凭phase=completed称结果有效。新工具不扩大首轮Reviewer、QM50原始规格绑定或模型执行权限。

### 结果详情、导出与复算

结果详情沿原入口打开，报告、观测数据、K线回放、完整账本和子实验均绑定打开时的工作空间与归档。关闭后不应用迟到读取；工作空间或目录被替换、主记录及所用伴随文件的文件身份发生变化时，旧视图失效，须重新打开。界面使用文件身份检查，不是永久文件租约、全文件SHA审计或数值正确性认证；策略归档深验与复算仍是单独操作。观测页修改筛选立即清旧行，读取失败不保留上次结果冒充当前筛选。

“导出实验复现包”和“使用归档K线复算并核对”沿用原实现。同一结果窗口不并发启动这两项写入；选择导出目标后、实际后台写入前再检查原空间，不跟随主窗口后来切换的目录。写入期间请求关闭会等待实际成败回执，不宣称已经取消、回滚或删除产物。复算只有明确的numerically_matched或available_results_matched且来源/新结果编号对应时才显示成功；后者仍保留原失败/未运行项。源行情离线不改变已冻结研究，源码或环境不匹配则拒绝复算。

导出先核对临时ZIP内实际字节与清单，以及读取期间的源文件/源码变化，再独占创建目标，不覆盖已有文件。恢复先完整校验再独占占用新目标目录，期间别人创建同名空目录也不会被覆盖。恢复发布中断会保留带`.restore-incomplete`标记的未完成目标；不要使用或覆盖重试，应另选新目录。最终ZIP复制中断也可能留存无效目标并返回错误；不会把失败当成可移交包。恢复和导出不认证Alpha、Strict PIT或断电耐久性；从恢复包重新读取及数值复算须各自成功。

## 5. 每日循环里的缩写

| 名称 | 含义 |
|---|---|
| PREP | 盘前准备：上一交易日事实、市场状态与完整候选集 |
| AUCTION | 集合竞价阶段的规则扫描和判断 |
| R1 | 开盘后的第一轮判断 |
| R2 | 后续复核；当前 Orchestrator 的采样点是午间收盘 |
| R3 | 收盘复核与定稿 |
| D1 / D2 / D3_PLUS | 后续交易日的分层结果复盘，不是新的买入信号 |

**Decision 允许提交的时间窗口，不等于 Orchestrator 自动采样时刻。** 前者见 [frame_policy.py](../../src/quantlab/trading/frame_policy.py)，后者见 [daily_orchestrator.py](../../src/quantlab/trading/daily_orchestrator.py)。统一使用 `Asia/Shanghai` 的交易时钟，不按电脑所在时区猜测交易窗口。

PREP 候选全集为空可以合法结束为 `COMPLETE_NO_TRADE`；候选非空但暂未选股则不等同于空候选。错过前瞻窗口不能补造 SYSTEM_PREDICTION。

## 6. 数据或页面为空时

先核对启动参数中的 `--data-root` 和 `--output`，确认打开的是同一工作空间。随后查看数据覆盖、JobQueue、System Health 和失败日志；不要靠把 UNKNOWN 改成通过、伪造历史状态或绕开 PIT 解决空页面。

客户端默认研究前复权 qfq，而底层 Python API 并非都以 qfq 为默认。成交账户模式、公司行动与价格口径见 [数据与证据](data-and-evidence.md)。

F12 老板键用于隐藏/最小化客户端，macOS 点击 Dock 可恢复；部分键盘需要 Fn+F12。离屏测试不替代真实窗口和键盘验收。

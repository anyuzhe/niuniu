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

| 页面 | 用途 | 不要混淆 |
|---|---|---|
| 今日交易 | 聚合当日市场事实、主题、股票状态、研究判断、Agenda 与 Watch | 页面有结论不等于已下单 |
| 主线市场 | 在日期和 Frame 下比较主题与市场证据 | 事实、机器规则、AI、风险分别阅读 |
| 股票中心 | 从证券进入 Stock Dossier 和 Decision 时间线 | 只看到部分证据不代表完整股票研究 |
| 持仓计划 | 查看 Strategy Intent 及允许的下一动作 | PLAN_OPEN、HOLD 等意图不是实际持仓 |
| 复盘中心 | 看原判、修订、跨轮对比和后续结果 | 不能用后来行情覆盖当时判断 |
| AI 团队 | 配置角色和按需同行复核 | 多模型一致不是独立市场证据 |
| 研究实验室 | 进入原数据、因子、理论、实验、回测，以及 Playbook/Research Skill | 研究与成交分开验证 |
| 开发工作台 | 隔离开发任务、差异、测试与人工合并 | Research Agent 不因此获得开发权限 |
| 系统中心 | 检查服务、任务、数据、PIT、Paper 与日志 | 在线健康不代表研究资料合格 |

菜单接线见 [trading_pages.py](../../src/quantlab/desktop/trading_pages.py)；具体布局以当前客户端为准。

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
  --adjustment qfq --backtest --execution-backend open --replay
```

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

策略统一封装按以下顺序继续，而不是把模板自动登记成成品策略：先固定信号版本与输入范围，再显式给出资金、持仓/退出、费用和成交配置，最后通过既有审批、ExecutionStudy/Paper 与复盘链验证。当前完成的是目录发现和通用链路的合成验收；没有替用户指定交易参数、增加已验证策略或部署常驻执行。

## 4. AI 问答与正式研究

在 AI 助手中明确证券代码或本地正式名称，可触发本轮明确范围的一次只读行情查询；唯一证券上下文的明确追问可以沿用，多股歧义不猜。配置扶摇后以扶摇为主，公开网页共识用于校验/回退；冲突与缺失需看返回的来源、时间和限制。

研究提案、预算、批准和执行是不同步骤。普通对话不能自行扩大下载、执行或实盘权限。Research Session Grant 和自主研究计划也各自有明确范围、有效期和预算，不是永久无限授权。

外部经验先作为来源或 DRAFT 假设。Research Skill Library 只读检索不等于已把外部规则写入 Playbook；显示原文不代表该方法已验证。

Playbook 选择结果复盘由宿主运行 `niuniu-selection-outcomes --output artifacts --auto-all` 生成（重新安装本项目前可用 `python -m quantlab.agent.selection_outcomes_cli`）。它比较同一冻结候选集内选中与未选中证券的后续信号收益，用来发现错杀或过度保守；不是可成交收益或 Alpha，不会自动修改 Playbook 或权重。AI 助手只能读取已生成的结果。

标准 MCP 已补齐同源只读 Playbook/来源/选择复盘工具；既有同名 MarketSnapshot 工具保持原实现与参数合同。可通过三个 `get/list_selection_outcome_*` 工具读取宿主已生成的结果和不完整提示，不产生第二份归档。首轮 Reviewer 仍不开放选择结果复盘及 Scorecard，MCP 不开放研究批准、Grant 提交、Paper 执行、下载或交易权限。

同一窗口重复运行会核对实际使用的交易日和 accepted 日线：日历仅正常延长时保留原始 v1 记录、哈希和创建时间，同时补齐新的成熟窗口；窗口内交易日或日线发生实质修订仍报告 `REVIEW_CONFLICT`。每次 build 重新观察输入，不沿用上次缺日或旧修订缓存。多个正式服务写入由进程锁串行化；兼容不支持硬链接的文件系统，不会因为两个服务同时运行而覆盖不同结果。

批量 `--auto-all` 的退出码：`0` 表示没有执行错误，`3` 表示部分窗口失败，`2` 表示全部尝试失败或请求无效。尚未成熟或不适用的窗口是 pending，不是执行错误；JSON 中另列 attempted/frozen/created/pending/failed 数量和逐窗口错误，调度器应同时读取这些字段。

读取归档时，坏记录、符号链接、路径身份或校验不一致会在 `errors` 中披露，并标记 `incomplete=true`，不能把剩余结果当作完整样本。AI 工具及桌面复盘引用保留该提示。只读 `--get/--list/--summary` 遇不完整归档同样返回非零：有有效结果时为3、没有有效结果时为2，不把不完整读取报告为SUCCESS。`--list --full --offset 0 --limit 20` 可分页查看逐证券明细；`--get SELECTION_ID --full` 查看单次选择全部窗口。

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

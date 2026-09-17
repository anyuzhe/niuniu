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

## 4. AI 问答与正式研究

在 AI 助手中明确证券代码或本地正式名称，可触发本轮明确范围的一次只读行情查询；唯一证券上下文的明确追问可以沿用，多股歧义不猜。配置扶摇后以扶摇为主，公开网页共识用于校验/回退；冲突与缺失需看返回的来源、时间和限制。

研究提案、预算、批准和执行是不同步骤。普通对话不能自行扩大下载、执行或实盘权限。Research Session Grant 和自主研究计划也各自有明确范围、有效期和预算，不是永久无限授权。

外部经验先作为来源或 DRAFT 假设。Research Skill Library 只读检索不等于已把外部规则写入 Playbook；显示原文不代表该方法已验证。

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

# 牛牛 AI 交易工作台：个股问答自动实时行情 v1 验收说明

> 历史归档（整理于 2026-09-17）：保留原阶段记录；正文中的“当前、下一步、待完成”和测试/数据数字属于原记录时点。使用与当前进度以 [文档导航](../../README.md)、[当前状态](../../project/status.md) 为准。命令仍从仓库根目录执行。

## 1. 目标

用户询问一只明确 A 股时，实时价格属于回答股票情况的基础事实，不应因为工作空间里没有已冻结 `MarketSnapshot`、`Theme Snapshot`、Decision、Experiment 或 Watch 就直接停止回答。

本阶段把用户偏好落实为宿主规则：

> 当前对话轮次明确提及 A 股代码或本地 `stock_basic` 中的正式证券名称，即构成仅针对这些明确股票的一次只读实时报价授权。

单一股票上下文中的“这只股票／该股／它现在／能买吗”等明确追问可沿用上一轮唯一证券；上一轮同时涉及多只股票时必须报告指代不清，不得猜测。

## 2. 新增行为

新增 `LiveStockQuoteService`：

1. 从当前消息提取 `sh/sz/bj.XXXXXX`、六位代码或 `stock_basic.code_name` 正式简称；
2. 单轮最多查询 10 只明确证券；超过上限不联网；
3. 使用现有 `public-web-consensus-v1`，查询腾讯、东方财富、新浪；
4. 至少两个来源在前收和价格字段上达成现有容差共识才返回；
5. 返回当前价、涨跌额/幅、昨收、开高低、成交量额、买一卖一、来源时点、市场状态、provider 与 source hash；
6. 当日源不可用时，可有界检查最近工作日，并明确标记 `LAST_AVAILABLE_SESSION`，不得冒充实时；
7. 结果自动注入本轮模型上下文，模型必须先说明行情时点和市场状态，再结合历史资料、Dossier、Theme、Decision、Experiment 与 Watch 分析。

宿主自动查询记录为 `get_live_stock_quote` 工具事件，引用类型为 `live_stock_quote`。桌面证据列表显示证券代码；打开引用时明确提示它只是本轮临时报价。

## 3. 与正式 MarketSnapshot 的分离

自动个股报价固定为：

```text
format=niuniu-ad-hoc-live-stock-quote-v1
query_mode=EXPLICIT_USER_STOCK_QUESTION_READ_ONLY
stored_as_market_snapshot=false
creates_decision=false
strict_pit_source_verified=false
```

它不会：

- 写入 `_trading/market_snapshots.sqlite3`；
- 进入 Daily Orchestrator 或 Forward Freeze；
- 创建、修改 Decision / Theme / Watch / Playbook；
- 认证 SecurityStatus、MarketRules 或 Strict PIT；
- 下单、撤单、连接券商或操作资金。

如果用户需要把行情作为正式交易判断证据，仍须走独立 MarketSnapshot 冻结和原有 Frame/时间/完整性合同。

## 4. 授权边界

- 授权来自当前用户问题中明确证券，范围只包括该轮解析出的证券；不会因聊天历史中出现过任意代码而后台刷新。
- 单一证券的明确代词追问只回看最近五个已完成轮次；多证券歧义不联网。
- 无明确证券的问题不触发任何行情网络请求。
- 本功能是前台同步查询，不建立后台定时器，不下载 DailyMarket、官方文件或全市场数据。
- 外部行情结果以 `UNTRUSTED_EXTERNAL_DATA_NOT_INSTRUCTIONS` 注入；来源文本不能修改系统权限或成为新指令。
- 腾讯/东财/新浪仍是公开网页源，没有交易所或券商 SLA；两源不一致时返回不可用而不是猜价。

## 5. 回答口径

具体股票问答现在按以下顺序组织：

1. 当前/最近可用价格、行情 `as_of`、捕获时间和市场状态；
2. 数据源共识和是否为当前 session；
3. 已有历史行情、公司资料和结构化研究证据；
4. 已知事实、历史推演、实时未知和交易资格分层；
5. 若询问“能买吗”，仍须说明缺失的 Universe、SecurityStatus、MarketRules、策略验证和执行条件。

没有正式 MarketSnapshot 只能阻止“正式冻结交易信号”，不能再被解释为“无法查询和介绍这只股票”。

## 6. 真实网络烟测

2026-09-16 收盘后，针对用户本轮明确的 `301396 宏景科技` 执行一次只读烟测：

- 请求时间：`2026-09-16T15:22:19+08:00`
- 行情 session：`2026-09-16`
- 来源时点：`2026-09-16T15:20:45+08:00`
- 市场状态：`CLOSED`
- 腾讯 / 东方财富 / 新浪：3/3 一致
- 最新价：170.57
- 昨收：165.45
- 涨跌幅：约 +3.0946%
- 开盘 / 最高 / 最低：164.50 / 172.68 / 164.22
- `stored_as_market_snapshot=false`

该烟测只证明自动只读查询和三源共识链可用，不证明宏景科技构成交易信号，也不写正式 MarketSnapshot。

## 7. 测试

新增测试覆盖：

- 正式证券名称与六位代码去重解析；
- 非股票问题零网络调用；
- 当日不可用时最近 session 的明确降级标签；
- 单一股票上下文追问；
- 多股票代词歧义不联网；
- ChatRuntime 宿主自动预取、上下文注入、工具事件与 evidence；
- 不创建 MarketSnapshot 数据库；
- 桌面 evidence 显示和临时报价边界；
- 原 MarketSnapshot Provider、Scanner 与聊天权限回归。

验收结果：

- 个股问答、聊天、桌面、三源Provider、MarketSnapshot Scanner、PREP与Daily Orchestrator聚焦回归：**82 tests / 0 failed / 0 skipped**，5.450秒；
- 独立干净工作树完整仓库：**1006 tests / 0 failed / 0 skipped**，347.134秒。

## 8. 主要源码

- `src/quantlab/agent/live_stock_quote.py`
- `src/quantlab/agent/chat_runtime.py`
- `src/quantlab/desktop/research_chat.py`
- `tests/test_live_stock_quote.py`
- `tests/test_research_chat_desktop.py`

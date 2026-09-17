# 牛牛 AI 交易工作台 P6 策略动作状态机验收说明

> 历史归档（整理于 2026-09-17）：保留原阶段记录；正文中的“当前、下一步、待完成”和测试/数据数字属于原记录时点。使用与当前进度以 [文档导航](../../README.md)、[当前状态](../../project/status.md) 为准。命令仍从仓库根目录执行。

日期：2026-09-13
阶段：P6 Strategy Intent State Machine
前置稳定基线：`a45ec8c`

## 一、目标

将 Decision 中的动作从普通标签升级为正式 Strategy Intent 状态机，同时继续严格区分：

- Strategy Intent：研究/交易计划层动作。
- Paper Position：只有模拟成交回执才能改变。
- Real Account Position：未来只有券商真实成交回报才能改变。

P6 不连接券商，也不把“建议开仓/持有”解释为真实持仓。

## 二、状态机

主链：`DISCOVERED → WATCH → READY → PLAN_OPEN → OPEN → ADD/HOLD → REDUCE → EXIT`。

旁路：`INVALIDATED / REJECTED / EXPIRED`。退出、失效、拒绝或过期后可重新回到发现/观察，形成新的交易机会周期。
## 三、执行合同

新增 `StrategyIntentService`，桌面人工 Decision 保存入口已经切到正式状态服务。

- 非法跳级直接拒绝，例如 WATCH → OPEN。
- 同一证券/交易日/Frame 已有当前 Decision 时，必须走 revision，不能再插第二条当前状态。
- 动作变化必须保留 `transition_reason`；留空时可复用当时 AI Thesis / Machine State 等明确依据。
- 第一条记录若直接初始化为 HOLD/OPEN 等非发现/观察状态，只允许作为显式 Bootstrap，并必须保留原因。
- 每条受控 Decision 保存前序 Decision、前序动作、状态机版本和转移类型。
- 当前状态读取按 `trading_day + Decision Frame` 业务时间排序，而不是按数据库最后写入时间。

因此，晚上补录一个早盘 R1 不会把已经存在的 R3 顶成“当前状态”。

## 四、历史保护

为了避免事后改写状态链：

- 已有更晚业务时间 Decision 时，不允许再插入新的旧 Frame 状态。
- 旧 Decision 可以 revision，但后面已有状态时，revision 不能改变旧动作。
- 同动作 revision 仍允许补充文字、证据等，不覆盖历史版本。
- Stock Dossier 的当前 Decision 同样按业务 Frame 选取，不按写入时间选取。
## 五、界面

“持仓计划”页现在展示的是 Strategy Intent 状态板：

- 当前状态
- 允许的下一动作
- 转移类型
- 转移理由
- 持有依据
- 退出条件

页面继续明确提示：这不是 Paper/真实账户持仓。

Decision 编辑器新增“状态转移理由”，并继续沿用 P5 的实际提交时间、Frame Policy、迟交/补录审计。

D1/D2/D3+ 使用“最近原判”时会继承上一计划的当前动作和必要计划字段，随后仍可人工调整。

## 六、模型权限

P6 没有新增模型写状态能力。

模型工具集合中不存在 `create_decision`、`transition_strategy_intent`、`set_position_intent` 等写入工具；状态变化仍由宿主人工 Decision 入口完成。
## 七、隔离端到端验收

证据：`artifacts/strategy-intent-p6-20260913/acceptance-latest.json`

完整生命周期实际走通：

`WATCH → READY → PLAN_OPEN → OPEN → HOLD → REDUCE → EXIT → WATCH`

并确认：

- 当前状态最终为 WATCH。
- EXIT 后重新观察是合法新周期。
- `position_scope = strategy_intent`。
- Paper 产物不存在。
- Real Account 产物不存在。
- 新增研究任务 = 0。
- 模型写状态工具 = 0。

## 八、测试结果

最终全仓：**720 passed / 0 failed / 0 skipped**，exit code = 0。

下一阶段：**P7 今日交易驾驶舱**，将市场、主线、股票、状态机、AI 结论、风险、Agenda 与 Watch 收敛到默认首页。
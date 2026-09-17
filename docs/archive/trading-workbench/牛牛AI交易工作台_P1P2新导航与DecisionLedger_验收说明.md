# 牛牛 AI 交易工作台 P1/P2 验收说明

> 历史归档（整理于 2026-09-17）：保留原阶段记录；正文中的“当前、下一步、待完成”和测试/数据数字属于原记录时点。使用与当前进度以 [文档导航](../../README.md)、[当前状态](../../project/status.md) 为准。命令仍从仓库根目录执行。

日期：2026-09-12

基线计划：`docs/archive/plans/牛牛AI交易助手_A股交易工作台改造总计划.md`

本阶段严格只完成计划中的：

- P1：新导航与 Trading Desk 外壳。
- P2：Decision Ledger 基础。

没有顺手实现 P3 Stock Dossier、P4 Theme Matrix、P8 多 Agent、P10 Dev Studio 等后续范围。

## 一、P1 新导航

牛牛桌面一级入口已从研究模块列表改为：

`今日交易 / 主线市场 / 股票中心 / 持仓计划 / 复盘中心 / AI 团队 / 研究实验室 / 系统中心`

窗口定位同步更新为“牛牛 AI · 个人 A 股交易研究助手”。
旧研究能力没有删除。原 12 个研究页面继续由兼容 `navigate(old_index)` 路由打开，并集中从“研究实验室”进入。

顶部主操作调整为：

- `＋ Decision`：交易工作台主要动作。
- `新建实验`：保留研究入口，但不再压过交易入口。

全局搜索已加入 Decision / 股票检索，同时继续保留因子、理论和实验搜索。

周末或非交易日不会把系统日期直接称为“当前交易日”；第一阶段只显示当前自然日。正式交易日和 Frame 时钟由后续 P4/P5 的交易日历驱动。

## 二、P2 Decision Ledger

新增 `quantlab.trading` 业务包和 append-only Decision Ledger。

Decision 最小业务合同包括：证券、交易日、Frame、策略动作、主题/角色、判断依据、触发/失效/持有/退出条件、证据引用、Agent/模型身份、revision 链和 Outcome。

第一版 Frame：`PREP / AUCTION / R1 / R2 / R3 / D1 / D2 / D3_PLUS`。

第一版动作：`DISCOVERED / WATCH / READY / PLAN_OPEN / OPEN / ADD / HOLD / REDUCE / EXIT / INVALIDATED / REJECTED / EXPIRED`。
账本具有以下约束：

- 同一 `request_id` 重试幂等；不同内容复用同一请求会冲突。
- 旧 Decision 不允许覆盖，只能新建 `revision_of`。
- revision 必须保持同一证券、交易日和 Frame。
- 被替代的旧版本默认不出现在“当前状态”查询中，但可显式读取完整历史。
- payload 与索引均有 checksum 校验，人工篡改可检测。
- 开仓/加仓必须保留买入区间或确认触发；减仓/退出/失效必须保留原因或条件。
- `OPEN / ADD / HOLD / REDUCE / EXIT` 目前表示 Strategy Intent，不等于真实成交或真实账户持仓。

第一版桌面只允许宿主人工创建和修订 Decision；没有给研究模型新增写 Decision 的工具权限。

## 三、测试与端到端验收

专项回归：35 项通过。

全部桌面相关联合回归：97 项通过。

最终全仓：**688 项通过，0 失败，0 跳过，exit=0**。

独立端到端工作区实际创建 3 条 Decision（含 1 条 revision）：当前记录 2 条、完整历史 3 条、`sh.600000` 时间线 2 条，当前动作正确收敛为 `READY`；整个验收过程中创建研究任务 **0**。
最终业务源码指纹：`99ba3c3460618db01f17976a8583242138386e706af7397b79037adf3658743c`。

证据目录：`artifacts/trading-desk-p1p2-20260912/`。

## 四、明确未完成范围

本阶段没有宣称完成：

- P3 完整 Stock Dossier（尚未聚合实验、Watch、Outcome 等证据）。
- P4 正式 Theme Matrix 与盘中市场事实。
- P5 自动交易日/Frame 时钟与 late-submission 规则。
- P6 完整策略状态机自动约束。
- P8 AI Team / Peer Review。
- P10 Dev Studio。

下一阶段按总计划进入 **P3 Stock Dossier**，继续建立“以股票为中心”的跨日研究档案。

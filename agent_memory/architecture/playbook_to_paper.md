# Playbook → Trading Desk → Paper 边界

P8.8 继续坚持四层分离：`SYSTEM_PREDICTION != Decision != Strategy Intent != Paper Position`。

- `PlaybookDecisionBridge` 只接受真实 SYSTEM_PREDICTION；历史回放不能自动进入 Trading Desk。
- 首次系统选择最多自动写 WATCH；不得直接写 PLAN_OPEN/OPEN。
- NO_TRADE 保存 receipt，但不制造虚假股票 Decision。
- 已有人工同 Frame Decision、PLAN_OPEN/OPEN/ADD/HOLD/REDUCE/EXIT 不由 bridge 覆盖。
- Orchestrator bridge 默认关闭，只有宿主创建计划时显式开启。

PaperPlan 是宿主冻结的模拟执行计划：

- 只有当前 PLAN_OPEN Decision 可进入 PaperPlan。
- 创建和执行都需要 host confirmation。
- 完成 bars + 显式 dated MarketRules 才能执行现有 PaperAccount。
- 固定 `PaperAccount` 继续作为旧研究账户，不修改其 fixed-universe 合同。
- 长期账户使用独立 `DynamicPaperAccount`；新增证券时历史 target 补0，且旧 NAV/fill/order 前缀必须逐项不变。
- fill→Intent 是独立严格桥：没有实际 buy fill 不得 PLAN_OPEN→OPEN；人工已经改变状态时人工状态优先。
- ADD/REDUCE/EXIT 必须由当前对应 Decision + RebalancePlan 驱动；rebalance 不能借机加入新股票。
- D1/D2/D3+ `PaperOutcomeReview` 只生成因果结果证据，不自动替用户做 HOLD/REDUCE/EXIT。
- 生命周期统计必须分开 Prediction / NO_TRADE / Plan / fill / rejection / costs / review / account return。
- AI/MCP 不得拥有 Paper 创建、执行、再平衡或 Intent 写工具；这些仍是宿主显式动作。
- 真实券商、真实资金、自动实盘均不属于 P8.8，继续留在 P13。

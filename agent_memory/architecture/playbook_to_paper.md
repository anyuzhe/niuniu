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
- 模拟 fill 不自动把 Strategy Intent 改成 OPEN；fill→Intent 需要独立严格合同。
- 现有 PaperAccount 是固定 universe；不得为了每日新股票重写历史 universe。
- 真实券商、真实资金、自动实盘均不属于 P8.8。

P8.8-C 再解决动态跨日 universe、成交回执驱动状态推进和 D1/D2/D3+ 自动复盘。

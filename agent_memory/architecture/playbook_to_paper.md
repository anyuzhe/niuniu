# Playbook → Trading Desk → Paper 边界

P8.8 继续坚持四层分离：`SYSTEM_PREDICTION != Decision != Strategy Intent != Paper Position`。

- `PlaybookDecisionBridge` 只接受真实 SYSTEM_PREDICTION；历史回放不能自动进入 Trading Desk。
- 首次系统选择最多自动写 WATCH；不得直接写 PLAN_OPEN/OPEN。
- NO_TRADE 保存 receipt，但不制造虚假股票 Decision；空 PREP CandidateSet 可使 Orchestrator 正常终止，不能为积累 Paper 样本而伪造计划或成交。
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
- `SelectionOutcomeService`（宿主 CLI `niuniu-selection-outcomes`；AI 只读 `get_selection_outcome_summary / list_selection_outcome_reviews / get_selection_outcome_review`）把同一冻结 CandidateSet 的选中与未选中证券当对照组：D0 只用于盘前 PREP，D1+ 以选择日收盘为基准，按 close/preclose 链式计算信号收益；缺日线即 DATA_MISSING，已冻结结果遇数据修订报 REVIEW_CONFLICT 而不覆盖。它是选择诊断，不是可成交收益、Alpha 或显著性检验；不自动调权、不写 Decision/Intent/Paper，也不进入 Peer Review 首轮 SAFE_TOOLS。
- 生命周期统计必须分开 Prediction / NO_TRADE / Plan / fill / rejection / costs / review / account return。
- AI/MCP 不得拥有 Paper 创建、执行、再平衡或 Intent 写工具；这些仍是宿主显式动作。
- 真实券商、真实资金、自动实盘均不属于 P8.8，继续留在 P13。

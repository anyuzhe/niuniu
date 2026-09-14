# 牛牛 AI 交易工作台：P8.8 Playbook → Trading Desk → Long Paper 验收说明

- 阶段：P8.8-A / P8.8-B / P8.8-C 核心闭环
- 日期：2026-09-14
- P8.8-C 开发基线：`04baf96`
- 最终全仓：**842 tests / 0 failed / 0 skipped**
- 全仓耗时：292.278 秒

## 1. 阶段目标

P8.8 的目标不是“让系统预测后自动买入”，而是把下列对象严格分层并建立可恢复的证据链：

`SYSTEM_PREDICTION → Decision → Strategy Intent → PaperPlan → Paper order/fill/position → D1/D2/D3+ Review`

始终坚持：**预测不等于计划，计划不等于成交，成交不等于真实券商持仓。**

## 2. P8.8-A：Prediction → Trading Desk

`PlaybookDecisionBridge` 只接受真实 `SYSTEM_PREDICTION`：

- NO_TRADE 只保存 receipt，不制造股票 Decision。
- 首次系统选中最多进入 `WATCH`，不能直接进入 `PLAN_OPEN / OPEN`。
- 已有人工作出的同 Frame Decision 不自动 revision。
- 已存在 `PLAN_OPEN / OPEN / ADD / HOLD / REDUCE / EXIT` 时系统 bridge 不覆盖。
- PARTIAL CandidateSet、QUEUE_DEPENDENT 等风险继续作为 evidence/risk 保留。
- receipt 丢失后可通过确定性 request identity 恢复，不重复制造 Decision。

Daily Orchestrator 的 Trading Desk bridge 默认关闭，只有宿主显式启用才运行。

## 3. P8.8-B：PLAN_OPEN → PaperPlan

`PlaybookPaperPlanService` 负责把当前 `PLAN_OPEN` 冻结为模拟执行计划：

- 每个 selected symbol 必须存在当前、未被 revision 的 PLAN_OPEN Decision。
- 创建和执行均要求宿主显式确认。
- 计划冻结 Selection、Decision、target weights、account、hash 和执行输入身份。
- 完成 bars + 显式 dated `MarketRules` 后才允许执行。
- fixed_v1 路径继续复用原有固定-universe `PaperAccount`，旧合同不修改。
- PaperAccount 已经提交成交、PaperPlan receipt 尚未落盘即崩溃时，可从 durable reservation 恢复原 fills/orders。

## 4. P8.8-C：DynamicPaperAccount

新增独立长期账户 `DynamicPaperAccount`，不替换旧固定-universe PaperAccount。

核心合同：

- 长期账户允许后续交易日加入新证券。
- 新证券加入后，历史 target 对该证券确定性补 `0`，不能重写旧策略意图。
- 每次扩展 universe 后必须验证旧 NAV / fills / orders 前缀逐项不变，否则拒绝更新。
- 重复交付幂等；迟到 target、历史 bar 修订、历史 MarketRules 修订、ExecutionConfig/代码身份变化均 fail-closed。
- 某证券目标权重发生变化时，本次交付必须包含该证券的完成 bar；不能在没有行情的情况下增仓、减仓或退出。
- 清零 target 会在后续可执行 bar 上产生真实模拟卖出，而不是直接删除持仓。

PaperPlan 新增显式 `--dynamic` 路径；默认 fixed_v1 行为保持兼容。

## 5. Paper fill → Strategy Intent

新增独立成交结果桥，成交事实才允许推动状态：

- 没有真实 paper buy fill，`PLAN_OPEN` 必须保持不变。
- 有真实 buy fill 且宿主显式确认后，才允许生成 `OPEN` Decision。
- OPEN 写在真实成交所属业务日/Frame，不把成交事后伪装成原 Selection 时点。
- 如果成交后人工已经修改 Strategy Intent，人工状态优先，自动桥只记录冲突/跳过。
- Decision 已成功写入但 receipt 写盘前崩溃时，重试复用已有 Decision，不重复 OPEN。

模型不能直接调用该写路径。

## 6. ADD / REDUCE / EXIT 长期再平衡

新增 `PaperRebalancePlan` 与成交结果桥：

- 只允许作用于长期 Dynamic Paper 账户已经存在的证券。
- ADD 必须绑定当前 ADD Decision；REDUCE 必须绑定 REDUCE；EXIT/INVALIDATED 才允许目标归零。
- Rebalance 不能借机加入新股票；新股票仍必须经过 Playbook Selection → PLAN_OPEN → PaperPlan。
- ADD 实际成交后状态回到 `HOLD`。
- REDUCE 实际成交且仍有持仓时状态回到 `HOLD`。
- EXIT 实际清仓后保留 EXIT，仅补充“退出已成交”证据，不制造第二条 EXIT。
- 无实际成交时原 Intent 不改变。
- 动态账户已提交 rebalance、receipt 尚未完成即崩溃时，可以识别本计划 target 并幂等恢复。

## 7. D1 / D2 / D3+ 因果复盘

新增 `PaperOutcomeReview`：

- 只读取复盘日及以前已经存在的 bars / fills / NAV / position evidence。
- D1 先冻结后，再追加 D2/D3 数据，重新计算 D1 必须得到相同 `review_hash`。
- Review 保存原 Decision、Paper 成交/未成交、持仓、价格兑现、账户净值和成本等 outcome evidence。
- `auto_all` 可批量为已经执行的 PaperPlan 生成已到期 D1/D2/D3+ review。
- Review **不会自动替用户做 HOLD / REDUCE / EXIT 决策**；它是复盘证据，不是事后交易信号。

## 8. 长期生命周期统计

新增只读生命周期汇总，明确分开统计：

- SYSTEM_PREDICTION 与 NO_TRADE；
- Decision Bridge / PaperPlan；
- EXECUTED_WITH_FILL / EXECUTED_NO_FILL；
- ADD / REDUCE / EXIT rebalance；
- rejection reason；
- commission / tax / transfer fee / slippage；
- D1 / D2 / D3+ review；
- Dynamic Paper 当前净值、收益和持仓。

统计不能把选择准确率、执行可达性和最终账户收益混成一个“Alpha胜率”。空工作区查询也是零副作用。

## 9. Trading Cockpit 与宿主 CLI

Trading Cockpit 现在只读展示 PaperPlan 和长期 Paper 生命周期摘要，打开首页不会创建计划、执行账户或修改 Intent。

P8.8-C 新增/扩展宿主入口：

- `niuniu-playbook-paper-plan --dynamic`
- `niuniu-paper-fill-intent`
- `niuniu-paper-rebalance`
- `niuniu-paper-rebalance-outcome`
- `niuniu-paper-review`（含 `--auto-all`）
- `niuniu-paper-lifecycle`

以上执行/写入动作均属于宿主边界，AI Research / MCP 不获得对应写工具。

## 10. 测试与验收

关键验证包括：

- Dynamic Paper：动态 universe、旧账前缀不变、目标清零卖出、迟到/修订/身份变化阻断。
- Fill Intent：有成交才 OPEN、没成交不 OPEN、人工状态优先、receipt 崩溃恢复。
- Rebalance：ADD/REDUCE/EXIT 动作资格、禁止新股绕过、成交后 HOLD/EXIT、账户先提交后 receipt 崩溃恢复。
- Review：D1 对未来 D2/D3 数据前缀不变、复盘不改 Intent。
- Lifecycle：Prediction / execution / review / costs 分层统计，空工作区零副作用。
- AI 权限：无 Paper 创建、执行、rebalance 或 Intent write 工具。
- P8.8-C 相关联合链路 **52/52 passed**，后续专项继续全绿。
- 最终完整仓库：**842 tests / 0 failed / 0 skipped**。

## 11. P8.8 完成后的边界

P8.8 的**核心 Paper/复盘软件闭环**已经完成，但以下事项不能被混同为已经完成：

1. 尚未积累数月真实前瞻 Paper 运行样本，因此不能宣称长期收益、稳定性或 Alpha 已验证。
2. P8.7 仍只自动编排 PREP/AUCTION/R1；R2/R3 自动编排尚未产品化。
3. AUCTION/R1 正式实时 MarketSnapshot provider 仍需产品化；Orchestrator 不使用临时网页抓取冒充正式数据源。
4. D1/D2/D3+ 自动 review 是 outcome evidence，不自动生成新的交易动作。
5. 真实券商、真实资金和自动实盘全部属于 P13，P8.8 没有任何 Broker Gateway。

下一正式阶段进入 **P9 Agent Scorecard**；并行继续积累真实前瞻 Paper 样本和补齐实时/PIT 数据基础设施。

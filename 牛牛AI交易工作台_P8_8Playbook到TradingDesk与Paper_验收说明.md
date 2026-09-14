# 牛牛 AI 交易工作台：P8.8 Playbook → Trading Desk → Paper 验收说明

- 阶段：P8.8-A / P8.8-B 核心接线
- 日期：2026-09-14
- 基线：P8.7 `fd52adb`
- 最终全仓：**821 tests / 0 failed / 0 skipped**

## 1. 本阶段解决的问题

P8.7 已能把 DailyMarket → PREP → AUCTION → R1 串成真实时间受控前瞻链，但 `SYSTEM_PREDICTION` 仍停留在研究对象中。P8.8 的目标是把“研究预测、业务判断、策略计划、模拟执行”分层连接起来，同时继续阻止 `预测 = 计划 = 成交 = 持仓` 的错误等价。

## 2. P8.8-A：Prediction → Trading Desk

新增 `PlaybookDecisionBridge` 与 `niuniu-playbook-decision-bridge`：

- 只接受真实 `SYSTEM_PREDICTION`，历史 `HUMAN_RECONSTRUCTION` 不能进入自动桥。
- NO_TRADE 只保存 bridge receipt，不制造虚假的股票 Decision。
- 首次被系统选择的股票最多进入 `WATCH`；已有 `DISCOVERED` 可推进到 `WATCH`；已有 `READY` 保持 READY。
- `PLAN_OPEN / OPEN / ADD / HOLD / REDUCE / EXIT` 等已有计划或持仓意图不会被自动桥覆盖。
- 同证券/同交易日/同 Frame 已有人工作出的当前 Decision 时，自动桥不偷偷 revision。
- CandidateSet PARTIAL、`QUEUE_DEPENDENT` 等执行限制会作为 risk/evidence 保存，不因“被选中”而升级。
- receipt 丢失后重试会复用已有 Decision，不重复制造状态。

Daily Orchestrator 新增显式 `--bridge-to-trading-desk` 开关；默认关闭，因此旧 P8.7 计划行为保持不变。

## 3. P8.8-B：PLAN_OPEN → PaperPlan

新增 `PlaybookPaperPlanService` 与 `niuniu-playbook-paper-plan`：

- 只有当前 `PLAN_OPEN` Decision 才能创建 PaperPlan。
- 每个 selected symbol 都必须有对应 PLAN_OPEN Decision，且 Decision 不能已被 revision。
- 创建和执行都要求宿主显式确认。
- PaperPlan 冻结 `selection_id / decision_id / target_weights / account_name / universe / hashes`。
- 计划创建本身不会创建 PaperAccount，也不会产生成交。
- execute 必须提供完成 bars、显式 dated `MarketRules` 和 ExecutionConfig；随后复用现有 `PaperAccount` 模拟成交。
- PaperPlan receipt 保存账户 revision、新订单 ID、新 fills、summary 与来源映射。
- 即使模拟成交成功，Strategy Intent **仍保持 PLAN_OPEN**；本阶段绝不自动把成交回执升级成 `OPEN`。

## 4. 固定 universe 与恢复合同

现有 `PaperAccount` 是固定 universe、append-only replay 的研究账户。P8.8-B 不篡改这个合同：

- PaperPlan v1 的 universe 固定为当次 Selection 的 `selected_symbols`。
- 已有账户 universe 不一致时直接 `ACCOUNT_UNIVERSE_MISMATCH`，不重写历史。
- 同一计划重复 execute 幂等。
- reservation 会冻结执行前 order/fill 基线；即使 PaperAccount 已落成交但 receipt 写盘前崩溃，重启后仍能恢复原成交 receipt，不误记为“无新成交”。

## 5. Trading Cockpit

Trading Cockpit 新增 PaperPlan 只读汇总：状态、账户、Universe、Selection Frame、账户 revision 和本次成交数。打开 Cockpit 不创建计划、不执行账户。

## 6. 权限边界

- AI Research / Peer Review 没有 Decision Bridge 写工具、PaperPlan 创建工具或 Paper execute 工具。
- Orchestrator 的 Trading Desk bridge 必须在计划创建时由宿主显式开启。
- PaperPlan 创建/执行均要求显式 host confirmation。
- 无券商 Gateway、无真实下单、无自动实盘。

## 7. 测试与验收

关键专项覆盖：

- Prediction bridge：NO_TRADE、WATCH/READY 保守状态、人工 Decision 保护、历史回放拒绝、QUEUE/PARTIAL 风险保留、receipt 恢复。
- PaperPlan：PLAN_OPEN 门槛、显式确认、Decision revision 失效、固定 universe、模拟 fill、幂等执行、不同 universe 拒绝。
- 崩溃恢复：PaperAccount 成交已提交但 PaperPlan receipt 尚未提交时，可从 durable reservation 恢复 fills/orders。
- 联合链路：Decision/Intent/Paper/Daily Orchestrator/Cockpit **40/40 passed**。
- 完整仓库：**821 tests / 0 failed / 0 skipped**。
- 两个新 CLI 已通过 editable install 与 `--help` 烟测。

## 8. 尚未完成的 P8.8-C

P8.8 还不能整体宣布“长期 Paper 闭环完成”。后续仍需：

1. 动态跨日 universe 的长期 Paper / Shadow 账户模型，而不是每个固定 universe 单独账户。
2. `Paper fill → Strategy Intent OPEN/REDUCE/EXIT` 的严格回执驱动状态合同；必须由成交事实推动，不能由预测推动。
3. D1 / D2 / D3+ 自动复盘，把原 Decision、Paper 成交/未成交、后续结果并排保存。
4. NO_TRADE、未成交、QUEUE_DEPENDENT、费用、滑点、T+1 的长期统计。
5. 真实券商仍属于 P13，P8.8-C 不接真实资金。

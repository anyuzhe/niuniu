# 牛牛 AI 交易工作台：P13-B0 RealTrade Readiness 验收说明

> 历史归档（整理于 2026-09-17）：保留原阶段记录；正文中的“当前、下一步、待完成”和测试/数据数字属于原记录时点。使用与当前进度以 [文档导航](../../README.md)、[当前状态](../../project/status.md) 为准。命令仍从仓库根目录执行。

- 阶段：P13-B0 v1
- 日期：2026-09-15
- 基线：P13-A `bb7be50`
- 最终全仓：**897 tests / 0 failed / 0 skipped**

## 1. 为什么先做 B0

当前没有明确可用的具体券商实时接入通道，因此不能为了推进进度而伪造 Broker Gateway。

P13-B0 的目标是先把未来实盘之前必须满足的能力、风险策略和安全门形式化；在任何一项缺失时，系统都必须 `BLOCKED`。

P13-B0 不连接券商、不认证、不保存密钥、不发送/撤销订单、不划转资金。

## 2. Broker Capability Registry

新增 `BrokerCapabilityRegistry` 与 capability contract。
当前唯一实现为 `json-export-v1`：

- transport=`offline-file`
- account_snapshot=true
- live_channel=false
- account_stream=false
- quote_stream=false
- order_submit=false
- order_cancel=false
- fund_transfer=false
- credential_storage=false

因此导入 P13-A Broker Snapshot 永远不能被解释成“券商在线”。

## 3. RealTrade Safety Policy

新增 `niuniu-real-trade-policy-v1` 合同和 `RealTradePolicyLoader`。

B0 中 `enabled` **只能为 false**；若写成 true 会直接拒绝。人工逐单确认、kill switch、Shadow、Strict PIT、System Health 五类安全门必须保持 true，不能通过 policy 关闭。
Policy 预留但不替用户猜测以下限额：

- `max_order_notional`
- `max_single_position_ratio`
- `max_gross_exposure`
- `max_daily_loss`
- `max_orders_per_day`
- `snapshot_max_age_seconds`
- `allowed_order_types`（B0 只预留 LIMIT）

示例见 `examples/real_trade_policy.example.json`。示例故意保留 null/空值，因此会被判定为 incomplete，而不是一个可启用的实盘配置。

Policy 同样拒绝 password/token/api_key/cookie/session/真实账号等敏感字段。

## 4. RealTrade Readiness Service

新增 `RealTradeReadinessService`，输出 `niuniu-real-trade-readiness-v1`。
当前真实工作区会明确列出以下 blocker：

- `NO_LIVE_BROKER_CHANNEL`
- `BROKER_AUTH_RUNTIME_NOT_IMPLEMENTED`
- `KILL_SWITCH_NOT_IMPLEMENTED`
- `ORDER_RISK_GATE_NOT_IMPLEMENTED`
- `PER_ORDER_CONFIRMATION_GATE_NOT_IMPLEMENTED`
- `ORDER_GATEWAY_NOT_IMPLEMENTED`
- `LIVE_ORDER_RECEIPT_RECONCILIATION_NOT_IMPLEMENTED`

未提供 policy 时还会有 `REAL_TRADE_POLICY_MISSING`；示例 policy 会得到 `REAL_TRADE_POLICY_INCOMPLETE + REAL_TRADE_POLICY_DISABLED`。

Broker Snapshot 若时间在未来、超过 policy 新鲜度、缺失，或 Shadow 不是 MATCH，同样 fail-closed。

即使所有风险参数与 Shadow 都满足，只要选中的 Adapter 仍是 offline-only，仍返回 `BLOCKED`。

## 5. CLI / MCP / System Health
新增 `niuniu-real-trade-readiness` CLI；只读检查当前 workspace，可选读取外部 policy 文件。

MCP 新增 `get_real_trade_readiness`，没有 policy 写入、connect、place_order、cancel_order、transfer_funds 等工具。

System Health 新增 `RealTrade Readiness` 观察项。当前无通道属于 `NOT_CONFIGURED`，不会把正常 Research/Paper 系统标成故障；但其 evidence 内部 readiness 仍明确为 `BLOCKED`。

顶层 `real_broker_connected` 始终保持 false。

## 6. 测试和真实工作区

- P13-B0 新增专项：**8/8 passed**。
- Readiness + P13-A + System Health + MCP 联合：**32/32 passed**。
- 完整仓库：**897 tests / 0 failed / 0 skipped**，352.959 秒。
- 真实 `artifacts`：**77006 → 77006**，CLI/MCP/System Health 查询均无写入副作用。
- MCP readiness 结果约 2.3KB，`ready_for_real_orders=false`。
## 7. 后续路线

P13-B0 到此完成。

下一层改为 **P13-B1：具体券商实时只读 Adapter**。只有当存在明确、可实际使用的券商通道时才开始，目标仍只是账户/持仓/资金/回执的实时只读连接，不默认获得订单权限。

之后再按独立评审拆分：

1. P13-B1：具体券商实时只读连接与认证运行时。
2. P13-B2：实时 Shadow 同步、kill switch、风险限额执行、逐单人工确认与订单预检（仍可保持 dry-run）。
3. P13-B3：若前两层长期验收通过，再单独评审极小范围真实订单能力。

在 B1 通道出现之前，继续开发可以转向并行项：R2/R3 Orchestrator、正式实时 MarketSnapshot provider、Strict PIT 原始资料、approval-time actual-byte freeze、Research Session Grant、Watch 序贯统计等。

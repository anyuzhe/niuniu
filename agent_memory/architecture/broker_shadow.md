# Broker Shadow / P13-A 边界

P13-A 只允许保存**脱敏、只读**券商账户证据并与 Dynamic Paper 做 Shadow 对账；它不是实盘连接层。

- Broker Adapter 在本阶段只能实现 `snapshot()` 只读合同，禁止下单、撤单、资金划转和权限修改。
- Broker Snapshot 不保存密码、Token、API Key、Cookie、Session、真实券商账号等凭证；账户只能使用本地 alias。
- 用户导出的账户快照只能由宿主 CLI 显式 `--confirm` 导入；AI/MCP 没有导入工具。
- Broker Snapshot append-only、checksum/hash 可审计；重复相同内容幂等，篡改必须拒绝。
- Shadow Reconciliation 只比较 Broker 与 Dynamic Paper 的持仓数量和现金；权益差因估值时点可能不同，仅描述不作为 MATCH 判据。
- `get_broker_shadow` 是 AI/MCP 唯一 Broker 工具，只读查询；不存在 connect/place_order/cancel_order/transfer_funds。
- 导入券商导出文件不等于建立实时连接，System Health 的 `real_broker_connected` 必须继续为 false。
- P13-B0 RealTrade Readiness 规则另见 `real_trade_readiness.md`；它已经把无券商通道、认证/kill switch/风险门/确认 Gate/订单 Gateway/回执链缺失全部做成 fail-closed blocker。
- P13-B1 若要连接具体券商，必须先有明确可用的实时只读通道；认证持久化、真实资金或订单能力继续在 B2/B3 单独冻结账户范围、风险限额、人工确认点、kill switch、对账和故障恢复合同。

# RealTrade Readiness / P13-B0 边界

P13-B0 是无券商通道时的 fail-closed 实盘准备层，不是实盘连接层。

- 当前 capability registry 只有 `json-export-v1`：offline-file、`live_channel=false`、`order_submit=false`。
- RealTrade policy 在 B0 固定 `enabled=false`；即使风险参数填写完整，也不能启用真实交易。
- policy 必须保留人工逐单确认、kill switch、Shadow、Strict PIT、System Health 五类安全门，不能关闭。
- 风险参数只定义合同：单笔金额、单票占比、总敞口、日损、每日订单数、快照新鲜度和允许订单类型；B0 不执行真实订单。
- 无实时 Adapter、认证运行时、kill switch、逐单风险门、人工确认 Gate、订单 Gateway、真实回执对账链任一项缺失都必须 BLOCKED。
- Broker Snapshot 未来时间、过期、缺失或 Shadow 非 MATCH 都必须 fail-closed。
- `get_real_trade_readiness` / System Health / CLI 全部只读；AI/MCP 没有 policy 写入、连接、下单、撤单或资金划转工具。
- P13-B1 只有在出现明确的具体券商实时只读通道后才开始；B1 仍不默认包含订单能力。
- P13-B2/B3 若涉及认证持久化、订单预检或真实订单，必须再次单独评审和冻结权限边界。

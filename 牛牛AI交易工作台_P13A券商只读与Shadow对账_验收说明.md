# 牛牛 AI 交易工作台：P13-A 券商只读与 Shadow 对账验收说明

- 阶段：P13-A v1
- 日期：2026-09-15
- 基线：P12 `5363e32`
- 最终全仓：**889 tests / 0 failed / 0 skipped**

## 1. 目标

P13 不直接从 Paper 跳到真实下单。第一层只建立可审计的 Broker read-only 边界：接收脱敏账户快照、append-only 保存，并与 Dynamic Paper 做 Shadow reconciliation。

P13-A **不连接真实券商、不保存券商认证、不发送订单、不撤单、不划转资金**。

## 2. ReadOnly Broker Adapter

新增正式 `ReadOnlyBrokerAdapter` 合同，P13-A Adapter 只能提供 `snapshot()`。

首个实现 `JsonBrokerExportAdapter` 读取用户主动导出的 JSON 账户快照，不联网、不登录券商。未来具体券商的只读 Adapter 可以实现同一合同，不需要修改 Shadow 业务层。

快照只允许：provider、本地 account alias、captured_at、CNY cash/equity、证券持仓和 source_ref。
## 3. 隐私与凭证边界

- 递归拒绝 password / passwd / token / secret / api_key / credential / cookie / session / account_number / account_no / client_id 等字段。
- `account_alias` 只允许本地别名；8 位以上纯数字直接按潜在券商账号拒绝。
- normalized snapshot 固定 `read_only=true`、`contains_credentials=false`、`order_submission=false`，这些权限标志不可伪造。
- JSON 导出文件超过 5MB、符号链接、非法证券代码、重复证券、非有限金额或非法可用数量全部拒绝。

## 4. Append-only Broker Snapshot

新增 `BrokerSnapshotStore`：

- 快照保存在 `_broker_shadow/snapshots/`，以内容 hash 派生稳定 UUID。
- 宿主导入必须显式 `--confirm`；未确认不会创建目录或记录。
- 同内容重复导入幂等；快照 checksum/hash 被修改后读取失败。
- snapshot_id 必须是规范 UUID，路径逃逸字符串不能参与文件路径。
- AI/MCP 没有 Broker Snapshot 导入能力。

示例合同见 `examples/broker_snapshot.example.json`，示例不包含真实账号或凭证。
## 5. Shadow Reconciliation

`BrokerShadowReconciler` 只读比较 Broker Snapshot 与指定 Dynamic PaperAccount：

- 逐证券比较真实快照 quantity 与 Paper `ending_positions`。
- 比较 Broker cash 与 Paper 最新 NAV cash，默认容差 0.01。
- Broker/Paper equity 差只做描述；两边估值价格和时点可能不同，因此不作为 MATCH 判据。
- position + cash 一致才返回 `MATCH`，否则返回 `DIFF`；无快照返回 `NOT_CONFIGURED`。
- 对账结果不创建订单、Decision、Strategy Intent、Paper target 或任何实盘状态。

## 6. CLI / MCP / System Health

新增 `niuniu-broker-shadow`：宿主可 `--import-json --confirm`、`--list` 或 `--reconcile`。

AI/MCP 只新增 `get_broker_shadow`。能力声明明确：`broker_snapshot_import_model=false`、`broker_order_tool=false`、`real_broker_connected=false`。

System Health 新增 Broker Shadow 观察项；即使存在导入快照也只表示有只读证据，**不会把 `real_broker_connected` 改为 true**。
## 7. 测试与真实工作区烟测

- P13-A 专项：**7/7 passed**。
- Broker + System Health + MCP 联合：**24/24 passed**。
- 完整仓库：**889 tests / 0 failed / 0 skipped**，305.046 秒。
- 真实工作区在未配置 Broker 时，CLI/MCP 都返回 `NOT_CONFIGURED`。
- 真实 `artifacts` 查询前后文件数 **77006 → 77006**，没有查询副作用。
- MCP Broker Shadow 返回约 412 bytes；模型工具表中 `import_broker_snapshot / connect_broker / place_order / cancel_order / transfer_funds` 均不存在。

## 8. P13-A 完成后的边界

P13-A 只完成“账户只读证据 + Shadow 对账”的工程底座，**不代表已经连接真实券商**。

下一层 P13-B+ 若选择具体券商并建立实时只读连接，或进一步允许任何真实订单，必须重新单独评审并冻结：认证/密钥存放、账户范围、资金和单票限额、日损/总敞口、订单类型、T+1/停牌/涨跌停、人工确认点、kill switch、审计回执、对账和故障恢复。

在这些合同正式批准前，牛牛继续保持 `real_broker_connected=false` 和无真实订单工具。

# MarketSnapshot Provider

MarketSnapshot Provider 任务必须把“存储已支持实时快照格式”和“存在正式实时数据源”严格分开。

- Provider Registry 当前只有 `manual-import-v1`，它是离线 JSON 导入能力：`live_channel=false`、`network=false`、`automatic_capture=false`。
- `MarketSnapshotProviderReadiness` 在 AUCTION/R1/R2/R3 任一 live provider 缺失时必须 `BLOCKED`；不能用已有 BACKFILL/手工快照冒充 provider ready。
- AI/MCP 只允许查询 `get_market_snapshot_provider_status`，没有 capture/connect/set_credentials 工具。
- 正式 Provider Adapter 必须输出符合 `MarketSnapshot` 合同的 FULL 快照，保留 `provider_ref`、`source_hash`、真实 `as_of` 与可审计 capture lag。
- `LIVE_NEAR_REALTIME` 资格仍由 MarketSnapshotStore 的真实捕获时钟和 Frame Policy 判定，Provider 自报“实时”不生效。
- 临时网页抓取、不可审计聚合源或未来时间快照都不能进入 Orchestrator live 链。
- Provider 缺失在 System Health 中是 `NOT_CONFIGURED` 的自动化能力缺口，不等价于离线 Research 系统故障。

未来接入真实源时，只新增 Adapter/凭证运行边界，不得绕过现有 MarketSnapshot checksum、PIT、Forward Freeze 与 Orchestrator fail-closed 规则。

# System Health 架构边界

P11 System Health 是**只读可观察性层**，不是自动修复器，也不是研究/策略正确性评分器。

- 顶层分离 `runtime_status` 与 `research_readiness_status`；禁止压成一个 health score。
- 组件状态只使用 `OK / WARN / BLOCKED / UNKNOWN / NOT_CONFIGURED`。
- daemon/process/adapter 在线只证明可观察运行状态，不证明数据、PIT、策略或收益正确。
- Market Data / Series 的 accepted cutoff 是回顾性批次合同，不自动升级 strict PIT。
- MCP v1 只报告 adapter、transport、工具数；stdio/stateless HTTP 没有持久 heartbeat 时必须保持 `server_liveness=None`。
- Notification Qt hand-off 不等于用户已看见；应用内 notice 是权威提醒。
- 历史 Orchestrator blocker 必须保留，但不能永久阻断今天；当天 blocker 才进入当前 BLOCKED。
- Artifact growth 使用快速顶层代理，不允许为了健康页递归扫描整个 artifacts 大树。
- System Health 不自动 restart、retry、download、接受数据修订、修改 PIT、merge/push 或交易。
- AI/MCP 只能只读调用 `get_system_health`。
- P11 相关状态语义变化必须同步验收说明与开发史。
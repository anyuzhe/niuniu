# 牛牛 AI 交易工作台：P11 System Health 验收说明

- 阶段：P11 System Health v1
- 日期：2026-09-15
- 开发基线：P10 `8805344`
- 最终全仓：**876 tests / 0 failed / 0 skipped**
- 全仓耗时：299.890 秒

## 1. 阶段目标

P11 把原先分散在 JobQueue、tracking daemon、DailyMarket、MarketSnapshot、Daily Orchestrator、PIT/Playbook、Paper、Dev Studio 和通知系统里的运行证据，统一成一个**只读 System Health 快照**。

核心原则：**进程在线不等于研究正确，服务可读不等于数据合格，Paper 正常也不等于可实盘。**

## 2. 双轴状态，而不是健康总分

System Health 不生成“95分/健康率”一类总分。顶层只分两条轴：

- `runtime_status`：工作空间、产物增长代理、JobQueue、tracking daemon、MCP adapter、Notifications、Dev Studio、后台日志。
- `research_readiness_status`：Market Data / Series、DailyMarket、MarketSnapshot、Daily Orchestrator、PIT / Playbook、Paper Lifecycle。

每个组件只使用 `OK / WARN / BLOCKED / UNKNOWN / NOT_CONFIGURED`，并保留独立 blocker、warning、evidence 和 limitation。
## 3. 覆盖组件

- Workspace：output/data-root 存在性、磁盘剩余容量；容量不等于数据正确。
- Artifact Growth：只扫描 artifacts 顶层，统计 run 目录与近24h顶层变化；避免递归扫描数万文件拖慢 UI。
- JobQueue：状态计数、worker lock、孤儿 RUNNING、近24h失败/中断，以及脱敏的最近10条任务元数据。
- Tracking Daemon：heartbeat、active/stale/error、heartbeat age；daemon 在线不认证研究结果。
- MCP：adapter 是否可构建、`stdio / streamable-http`、loopback HTTP、工具数；v1 不伪造进程 heartbeat，`server_liveness=None`。
- Notifications：应用内 unread、delivery receipt 状态、近24h dispatch failure / unresolved reservation；Qt hand-off 不等于用户看见。
- Market Data / Series：host-approved Baostock Series 数量、generation、accepted cutoff、symbols/modes；不升级为 strict PIT。
- DailyMarket：accepted 最新日期、revision review、calendar lag。
- MarketSnapshot：快照数量、FULL/LIVE、当前市场窗口内近实时证据；缺少 LIVE 时允许 UNKNOWN，而非伪造 provider outage。
- Daily Orchestrator：当天 blocker 才阻断当前 readiness；历史 blocked/missed 计划保留为 WARN，不永久污染今天状态。
- PIT / Playbook：最新 CandidateSet 的 FULL/STRICT_PIT 状态、FROZEN definition、official-rule receipt 线索。
- Paper Lifecycle：预测、计划、成交/未成交、再平衡、Review、动态账户的只读运行证据。
- Dev Studio：DevTask 状态、缺失 worktree、READY_FOR_HUMAN、长时间 RUNNING。
- Logs：已知后台日志只读 size/mtime，不自动读取可能包含敏感内容的日志正文。

## 4. 产品接入与权限

- 系统中心升级为 P11 `SystemHealthWidget`，异步只读刷新。
- 新增 `niuniu-system-health --output ... [--data-root ...]` CLI。
- AI/MCP 新增 `get_system_health` 只读工具。
- 没有 restart/retry/download/accept revision/merge/push/trade 等修复动作。
- `health_score=None`、`automatic_actions=false`、`real_broker_connected=false`。
## 5. 关键反向验收

- Tracking daemon 可为 `OK`，但 DailyMarket revision pending 时 `runtime_status=OK`、`research_readiness_status=BLOCKED`。
- orphan RUNNING Job 没有 worker lock 时明确 BLOCKED。
- active DevTask worktree 丢失时明确 BLOCKED。
- 昨日 Orchestrator `BLOCKED_*` 今天只保留 WARN；当天阻断仍为 BLOCKED。
- 空工作区读取 System Health 不创建 `_jobs`、daemon、Orchestrator、通知或数据库状态。

## 6. 真实工作区烟测

使用真实 `/Volumes/Lexar/niuniu/artifacts` 与本地 MQC 数据目录只读运行：

- artifacts 文件数：**77006 → 77006**，无写入副作用。
- 优化后 CLI 刷新约 **0.82 秒**；此前递归扫描 77006 文件约14秒，因此改为顶层增长代理。
- 当前真实快照：`runtime_status=OK`、`research_readiness_status=WARN`、`blocker_count=0`。
- 当前唯一 warning 为 `no_frozen_playbook_definition`；最新 CandidateSet 本身为 `FULL/STRICT_PIT`。
- MCP adapter 可用，当前工具数 47；这不代表 MCP 进程正在运行。
- AI `get_system_health` 返回体低于 24KB 限制，未被截断。

## 7. 测试与下一阶段

- P11 专项 + offscreen UI：**14/14 passed**。
- MCP / Agent Catalog / Trading Desk 相关回归通过。
- 完整仓库：**876 tests / 0 failed / 0 skipped**。

P11 v1 到此完成。下一正式阶段进入 **P12 移动端 / 机器人**：复用现有 MCP/API、Stock Dossier、Decision Ledger 与统一状态源，不建立第二份记忆或第二份持仓状态。
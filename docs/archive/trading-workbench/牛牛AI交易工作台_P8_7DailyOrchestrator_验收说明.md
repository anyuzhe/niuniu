# 牛牛 AI 交易工作台 P8.7：Daily Orchestrator v1 验收说明

> 历史归档（整理于 2026-09-17）：保留原阶段记录；正文中的“当前、下一步、待完成”和测试/数据数字属于原记录时点。使用与当前进度以 [文档导航](../../README.md)、[当前状态](../../project/status.md) 为准。命令仍从仓库根目录执行。

## 1. 本轮范围

P8.7 v1 把已完成的 DailyMarket、PREP Scanner、MarketSnapshot、AUCTION/R1 Scanner 和 Forward Freeze 串成**单交易日、宿主授权、持久可恢复**的自动编排链。

它不是实时行情供应商，也不是自动实盘系统。当前只覆盖 `PREP → AUCTION → R1`；R2/R3 仍明确标记 unsupported。

## 2. 持久计划与运行方式

新增 `DailyPlaybookOrchestrator` 和 CLI `niuniu-daily-orchestrator`。

宿主先用 `--init` 冻结 `trading_day / as_of_session / definition_id / target_streak / allow_daily_market_capture / data_root`。同一交易日不同计划会冲突；同计划重复 init 幂等。

运行方式：

- `--status`：只读当前状态；
- `--tick`：执行一个确定性推进周期；
- `--run --poll-seconds N`：持续轮询到 COMPLETE / MISSED / 不可恢复终态。

状态写入 `artifacts/_daily_orchestrator/<trading_day>.json`，使用 checksum、原子替换和文件锁；事件历史最多保留500条。

## 3. DailyMarket 阶段

默认计划**没有联网权限**。只有 `--allow-daily-market-capture` 才允许在上一交易日18:30后调用现有 DailyMarketArchive。

- 已有 accepted snapshot：直接复用，不联网；
- 尚未到18:30：等待；
- 网络失败：15分钟冷却后才能重试；
- 单计划最多8次 capture；
- 出现 `revision_review`：停止推进，宿主通过原 `niuniu-daily-market --accept-revision` 明确接受后，下一 tick 可继续。

同时修正 DailyMarket `revision_candidates` 语义：已被宿主接受的新版本不会把旧 accepted 历史版本继续算成“待审修订”。

## 4. PREP 阶段

Orchestrator 不复制 PREP 规则，而是调用正式 `scan_prep_universe`。

PREP 在写 MarketSnapshot/Case 前先持久保存 `scan + as_of + snapshot_content + deterministic request_id`。因此若进程在 MarketSnapshot 已写出但 Forward Freeze 未完成时中断，重启后会复用同一 reservation 和同一 snapshot，不制造第二份历史。

Router UNKNOWN 且宿主没有 target_streak 时保持 BLOCKED；PREP 窗口错过后标 `BLOCKED_PREP_MISSED`，不允许历史回填 SYSTEM_PREDICTION。

## 5. AUCTION 阶段

只接受当日 **09:25–09:30** 的 `LIVE_NEAR_REALTIME` AUCTION MarketSnapshot。

- 09:25前：WAIT_DATA；
- 09:25–09:30没有正式实时快照：WAIT_MARKET_SNAPSHOT；
- BACKFILL 快照：忽略；
- 09:30后仍未冻结：AUCTION=MISSED，不再补预测。

AUCTION 继续复用 `DailyPlaybookScanner`，当前规则仍是“只排序，不直接产生入场选择”。

## 6. R1 阶段

R1 v1 固定为首个完整5分钟窗口，只接受 **09:35–09:40** 的 LIVE_NEAR_REALTIME R1 MarketSnapshot，同时要求存在09:25–09:30的实时 AUCTION事实快照。

如果 AUCTION 的 SYSTEM_PREDICTION 本身因调度错过，但当时的实时 AUCTION MarketSnapshot 已正式冻结，R1 仍可继续；这区分了“事实证据存在”和“预测是否按时提交”。

超过窗口或首个R1快照超过10分钟冻结限制后标 MISSED，不使用后来的 R1 数据伪装09:35判断。

## 7. 数据资格继续 fail-closed

Orchestrator 不提高任何数据资格。当前全自动 PREP 若缺 PIT Universe / 交易所逐日 MarketRules，会保持 `PARTIAL + RETROSPECTIVE_REFERENCE`。

因此即使 AUCTION/R1 快照完整，DailyPlaybookScanner 也会因为基础 CandidateSet 非 FULL 而冻结 `NO_TRADE`，而不是为了自动化强行选择股票。

## 8. 权限边界

P8.7 没有给 AI Research、MCP 或 Reviewer 新增 init/tick/run 工具。计划创建、DailyMarket capture 授权和运行都是宿主动作。

`--run` 只执行已经存在的单日计划，不会自动生成下一交易日计划，不会改变 Frame Policy，不会接受 DailyMarket 修订，也不会创建实时行情来源。

## 9. 实时行情边界

当前仓库已有 MarketSnapshotStore，但尚没有产品化的正式 AUCTION/R1 实时 provider。P8.7 只消费已有正式快照；没有快照就等待/错过。

本轮刻意没有把临时网页接口、未审计第三方接口或后验行情写进 Orchestrator。正式实时 provider 以后作为独立数据源模块接入。

## 10. 测试与验收

- Daily Orchestrator 自身：12/12 passed；
- DailyMarket + Orchestrator：16/16 passed；
- PREP / Forward / MarketSnapshot / Scanner 联合：36/36 passed；
- editable install 后 `niuniu-daily-orchestrator --help` 实际可运行；
- 完整仓库：**805 tests / 0 failed / 0 skipped**。

真实 `artifacts` 在本轮验收中没有创建 `_daily_orchestrator` 状态；正式 PlaybookStore 计数仍为 42 ExpertSource / 17 Definition / 36 Case / 26 CandidateSet / 37 Selection / 2 Validation。

下一阶段：**P8.8 Playbook → Decision Ledger → Strategy Intent → Paper/Execution → D1/D2/D3+**。

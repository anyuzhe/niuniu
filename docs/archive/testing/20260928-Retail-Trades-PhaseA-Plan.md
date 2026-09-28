# Retail Trades Phase A 回补规划

日期：2026-09-28

## 目标

Retail Microstructure V2 已能从 TDX trades 构造 BuyImbalanceProxy、VolumeImbalance、SmallOrderNotionalShare 与 SmallOrderBuyImbalance，但当前只有 1 个接近全市场的有效交易日，冻结推断门为至少 120 个合格日。

本轮只规划逐笔 trades 历史回补，不启动网络采集、不解除 STOP、不修改任何真实 worker collection scope。

## 现状

原 TDX plan c4566306e15db946c8c853975a6a3f36aac4a57ffcd8080619e2fe4522c4a927 已包含 1990-12-19 至 2026-09-17 的完整交易日历，原 Runner 也支持 trades 在同一证券上按交易日向历史递推，并受上市/退市日期约束。

真正阻断历史递推的是 2026-09-18 固化的 collection scope：

- excluded: bars_1m, bars_5m, bars_daily, trades, opening_match
- 原因：用户从其他来源取得 K 线，同时不再需要成交量/逐笔历史
- Mac worker 仍处于 STOPPED / USER_STOP

因此单纯等待不会增加 V2 逐笔历史。

## 当前真实 V2 覆盖

canonical tdx_trades_compacted 当前约 14,043,754 行，5 个日期：

- 2026-09-17：原始 5,562 只，5,553 只可计算方向特征
- 2026-09-16：833 只可计算
- 另外 3 天：单股测试记录

V2 覆盖门为每日 feature symbols ≥ max(3000, 当前范围最大 feature symbols × 90%) 且至少 120 个合格日；当前仅 1/120。

## 20 / 40 / 120 日 dry-run

规划器：scripts/research/retail_trades_backfill_plan.py

它只读原 plan、scheduler lifecycle policy、canonical coverage 与现有三分片算法，不改队列、不改 scope、不改 STOP、不联网。

| 窗口 | 日期范围 | lifecycle 后 symbol-day | shard 0 / 1 / 2 | 估算页面请求 | 三节点 0.35s 理论下限 |
|---|---|---:|---|---:|---:|
| 20 日 | 2026-08-21..09-17 | 111,280 | 37,605 / 37,455 / 36,220 | 303,362 | 9.8 h |
| 40 日 | 2026-07-24..09-17 | 222,214 | 75,067 / 74,783 / 72,364 | 605,781 | 19.6 h |
| 120 日 | 2026-03-27..09-17 | 664,247 | 224,288 / 223,519 / 216,440 | 1,810,813 | 58.7 h |

页面倍率使用 2026-09-17 canonical 已有任务估算，约 2.726 页 / symbol-day；真实值会随流动性变化。

120 日完整规划保存在本机 artifacts/retail-trades-backfill-plan-v1-20260928.json，plan digest 为 6decff4cec830e78c61dcae77976bf0173051211d60aea99235a0c962a7a410e。

## 存储估算

2026-09-16/17 已归档逐笔源页的 raw + Parquet + manifest 均稳定在约 61–62 bytes / trade row。2026-09-17 约 12.99M 行，源页归档约 798 MB。

按 2026-09-17 活跃度粗略外推：

- 120 日约 15.5 亿行
- 源页 archive 约 88.9 GiB
- 当前 DuckDB compacted 表约 127 bytes / row 的块占用粗略换算，120 日约 180+ GiB
- canonical 合计保守接近 270–300 GiB，另有 worker 离线副本与临时空间

Lexar 当前约 1.9 TiB，总已用约 470 GiB，可用约 1.4 TiB，因此容量不是硬阻塞，但一次性 120 日仍不应无阶段保护执行。

## 为什么先做 20 日 Phase A

Phase A 固定最近 20 个交易日（2026-08-21..09-17）：

- 理论请求约 30.3 万页
- 三节点限速下理论约 9.8 小时
- 可以验证三机逐笔回补、分页倍率、ProtocolError 比例、离线搬盘、canonical merge、V2 特征稳定性
- 不改变 V2 的 120 日正式推断门；20 日数据不得用于宣称显著性

## collection scope 的窗口下限

不修改 scheduler policy，因为 worker assignment 与 scheduler policy ID 强绑定；改 policy 会迫使三机 assignment/bootstrap 迁移。

本轮扩展 collection scope 支持可选 family_history_floors，目前只允许 trades。这是“本次采集窗口限制”，与 scheduler 的供应商 retention floor 完全分开。

Phase A proposed scope：

- trades 从 excluded 移出
- bars_1m, bars_5m, bars_daily, standalone opening_match 继续 excluded
- trades floor：sh/sz/bj 均为 2026-08-21
- scheduler policy ID 不变
- distributed assignment ID 不变
- ERROR trade jobs不因 scope 迁移而重试或改写
- standalone opening_match 仍不做网络请求；trade 页中真实 opening-match 行可沿原逻辑本地派生

Mac worker dry-run：

- current scope ID：0ec7436fe87645b4bc5917a7a4676f15a5d81d24d090ef911302f370e69af28f
- proposed scope ID：e8a57a52b8e859e4164e04a16c1351ad088942b19b86a6c45dd427e0c9ecd41e
- would restore 1,882 个旧 collection-scope trade seeds
- would leave 69 个已有 ProtocolError trade jobs untouched
- 当前 floor 以下无 PENDING 被误恢复
- STOP 文件仍存在

预览证据：artifacts/retail-trades-phasea-scope-preview-mac-20260928.json。

## 验证

TDX scheduler / lake / distributed / V2 / planner 相关 5 模块合计 80 项测试全部通过，0 failure/error。

其中新增覆盖：

- collection scope trade floor schema
- 旧 scope skip 的可审计恢复
- floor 外任务保持 skip
- Runner 到 floor 后停止向更早日期递推
- scheduler retention floor 语义不变
- worker policy/assignment identity不变
- backfill planner dry-run 不修改 queue

## 尚未执行

- 未把 proposed scope 写入 Mac/HomePc/601
- 未解除任何 STOP
- 未发起任何 TDX 网络请求
- 未在 HomePc/601 实际核对 proposed scope
- 未生成或导入新的 worker result bundle
- 未进行 V2 收益统计推断

真正执行 Phase A 仍需在三台 worker 上分别核对 scope/assignment 后，明确写入 reviewed scope，再显式 resume。

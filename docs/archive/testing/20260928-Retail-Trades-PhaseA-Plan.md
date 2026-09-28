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


## 跨机只读核对补充

Phase A 代码发布后，对现有 WebCodex Windows 节点做了只读执行前核对：

### 601

601 WebCodex 在线；仅做文件/SQLite/磁盘读取，没有 pull、scope 写入、STOP 变更或采集。

- 仓库当时仍停在旧提交 92b46f8，因此不能直接执行新的 collection-scope floor 逻辑。
- data root：D:\AI\testData\niuniu-data
- active plan：与 Mac 相同 c4566306...
- scheduler policy：与 Mac 相同 7829c3c...，0.35 秒
- cluster：fbe957f3...
- assignment：d1c90c05...，shard 2/3，machine=601，1905 symbols
- STOP：存在；AUTO_HALT：不存在
- collection-scope.json 不存在
- trades：PENDING 1814、ERROR 91，另有已有 CHECKPOINT/EMPTY/SAVED；日期只到 2026-09-16/17
- D 盘 data root 所在卷约 1.86 TiB，总空闲约 1.52 TiB

这说明原 Phase-A preview 的“继承当前 scope 再移除 trades”在 Mac 上正确，但跨机器不安全：601 无旧 scope 时会把 K 线与 standalone opening_match 也意外放开。

因此 Phase-A scope 生成器修正为显式固定语义，不再继承任何 worker 的旧 excluded 列表：

- 必须排除：bars_1m / bars_5m / bars_daily / opening_match
- 必须允许：trades
- trades floor：sh/sz/bj 都等于 Phase A 起始日
- scheduler policy / assignment 不改

这个修正只影响 Phase-A preview/后续显式 scope 内容，不会修改已有数据或立即执行采集。

### HomePc

HomePc WebCodex tunnel 超过 300 秒未在线，因此没有换用其他远控通道，也没有推断其当前 scope/queue。Phase A 真正执行前必须等 HomePc WebCodex 恢复后做同样只读核对。

### 执行前新增硬条件

真正 resume Phase A 前必须同时满足：

1. 三台 worker 代码都包含本次 Phase-A scope floor 支持；
2. 三台 plan/policy/cluster/assignment 身份逐项一致；
3. 三台 proposed scope 都解析为同一显式 excluded 集与同一 2026-08-21 trades floor；
4. 三台 STOP 在 scope 写入和队列预览期间保持；
5. HomePc 恢复在线并完成只读预检；
6. scope 写入后先复核队列变化，再由独立显式动作解除 STOP / resume。


## Guarded reviewed-scope apply

为避免人工写 collection-scope.json 或使用陈旧 preview，本轮进一步给 Phase-A 工具增加 guarded apply 模式。

只有同时满足以下条件才允许写 reviewed scope：

- worker STOP 文件仍存在；
- 无 RUNNING / STORED 任务；
- 当前 scope ID 与 preview 时完全一致；
- proposed scope ID 与 preview 时完全一致；
- trade queue 逻辑快照与 preview 时完全一致；
- 持有既有 TDX writer lease；
- 只调用 apply_collection_scope，不调用 resume/autoresume，不删除 STOP，不访问网络。

成功后额外写 retail-phasea-scope-receipt.json，记录 before/current scope、before/after queue snapshot、实际变更行数、STOP 状态，并明确 network_accessed=false、resume_performed=false。

新增测试验证：

1. 指纹完全匹配时，scope 被写入、旧 scope skip 可恢复为 PENDING，但 STOP 仍存在；
2. preview 之后 queue 任意变化时，apply 必须 fail-closed，旧 scope 保持不变；
3. queue snapshot 覆盖 proposed scope 能修改的全部 family（bars_1m / bars_5m / bars_daily / opening_match / trades），非 trades 队列变化同样会使 apply fail-closed。
4. 加入这些保护后，TDX scheduler/lake/distributed/V2/planner 完整回归为 84 项，全部通过。

该能力仅用于把 worker 安全配置到同一 reviewed scope；它本身不启动 Phase A 采集。


## Phase A reviewed scope 实际写入状态

在 guarded apply 与全 family stale-queue guard 发布后，对 Mac 与 601 分别重新生成 fresh preview，并使用各自 current scope ID 与 queue snapshot 执行 reviewed apply。

### Mac / shard 0

- proposed scope ID：e8a57a52b8e859e4164e04a16c1351ad088942b19b86a6c45dd427e0c9ecd41e
- before scope：0ec7436fe87645b4bc5917a7a4676f15a5d81d24d090ef911302f370e69af28f
- queue snapshot：976249a291044eb83b457479ea3ab551fb37620d43861ff22b828010440b3d9f
- changed rows：1882，全部为旧 collection-scope skip 的 trades 恢复为 PENDING
- STOP=true，inflight=0，network_accessed=false，resume_performed=false

### 601 / shard 2

- 代码先由旧 92b46f8 ff-only 到当前 Phase A 版本；同步前后 STOP、plan、policy、assignment、queue SHA 均核对未因代码同步改变
- proposed scope ID 与 Mac 完全一致
- before scope：NONE
- queue snapshot：6427db19e5b71403fa7c9f17ac80d1b31eba9250135df2120ff1dca6a75bf88f
- changed rows：5313，审计分解为 bars_1m 1809、bars_5m 1807、bars_daily 1697 的 PENDING→SKIPPED_POLICY
- trades PENDING 1814 保持，ERROR 91 保持
- STOP=true，inflight=0，network_accessed=false，resume_performed=false

### HomePc / shard 1

HomePc WebCodex tunnel 仍未在线；未改走其他远控通道，未写 scope、未改 STOP、未推断 queue 状态。由于 V2 0.2 现在要求每个 shard 独立达到覆盖门，即使只运行 Mac+601，未来日期也不会被误判为近全市场。真正启动 Phase A 仍以 HomePc 恢复、同步代码、只读预检、写入同一 reviewed scope 为前置条件。


## Mac-only Phase A：一台物理机、三个逻辑 shard

用户决定 Phase A 只使用 MacBook。现有 Mac 数据盘已经保留原三份 worker root，因此不需要重新 bootstrap：

- worker-0：assignment c9a7a020...，逻辑 machine=macbook，shard 0/3，1951 symbols
- worker-1：assignment a54018ed...，逻辑 machine=homepc，shard 1/3，1953 symbols
- worker-2：assignment d1c90c05...，逻辑 machine=601，shard 2/3，1905 symbols

三个 assignment 均属于原 cluster fbe957f3...，plan/policy 完全一致。machine_name 仅是冻结 assignment 的逻辑标签；实际三个 worker 都在同一台 Mac 上顺序运行。canonical 仍按原 distributed bundle/merge 契约接收数据，V2 0.2 继续按原 shard0/1/2 检查完整度。

### strict trades-only scope

原 Phase A scope 只排除了 K 线和 standalone opening_match，但真实队列还存在大量 auction PENDING，worker-0 另有 limit_ladder PENDING。直接启动 Runner 会顺带采无关 family。

因此 Phase A scope 再冻结为严格 trades-only：

- 允许：trades
- 排除：securities / bars_1m / bars_5m / bars_daily / opening_match / auction / quotes / depth / finance / capital_changes / topics / limit_ladder
- trades floor：sh/sz/bj 都为 2026-08-21
- scope ID：a4f26280051643665304d1a2f80ac630d1779227dcd5f0e4197d7928c4d1cc93

三个本地 worker 使用 fresh queue snapshot guarded apply：

- shard0：额外变更1880行非-trades PENDING，STOP保持
- shard1：额外变更1864行非-trades PENDING，STOP保持
- shard2：额外变更1812行非-trades PENDING，STOP保持

最终三个队列的 PENDING 均只有 trades：1882 / 1877 / 1813。

### Mac 串行 runner

新增 scripts/research/retail_trades_mac_serial.py。默认不联网，只输出三 worker preflight。真实 dry-run 已确认三个 assignment 唯一且完整覆盖0/1/2、plan/policy/cluster/scope一致、STOP=true、inflight=0、无AUTO_HALT、PENDING只有trades。

只有同时传 --execute 与 --personal-research-only 才允许联网。单个 shard 的 batch 在现有 writer lease 内执行，启动前再次复核所有条件；批次期间临时移除该 shard STOP，finally 中无论成功或异常都恢复 STOP。其他两个 shard 始终保持STOP。Runner若进入HALTED，串行流程停止，不继续下一个shard。

新增正常结束与异常两类 STOP 恢复测试。focused Phase-A/scheduler 21项PASS，完整 TDX scheduler/lake/distributed/V2/PhaseA 87项PASS。

### SQLite 外置卷兼容

worker-1/2 Phase-A preview 初次在大 ORDER BY job_id 查询上触发 sqlite3 OperationalError: unable to open database file。直接读写打开同一数据库正常，说明不是数据库损坏。preview 改为 SQLite 只过滤行，Python 内存按 job_id 稳定排序后计算 snapshot，避免外置卷上的 SQLite 临时排序文件依赖；随后 worker-1/2 真实 preview 均通过，snapshot 语义不变。

### Windows 节点

HomePc/601 不再是 Mac-only Phase A 的启动前置条件。Windows 601 之前写入的 reviewed scope 仍保持 STOP，不参与本轮；后续 Mac-only 不再操作 Windows 数据。V2 0.2 shard-aware coverage gate保证物理采集迁移到一台Mac后，最终canonical仍必须三个逻辑shard都达到覆盖阈值才允许推断。

## 2026-09-28 Mac-only真实采集与主库验收

本节是后续真实执行结果，不覆盖上文各阶段当时的“尚未执行”记录。执行版本95d0422，隔离eltdx接线修复afa934a已包含在内。前置页恢复针对sh.688786 / 2026-09-16：worker丢失的是本地页副本，canonical仍有相同source_id、1800行与三份原始字节SHA；恢复后精确分页为0→1800→2227（最后EMPTY），不重新请求原第一页、不改变历史错误证据。

### 本次有界批次

物理主机仅MacBook。worker标签homepc/601只是既有逻辑assignment名称，不代表调用对应Windows电脑。日期下限2026-08-21、trades-only、0.35秒请求间隔、每组500请求预算保持。

| 逻辑分组 | 请求页数 | 新增逐笔行数 | 非空页 | 空响应页 | 网络错误 |
|---|---:|---:|---:|---:|---:|
| 0 | 500 | 426881 | 325 | 175 | 0 |
| 1 | 500 | 283618 | 268 | 232 | 0 |
| 2 | 500 | 305992 | 270 | 230 | 0 |
| 合计 | 1500 | 1016491 | 863 | 637 | 0 |

原236条ProtocolError（69/76/91）的job_id、state、error、attempts、updated_at在验收中逐项比对保持。三个批次因REQUEST_BUDGET正常结束，STOP全部恢复，无RUNNING/STORED，无AUTO_HALT。零新增网络错误不等于历史数据已经没有问题。

### 主库接收与字节验证

三个worker使用原export/import/ack链完成本地合并；本次明确锁定的1500个trades source_id全部出现在canonical publications，证券、日期、行数、观察时间和计划等metadata与worker完全一致。对应bundle在canonical有同SHA和sequence_no的导入记录，worker acked=1。随后仅对trades执行compaction，本次归档1500页、1016491行、原始文件逻辑字节61969265。

独立只读验收重新计算每个归档的raw、Parquet、manifest SHA，共4500个字节哈希，并重新核对manifest checksum及source_id/family/rows。主库trades publication总行数从14517661增至15534152，新增精确为1016491；compacted表总量和每一组新增source的行数均一致。空响应页单独存证，不计入逐笔行数。

### 剩余覆盖与结论边界

2026-09-16：2539928行、1775只原始出现证券、1768只有有效方向特征；分组实际777/478/513，对照门槛1694/1690/1632，全不合格。2026-09-17：12994164行、5562只原始出现证券、5553只有效方向特征，三个分组仍全部合格。其余三个历史日期仅为单股测试记录。

因此当前仍只有1/120个合格日。20日Phase A尚未完成，也没有运行V2的未来收益显著性检验。验收另列canonical分页库存：9月16日1773个非空股票日已从offset=0连续到EMPTY，11个完全空响应，27个已出现队列的股票日未闭合；这个数字只描述已出现的队列，不是全市场完成率。某股票日出现数据、方向特征可算、分页完整、达到研究资格是不同层次。

原始验收位于artifacts/retail-phasea-mac-acceptance-20260928/：before_merge.json、collection_receipt.json、verify_acceptance.py、acceptance.json、summary.md。acceptance.json SHA256为4697261f06900b08dff218730ef65c6950d0d62359e7fc104d7d9b123bc92e37，accepted=true，phase_a_20_days_complete=false，return_inference_performed=false。此前修复代码的90项相关回归与本节真实数据验收分开，不累计为新测试数量。

# 牛牛 AI 交易工作台：Approval-time Actual-byte Freeze 验收说明

> 历史归档（整理于 2026-09-17）：保留原阶段记录；正文中的“当前、下一步、待完成”和测试/数据数字属于原记录时点。使用与当前进度以 [文档导航](../../README.md)、[当前状态](../../project/status.md) 为准。命令仍从仓库根目录执行。

- 阶段：Research Lab 基础设施 / Approval-time Actual-byte Freeze v1
- 日期：2026-09-15
- 基线：P8.7 v2 `de32343`
- 最终全仓：**912 tests / 0 failed / 0 skipped**

## 1. 目标

旧 Proposal 只冻结配置和代码/工作空间绑定；实际行情字节仍在执行时读取，因此批准后到真正执行前，底层数据可能发生变化。

本阶段把正式 Proposal 流程升级为：

`propose → host approval → actual input freeze → approved → JobQueue → frozen input execution`

批准后执行、重试和恢复都必须使用同一个冻结包，不能悄悄回退到 mutable data root。

## 2. 冻结对象

冻结包位于 `_approval_input_freezes/<proposal_id>/`，保存 checksum manifest 与独立文件 SHA256。

实际冻结对象覆盖主行情 DataBatch、Multi-timeframe Context、PIT/listing Universe eligibility mask，以及精细账户执行需要的 qfq 信号价 + raw 成交价。
Campaign 多节点使用同一个 Proposal freeze bundle，manifest 保存 node/role 关联；Holdout / Walk-forward 的子区间由 frozen provider 从批准时的大区间安全切片。

冻结的是**引擎实际使用的规范化研究输入字节**，不是无差别复制整个历史数据湖；manifest 同时保留原 `DataSnapshot` 身份和源文件信息。

## 3. 数据来源语义

冻结只改变“执行从哪一份不可变字节读取”，不改变研究口径。

因此执行产物继续保留原 provider 和 adjustment，例如 `mqc_parquet / qfq`；冻结身份写入 `files[].approval_time_frozen=true`、`source_snapshot_id` 和 Approval Freeze receipt。

这样 Watch / Rebase 等依赖 provider、复权口径和 Universe 身份的长期合同不会把审批冻结误判为一种新行情来源。

## 4. Proposal / JobQueue

只有宿主 `approve_and_submit` 可以创建冻结包；模型仍只有 qualify / preview / propose / query 权限。

冻结包在 Proposal 进入 `approved` 之前完成。队列 guard 保存 freeze receipt；submit、resume、run 及运行完成后的检查都会重新验证 manifest、spec digest 和每个冻结文件 SHA256。

批准后即使原行情文件被修改、qfq 目录被移走，任务仍从冻结包完成；若冻结包自身被篡改，则直接拒绝执行，绝不回退 live data。
旧 direct JobQueue 与 Tracking 的 `input_signature` 路径继续兼容；旧 `approved` Proposal 如果没有 approval freeze，则不会静默升级执行，必须重新生成 Proposal 并重新批准。

## 5. System Health / 审计

System Health 新增 `Approval Input Freeze` 观察项，显示 valid / invalid / pending staging 数、引用文件数和最近冻结时点。

健康页只检查 manifest 与文件存在性，不在每次刷新时对大量 Parquet 重算 SHA256；完整哈希强校验发生在 submit / resume / run 的真正使用边界。

`get_proposal` 在存在冻结包时会返回其 `freeze_id / manifest_hash / spec_digest`，因此批准对象和后续 Job 可以直接对上同一冻结证据。

## 6. 验收证据

新增专项 **7/7 passed**：

- 批准后修改并移走原 qfq 目录，已批准 Job 仍完成且读取冻结文件。
- 冻结文件追加一个字节后，重试 fail-closed。
- Holdout 三段子区间可从冻结大区间运行。
- Campaign 两节点共用一个 approval bundle。
- `price_mode=account` 同时冻结 qfq signal 与 raw execution 输入。
- PIT Universe eligibility mask 在批准时固化并用于执行。
- System Health 只读展示冻结包元数据。
相关 Proposal / Campaign / JobQueue / System Health / Execution / Qualification 联合回归 **64/64 passed**。

真实工作区只读查询前后 `artifacts` 文件数 **89484 → 89484**，没有因为查看 capability / health 创建 `_approval_input_freezes`；该目录只会在用户真正批准 Proposal 时创建。

完整仓库最终 **912 tests / 0 failed / 0 skipped**，366.669 秒。

## 7. 当前边界

Approval-time freeze 固定的是正式研究执行实际消费的数据与资格 mask，解决批准到执行之间的输入漂移。

它不自动补齐 Strict PIT 缺失的原始来源，不证明数据供应商正确，也不替代实验完成后的 frozen_inputs / bundle / reproduction 归档。

下一项不依赖外部券商/实时行情通道的 Research Lab 主线是 **Research Session Grant**：给 Agent 一个有限次数、有限预算、有限研究范围且可撤销的自主研究沙箱，而不是无限授权。

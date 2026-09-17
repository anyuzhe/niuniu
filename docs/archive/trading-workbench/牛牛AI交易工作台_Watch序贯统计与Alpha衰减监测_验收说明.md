# 牛牛 AI 交易工作台：Watch 序贯统计与 Alpha 衰减监测 v1 验收说明

> 历史归档（整理于 2026-09-17）：保留原阶段记录；正文中的“当前、下一步、待完成”和测试/数据数字属于原记录时点。使用与当前进度以 [文档导航](../../README.md)、[当前状态](../../project/status.md) 为准。命令仍从仓库根目录执行。

- 日期：2026-09-15
- 范围：Factor Watch / Tracking / Research Agenda / AI 只读工具 / PyQt Watch
- 目标：在不改变原研究与审批边界的前提下，为长期 Watch 增加可重复查看的 Rank IC 衰减证据。

## 1. 已完成能力

新增 `watch_sequential.py`，把 Watch 创建时的已成熟每日 Rank IC 冻结为经验参考。后续刷新只消费基线截止以后**新成熟**的每日 Rank IC，不重新挑基线、不按结果改参数。

v1 创建 Watch 时冻结：

- `family_alpha`，默认 0.05；
- `min_effect`，默认 Rank IC 下降 0.02；
- `min_new_dates`，默认 10 个新增成熟日期；
- `block_sessions`，默认 5 个交易日；
- Sequential algorithm fingerprint。

## 2. 序贯判定

新增成熟日期先按固定、非重叠 block 聚合，尾部不足一个完整 block 的数据只保留为 pending，不进入证据。完整 block 的平均 Rank IC 进入固定 lambda 网格的 mixture e-process。

同一个 Watch 内，family alpha 预先分配到各 horizon。只有同时满足：

1. 基线有效样本达到 Watch 的 `min_dates`；
2. 新成熟日期达到 `min_new_dates`；
3. e-value 达到 `1 / local_alpha`；
4. 检验目标已经包含预先冻结的 `min_effect`；

才输出 `DEGRADATION_EVIDENCE`。否则保持 `NO_DECISIVE_CHANGE` 或 `INSUFFICIENT_*`。

重复打开/重复刷新同一份数据不会产生新的统计证据；一旦历史路径曾越过阈值，后续快照仍保留首次越界时点和 `max_e_value`。

## 3. 兼容与 fail-closed

- 旧 Watch 不自动迁移，继续显示 `LEGACY_NOT_CONFIGURED`，原描述性窗口与刷新流程不变。
- 新 Watch 的序贯参数随 Definition 固定；算法指纹变化时必须新建 Watch 或走正式 Rebase。
- Rebase 保留原 Watch 的序贯参数；legacy Watch 换版后仍是 legacy。
- 基线不足时完全不产生衰减结论。
- 历史输入 revision 时序贯解释停止为 `HISTORICAL_REVISION_BLOCKED`。
- 新成熟日期不足完整 block 时 e-value 不前进。

## 4. 产品与权限

Factor Watch 桌面创建页已增加 family alpha、最小 Rank IC 衰减、最少新增成熟日期、非重叠 block 交易日四个参数。

`get_factor_watch` 可只读返回 Sequential Monitor 状态；模型没有自动停用、接受衰减、修改因子参数或绕过 Watch 刷新审批的工具。真正出现衰减证据时，只生成 `watch_decay_evidence` Research Agenda 人工复核项，不做自动交易动作。

## 5. 统计解释边界

e-process 的 repeated-look 控制相对于**冻结的经验基线均值**成立，不代表基线样本均值就是已知总体真值；多个事后挑选的 Watch 之间也没有共享一次全局 family-alpha 认证。市场状态改变、长期时间相关、股票池变化仍可能影响解释。

因此 `DEGRADATION_EVIDENCE` 的正确含义是“需要复核”，不是“因子已经死亡”，更不是自动卖出/停用/换参数的授权。

## 6. 验收证据

- Watch/Tracking/Agenda/Factory/System Health 相关联合回归：**99/99**。
- 完整仓库：**945 tests / 0 failed / 0 skipped**，376.376 秒。
- 真实工作区只读 smoke：当前 Watch=0，`artifacts` 文件数 **77006 → 77006**；AI 写动作工具交集为空。
- 发布纪律要求 committed Agent Memory 关键回归、敏感信息扫描和 Git SHA 同步检查全部通过后才允许 push。

# Watch Sequential Monitor

Watch 序贯监测用于回答“相对创建 Watch 时冻结的经验 Rank IC 基线，后续新成熟样本是否已出现持续衰减证据”，不是未来 Alpha 认证，也不自动改变策略或因子状态。

## 固定统计合同

- 仅新建 Watch 默认启用 v1；旧 Watch 保持 `LEGACY_NOT_CONFIGURED`，禁止静默升级统计口径。
- 创建时冻结 `family_alpha`、`min_effect`、`min_new_dates`、`block_sessions` 和 Sequential algorithm hash；后续不得按结果改阈值。
- 基线只使用创建 Watch 截止时已成熟的每日 Rank IC；后续只消费 `mature_at > baseline_as_of` 的新增成熟日期。
- 新成熟每日 Rank IC 先组成固定、非重叠 block；默认 5 个交易日。尾部不足一个完整 block 的数据只显示 pending，不进入序贯证据。
- v1 使用固定 lambda 网格的 mixture e-process；family alpha 在同一 Watch 的 horizons 间预先分配。重复查看同一数据不能制造新的证据。
- 只有达到 `min_new_dates` 且 e-value 越过预先冻结阈值，才标记 `DEGRADATION_EVIDENCE`；未越界为 `NO_DECISIVE_CHANGE`，样本不足保持 `INSUFFICIENT`。

## Fail-closed 与权限

- 基线有效日期不足时完全不计算衰减结论；历史输入发生 revision 时返回 `HISTORICAL_REVISION_BLOCKED`，先处理来源问题。
- Sequential algorithm hash 变化时必须新建 Watch 或走正式 Watch Rebase；Rebase 保留原序贯参数，legacy Watch 仍保持 legacy。
- `DEGRADATION_EVIDENCE` 只进入 Watch alert 和 Research Agenda 人工复核待办；禁止自动暂停因子、自动换参数、自动移出策略或自动下单。
- AI/MCP 仅只读查看 Watch/Sequential 状态，没有 accept_decay、pause_factor_for_decay、change_factor_parameters 等动作工具。
- e-process 的 repeated-look 控制是相对冻结的**经验基线均值**，不是把基线样本均值当成已知总体真值；跨多个事后挑选的 Watch 不共享一次 family-alpha 认证。
- 市场状态变化、长期相关性和 cohort 改变仍可能影响解释；统计越界是复核信号，不是“因子已死亡”的自动结论。

任何后续 Watch/Tracking/Alpha decay 任务都必须读取本文件，并保留旧快照、失败/未知状态和统计口径版本。
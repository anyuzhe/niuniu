# 期末50分 · 首个 Expert Playbook 试点

当前状态：**SOURCE_REQUIRED / 尚未形成正式交易规则**。

这个目录只确认研究方向，不把当前二手描述直接写成“期末50分玩法”。在获得足够可核验的原帖、实盘记录、交易时间和当时市场上下文前，`eligibility / selection / veto / entry / exit` 均保持未冻结。

## 第一阶段要回答的问题

- 能否稳定确认原始资料是谁、何时公开、当时何时可见？
- 能否按当时信息重建每个真实案例，而不是事后只看赢家？
- 能否重建当时全部符合 eligibility 的 CandidateSet？
- 当候选是 10 只而实际选择 2 只时，A/B 与其余 C–J 的差异是什么？
- 差异规则冻结后，在没看过的 Case 上还能否解释选择？
- 按 A 股真实可成交约束执行以后，结果是否仍成立？

## 来源晋级条件

正式 `ExpertSource` 至少保存来源定位、可用时间与内容 SHA256。只有达到 `VERIFIED` 的来源，才允许支撑 FROZEN PlaybookDefinition。

原始大体积或受版权限制材料不复制进 Git；Git 只保存引用、哈希、合法本地归档说明和研究摘要。

## 当前前瞻样本

- `notes/forward_prediction_20260914_prep.md`：v3 建立后的首个 PREP 前瞻样本；非空候选集，盘前不提前选具体股票。
- `notes/forward_prediction_20260916_prep.md`：2026-09-15 accepted DailyMarket 驱动的 `EXTREME_RISK / NO_TRADE`；CandidateSet 为空，Orchestrator 正常进入 `COMPLETE_NO_TRADE`。

这些记录只证明预测是在目标交易日前冻结，不改变本 Playbook 的 `SOURCE_REQUIRED / DRAFT` 边界，也不证明 Strict PIT、Alpha 或可交易收益。

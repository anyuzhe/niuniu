# Agent Scorecard 架构边界

P9 Scorecard 只用于观察已持久化证据中的运行纪律、覆盖和后续跟踪；它不是模型排行榜，也不是自动路由权重。

## 核心规则

- 必须按 `task_type` 分离评价，禁止跨任务生成 composite score。
- 样本为 0 时保持 `NO_SAMPLES`；样本不足 3 时保持 `INSUFFICIENT_SAMPLES`。
- Decision 字段齐全、引用了 evidence、调用了工具，都不等于结论正确。
- Evidence correctness 只有存在独立可核验标签/事实时才能评价；不能由 Agent 自评替代。
- Paper 收益、Playbook 命中和多数 Agent 共识都不能直接变成某个 Agent 的分数。
- 宿主拦截但未持久化 receipt 的违规尝试不可观察，禁止臆造 violation 次数。
- Scorecard v1 不自动修改 TeamConfig、模型、effort、Agent 权限或任务路由。
- Developer 在 P10 产品化前不进入 P9 Scorecard。

## 防迎合

AI Research 可以只读查询 Scorecard，帮助人理解历史表现；第一轮 Peer Reviewer 的工具集合必须排除 Scorecard，避免 Reviewer 先看评分再迎合指标。

## System Baseline

Playbook Prediction 与 Paper Lifecycle 属于系统基线，不是 Agent 分数。只有唯一 `OBSERVED_EXPERT` 标签时才允许计算 Selection Exact / Precision / Recall；这些指标仍不等于 Alpha 或盈利认证。

# Expert Playbook Lab

`playbooks/` 保存高手玩法的**人类可读研究假设、来源说明、规则版本和变更理由**。

这里不是收益数据库，也不是“高手语录 = 系统真理”的规则库。结构化 CandidateSet、SelectionDecision、PlaybookValidation 与执行审计保存在工作空间 `_playbooks/` 中。

## 基本纪律

1. 先登记可核验 `ExpertSource`，再抽取玩法。
2. DRAFT 可以记录待验证假设；FROZEN 必须绑定 VERIFIED 来源。
3. 每个历史 Case 必须尽量重建当时完整候选全集，而不是只保存最终买入者。
4. Selection 研究的是“为什么从候选中选这些”，未选股票同样是证据。
5. 看到结果后改变 eligibility / selection / veto，必须新建规则版本，不能覆盖旧版本。
6. HOLDOUT / WALK_FORWARD 只有在 FROZEN + FULL CandidateSet + STRICT_PIT + VERIFIED 来源时才允许称正式验证。
7. Playbook 命中、选择一致率或高手长期盈利都不等于牛牛已经获得 Alpha。
8. 可执行收益必须另行审计 T+1、涨跌停、停牌、费用、滑点和资金占用。

## 目录约定

每个高手/玩法使用独立目录。README 记录研究状态；`definition.json` 是 Git 中的机器可读研究骨架；`notes/` 只保存合法摘要和人工标注，不替代原始来源。

# Research Skill Curation Plans

这里保存可审阅、可版本化的**选择计划**，不保存第三方原文字节。

每份计划同时固定：

- Git 跟踪控制包的 `control_snapshot`；
- 独立数据根 Git receipt 的 `archive_snapshot`；
- 选中 upstream path、目标 path、bytes、SHA256、角色与 locator；
- 原话 claim、“说／做／结果” alignment 和仅限 DRAFT 的 hypothesis。

运行 `research-skill-git-curate --confirm-retrospective-only` 后，第三方字节从内容寻址对象复制到独立数据根中的新 package snapshot。计划不授予 source identity、publication time、Strict PIT、Alpha、Daily Scanner 或交易资格，也不会写 StrategySource/Playbook。

当前计划：`zhengxi-304ac3e4.json`、`ai_industry_radar-a245cef7.json`。上游更新或控制包变化必须显式更新 snapshot 并生成新策展包，禁止覆盖旧包。

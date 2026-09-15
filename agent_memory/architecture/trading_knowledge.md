# Trading Knowledge / StrategySource Architecture

架构生效：2026-09-14。完整说明见仓库根目录 `牛牛AI交易助手_项目说明与总体架构.md`。

## 核心定义

牛牛的长期中心不是某位交易者，而是：

`StrategySource → Playbook → Validation → Daily Decision → Review`。

`StrategySource` 目标类型：

- TRADER
- USER_EXPERIENCE
- PUBLIC_METHOD
- HISTORICAL_CASE
- STATISTICAL_DISCOVERY
- SYSTEM_REVIEW

当前 `ExpertSource` 是 TRADER 类型的兼容实现，不得破坏性改写已有 ID、哈希、Case 或 Validation。

## External Research Skill adapter

- 外部专家知识库不直接进入交易核心；先放在 `research_skills/<skill>/`，由 `research-skill-audit` 只读验证 `skill.yml / SKILL.md / references / method.md / scorecard.md / scripts`。
- 原始观点、披露行为与后续结果分别使用 `PRIMARY_STATEMENT / DISCLOSED_ACTION / REALIZED_OUTCOME`；claim 必须区分 `DIRECT_QUOTE / METHOD_INFERENCE / FACT_TO_VERIFY`。
- “说/做/结果” alignment 是交叉核验，不是因果或 Alpha 证明。季度持仓只能作为 Theme Matrix / Stock Dossier 中期辅助证据，不能进入 AUCTION/R1/R2/R3。
- 外部评分只能是 `SOURCE_STYLE_SIMILARITY_ONLY`；所有 hypothesis 固定 DRAFT。审计不执行脚本、不联网、不写结构化库，只给 `PENDING/PARTIAL StrategySource` 预览。
- Research Skill 永不自行签发 Strict PIT、Daily Scanner 或交易资格；publication-time、CandidateSet、Holdout/Walk-forward 与 execution 继续走牛牛既有门。
- `research_skills/zhengxi` 当前只是 `SOURCE_REQUIRED` 脚手架；没有外部 corpus、持仓、结果或脚本，不得把用户二次概述冒充原话。

## 规则与证据边界

- 来源不是规则；Playbook 初始必须为 DRAFT。
- 一个来源可支持多个 Playbook；一个 Playbook 可引用多个支持/反对来源。
- Git/Markdown 保存人类可读规则、经验、架构和 Agent Operating Memory。
- CandidateSet、MarketSnapshot、Decision、PIT、实验、成交和收益继续以 Structured Evidence 为权威源。
- Markdown 不得覆盖结构化事实；索引/向量库只能是可重建缓存。
- Eligibility、Selection、Execution Access、P&L 必须分别验证。
- NO_TRADE、失败样本、未选样本、未知和不可成交样本必须保留。

## Agent 行为

- 不把“期末50分”或任何单个交易者当系统一级模块。
- 不因来源知名而升级规则证据等级。
- 多 Agent 一致不是独立市场证据；Chief 负责综合并保留分歧。
- Daily Scanner 只消费冻结事实和规则；证据不足时允许 UNKNOWN / PARTIAL / NO_TRADE。
- 系统复盘产生的新经验先进入 SYSTEM_REVIEW 来源，再形成新 DRAFT；不得回写旧版本预测。

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

# Trading Knowledge / Playbook Lab

`playbooks/` 保存交易知识的**人类可读研究假设、概念定义、规则版本、来源摘要和变更理由**。

系统中心不是某一位高手。实盘交易者、用户经验、公开方法、历史案例、统计发现和牛牛自身复盘都只是 `StrategySource`；真正长期积累的是可版本化、可验证、可前瞻检验的 `Playbook`。

这里不是收益数据库，也不是“经验 = 系统真理”的规则库。结构化来源、CandidateSet、SelectionDecision、PlaybookValidation、MarketSnapshot 与执行审计保存在工作空间结构化存储中。

## 来源模型

目标来源类型：`TRADER / USER_EXPERIENCE / PUBLIC_METHOD / HISTORICAL_CASE / STATISTICAL_DISCOVERY / SYSTEM_REVIEW`。

当前历史 `ExpertSource` 保持兼容，并统一视为 `StrategySource(type=TRADER)`。一个来源可以支持多个 Playbook，一个 Playbook 也可以拥有多个 `ORIGIN / SUPPORT / CONTRADICT / EXAMPLE / COUNTEREXAMPLE` 关系。

## 基本纪律

1. 来源不是规则；任何经验先作为 DRAFT 假设。
2. 正式 `HOLDOUT / WALK_FORWARD` 仍要求既有 **FROZEN Playbook + VERIFIED ExpertSource + FULL CandidateSet + STRICT_PIT + 实时 SYSTEM_PREDICTION + A股执行审计**；P8.6 新 StrategySource 关系只是补充知识来源，不能绕过任何正式门槛。
3. 每个历史 Case 必须尽量重建当时完整候选全集，而不是只保存最终买入者。
4. Selection 研究“为什么从候选中选这些”；未选、失败、不可交易和 NO_TRADE 同样是证据。
5. 看到结果后改变 eligibility / selection / veto，必须新建规则版本，不能覆盖旧版本。
6. Playbook 命中、来源知名、多 Agent 一致或选择匹配率都**不等于牛牛已经获得 Alpha**。
7. 可执行收益必须另审 T+1、涨跌停、停牌、费用、滑点、资金占用和 execution access。
8. Git/Markdown 只保存人类可读知识；数值和时点事实以 Structured Evidence 为权威源。

## 外部 Research Skill 边界

`../research_skills/` 是进入本层之前的独立知识适配区。它可以按专家/方法保存 `SKILL.md + references + method.md + scorecard.md + scripts`，并通过 `research-skill-audit` 核文件哈希、时点、原话/推演/待核实事实和“说/做/结果”关系。

审计只生成 `PENDING/PARTIAL StrategySource` 预览，不写本数据库；外部评分固定为来源风格相似度，季度机构数据只可作为 Theme/Dossier 中期辅助证据。任何包都不能自动变成 FROZEN Playbook、Daily Scanner、Strict PIT、Alpha 或交易信号。

## 目录约定

本目录可以按 Playbook 或研究主题组织，不要求“每个高手一个目录”。现有 `qimofenshu/` 保留为首个 TRADER 来源历史试点；后续规则应逐步按规则本身命名和组织，来源通过结构化关系关联。外部专家原始知识包放 `research_skills/`，不要把其独立评分/脚本直接复制进 Playbook 或 execution。

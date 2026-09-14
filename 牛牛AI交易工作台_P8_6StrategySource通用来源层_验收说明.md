# 牛牛 AI 交易工作台 P8.6：StrategySource 通用来源层验收说明

## 1. 本轮目标

P8.6 将 P8.5 的“高手来源试点”升级为通用 Trading Knowledge 来源层。系统不再把某一个交易者等同于一套策略，而是把来源和 Playbook 拆成独立对象，并允许多对多证据关系。

本轮不改变既有 Alpha / HOLDOUT 正式验证语义，不把“来源更多”解释成“规则更可靠”。

## 2. StrategySource

新增六类来源：

- `TRADER`
- `USER_EXPERIENCE`
- `PUBLIC_METHOD`
- `HISTORICAL_CASE`
- `STATISTICAL_DISCOVERY`
- `SYSTEM_REVIEW`

每条来源保存 `source_key / source_kind / title / locator / published_at / available_at / content_hash / archive_ref / completeness / notes / evidence_ids`；`VERIFIED` 必须有可用时间与 SHA256。

## 3. ExpertSource 向后兼容

原 `ExpertSource` 表、source_id、payload、checksum、Case 和 Validation 不修改。统一 StrategySource 查询会把旧 ExpertSource 投影为：

`StrategySource(source_kind=TRADER, strategy_source_id=<原 source_id>)`。

因此旧期末50分 42 条来源无需迁移即可读取。旧 ExpertSource 人工导入入口继续保留。

## 4. PlaybookSourceLink 多对多关系

新增关系：`ORIGIN / SUPPORT / CONTRADICT / EXAMPLE / COUNTEREXAMPLE`。

一个 StrategySource 可以关联多个 PlaybookDefinition，一个 PlaybookDefinition 也可以关联多个支持/反对来源。链接 append-only、request_id 幂等，并保存 definition_hash 与 source snapshot hash。

## 5. 正式验证门槛没有放宽

P8.6 不让新 StrategySource 直接替代 `definition.source_ids`。当前正式 `FROZEN / HOLDOUT / WALK_FORWARD` 仍要求旧合同中的 VERIFIED ExpertSource、FULL CandidateSet、STRICT_PIT、真实 SYSTEM_PREDICTION 与执行审计。

也就是说，新来源关系可以帮助研究、解释、支持或反驳 Playbook，但不能自动把 DRAFT 升级成正式规则。

## 6. schema v1 → v2

PlaybookStore schema v2 新增 `strategy_sources` 和 `source_links` 两张表。

- 旧 v1 数据库只读时无需迁移；统一来源查询直接投影旧 ExpertSource。
- 首次创建 StrategySource/Link 时，在同一数据库内增量创建新表并升级 user_version。
- 不重写旧表，不重算旧 checksum。

真实 `artifacts/_playbooks/playbook_lab.sqlite3` 的临时副本完成 v1→v2 烟测：原 42 Source / 17 Definition / 36 Case / 26 CandidateSet / 37 Selection / 2 Validation 的 payload+checksum 聚合指纹全部不变。

## 7. AI / MCP / Peer Review 权限

新增只读工具：统一列出/读取 StrategySource、列出 PlaybookSourceLink、读取 Definition + 来源关系 Bundle。

模型没有 `create_strategy_source` 或 `create_playbook_source_link` 工具；Peer Reviewer 只获得相同只读查询能力。桌面宿主人工导入仍是写入入口。

## 8. 桌面产品变化

Research Lab 入口改名为“交易知识 / Playbook Lab”。来源页统一展示旧 TRADER 投影和新 StrategySource；Definition 详情同时展示旧正式 source_ids 和新的多来源关系。

“期末50分试点”不再作为一级标签页，改成“来源 / Playbook关系”架构说明；原 `playbooks/qimofenshu/` 历史资料继续保留。

## 9. 测试与结论

- StrategySource 核心：7/7 passed。
- AI/桌面产品专项：13/13 passed。
- Playbook/Forward/MarketSnapshot/Stock Dossier/AI Team 联合：41/41 passed。
- 完整仓库：**793 tests / 0 failed / 0 skipped**。

本阶段完成的是“通用交易知识来源层”，不是任何新 Playbook 的 Alpha 认证。下一阶段为 **P8.7 Daily Orchestrator**。

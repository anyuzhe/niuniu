# 牛牛 AI 交易工作台：外部 Research Skill 接入规范 v1 验收说明

- 验收时间：2026-09-16 01:16（Asia/Shanghai）
- 范围：外部专家/机构方法知识包 → StrategySource 预览 → Playbook DRAFT 候选
- 结论：完成只读、无联网、无脚本执行、无自动写库的 Research Skill 边界适配器；郑希目录目前只是 `SOURCE_REQUIRED` 脚手架，没有导入或冒充外部原始语料

## 1. 本轮采用什么、不采用什么

借鉴外部知识库的四项结构：

1. 原始语料 → 方法提炼 → 评分语义分层；
2. “说了什么 / 披露做了什么 / 后续结果怎样”显式对照；
3. `SKILL.md / references / method.md / scorecard.md / scripts` 包结构；
4. 基金观点与季度持仓作为 Theme Matrix / Stock Dossier 的中期辅助证据。

不把外部库整体并入交易核心，不复制其评分为交易策略，不自动执行其脚本，也不让季度基金持仓进入 AUCTION/R1/R2/R3。

## 2. 新架构位置

```text
External Research Skill（独立知识边界）
  ↓ 只读 audit + PENDING/PARTIAL preview
StrategySource
  ↓ 宿主复核、多对多 SourceLink
Playbook DRAFT
  ↓ 牛牛自己的特征、PIT、CandidateSet
Holdout / Walk-forward / 行业市值中性 / 成本后验证
  ↓
Daily Decision / Outcome Review
```

Research Skill 不导入 Daily Scanner、Paper 或 execution。现有 `StrategySource / PlaybookDefinition / CandidateSet / Validation` 仍是结构化权威对象；本轮不修改 Playbook SQLite schema，也不绕过新 StrategySource 尚不能直接成为正式 FROZEN source 的兼容门。

## 3. 固定包结构与机器合同

```text
research_skills/<skill>/
├── skill.yml
├── SKILL.md
├── method.md
├── scorecard.md
├── references/
└── scripts/
```

`skill.yml` 使用确定性的 JSON-compatible YAML，避免增加 YAML 执行器/隐式类型依赖；同时声明检索 keywords、资源、claim、alignment、DRAFT hypothesis 和固定权限政策。审计器要求文件清单闭合、拒绝符号链接和越界路径，并逐文件核对 bytes/SHA256。

资源角色：

- `PRIMARY_STATEMENT`：原始公开观点；
- `DISCLOSED_ACTION`：独立披露的持仓/行为；
- `REALIZED_OUTCOME`：独立结果资料；
- `BEHAVIOR_CONTRACT / METHOD / SCORECARD / SCRIPT / SCRIPT_POLICY / DOCUMENTATION`：方法与工具层，不得冒充 publication evidence。

证据资源必须有 locator、带时区 `available_at` 和 `PUBLICATION_VERIFIED / RETROSPECTIVE_REFERENCE` 分类。`PUBLICATION_VERIFIED` 还必须有 `published_at <= available_at`。仅有 URL、二次摘要或“真实数据”标签不产生 Strict PIT。

## 4. 原话、推演、事实与言行对照

claim 固定分成：

- `DIRECT_QUOTE`：只能回链 `PRIMARY_STATEMENT`；
- `METHOD_INFERENCE`：必须回链至少一份原始观点；
- `FACT_TO_VERIFY`：必须回链观点、披露行为或结果证据。

alignment 显式绑定 `statement_claim_id + action_resource_ids + outcome_resource_ids`，只允许 `CONSISTENT / INCONSISTENT / MIXED / UNKNOWN`。观点和披露持仓一致仍不证明因果或 Alpha；缺结果时不能冒充完整三联证据。

## 5. 评分与假设边界

所有包必须固定：

- `score_semantics=SOURCE_STYLE_SIMILARITY_ONLY`；
- hypothesis 只能是 `DRAFT / RESEARCH_HYPOTHESIS_NOT_ALPHA`；
- `direct_trade_eligible=false`；
- `daily_scanner_eligible=false`；
- `quarterly_data_intraday_eligible=false`；
- `strict_pit_eligible=false`；
- `alpha_claimed=false`；
- `institutional_data_role=THEME_DOSSIER_AUXILIARY_ONLY`。

审计输出可以给出候选特征和 `strategy_source_preview`，但不会写 Playbook Lab。即使来源完整，preview 最高也只是 `PARTIAL`；宿主仍须复核并显式导入，规则仍从 DRAFT 开始。

## 6. 脚本与权限

`quantlab research-skill-audit`：

- 只读本地包；
- 不联网；
- 不执行任何 `scripts/`；
- 不写 StrategySource、Playbook、Decision、Paper 或订单；
- 不签发 PIT/MarketRules receipt。

外部基金列表、净值或持仓脚本未来若接入，必须逐文件审阅和哈希；联网抓取仍需宿主对具体任务显式授权，原响应/headers/观测时间进入独立数据根中的完整 Research Skill package。v1 只审 package 内普通文件，不跟随 symlink 或外部绝对路径。

## 7. 首个郑希脚手架真实状态

新增 `research_skills/zhengxi/`，只保存接入协议和五个候选研究维度：行业景气、ROE 低位修复、全球竞争优势、产业链利润再分配、机构可承载流动性。

当前 audit：

- package snapshot：`d9660110e0105404adb2ee4ddfc757214b27e59985c0359c18fbd58be05dd43c`
- status：`SOURCE_REQUIRED`
- resources：5
- hypotheses：5，全部 DRAFT 且尚未回链 claim
- primary statements / claims / disclosed actions / outcomes / alignments：全部 0
- `source_layer_ready=false`
- `playbook_draft_candidate_ready=false`
- `strategy_source_preview.completeness=PENDING`

blockers：`primary_statement_missing / claim_layer_missing / disclosed_action_missing / say_do_alignment_missing / realized_outcome_missing / say_do_outcome_triad_missing`。

仓库没有发现本地 `zhengxi-views`，用户也没有提供可导入 URL；本轮没有联网、下载、复制原语料、基金数据或外部脚本，不把用户二次概述伪装成郑希原话。

## 8. 命令

```bash
quantlab research-skill-audit --package research_skills/zhengxi
```

输出包含完整性、角色计数、publication blocker、说/做/结果覆盖、DRAFT readiness、固定非交易边界以及与现有 `normalize_strategy_source` 合同兼容的只读预览。

## 9. 测试

- Research Skill + StrategySource + Playbook Lab/Tools 专项：**23/23 passed**。
- 完整仓库按互斥文件集合运行：非 Desktop **853/853**、Desktop **118/118**，合计 **971 tests / 0 failed / 0 skipped**。
- 单进程 `unittest discover` 同样报告 `Ran 971 tests / OK`，但一次在结果输出后触发 macOS/PyQt 解释器退出期 `Bus error`；采用上述互斥双进程复核后两组退出码均为0，不把 teardown 异常隐瞒成测试失败或业务通过证据。

## 10. 下一道门

只有取得外部仓库/原始语料的本地副本，或宿主对明确 URL 的联网抓取授权后，才开始逐项导入 corpus、publication metadata、季度持仓与结果资料。其后仍只形成 StrategySource/PUBLIC_METHOD 证据和 Playbook DRAFT，再由牛牛自己的 PIT 数据与 Quant Validation 判断哪些维度是否存在 Alpha。

# 牛牛 AI 交易工作台 P8.5-A：Expert Playbook Lab 基础框架验收说明

## 1. 本轮范围

本轮完成的是 P8.5 的**基础设施与“10选2”验证框架**，不是宣布“期末50分玩法已经提取完成”。

新增六类正式结构化对象：`ExpertSource / PlaybookDefinition / PlaybookCase / CandidateSet / SelectionDecision / PlaybookValidation`。

核心原则是 Playbook-first hypothesis discovery + deterministic evidence + Quant/PIT validation；原有 Factor / Experiment / Campaign / Watch 不删除，继续作为验证和对照工具。

## 2. 候选全集与防事后偏差

`CandidateSet` 保存当时所有满足 eligibility 的股票，不能只保存最终买入者。每个候选保留 eligibility 原因、features 和 evidence 引用；同一 Case 只允许冻结一份 CandidateSet，改变候选全集必须新建 Case。

`SelectionDecision` 只能引用冻结候选集中的股票，并自动保留 selected / unselected 两侧。`SYSTEM_PREDICTION` 必须与 CandidateSet 使用同一冻结时点，禁止看完后续行情再回填“当时选择”。

## 3. 正式验证门槛

`HOLDOUT / WALK_FORWARD` 不允许仅凭人工填表晋级。正式验证同时要求：

- PlaybookDefinition 已 `FROZEN`；
- Case 来源均为 `VERIFIED ExpertSource`；
- CandidateSet 为 `FULL`；
- 候选资格为 `STRICT_PIT`；
- target selection 为带 evidence 引用的 `OBSERVED_EXPERT`；
- model selection 为冻结时点的 `SYSTEM_PREDICTION`。

Validation 保存 Precision、Recall、Jaccard、Exact Match 等选择重建指标；这些指标只回答“为什么 10 选 2 能否被稳定重建”，不自动证明盈利。

## 4. A 股执行审计

只有保存 gross/net return、costs、slippage，并明确审计 T+1、涨跌停和停牌，且绑定执行证据时，执行合同才标为 ready。

即使达到完整审计状态，记录仍固定 `alpha_verified=false`、`profitability_claim=not_established`；真正 Alpha 结论仍需后续统计、样本外稳定性与真实执行证据。

## 5. AI 与桌面权限

AI Research Chat 与 P8 Reviewer 新增 Playbook **只读**工具，可查看 overview、来源、规则版本、Case Bundle、Validation 和股票历史；没有 create/save/revise Playbook 工具。

Research Lab 已增加“高手玩法 / Playbook Lab”入口。桌面支持宿主人工导入六类严格 JSON 对象、查看来源/规则/案例/候选全集/历史验证；打开页面不会创建研究任务。

Stock Dossier 增加 `Playbook / 10选2` 页签，同一股票既保存被高手/系统选中的历史，也保存进入候选但未被选择的历史。

## 6. Git-first 试点目录

新增 `playbooks/`。首个 `playbooks/qimofenshu/` 明确保持 `SOURCE_REQUIRED`：`formal_definition_id=null`，全部正式规则字段保持 `null`。

当前二手总结不能静默升级成正式玩法；必须先取得并登记足够可核验的原始资料，再从 DRAFT → FROZEN。

## 7. 测试证据

Playbook/Trading Desk/AI Team 专项联合回归：**32 项通过**；追加严格 target evidence 后专项核心 **7 项通过**。

最终全仓：**750 passed / 0 failed / 0 skipped，exit=0**。

本轮没有接入“期末50分”的真实原帖或实盘数据，因此证明的是对象合同、权限、防回填、候选全集、验证门槛和 UI 链路，不证明任何高手玩法有效或有 Alpha。

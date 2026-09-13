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
## 8. 首批真实来源核验进度

2026-09-13 已从开发机直接访问并哈希两条真实公开页面：期末50分本人 2026-07-24 主帖，以及组织者公开交割单链接/验证讨论。二者均登记为 `PARTIAL ExpertSource`，并建立 `source-hypothesis-1` DRAFT；打开/登记来源前后 `_jobs` 都是 8。

本人主帖只足以支持“主动性、带动性”属于其选股气质的定性假设；组织者线程虽然声明账户验证，但同一线程存在交易记录缺口质疑，而且 KDocs 当前只能取得登录页，故不得升级为完整交割记录。

因此 P8.5 仍处于进行中：下一步先完成真实成交记录连续性审计，再建立第一批真实 Case/CandidateSet。
## 9. P8.5-B：用户提供交割记录与首批候选全集

2026-09-13 用户直接提供公开 KDocs 交割表的 56 条成交明细副本。牛牛本地保存原始副本与机器审计，但 `source_raw/` 被 Git 忽略；Git 只保留来源哈希、缺口和研究摘要。

持仓勾稽显示：同一证券已给出的相邻成交内部无数量断裂；7 月 1 日至 7 月 23 日可形成多段从 0 持仓到 0 持仓的闭合真实交易。7 月 24 日以后仍存在长缆科技 293600 股、国新能源 200 股、百花医药 835200 股未闭合，以及传智教育首条即卖出 751000 股的前置持仓来源缺口，因此交割副本继续为 PARTIAL。

结构化 Evidence 已增加 10 个真实 PlaybookCase，并建立 `source-hypothesis-2` DRAFT；仍不由成交赢家反推 CandidateSet。

随后新增 `playbook_reconstruction` 回顾性候选重建器，按真实交易日、精确涨停价、逐日涨跌幅限制和停牌处理重建二连板全集。粗略“涨幅≥9.7%”被禁止代替精确涨停判断；彩虹股份 6 月 29 日差 0.01 元未封真实涨停，因而不进入 7 月 1 日二板候选。
历史制度边界也被纳入重建：未股改 S佳通按 5%；ST通脉 6 月 30 日按 5%，7 月 1 日停牌，7 月 2 日摘帽后中通国脉按 10%；恒尚节能的停牌占位 K 线不重置真实交易日连板高度。

最终首批候选全集得到：

- 2026-07-01：18 个 `FULL + RETROSPECTIVE_REFERENCE` 候选，真实选择浙江东日；其竞价开盘涨幅在 18 只中仅第 2。
- 2026-07-03：16 个 `FULL + RETROSPECTIVE_REFERENCE` 候选，真实选择宜宾纸业；其竞价开盘涨幅第 1，并直接开在涨停价。

这两组只证明 Eligibility 已能稳定重建，不证明 Selection 规则。尤其浙江东日 09:25 已成交，因此买入后才出现的“当天第一个上板”等盘后特征不能作为该次选择的因果解释。

Playbook 专项联合回归本轮为 **20 项通过**。正式 Validation 仍为 0；下一阶段继续提取 Selection 层可计算事实，并用未参与规则提取的日期验证。

本轮 P8.5-B 收尾全仓回归：**756 passed / 0 failed / 0 skipped，exit=0**。原始交割表和网页/PDF归档继续只留本机 `source_raw/`，不进入 Git；结构化 Playbook Evidence 留在 `artifacts/_playbooks`，Git 仅提交代码、来源哈希与审计摘要。

## 10. Selection 外推与 Meta-Playbook 进展

2026-09-13 继续使用交割副本和全市场 MQC 数据推进 Selection 研究。新增 7/2 康欣新材 19 选 1 失败案例：候选冻结于 10:15，真实首笔成交 10:16:36；买入前价格强度仅排第 8、距离涨停约 7%，但早盘成交额已约为前一整日 2.14 倍。该案例只用于提出待验证 veto，不反推“本人规则”。

selection-hypothesis-v1 固定由 7/1、7/3 两个发现样本提出。7/13 立方制药作为首个未参与发现的 2→3 回放样本，v1 因贵绳股份唯一 auction_open_at_limit 而回放选择贵绳，真实选择为立方；结构化 RECONSTRUCTION 保存 0 命中、0 precision/recall、exact_match=false，失败保持不可覆盖。

v1 失败后建立 selection-hypothesis-v2 DRAFT：先看市场节点/新旧题材，再看 buyability，再看主动拉升/换手确认，最后比较主动性、带动性和拥挤度。7/13 只属于 v2 的发现样本，不重新计算为验证成功。

同时新增 Meta-Playbook DRAFT，暂分 low_board_2_to_3、space_leader_first_buyable_divergence、space_leader_reentry、high_low_switch、second_wave_repair 五个研究分支。唯一空间板反例统计证明“买最高板”不是充分条件；后续每个分支都必须连同不交易日重建负样本。

权限侧进一步封堵历史回填：SYSTEM_PREDICTION 除 as_of 必须与 CandidateSet 一致外，CandidateSet 的真实 frozen_at 与预测真实创建时间也必须处于近实时窗口；历史规则回放改用 HUMAN_RECONSTRUCTION，只允许 RECONSTRUCTION / IN_SAMPLE，不能冒充 HOLDOUT / WALK_FORWARD。

本轮 Selection / Meta-Playbook 与防历史回填修改专项联合回归 **22 passed / 0 failed**；最终全仓 **758 passed / 0 failed / 0 skipped，exit=0**。相对上一稳定基线 756 项新增的测试专门覆盖历史 CandidateSet 不能冒充近实时 SYSTEM_PREDICTION，以及 HUMAN_RECONSTRUCTION 只能用于描述性回放、不能进入正式 HOLDOUT/WALK_FORWARD。

## 11. 空间龙 / 重入 / 高低切 / 二波分支

继续将 7/1–7/24 可靠交割区间中的正负样本按账户状态与市场高度拆分。`space-leader-first-buyable-hypothesis-v1` 保存 10 个“前一日唯一最高板且开盘未持有”的机会日：3 个真实买入、7 个明确未买；同一发现窗口内的 DRAFT 条件可以 3/3 命中且 0 误报，但 Validation 明确使用 `IN_SAMPLE`，`alpha_verified=false`，不得称验证成功。

同时建立 `space-leader-reentry-hypothesis-v1`（哈药 7/17 清仓后 179 秒涨停重入）、`high-low-switch-hypothesis-v1`（7/24 四只3板梯队中实际选择长缆而非超大一字爱丽）、`second-wave-repair-hypothesis-v1`（恒尚旧8板龙断板清仓后首次修复板、次日早盘大分歧回收）。二波修复因尚未重建全市场历史旧龙身份，CandidateSet 刻意保持 PARTIAL。

当前实际 PlaybookStore：15 sources / 11 DRAFT definitions / 27 cases / 17 candidate sets（16 FULL）/ 28 selections / 2 descriptive validations；FROZEN=0，audit_complete=0。下一阶段禁止继续在这批7月发现样本上调阈值，优先取得新的连续交割记录进行真正未见样本检查。

## 12. 新时间段样本与执行访问边

继续自主搜索公开资料后，结构化 Playbook Lab 已扩展到 22 个 ExpertSource、13 个 DRAFT Definition、29 个 Case、19 个 CandidateSet（18 个 FULL）、30 个 SelectionDecision、2 个描述性 Validation；仍无 FROZEN、无 AUDIT_COMPLETE。

8/7 百花医药没有被强行解释成既有五分支成功，而被记录为 Meta-Playbook 覆盖缺口；8/28 万向德农与 9/1 竞业达则建立 `queue-dependent-overnight-board-hypothesis-v1`。两者说明策略复现必须拆分 `selection_alpha` 与 `execution_access_alpha`：高速通道能够成交的一字排板，不得在普通账户回测中默认可成交。

`meta-playbook-hypothesis-v2` 已建立但保持 DRAFT；它新增中位题材核心加速候选分支与通道依赖执行分支，并明确比赛 8/20–8/27 报单展示缺口是来源完整性 blocker。以上仅为结构化研究数据和文档增量；生产代码仍沿用上一轮全仓 **758 passed / 0 failed / 0 skipped** 的稳定基线。

### P8.5-B 新增证据（2026-09-13）
- ExpertSource：22 → 29；PlaybookDefinition：13 → 16；PlaybookCase：29 → 31；CandidateSet：19 → 21；FULL CandidateSet：18 → 19；SelectionDecision：30 → 32。
- 华西股份：8/13官方买入、8/14官方卖出+9.94%，龙虎榜华安武汉百步亭11709980元与6.34元对应1847000股；候选全集仍有3只左右制度差异，故只标PARTIAL。
- 正裕工业：8/17完整二板10只，8/18官方买入一字3板，龙虎榜12864360元与11.80元对应1090200股，8/19公开割肉且历史次日-10%；作为 queue-dependent 明确失败样本。
- 新建 `queue-dependent-overnight-board-hypothesis-v2` 与 `meta-playbook-hypothesis-v3`，二者均保持 DRAFT / RETROSPECTIVE_REFERENCE。
- v3 research cutoff 固定为 2026-09-13；后续真实前瞻记录必须先预测、后揭晓，历史补录不得伪装为 SYSTEM_PREDICTION。

### P8.5-B 桂林/龙版补充（2026-09-13）
- 结构化状态更新为：ExpertSource 38、PlaybookDefinition 17、PlaybookCase 33、CandidateSet 23、FULL CandidateSet 21、SelectionDecision 34、Validation 2；FROZEN / AUDIT_COMPLETE 仍为 0。
- 桂林旅游：9/9四只3板全集，9/10竞价唯一涨停；9/10华安武汉百步亭买入、9/11同席位卖出与账户已验证截图闭合，写入 `OBSERVED_EXPERT`。
- 龙版传媒：9/3两只4板全集，9/4 09:35历史回放选择龙版；因三日龙虎榜不能确定专家精确买入日，只写 `HUMAN_RECONSTRUCTION`，不生成专家目标标签。
- 原始账户截图、网页和龙虎榜快照继续只保存在 `source_raw/`，Git 仅保存研究结论与方法。

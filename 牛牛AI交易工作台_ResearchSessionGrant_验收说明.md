# 牛牛 AI 交易工作台：Research Session Grant v1 验收说明

- 完成日期：2026-09-15
- 目标：在一次宿主明确授权内，允许 AI 连续提交有限本地研究，同时保持权限、范围、预算和有效期 fail-closed。
- 最终全仓：**925 tests / 0 failed / 0 skipped**，365.415 秒。

## 1. 已实现

Research Session Grant v1 冻结以下授权边界：

- 证券白名单、日期范围、K 线周期、raw/qfq、qualification；
- 允许的 `factor_id@version` 与研究 mode；
- 有效期 5 分钟～24 小时；
- 最多 1～20 个任务，同时活动任务最多 1～4；
- 单任务/总叶子研究、总 K 线评价量、总重采样量和 cooperative time budget。
## 2. 权限模型

- Grant 只能由宿主 CLI/桌面界面预览、确认、启用、撤销。
- 模型只获得 `get_research_session_grant` 和有效授权下的 `submit_granted_experiment`。
- 无宿主共享 JobQueue 的 Chat/CLI 环境只提供状态查询，不提供自动提交。
- v1 明确禁止 Shell、网络下载、代码写入、Campaign、Execution、Theory/Context、Broker 和真实交易。
- 所有授权任务仍进入同一个共享 JobQueue，不创建第二 worker。

## 3. 数据与执行

每个授权任务入队前都会单独调用 Approval Input Freeze，冻结实际输入字节；JobQueue guard 同时绑定 Grant receipt 与 approval freeze receipt。

submit / resume / run start / input check / cooperative checkpoint 都重新核验 Grant。撤销或过期后，运行任务在下一检查点以 `cancelled` 结束。
## 4. 防绕过规则

- 模型传入的 request_id 会被 ChatRuntime 用 turn + spec 的宿主确定性 UUID 重写。
- 同一 request_id 不得对应不同 spec。
- 失败/取消任务仍占用任务槽位和计算预算，不退款。
- 伪造 Grant receipt 直接提交 JobQueue 会被拒绝，因为 request_id 必须真实存在于当前 Grant reservation。
- 有 queued/running 任务的旧 Grant 不能被新 Grant 覆盖；终止后旧状态进入 `history/<grant_id>.json`。

## 5. 产品接入

- CLI：`niuniu-research-session-grant preview|authorize|revoke|status`。
- AI 研究助手新增“研究会话授权”窗口；打开/预览不授权，必须勾选完整确认后启用，撤销也需确认。
- System Health 新增 Research Session Grant 观察项，显示授权状态、到期、binding 和预算使用；无 Grant 不影响 Research Readiness。
## 6. 验收结果

- Research Session Grant 核心专项：**12/12 passed**。
- Session/Chat/Proposal/Campaign/Tracking/Alpha Factory/Approval Freeze/System Health 联合：**110/110 passed**。
- 桌面授权窗口 + 原 AI Chat/Research Chat：**8/8 passed**。
- 真实工作区只读烟测：`artifacts` **77006 → 77006**；读取状态没有创建 `_research_session_grants`。
- editable install 与 CLI help 通过。
- 完整仓库：**925 tests / 0 failed / 0 skipped**。

## 7. 仍未开放

Research Session Grant 不改变 P13 边界，也不提供实时行情源。正式 live MarketSnapshot Provider 与券商 B1/B2/B3 仍受外部通道约束；下一内部主线转向 Strict PIT 原始历史资料和 Watch 序贯/在线衰减统计。

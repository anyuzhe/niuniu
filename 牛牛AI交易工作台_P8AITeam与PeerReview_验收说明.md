# 牛牛 AI 交易工作台 P8：AI Team / Peer Review 验收说明

## 1. 阶段目标

P8 将“多 Agent”实现为有限、可审计的按需同行复核，而不是常驻多模型会议。

稳定角色固定为：Chief Researcher、Market Scanner、Skeptic / Risk Reviewer、Quant Researcher、Developer；角色与具体模型分离。Developer 在 P10 Dev Studio 前保持禁用。

本阶段同时正式启用 Git-first Markdown Memory：`agent_memory/README.md` 为固定入口，规则/角色/架构 Markdown 为 Agent Operating Memory 权威源；研究数值证据仍由原结构化归档负责。## 2. Peer Review 工作流

正式流程固定为两轮上限：

1. Reviewer 第一轮独立作答，彼此不可见，也看不到 Chief 的答案。
2. 只有第一轮结束后，Chief 才获得各 Reviewer 的已冻结文本并做综合。

第一轮不是“投票”。Chief 系统提示明确要求区分共同证据、分歧、相关错误和仍未解决的问题，多数意见不得自动解释成正确。

Peer Review spec 会冻结 question、共享 context、reviewer 列表和可选 parent_task_id；任务持久化保存 task_id、requester role、rounds、stop_reason、错误和最终综合。## 3. 权限边界

Reviewer 使用专用 `ReviewReadOnlyAPI`，只保留查询和核验证据的工具。`propose_*`、`record_*`、执行、批准、提交、同步、推广、创建等写入/动作工具均不进入 Reviewer schema。

Chief 的普通研究聊天可以 `preview_peer_review / propose_peer_review / get_peer_review / list_peer_reviews`，但 `propose_peer_review` 只保存 pending 请求；模型没有“启动 Reviewer”的工具。真正向模型发送 Peer Review 仍要求用户在 AI Team 面板显式勾选发送许可并点击启动。

Peer Review 不修改 Decision、Theme、Watch、Strategy Intent，不建立研究任务，不批准研究，也不具备交易能力。Developer 角色在 P10 前由配置合同强制关闭。## 4. Git-first Memory

每个正式 Agent 运行时读取 `agent_memory/README.md`、通用 rules/architecture、对应 role 文件以及经验/事故记录；每个文件都记录 SHA256，整包记录 memory_hash 和当前 Git commit。

如果当前仓库存在未提交的 `agent_memory/` 修改，正式 Agent 运行会拒绝使用，避免 HEAD 指向一个版本、实际读到另一份未审查规则。向量数据库不是权威记忆；未来即使增加检索索引，也只能是可重建缓存。

本阶段不会在运行中自动 `git pull` 修改正在执行的应用代码。部署/Dev Studio 会在任务开始前负责同步/隔离工作树；正式 Peer Review 只读取已经提交并可审计的本地 Agent Memory。## 5. 验收证据

专项/联合回归：AI Team、现有 Chat、MCP、Trading Cockpit、Strategy Intent、Decision Frame、Stock Dossier、Theme Matrix、Agenda、Watch 等 87 项全部通过。

最终全仓：**736 passed / 0 failed / 0 skipped，exit=0**。

隔离端到端目录：`artifacts/ai-team-p8-20260913/`。最终 receipt 验证：3 个 Reviewer 首轮互盲；Chief 第二轮看到全部独立输出；Reviewer 写工具为 0；Memory 干净且绑定 Git commit/hash；Developer 关闭；研究任务 0→0。

端到端使用确定性 Fake Provider，所以证明的是编排、隔离、权限和持久化，不证明任何具体模型的判断质量；真实模型连接继续复用并由原 ChatRuntime/HTTP/Codex 测试覆盖。
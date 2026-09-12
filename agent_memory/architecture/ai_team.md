# AI Team / Peer Review Architecture

P8 采用“单主助理负责 + 按需同行复核”，不建立常驻多人会议。

## 工作流

1. Chief 默认单独处理普通任务。
2. 仅当用户主动要求、风险较高、证据冲突或 Chief 认为需要挑战时创建 Peer Review Task。
3. 第一轮 Reviewer 只看同一冻结问题、同一上下文与各自角色记忆；互相看不到答案，也看不到 Chief 草稿。
4. 第一轮完成后，Chief 才收到各 Reviewer 的独立输出并做一次综合。
5. 不允许 Reviewer 互相无限追问；P8 固定最多两轮：独立评审 + Chief 综合。

## 审计要求

每个任务保存 task_id、parent_task_id、requester_role、reviewers、memory commit/hash、模型映射、冻结问题、轮次、输出、evidence、stop_reason。

Role 与 Model 分离；角色是稳定业务职责，模型只是可替换运行配置。Developer 角色在 P10 才获得隔离 worktree 开发能力。
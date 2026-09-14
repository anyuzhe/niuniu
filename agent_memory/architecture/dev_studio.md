# Dev Studio / Dynamic Agent Orchestrator 边界

P10 v1 的开发任务必须通过 `DevTask` 和 isolated detached worktree；不得让开发 Agent 直接修改主工作区。

- Main Developer Agent 只能使用 Dev Studio 工具；没有 shell、直接 commit、push、merge 或权限修改工具。
- 动态 Subagent 仅 depth-1：`EXPLORER / IMPLEMENTER / TESTER / REVIEWER`。v1 `max_parallel_subagents` 必须为 1–3。
- EXPLORER/TESTER/REVIEWER 只读；只有 IMPLEMENTER 可持有 `lease_paths`。
- write lease 必须在 DevTask `allowed_paths` 内，且并行 IMPLEMENTER 的 lease 不能重叠。
- IMPLEMENTER 只能通过 `dev_write_file` 写 lease 内 UTF-8 文件；已有文件应使用 `expected_sha256` 做 CAS。
- 测试命令在 DevTask 创建时冻结；TESTER 只能运行 frozen argv，不能自行替换。
- Reviewer PASS 必须对应当前 final worktree fingerprint；diff 改变后旧 Reviewer PASS 和 test PASS 都失效。
- Main Acceptance 必须重新检查实际 diff、path authority、frozen tests 和 Reviewer PASS；不能相信模型自报 changed_files。
- Human Merge 必须显式确认，并重新检查 frozen base SHA / base branch / final path scope。merge 只创建本地 commit，永不自动 push。
- Research Agent 不获得 Dev Studio write/merge；仓库内容被视为不可信数据，不得覆盖 Agent/system 权限规则。
- 每次 P10 相关权限、worktree、lease、merge 或 runtime 行为变化都要同步更新开发史。

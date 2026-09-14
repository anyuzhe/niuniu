# 牛牛 AI 交易工作台：P10 Dev Studio + Dynamic Agent Orchestrator 验收说明

- 阶段：P10 v1
- 日期：2026-09-15
- 基线：P9 `8562012`
- 最终全仓：**862 tests / 0 failed / 0 skipped**

## 1. 目标

把“主 Agent 拆任务、子 Agent 协作写代码”产品化，但继续保留宿主权限边界：开发 Agent 可以在隔离 worktree 内受控工作，不能直接污染 main、不能自行 commit/push、不能把模型自报结果当作验收证据。

## 2. DevTask 与隔离工作区

- DevTask 创建时冻结 request、acceptance criteria、allowed_paths、test_commands、max_parallel_subagents、base branch 和 base SHA。
- 每个 DevTask 创建 detached isolated git worktree；主工作区必须 clean。
- worktree 路径固定在仓库外专用目录；拒绝 symlink、path escape 与 `.git` 路径。
- 主分支或 base SHA 在 human merge 前变化时 fail-closed，不做隐式 rebase。

## 3. Dynamic Subagents

角色：`EXPLORER / IMPLEMENTER / TESTER / REVIEWER`。

- v1 仅 depth-1，不允许子 Agent 再递归派生。
- `max_parallel_subagents` 为1–3硬预算，不是目标数。
- EXPLORER/TESTER/REVIEWER 只读；IMPLEMENTER 才有 write lease。
- 多 IMPLEMENTER 的 lease 不能重叠；lease 必须位于 DevTask allowed_paths 内。
- 子 Agent 无 shell、commit、push、branch switch、git config 和 main workspace 写权限。

## 4. 写入、测试与 Reviewer

- IMPLEMENTER 通过受控 UTF-8 文件工具写入，并可用 SHA256 CAS 防止覆盖已变化文件。
- TESTER 只能执行 DevTask 创建时冻结的 argv 测试命令。
- Host 记录实际 test output / exit code / worktree fingerprint。
- Reviewer 独立只读，PASS 必须绑定当前 final diff fingerprint。
- final diff 一旦改变，旧 test PASS / Reviewer PASS 会变 stale，Main Agent 不能继续接受。

## 5. Main Acceptance 与 Human Merge

Main Acceptance 重新核对：

1. 实际 changed files 是否全部在 allowed_paths；
2. 实际变更是否全部被 IMPLEMENTER lease 覆盖；
3. frozen tests 是否通过且覆盖当前 final diff；
4. 独立 Reviewer 是否对当前 final diff PASS。

满足后只进入 `READY_FOR_HUMAN`。真正 merge 仍要求宿主 `--confirm`；merge 可创建 main 本地 commit，但不会 push。

## 6. 产品与权限

- 新增顶级“开发工作台”页面。
- 新增 `niuniu-dev-studio` CLI：create/status/list/run-main/run-ready/run-cycle/diff/merge/cleanup。
- CLI 没有 push action。
- Research Agent / AI Team 工具目录没有 Dev Studio write 或 merge 权限。
- Repository 文件、注释、测试和文档均作为不可信数据，不能变成新的系统权限指令。

## 7. 测试

专项覆盖：并行预算、非重叠 lease、Unicode git path、隔离 worktree、越权写入、真实 human merge、Main HEAD 变化阻断、Reviewer/test stale、动态完整循环停在 Human Gate、Subagent 无结果阻断、Research/Dev 权限隔离、CLI 无 push。

- P10 专项：**13/13 passed**
- Trading Desk 导航：**2/2 passed**
- editable install 与 `niuniu-dev-studio --help`：通过
- 完整仓库：**862 tests / 0 failed / 0 skipped**，298.180 秒

## 8. v1 边界

- Human Merge 后不自动 push。
- v1 最大动态深度为1，最大并行子 Agent 为3。
- Dev Studio 不替代人工定义业务需求/关键 acceptance criteria，也不扩大 Research Agent 权限。
- P11 System Health 负责下一步统一观察 DevTask/daemon/data/PIT/market/orchestrator 等运行健康度。

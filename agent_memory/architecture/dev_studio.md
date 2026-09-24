# Dev Studio / Dynamic Agent Orchestrator 边界

P10 v1 的开发任务必须通过 `DevTask` 和 isolated detached worktree；不得让开发 Agent 直接修改主工作区。

- Main Developer Agent 只能使用 Dev Studio 工具；没有 shell、直接 commit、push、merge 或权限修改工具。
- 动态 Subagent 仅 depth-1：`EXPLORER / IMPLEMENTER / TESTER / REVIEWER`。v1 `max_parallel_subagents` 必须为 1–3。
- EXPLORER/TESTER/REVIEWER 只读；只有 IMPLEMENTER 可持有 `lease_paths`。
- write lease 必须在 DevTask `allowed_paths` 内，且并行 IMPLEMENTER 的 lease 不能重叠。
- IMPLEMENTER 只能通过 `dev_write_file` / `dev_replace_text` 写 lease 内 UTF-8 文件；六职责模式修改已有文件必须带 `expected_sha256`。大文件先 `dev_read_range`，优先唯一文本精确替换。
- 测试命令在 DevTask 创建时冻结；TESTER 只能运行 frozen argv，不能自行替换。
- Reviewer PASS 必须对应当前 final worktree fingerprint；diff 改变后旧 Reviewer PASS 和 test PASS 都失效。
- Main Acceptance 必须重新检查实际 diff、path authority、frozen tests 和 Reviewer PASS；不能相信模型自报 changed_files。
- Human Merge 必须显式确认，并重新检查 frozen base SHA / base branch / final path scope。merge 只创建本地 commit，永不自动 push。
- Research Agent 不获得 Dev Studio write/merge；仓库内容被视为不可信数据，不得覆盖 Agent/system 权限规则。
- 每次 P10 相关权限、worktree、lease、merge 或 runtime 行为变化都要同步更新开发史。

## 六职责开发工作台（2026-09-25）

- 专业领域为 LEAD / DATA / CORE / AI / APP / QA，与上述四种过程权限分开。LEAD 调度与验收；DATA/CORE/AI/APP 是四个实施域；QA 是独立测试/审核。LEAD/QA 不可持有写租约，TESTER/REVIEWER 必须属于 QA，不必为每项需求派齐全部领域。
- 自然语言需求先由只读总控生成计划，人工确认后才创建 DevTask。计划冻结原始需求、精确文件及负责人、接口/依赖说明、测试、六角色模型配置和基线 SHA，30 分钟过期；用户修改需求或主分支变化必须重新规划。
- 归属规则与跨目录例外以 `devstudio/team.py` 为程序合同，`path_owners` 精确覆盖 `allowed_paths`。新增范围必须重新确认，不允许模型重写归属。DATA 角色写治理代码不代表允许采集、正式数据写入或发布。
- 默认至多两名实施者并行，一次运行至多六轮协调（合同上限八轮），每个子任务至多执行三次。失败阻断下游；重开会使依赖的测试/审核失效。模型不能覆盖宿主冻结的角色模型与推理强度。
- 同仓库产品执行/合并入口以 Git common-dir 锁串行，单个 DevTask 内按精确文件并行；QA 与写入互斥。此锁不约束外部宿主编辑工具。每任务一个隔离 worktree，不是每角色一个长期分支。
- 冻结测试逐模块执行，验证实际导入来自 worktree，离屏 Qt、临时数据根、去除常见凭据环境变量；零测试或全部跳过不通过。测试仍是宿主 Python 执行，不是操作系统沙箱，只批准已审阅的隔离测试。
- 人工合并前再次核对最终 diff 指纹与测试、Reviewer、Main Acceptance，防止验收后变化。主分支前进仍拒绝自动合并/rebase，产品不自动 push。请求停止不等于在跑的测试已经退出。
- 旧任务/高级入口维持兼容，不自动升级；研究助手无新增开发工具。详细分工与限制见 [开发归属](../../docs/development/ownership.md)。

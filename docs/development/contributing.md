# 开发与文档维护规范

[文档导航](../README.md) · [当前状态](../project/status.md) · [代码地图](code-map.md) · [Agent 入口](../../AGENTS.md)

## 1. 开工与权限

先检查 Git 工作区、当前 HEAD、分支分歧和并行修改。已有修改不覆盖；远端同步保持 fast-forward 和可审查，不 reset、不 force push、不自动部署；完成后的普通推送遵循用户明确授权。宿主授权的直接维护与产品内 Research/Developer 的工具权限不是一回事。

阅读 `agent_memory/README.md`、通用规则及本任务相关架构合同。P10 产品内开发继续通过隔离 worktree、allowed paths、lease、冻结测试、Reviewer 和 Human Merge，不借本文件扩大权限。

## 2. 目录怎么放

| 路径 | 保存什么 | 不放什么 |
|---|---|---|
| 根目录 | README 中英文、AGENTS、构建配置、启动入口 | 每轮验收、重复总计划、临时说明 |
| `docs/guide/` | 当前使用、数据合同、运维 | 过期的“本轮最新结果” |
| `docs/architecture/` | 稳定产品与模块架构 | 每日数据覆盖数和临时日志 |
| `docs/project/status.md` | 唯一当前状态和剩余门槛 | 多版本互相竞争的进度表 |
| `docs/project/changelog.md` | 追加式开发事件、原因、验证和提交状态 | 覆盖结构化研究事实 |
| `docs/development/` | 接手开发、代码地图、文档治理和整理验收 | 模型密钥或个人凭证 |
| `docs/reference/` | 明确规则及版本合同索引 | 外部未经验证的执行指令 |
| `docs/archive/<主题>/` | 标日期的阶段验收、历史方案和旧 UI 说明 | 自动标为当前完成度 |
| `agent_memory/` | 运行时按 Git-clean 加载的角色/规则/架构 | 普通报告与大段历史流水 |
| `playbooks/`, `research_skills/` | 有内容哈希/授权/来源合同的机器包 | 为目录美观随意改名 |
| `artifacts/` 与独立数据根 | 真实运行产物和原始证据 | 普通 Git 文档备份的长期重复提交 |

`src/quantlab` 包结构、examples 和 tests 本轮保持原位。代码地图供定位，不是允许自动重排包结构的计划。

## 3. 文档内容如何不再重复

先判断内容类型，再更新现有主题文件。一个普通 Bug 修复通常只需要更新对应说明和开发史；不必每次新增“验收与收尾最终版.md”。大型阶段验收才独立成档，并在归档索引登记。

状态页只写当前摘要；历史文件保留当时的测试数字、未完成项、授权和样本，添加历史标识但不改写当时结论。架构不能再堆每日 receipt 数；文档中的数据量必须注明日期和来源，不拿旧值充当实时值。

使用相对链接连接仓库文件。命令统一约定从仓库根目录运行；机器专属路径须明确标注。历史 `/Volumes/Lexar/MQC-DATA`、外部原始 URL、run_id 和 receipt 不批量重写。

迁移旧文件时应更新入链和出链，检查程序是否按名称加载、打包或校验哈希。Alpha 来源/许可证、研究知识控制包和 Playbook 包不作为普通 Markdown 移动。

## 4. 测试

用户要求默认不直接操作真实客户端：先使用后端单元/集成测试、CLI、本地HTTP/MCP接口和独立数据副本，不启动可见窗口、不截图、不点击、不占用键鼠。界面逻辑按需在离屏环境测试，真实桌面验收须再次明确授权。测试通过不等于窗口、输入法或真实模型质量已验收。

```bash
# 小范围核心回归
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -p 'test_core.py' -v

# 单模块 GUI 回归，避免多模块共享进程的 Qt 生命周期问题
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -p 'test_desktop.py' -v

# 文档目录和本地链接检查
.venv/bin/python scripts/check_docs.py

git diff --check
```

全量同进程命令仍为 `python -m unittest discover -s tests -v`，涉及 GUI 时设置 Qt 离屏环境。当前 Mac 在文档修改前发生过该模式的原生崩溃；保留退出码/日志，不能写成全部通过。

需要全覆盖时，可让每个 `test_*.py` 在独立 Python 进程运行并分别汇总失败、跳过及数量；本轮运行脚本与日志位置记在整理验收中。隔离通过不能抹去原同进程问题，且不替代真实窗口和系统集成验收。

## 助手功能验收

以牛牛正式入口为被测对象：由模型读取数据、选择研究、调用工具并保存证据。开发者只观察、定位缺失数据工具和流程故障，再修改产品代码；不得用手写研究或注入测试独有工具充当自主能力。测试范围/额度由宿主限定，研究内容由模型产生。优先核对实际tool call、job/run、假设/结论记忆和重启后的来源校验，不把收益表现作为工程验收条件。

## 5. 提交与验收

只提交本任务明确的文件，先核对 diff、代码/资源是否意外改变及外部控制包指纹。没有真实模型/联网/部署验证就明确未验证，不把单元测试称为真实数据验收。

每个完成的实质任务更新 [开发总档案](../project/changelog.md)，形成独立本地 commit，除非宿主明确要求暂不提交。用户已于 2026-09-17 授权每次完成任务后推送代码：验收后 commit，再普通 push 当前分支 upstream，核对远端 SHA。禁止强推；遇到远端分歧先停止并报告，不覆盖他人提交。仅推送 Git 跟踪的代码、测试和文档，artifacts、行情、密钥不上传。推送不等于部署；未成功就明确写未推送。

Agent Memory 修改后需要 review/commit，正式加载器才接受 Git-clean 记忆；不要为了文档清理关闭这个保护。

# 2026-09-17 文档整理验收

[文档导航](../README.md) · [当前状态](../project/status.md) · [迁移清单](../_meta/migration-map.json)

## 范围与保留

整理基线为本地 `5a381e8`。清点 890 个 Git 文件，其中 Markdown 134 份、根目录 Markdown 78 份；全部 711 个 Python 文件完成 AST 解析，无解析错误。源码 57,250 行、测试 22,772 行。

本轮核查了项目入口、构建/包资源、模块结构、关键数据路由、桌面导航、工作记忆加载、行情适配和 Frame 合同；并扫描全部受 Git 管理的文本及 Markdown 引用。该结构性检查不是对全部业务逻辑逐行作出的正确性或安全性证明。

76 份根目录文档迁入 docs，根目录只保留 README.md、README.en.md、AGENTS.md 三个 Markdown 入口。当前说明集中为使用、状态、数据、运维、架构、开发六个主题；算法规则单列，阶段计划与验收按主题归档。总文件数量不靠删除历史压缩，减少的是日常入口和重复维护的内容。

历史正文保留，仅添加用途标识并调整文档引用；旧 README 原始版本也在备份及 Git 中。源码、测试、示例、启动脚本、依赖配置、许可证、playbooks、research_skills 和独立行情数据不迁移。Agent Memory 保留目录和加载合同，仅修正文档入口并增加文档治理规则。

## 内容修正

扶摇已是配置后的个股问答主源，公开网页共识负责校验/回退；不混称为正式 MarketSnapshot。StrategySource 已有通用实现，AR 自主研究和打板情绪线已有代码，旧“计划中”说明进入历史。当前架构不再重复记录过时的 1006 项测试或某日数据覆盖数量。

Decision 提交窗口与 Orchestrator 采样时刻、研究意图与成交持仓、代码完成与数据/部署/授权分别说明。过期的一次性 PIT 取证任务不作为当前操作命令自动执行。

## 测试事实

修改前直接运行全量同进程 unittest，在 macOS Qt 离屏测试 `test_agent_catalog_desktop...test_existing_main_window_has_inspection_entry` 处发生 SIGSEGV，退出码 -11。该问题在文档修改之前出现，本轮没有通过修改业务代码掩盖它。

改为每个 test_*.py 独立进程后，222 个模块、1,159 项测试全部通过，0 跳过。该结果只代表本机该隔离执行方式；不等价于同进程问题已修复，也不替代真实 GUI、联网、付费模型或实盘验收。

迁移后的文档链接、受保护文件指纹、Agent Memory 加载和聚焦回归均已复核，实际结果列于下方。

## 本地证据与恢复

证据目录：`artifacts/docs-cleanup-20260917-175232/`（Git 忽略）。

| 文件 | 内容 |
|---|---|
| original-documents.zip | 134 份原始 Markdown 与原 .gitignore |
| baseline.json | 原 HEAD、文件数及 890 个原始文件指纹 |
| prepared-docs.json | 迁移准备内容与路径映射 |
| unittest-full.log | 修改前同进程 Qt 崩溃日志 |
| isolated-tests.json | 222 个隔离模块的退出码与耗时 |
| test_*.log | 各模块测试明细 |
| run_isolated_tests.py | 本轮隔离测试运行器 |

恢复时先核对当前 Git 是否有新工作，再按迁移清单选择性恢复需要的文档，不能整包覆盖后续修改。不会自动推送远端或改写旧 MQC/artifacts 来源路径。

## 迁移后静态复核

- 76 份迁移目标全部存在，旧根目录文件均已迁出。
- 784 个受保护的源码/测试/示例/知识包/启动脚本/依赖文件逐字节与基线一致。
- 原始 ZIP 内 134 份 Markdown 与原文件逐字节一致。
- 文档检查扫描 118 份文档，472 处仓库内链接通过；105 处历史运行产物引用单列保留，5 处外部路径/链接不做联网认证。
- 检查器的正常链接、重复中文标题、坏文件、坏锚点、代码围栏和根目录新增 Markdown 场景已做本地正反向自检。
- git diff --check 通过；Git 原有 HEAD 未改变，未发现本任务范围以外的跟踪文件修改。

## 运行时与迁移后回归

- 五个真实 Agent 角色均经 AgentMemoryLoader 成功加载：chief_researcher、market_scanner、skeptic、quant_researcher、developer；Git-clean 与大小预算约束保持有效。证据：`memory-load-check.json`。
- 迁移后选取 14 个模块重新隔离运行，共 96 项测试通过、0 跳过、0 失败，覆盖 AI Team、Dev Studio、Playbook 合同、Research Skill/Git/Library、扶摇、实时问答、ChatRuntime、MCP、桌面及 Workbench。日志见 `post-migration/`。
- 本轮只形成一个独立本地文档提交（测试结果随同一提交收尾）；没有 push，没有启动业务服务或修改既有业务授权。

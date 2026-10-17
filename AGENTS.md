# 牛牛开发入口

仓库：`/Volumes/Lexar/niuniu`。本文件只导航和约束本仓库开发，不给产品内 Research Agent 增加 Shell、写库或交易权限。

## 开工读取

先检查 Git 状态、当前分支及并行任务；不得覆盖他人的未提交工作。同步远端时只做可审查的 fast-forward，遇到分歧停止，禁止强制重置或强制推送；宿主开发任务完成后按下方约定普通推送。

依次阅读 [当前状态](docs/project/status.md)、[总体架构](docs/architecture/overview.md)、[开发规范](docs/development/contributing.md)、[Agent Memory](agent_memory/README.md)，再读相关 `rules/`、`architecture/` 和角色文件。查源码从 [代码地图](docs/development/code-map.md) 开始。

## 本次任务边界

只做用户明确授权的改动；不要顺手扩展无关功能或为通过测试放宽证据门槛。P10 产品内开发继续遵守隔离 worktree、path lease、冻结测试和 Human Merge Gate。宿主直接维护也必须保留 diff、复核并防止覆盖并行工作。

不搬动 `src/quantlab`、两个启动脚本、`agent_memory`、`playbooks`、`research_skills` 和第三方许可证。行情根为 `/Volumes/Lexar/niuniu-data`；旧 MQC 来源及历史 artifacts 不做批量路径替换。

## 默认测试方式

用户于 2026-09-17 明确要求不直接操作真实客户端做测试。默认使用命令行、后端接口、隔离数据与自动化回归；不得启动可见窗口、截图、点击或占用键鼠。必须检查界面逻辑时可使用明确离屏的测试环境，但不能冒充真实桌面验收。只有用户再次明确授权，才开展真实客户端操作。

## 内置 AI 助手已冻结（2026-10-17）

用户于 2026-10-17 决定：牛牛桌面版内置的 AI 助手（`src/quantlab/agent/`、`src/quantlab/devstudio/` 的模型通道、日常/混合/研究/提案四种模式、Alpha Factory、Research Session Grant、DSL 候选、同行复审、AI Team、Dev Studio、Scorecard）**整体冻结**：不新增功能、不再为其修 bug、不再以"让牛牛自主研究"作为验收标准。代码和测试原样保留，入口不删（保证既有测试与历史记录可复现）；若测试因环境变化失败，允许标记跳过，不投入修复。2026-09-17 的"研究必须由牛牛助手自行完成"条款自本日起作废。

研究改由外部 agent（Claude Code 等）在 `/Volumes/Lexar/niuniu-research-ext` 按该目录 `CLAUDE.md` 的规矩做：先预登记并登记哈希、股票池按规则生成、每次检验记试验账本、族内 Holm、样本外不动、否定结果也记录。quantlab 对研究只当库用（面板、账本、置换/Holm、事件库）。研究出肯定结论后，由代码侧在策略台实现并前向跟踪（A–D、E 系列的既有路径）。

牛牛桌面版继续维护的是产品部分：数据湾与采集、面板、策略台、前向跟踪、持仓、手机页、值班与收盘更新。

## 文档收尾

当前说明写入 `docs/guide/`、`docs/architecture/` 或 `docs/project/status.md`；只保留一个当前状态入口。阶段验收放 `docs/archive/<主题>/` 并标日期。不要在根目录新增“最新版、最终版、本轮收尾”等 Markdown，不为每个小改动单独造一份说明。

每项完成的实质改动同步追加 [开发总档案](docs/project/changelog.md)，记录测试的真实结果、限制和提交状态。遵守 [文档治理规则](agent_memory/rules/documentation.md)。

用户于 2026-09-17 明确要求每次任务执行完成后都推送代码。宿主开发任务验收后形成独立 Git commit，并普通 push 当前分支配置的 upstream（当前 main → origin/main）；成功后核对远端 SHA。没有实质修改时不创建空提交，但应检查已有待推送提交。禁止 force push；远端分歧、权限或网络失败须如实报告，不能写成已推送。这不授权自动部署、真实交易或改变产品内 P10 的 Human Merge Gate。

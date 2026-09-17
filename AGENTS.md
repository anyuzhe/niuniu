# 牛牛开发入口

仓库：`/Volumes/Lexar/niuniu`。本文件只导航和约束本仓库开发，不给产品内 Research Agent 增加 Shell、写库或交易权限。

## 开工读取

先检查 Git 状态、当前分支及并行任务；不得覆盖他人的未提交工作。同步远端时只做可审查的 fast-forward，遇到分歧停止，禁止强制重置或自动推送。

依次阅读 [当前状态](docs/project/status.md)、[总体架构](docs/architecture/overview.md)、[开发规范](docs/development/contributing.md)、[Agent Memory](agent_memory/README.md)，再读相关 `rules/`、`architecture/` 和角色文件。查源码从 [代码地图](docs/development/code-map.md) 开始。

## 本次任务边界

只做用户明确授权的改动；不要顺手扩展无关功能或为通过测试放宽证据门槛。P10 产品内开发继续遵守隔离 worktree、path lease、冻结测试和 Human Merge Gate。宿主直接维护也必须保留 diff、复核并防止覆盖并行工作。

不搬动 `src/quantlab`、两个启动脚本、`agent_memory`、`playbooks`、`research_skills` 和第三方许可证。行情根为 `/Volumes/Lexar/niuniu-data`；旧 MQC 来源及历史 artifacts 不做批量路径替换。

## 文档收尾

当前说明写入 `docs/guide/`、`docs/architecture/` 或 `docs/project/status.md`；只保留一个当前状态入口。阶段验收放 `docs/archive/<主题>/` 并标日期。不要在根目录新增“最新版、最终版、本轮收尾”等 Markdown，不为每个小改动单独造一份说明。

每项完成的实质改动同步追加 [开发总档案](docs/project/changelog.md)，记录测试的真实结果、限制和提交状态。遵守 [文档治理规则](agent_memory/rules/documentation.md)。

形成独立本地 Git commit，除非用户明确要求暂不提交；不自动 push。不得把已完成本地修改写成已部署或已推送。

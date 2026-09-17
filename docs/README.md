# 牛牛文档导航

[返回项目首页](../README.md)

日常使用和开发先看下面的当前文档，不必翻阅几十份阶段验收。历史原文按主题完整保留；重复的项目定位、操作步骤、状态和开发规则已归并到各自唯一入口。

## 当前文档

| 顺序 | 文档 | 解决的问题 |
|---|---|---|
| 1 | [使用指南](guide/user-guide.md) | 如何启动、各页面做什么、如何走通一次研究 |
| 2 | [当前状态与后续路线](project/status.md) | 代码完成度、资料/部署/授权门槛和剩余工作 |
| 3 | [数据与证据说明](guide/data-and-evidence.md) | 数据根、复权、PIT、问答报价与正式快照 |
| 4 | [运行与运维](guide/operations.md) | CLI/MCP、跟踪、日内编排、证据调度与故障定位 |
| 5 | [总体架构](architecture/overview.md) | 产品模块、数据流、研究/执行/权限边界 |
| 6 | [开发与文档规范](development/contributing.md) | Agent 接手、目录规范、验证与本地提交 |

源码定位使用 [代码地图](development/code-map.md)。开发事件追加在 [开发总档案](project/changelog.md)，具体规则见 [规则参考](reference/README.md)，阶段事实见 [历史归档索引](archive/README.md)。

## 三类内容的权威边界

**当前指南**随代码更新，不重复堆历史流水；**历史归档**保留当时结论与限制，不能拿旧“下一步”充当当前待办；**结构化证据**决定数值、时点、Decision、成交与资格，Markdown 不覆盖它。

机器读取的 [Agent Memory](../agent_memory/README.md)、[Playbooks](../playbooks/README.md)、[Research Skills](../research_skills/README.md) 保持原位，不随普通文档迁移。

## 找原来的文件

根目录原有文档的 [旧名→新路径清单](./_meta/migration-map.json) 包含原始 SHA256；历史归档索引也保留原主题名称。本轮范围、备份、测试和限制见 [文档整理记录](development/documentation-cleanup.md)。

后续请优先更新现有主题文档，不再在根目录新增“最终版/最新版/本轮收尾.md”。

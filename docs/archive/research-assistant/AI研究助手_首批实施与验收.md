# 牛牛 AI 研究助手：首批实施与验收

> 历史归档（整理于 2026-09-17）：保留原阶段记录；正文中的“当前、下一步、待完成”和测试/数据数字属于原记录时点。使用与当前进度以 [文档导航](../../README.md)、[当前状态](../../project/status.md) 为准。命令仍从仓库根目录执行。

日期：2026-09-11。项目：`/Volumes/Lexar/niuniu`。基线：`c6cb2fd`。

## 结论与边界

已完成整体改造方案，并实际落地统一只读研究接口、JSON CLI 与原生查询入口。**尚未接入聊天模型，也没有实现提案审批、研究自动提交、持久研究记忆或因子追踪调度。**

本轮涉及提案工具的源码写入被远程工具执行层拦截，未给出具体原因。没有换通道重放该操作，转为独立的只读实现。被拦截的 `agent/contracts.py` 没有落盘或被导入；不能把原先规划的执行闭环记为完成。

## 已落地代码

| 文件 | 实际能力 |
|---|---|
| `src/quantlab/agent/__init__.py` | 新助手层包入口 |
| `src/quantlab/agent/catalog.py` | 六项只读工具、JSON Schema、类型/分页/UUID校验、缩减提示、实际引用 |
| `src/quantlab/agent/__main__.py` | 机器可调用 JSON CLI；失败返回退出码 2 |
| `src/quantlab/desktop/agent_catalog.py` | 中文只读查询表单、工具合同、实际实验引用与打开原结果 |
| `src/quantlab/desktop/app.py` | 顶栏新增“AI 研究接口”，不改变既有导航索引 |
| `tests/test_agent_catalog.py` | 六项后端/CLI边界测试 |
| `tests/test_agent_catalog_desktop.py` | 两项 Qt 功能与主窗口接线测试 |

工具：`get_capabilities`、`search_factors`、`describe_factor`、`list_experiments`、`get_experiment`、`get_job`。

能力接口明确返回只读、模型未连接、执行工具不可用。它不创建任务、不写行情、不启动新研究。只检索配置的单一产物目录，不自动跨工作空间递归汇总。

## 验证结果

- 新增定向测试：**8 项通过**，`2.633s`，无失败、无跳过。
- 全仓回归：**383 项通过**，`112.836s`，无失败、无跳过。
- Qt 测试使用隔离 offscreen 环境和真实查询接口，不能当成全部原生人工点击验收。
- 使用既有真实行情研究归档完成五项实际只读查询；不是新回测，也不是连接真实模型的测试。
- 核对目标实验 `experiment.json`、`report.md` 查询前后 SHA256，一致。

真实归档工作空间：`artifacts/completion-round-20260910/real-validation/runs`。

目标实验：`e81c4890-25d2-406c-9145-4e9dee9c1cea`。

证据目录：`artifacts/agent-foundation-20260911/`，包括 `baseline.json`、`targeted-tests.log`、`full-tests.log`、`real-archive-query.json`。

## 使用入口

重新启动项目后，点击顶栏 **AI 研究接口**。可查询因子、实验与任务，并通过真实实验引用打开原有结果页面。当前面板不是聊天机器人，没有伪装成模型回答。

```bash
cd /Volumes/Lexar/niuniu
.venv/bin/python -m quantlab.agent --output artifacts --schemas
.venv/bin/python -m quantlab.agent --output artifacts --call get_capabilities
.venv/bin/python -m quantlab.agent --output artifacts --call search_factors \
  --arguments '{"query":"MOMENTUM","offset":0,"limit":5}'
```

这些调用是可复用的机器入口，不是已经部署的 MCP 服务。外部智能体可通过其获准的本地执行入口使用 CLI，今后再加正式协议适配。

## 后续顺序

先补精确研究提案、预算、用户批准、幂等 job_id 与共享队列，再接模型协议和聊天循环；之后依次做结构化研究记忆、有限研究包、因子追踪、候选因子生成。完整合同见 `docs/archive/plans/AI研究工作台_改造方案.md`。

## 未改变与注意事项

没有新增依赖、改动因子公式/回测口径、提交或取消真实研究任务，也未读取模型密钥或发出模型请求。原始行情及旧实验未覆盖；原有窗口未被强制关闭。

新增源码会改变当前全仓运行指纹；旧归档的严格源码一致复算仍须使用其对应源码版本。只读查看旧结果不受此限制。当前运行指纹为 `4677894b3e045614c66dba776005beff9de8c19b449736c5a40fea2d587b7a30`。

本轮改动保留为未提交工作区，没有自动 Git 提交或推送。不要把前一轮的 `c6cb2fd` 当成已经包含本轮新增代码的版本。

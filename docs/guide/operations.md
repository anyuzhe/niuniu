# 运行与运维

[文档导航](../README.md) · [使用指南](user-guide.md) · [数据与证据](data-and-evidence.md)

所有命令默认从仓库根目录执行。示例中的 `/path/to/niuniu-data` 要替换成实际数据根。本文是操作说明，整理文档本身不会启动服务、下载、加载 LaunchAgent 或建立授权。

## 1. 各入口的职责

| 入口 | 用途 |
|---|---|
| `quantlab desktop` | 完整 PyQt 桌面工作台 |
| `python -m quantlab.agent.chat_cli --gui` | AI 对话助手 |
| `quantlab serve` | 本地 Web 工作台，同源移动只读页面 |
| `niuniu-mcp` | 牛牛产品的标准研究 MCP |
| `niuniu-tracking-daemon` | 只执行已有宿主跟踪授权的守护进程 |
| `niuniu-daily-orchestrator` | 单交易日冻结计划的 PREP/AUCTION/R1/R2/R3 编排 |
| `niuniu-evidence-scheduler` | 公开证据、研究派生和已授权研究任务的调度工具 |

完整 CLI 清单从 [代码地图](../development/code-map.md) 的入口表查询；参数以对应 `--help` 和 `pyproject.toml` 为准，不从过期验收命令猜测。

## 2. 本地 MCP 和 Web

```bash
niuniu-mcp --output ./artifacts --data-root /path/to/niuniu-data
```

默认 stdio。确需 HTTP 时可以显式使用回环地址：

```bash
niuniu-mcp --output ./artifacts --data-root /path/to/niuniu-data \
  --transport streamable-http --host 127.0.0.1 --port 8766
```

程序拒绝非回环监听。跨机访问需独立配置 SSH 隧道或受认证反向代理，不能靠把监听改成公网地址绕过边界。8766 是该程序默认值，**不代表本机该端口空闲**；和其他 Agent 服务冲突时，应检查现有配置并选择明确端口，不终止未知进程。

```bash
quantlab serve --data-root /path/to/niuniu-data --output ./artifacts
quantlab serve --help
```

Mobile/Bot 复用同一工作空间，不另建 Decision、持仓或记忆数据库。MCP 协议也不自动扩大模型的批准、执行、下载和交易权限。

## 3. 跟踪、日内编排和证据调度是三条链

**Watch 跟踪**：守护进程只消费已保存的跟踪授权，和桌面共享 JobQueue 的 worker 边界；退出界面不等于授权自动取消。创建/撤销授权、通知策略和基准换版分别处理。

```bash
niuniu-tracking-daemon --output ./artifacts --data-root /path/to/niuniu-data
quantlab tracking-launchd-write --help
```

生成 plist 不等于已经加载，也不等于创建授权。

**Daily Orchestrator**：宿主先为单个交易日建立计划并冻结定义、交易日等输入，再 tick/run。显式联网选项与既有快照模式不同；错过窗口不回填。空 PREP CandidateSet 可合法进入 NO_TRADE 终态。

```bash
niuniu-daily-orchestrator --help
niuniu-market-provider-status --help
```

**AR 公开证据与自主研究**：有独立收盘/盘中调度及研究预算。AR 代码完成不证明 LaunchAgent 已安装、机器未休眠或今日采集已成功。盘中快照、夜间研究和模拟盘授权不可互相代替。

```bash
niuniu-evidence-scheduler --help
niuniu-auto-research --help
niuniu-premarket-brief --help
```

本轮不复用或重新执行历史文档中针对某一交易日的一次性授权。2026-09-17 PIT 取证窗口属于该日期的历史运行记录，不是现在应重复安装的定时任务。

## 4. 扶摇与模型凭证

扶摇读取 `HITHINK_FINANCE_API_KEY` 或 macOS 钥匙串服务 `cn.niuniu.fuyao.api-key`；代码侧只暴露白名单聚合工具。不要把密钥粘贴到 README、Git、报告或模型消息里。

启用扶摇后的能力与回退行为见 [数据与证据](data-and-evidence.md) 和 [专项验收](../archive/integrations/牛牛AI交易助手_扶摇MCP接入与验收说明.md)。本轮没有读取、导出或修改任何凭证，也没有发起付费模型问答。

模型配置和已保存会话属于实际工作空间，不能通过移动文档替它们“升级”模型。外部 Research Skill 的 Git-clean 授权表和包指纹同样不可随意改变。

## 5. 状态、失败与恢复

先检查 System Health 的 Runtime / Research Readiness 两个轴，再读本次任务日志与证据。重点区分：程序在线但无合格数据、任务失败但历史产物仍完整、资料已下载但尚未确认发布时点、代码已实现但真实授权/部署未完成。

恢复使用原任务/计划的既有恢复入口，避免复制状态库或另造新的正式预测。重新查询和重试不应覆盖旧 receipt、Decision、未选候选和失败样本。

历史运行清单包含机器专属路径与状态，完整保存在 [AR 规划与验收原文](../archive/autonomous-research/牛牛AI交易助手_自主研究与打板情绪研究_规划与进度.md)。其中的“待安装”“已启用”属于各自记录时点，当前状态需在宿主实际查询，本轮未重新部署或验证那些后台服务。

## 6. 测试与文档维护

本项目测试使用 unittest。当前 Mac 全量同进程离屏测试出现过 Qt 原生崩溃；应保留日志，并可逐测试模块在独立进程中定位，而不是修改业务规则使其通过。操作方法和本轮结果入口见 [开发规范](../development/contributing.md) 与 [文档整理记录](../development/documentation-cleanup.md)。

日常维护只更新对应主题文档和开发史；复杂验收才另存 dated archive。历史产物路径、外部数据根和机器可读知识包不属于普通文档清理对象。

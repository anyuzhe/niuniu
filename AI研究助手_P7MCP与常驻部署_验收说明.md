# 牛牛第8步：标准 MCP 与常驻跟踪验收

日期：2026-09-12

## 交付范围

本轮完成原八步路线的第8步工程主体：

- 使用官方 MCP Python SDK v2 适配牛牛现有研究工具；
- 支持本地 `stdio` 与回环 `Streamable HTTP`；
- MCP 不增加任何下载、批准、研究执行、DSL 注册或跟踪授权权限；
- 新增独立跟踪守护进程，使牛牛桌面退出后仍可处理已经由宿主授权的跟踪计划；
- 新增守护心跳、单进程锁、桌面让位、研究 worker 冲突让位及 launchd 配置生成；
- launchd 只生成配置，不自动加载，也不会创建研究授权。

## MCP 边界

外部智能体看到的工具集合来自现有 `MarketDataResearchAPI.schemas()`，当前为 31 个工具。协议适配层不重新实现业务逻辑，参数先经过 MCP/Pydantic 校验，再经过牛牛原工具合同复核。

禁止通过 MCP 暴露的宿主动作包括：市场数据下载、提案批准、研究执行/恢复、DSL 候选注册、跟踪授权修改和任意 Shell。研究记忆与提案保存仍按既有模型工具边界允许，但不等于研究批准或 Alpha 认证。

Streamable HTTP 默认且强制只监听 `127.0.0.1` / `::1` / `localhost`。跨机器使用推荐 SSH 端口转发或另设有认证的反向代理；程序本身拒绝 `0.0.0.0` 等非回环绑定。

## 常驻调度边界

守护进程不会创建授权，只读取 `_tracking_control` 中已经由宿主明确保存的授权。它复用 `TrackingScheduler`、`JobQueue`、数据完整性检查、下载预算和原队列幂等规则。

- 同一工作空间只允许一个守护进程；
- 原 `JobQueue` 的 `worker.lock` 仍保证一个研究 worker；
- 桌面手动研究占用 worker 时，守护进程只跳过本轮，不修改授权状态；
- 守护进程运行时，桌面定时跟踪让位，但手动研究在 worker 空闲时仍可启动；
- 心跳记录 `active/stale/status`、最后检查和网络请求数；
- 守护进程退出不取消已经完成的研究，也不会自动重试失败任务；原恢复规则保持不变。

## 启动方式

安装可选依赖：

```bash
python -m pip install -e ".[mcp]"
```
本地 MCP：

```bash
niuniu-mcp --output /path/to/artifacts --data-root /path/to/data
```

回环 HTTP：

```bash
niuniu-mcp --output /path/to/artifacts --data-root /path/to/data \
  --transport streamable-http --host 127.0.0.1 --port 8766
```

远程机器推荐先建立 SSH 隧道：

```bash
ssh -N -L 8766:127.0.0.1:8766 user@research-host
```

守护进程：

```bash
niuniu-tracking-daemon --output /path/to/artifacts --data-root /path/to/data --poll-seconds 60
```

生成 macOS LaunchAgent（不自动加载）：

```bash
quantlab tracking-launchd-write --output /path/to/artifacts --data-root /path/to/data \
  --path ~/Library/LaunchAgents/com.niuniu.quantlab.tracking.plist
```

## 实际验收

### MCP

- 官方 MCP 客户端内存握手通过；
- `stdio` 子进程握手和参数拒绝通过；
- Streamable HTTP 在当前最终源码上实际连接成功；
- 协商协议版本：`2026-07-28`；
- 暴露工具：31 个；
- 越权工具暴露：0 个；
- HTTP 非回环绑定会在启动前拒绝。

### 常驻跟踪

隔离工作空间实际抓取 Baostock 2026-09-09 至 2026-09-12 的三股日线与日历，建立 2026-09-10 基准并由独立 `tracking-daemon` 子进程处理已授权刷新：

- 自动选择最后已发布交易日 2026-09-11；
- 原队列完成 1 个研究任务；
- 跟踪快照由 1 份变为 2 份；
- 控制状态为 `synchronized`，授权仍按原 60 分钟时钟有效，没有伪造下一次调度时间；
- 守护本轮网络请求为 0（使用已下载完整批次）；
- 数据源文件前后哈希一致；
- 原基准冻结复算 `numerically_matched`。

另行验证了无授权守护生命周期、SIGTERM 正常停止、心跳回执、单守护锁、worker 冲突让位及 launchd plist 的 `plutil -lint`。

### 回归

最终业务源码全仓测试：**649 项通过，0 失败**。最终源码运行指纹：`a77622b9b64db1deb7a9f5926f7e4c984600f3c87f79204ab3a6c4012d44bbd8`。

证据目录：`artifacts/step8-finish-20260912/`，其中：

- `full-tests.log` / `full-tests.exit`：全仓回归；
- `mcp-http-acceptance.json`：最终源码 HTTP MCP 验收；
- `daemon-real-acceptance.json`：真实 Baostock + 独立守护进程验收；
- `com.niuniu.quantlab.tracking.plist`：未加载的 launchd 示例配置。

## 仍然存在的边界

第8步完成不等于把牛牛变成公网 SaaS。HTTP 默认拒绝公网绑定；远程访问需 SSH 隧道或另行配置认证网关。launchd 配置不会自动加载，需要宿主明确执行系统加载动作。

严格 PIT、真实每日总市值、官方历史涨跌停和特殊上市规则仍是数据资料缺口。MCP、常驻调度和自动下载都不能替代这些数据认证，也不能证明任何因子未来存在 Alpha。

# 牛牛 AI 交易工作台：P12 移动端 / 机器人验收说明

- 阶段：P12 v1
- 日期：2026-09-15
- 开发基线：P11 `c4c772d`
- 最终全仓：**882 tests / 0 failed / 0 skipped**
- 全仓耗时：305.026 秒

## 1. 阶段目标

P12 不建立“手机版牛牛”的第二套后端，而是在现有权威状态之上增加轻客户端：手机 Web 与机器人都直接读取同一 Decision Ledger、Stock Dossier、Theme、Paper Lifecycle、System Health 与既有 MCP/API。

核心约束：**手机端没有第二份记忆、第二份 Decision、第二份持仓，也没有独立交易状态机。**

## 2. Mobile Brief

新增 `MobileBriefService`，格式为 `niuniu-mobile-brief-v1`。

首屏只聚合轻量状态：交易日、最新 Frame、Strategy Intent 计数、候选、计划/持仓、主线、风险、Paper Lifecycle 与 System Health。它直接读取既有存储，并复用 Trading Cockpit 的动作/主题优先级常量，不复制业务状态。

股票搜索按需调用现有 Stock Dossier，保留 Decision、实验、Watch、Playbook 证据；全历史实验关联在大工作区可能较慢，因此不进入首屏自动加载。
## 3. 手机 Web

现有 loopback Workbench 新增：

- `/mobile`：独立手机布局，只读展示今天、候选/计划、主线/风险和股票档案。
- `/api/mobile/brief`：轻量当天简报。
- `/api/mobile/stock`：Stock Dossier 紧凑视图。
- `/api/mobile/decisions`：同一 Decision Ledger timeline。
- `/api/mobile/system-health`：同一 P11 System Health。

主 Workbench 增加“手机简报”入口。移动页面没有 POST 写接口，也没有买入/卖出/修改 Decision 按钮。

Workbench 继续只绑定 `127.0.0.1`。P12 不因为“手机访问”而开放无认证 LAN/公网监听；跨设备访问需使用安全隧道或有认证的反向代理。

## 4. 机器人 / MCP / CLI

- MCP 增加 `get_mobile_brief` 只读工具。
- `get_capabilities` 明确 `mobile_brief_write_model=false`、`mobile_has_independent_state=false`。
- 新增 `niuniu-mobile-brief` CLI，供脚本/机器人读取同一简报。
- 无 mobile write、Decision write、Paper execution 或 real trade 工具。

## 5. 真实工作区烟测

真实 `/Volumes/Lexar/niuniu/artifacts`：

- `niuniu-mobile-brief` 读取前后 artifacts 文件数 **77006 → 77006**。
- 首屏 Direct brief 约2.5KB；MCP 空股票简报约2.8KB。
- 优化后 Direct + MCP 连续两次聚合总计约1.02秒，首屏单次约0.5秒级。
- MCP 查询 `sh.600000` 带完整紧凑 Stock Dossier 约12KB，未触发24KB工具结果限制。
- 真实 HTTP `/mobile` 与 `/api/mobile/brief` 可读，读取前后 artifacts 仍 **77006 → 77006**。
- 股票档案中的全历史实验关联在当前大工作区约7–8秒，因此只按需加载，不进入手机首屏。

## 6. 测试与边界

P12 新增测试覆盖：

- 同一 Decision ID 在主账本、Mobile Brief、Stock Dossier、HTTP、MCP 中保持一致。
- 读取前后文件集合不变，`_mobile` / `mobile.sqlite3` 不存在。
- Mobile HTTP 恶意 Host 被403拒绝；不存在 mobile POST 写端点。
- 空工作区可只读打开，不自动创建手机端状态。
- 旧 Stock Dossier、Trading Cockpit、Workbench 与 MCP 联合回归继续通过。

- P12 新增专项：**6/6 passed**。
- P12 相关联合回归：**18/18 passed**。
- 完整仓库：**882 tests / 0 failed / 0 skipped**。

P12 v1 到此完成。下一阶段 P13 涉及真实券商/真实资金，继续遵守原路线：必须单独评审，不因 Paper 或 Mobile 已完成而自动开启实盘能力。
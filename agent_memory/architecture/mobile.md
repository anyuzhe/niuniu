# Mobile / Bot 架构边界

P12 是现有牛牛状态之上的轻客户端，不是第二套后端。

- 手机 Web、CLI、机器人/MCP 必须读取同一 Decision Ledger、Stock Dossier、Theme、Paper Lifecycle、System Health 与既有研究证据。
- 禁止创建 `_mobile`、mobile SQLite、独立持仓、独立 Decision、独立 Agent Memory 或第二套 Strategy Intent。
- `MobileBriefService` 只做紧凑只读聚合；`mobile_state_store=None`、`bot_state_store=None`。
- 手机首屏只加载轻量状态；Stock Dossier 的全历史实验关联只按需加载，不复制为手机缓存库。
- Workbench `/mobile` 继续服从原 loopback-only Host / same-origin 边界，没有 mobile POST 写接口。
- 跨设备访问不得为了方便直接开放无认证公网/LAN监听；使用安全隧道或有认证反向代理。
- MCP `get_mobile_brief` 与 CLI `niuniu-mobile-brief` 都是只读；机器人无 Decision/Paper/Real Trade 写权限。
- P13 真实券商与真实资金必须单独评审，P12 不得顺带打开任何实盘能力。

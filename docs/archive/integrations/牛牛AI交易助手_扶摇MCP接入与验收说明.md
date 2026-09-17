# 牛牛 AI 交易助手：扶摇 MCP 接入与验收说明

> 历史归档（整理于 2026-09-17）：保留原阶段记录；正文中的“当前、下一步、待完成”和测试/数据数字属于原记录时点。使用与当前进度以 [文档导航](../../README.md)、[当前状态](../../project/status.md) 为准。命令仍从仓库根目录执行。

日期：2026-09-17
状态：已实现并完成模拟、真实只读调用与用户问答行情链路验证

## 本次实现

扶摇以宿主侧只读数据适配器接入，模型不能直接访问远端全部 MCP 工具，也不能接触 API Key。当前只开放五个聚合工具：

- `resolve_fuyao_security`：股票、指数和板块名称消歧；
- `get_fuyao_stock_context`：当前快照、近期日 K 与成交量摘要；
- `get_fuyao_sector_context`：概念/行业/特色指数匹配、当前成分股核验与板块快照；
- `get_fuyao_short_term_context`：热度、异动、竞价、涨跌停池、连板天梯和龙虎榜摘要；
- `get_fuyao_fundamental_context`：当前估值与指定报告期财务指标。

实时个股问答使用以下顺序：

1. 扶摇 MCP 作为主行情源；
2. 原有腾讯、东方财富、新浪公开网页两源共识作为交叉校验；
3. 扶摇不可用时保留原公开网页共识回退；
4. 两侧价格冲突时返回 `PARTIAL` 和 `consensus_issues`，不静默选择有利数值。

扶摇只用于当前问答和回顾性研究上下文，不写入正式 `MarketSnapshotStore`，不升级为 Strict PIT、官方 `MarketRules`、交易所行情 SLA、交易信号、`Decision` 或订单。

## 安全与证据边界

- 凭证只从 `HITHINK_FINANCE_API_KEY` 或 macOS 钥匙串服务 `cn.niuniu.fuyao.api-key` 读取；仓库不保存密钥。
- 网络地址固定为 `https://fuyao.aicubes.cn`，只允许 `/mcp/meta`、`/mcp/a-share`、`/mcp/a-share-index`。
- 远端工具有代码白名单，模型无法提交任意工具名。
- 每次结果保留 `request_id`、`data.timestamp`（服务端声明的数据就绪/最新上游有效时间）、宿主采集时间、工具名和 `source_hash`。
- 响应体上限为 2MB，单个模型工具结果上限为 24KB；HTTP 429 / 业务码 4001 不立即重试。

## Bug 修改记录

### FUYAO-001：远端能力面过宽

- 问题：若把扶摇全部远端工具直接提供给模型，查询范围和上下文体积难以控制。
- 修改：增加宿主白名单客户端和五个聚合工具；远端原始工具不进入模型 Schema。
- 验证：`ChatRuntime` 能看到五个聚合工具，看不到 `get_a_share_prices_snapshot` 等原始工具。

### FUYAO-002：新增外层 API 包装器遮住原宿主属性

- 问题：首次接线后，既有测试通过 `runtime.api.proposals` 访问提案服务时报 `AttributeError`。
- 修改：`FuyaoResearchAPI.__getattr__` 透明转发原 API 链属性。
- 验证：原“提案具有宿主 ID 且不执行”回归测试恢复通过。

### FUYAO-003：行情来源提示仍写成“仅公开网页”

- 问题：接入扶摇后，实时行情失败提示与限制说明仍沿用旧文案。
- 修改：改为“宿主行情源”和“扶摇及公开网页交叉校验行情”，保持真实来源语义。
- 验证：现有实时问答测试通过，实际返回 provider 为 `fuyao-with-public-cross-validation-v1`。

### FUYAO-004：会话重试边界需收紧

- 问题：失效 MCP Session 可以安全重建，但鉴权、限流和业务错误不应自动重试。
- 修改：只对 HTTP 400/404 清理会话并重建一次；HTTP 429 和业务码 4001直接返回限流错误。
- 验证：协议握手、Session Header、白名单和业务信封测试通过。

## 验收结果

自动化验证：

- `tests.test_fuyao_integration`：协议、凭证优先级、五个聚合工具、运行时接线、行情转换、冲突标记和回退；
- `tests.test_live_stock_quote`：原个股问答自动行情；
- `tests.test_agent_chat`：原对话、预算、提案、脱敏；
- `tests.test_research_skill_library`：原交易经验/研究资料只读工具面。

2026-09-17 真实只读验证：

- “宏景科技”成功解析为 `301396.SZ`；
- 快照、30 日历史、估值、财务指标、竞价、异动、涨跌停情绪、龙虎榜接口成功；
- 板块匹配并逐一核验当前成分：智慧城市、人工智能、东数西算（算力）、数字经济、算力租赁；
- 用户问答行情链路返回 `FULL`，扶摇与腾讯/东方财富/新浪三源校验一致。

实际收盘行情回读：宏景科技 `174.90` 元、涨幅约 `2.54%`；成交量 `14,841,823` 股、成交额 `2,608,405,000` 元。该数值仅用于确认数据链路和来源一致性，不是交易建议。

测试命令：

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_fuyao_integration \
  tests.test_live_stock_quote \
  tests.test_agent_chat \
  tests.test_research_skill_library -q
```

结果：28 项全部通过；`py_compile` 与 `git diff --check` 通过；仓库扫描未发现用户提供的 API Key。真实测试只调用宿主只读数据链路，没有额外发起付费模型问答。

## 部署与 Git 记录

- API Key 已写入当前 Mac 用户的系统钥匙串，service 为 `cn.niuniu.fuyao.api-key`；代码和文档不保存明文。
- 应用重启后由 `ChatRuntime` 自动读取钥匙串并注册五个聚合工具；未配置凭证时保持原公开网页共识行情，不暴露不可用工具。
- 本次代码、测试、专项说明、用户端 Bug 记录和项目开发总档案使用同一 Git 提交归档。
- 未执行远端 `push`。

## 已知限制

- 扶摇当前没有可替代本项目严格 PIT 归档、官方逐日交易规则和成交模拟的资格证明。
- 当前 A 股接口没有个股分钟 K、逐笔成交、公告和新闻的统一 MCP 能力；短线工具是供应商快照口径。
- 同花顺板块成分是“当前成分”，不能当作历史成分回放。
- 文档工具总数与服务端实际 `tools/list` 可能短期不同；运行时以服务端列表和本地白名单共同约束。

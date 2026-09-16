# MarketSnapshot Provider

当前正式低成本 live Adapter 为 `public-web-consensus-v1`：腾讯主实时源、东方财富第二源、新浪备用与交叉校验。

- Provider Registry 同时保留 `manual-import-v1` 离线导入；不能把手工/BACKFILL 快照冒充 live provider。
- Public Web Provider 覆盖 AUCTION/R1/R2/R3，至少两个来源价格一致才生成可用证券快照；一个异常源可剔除，只剩一源必须 fail-closed。
- 来源时间必须属于目标交易日，明显未来时间剔除；`LIVE_NEAR_REALTIME` 仍由 MarketSnapshotStore 的真实捕获时钟和 Frame Policy 决定。
- 腾讯是共识值优先源；东财采用有限并发/重试；新浪主要作为备用和价格/盘口校验。
- `STANDARD_ACCESS` 需要至少两个已接受来源共同提供有效双边买卖盘；证据不足保持 UNKNOWN/QUEUE_DEPENDENT。
- Public Web Provider 固定 `strict_pit_source_verified=false`；即使 FULL+LIVE，也不能因此升级 Strict PIT。
- 三个接口都属于公开网页行情，适合当前研发/个人自用；没有交易所级 SLA，端点或字段可能变化。
- Daily Orchestrator 默认不联网；只有宿主计划显式 `allow_market_snapshot_capture=true` 才可自动抓取，每 Frame 有冷却与次数预算。
- `niuniu-market-snapshot-live` 必须 `--confirm-network` 才联网，只有 `--store` 才正式写 MarketSnapshot。
- MCP仍只允许查询 `get_market_snapshot_provider_status`，没有capture/connect/set_credentials工具。AI聊天新增宿主侧ad-hoc只读报价：当前轮明确代码/正式名称，或唯一股票上下文明确追问，即授权最多10只明确证券的一次三源查询；它不是模型任意联网工具。
- ad-hoc结果以 `niuniu-ad-hoc-live-stock-quote-v1` 注入当前聊天并保留工具事件，固定 `stored_as_market_snapshot=false / creates_decision=false / strict_pit_source_verified=false`。多股指代不清、超过上限或两源不足时不查询/不猜价。

未来取得 QMT/XtQuant、券商或交易所级行情后，可增加更高等级 Adapter 并替代实时主源；腾讯/东财/新浪仍可保留为备份与独立校验，但不得绕过 checksum、PIT、Forward Freeze 与 Orchestrator fail-closed 规则。

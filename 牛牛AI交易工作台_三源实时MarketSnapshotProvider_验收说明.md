# 牛牛三源实时 MarketSnapshot Provider v1 验收说明

- 完成日期：2026-09-15
- Provider ID：`public-web-consensus-v1`
- 数据源：腾讯 / 东方财富 / 新浪
- 定位：当前研发与个人自用的低成本实时行情层；不是交易所级行情或券商实盘通道

## 1. 三源角色

- 腾讯：主实时源，批量 `qt.gtimg.cn`。
- 东方财富：第二源，`push2.eastmoney.com` 单股行情，有限并发与重试。
- 新浪：备用与交叉校验，`hq.sinajs.cn` 批量行情。
- 三者都属于公开网页行情接口，不声明 SLA，也不认证 Strict PIT。

## 2. 共识规则

每只证券至少需要两个来源在前收、当前价以及对应 Frame 所需 OHLC 上一致，才能形成可用快照。
价格容差为 `max(0.011, min(0.03, price × 0.0002))`。
三源全部一致时优先保留三源；一源异常时自动剔除；只剩一源时 fail-closed。

## 3. 时间与执行访问

- 来源时间必须属于目标交易日；旧日期残留自动剔除。
- 来源时间明显晚于宿主捕获时钟时自动剔除。
- `LIVE_NEAR_REALTIME` 仍由 `MarketSnapshotStore + Frame Policy` 根据真实 `as_of/captured_at` 判定，Provider 不能自报实时。
- `STANDARD_ACCESS` 需要至少两个已接受来源同时提供有效买一/卖一且当前 OHLC 不是一字状态。
- 当前东财轻量接口不提供稳定买一/卖一，因此腾讯+东财两源虽可确认价格，执行访问仍保守降为 `UNKNOWN`；腾讯+新浪双边盘口可共同确认普通访问。

## 4. Strict PIT 边界

Provider 固定输出 `strict_pit_source_verified=false`。
即使快照同时满足 `FULL + LIVE_NEAR_REALTIME`，也不会因此得到 `strict_pit_eligible=true`。
公开网页行情可以作为当天实时研究事实，但不能替代交易所历史发布证据、官方逐日规则或券商级行情。

## 5. 宿主联网边界

`niuniu-market-snapshot-live` 必须显式提供 `--confirm-network` 才联网；只有额外 `--store` 才写入正式 MarketSnapshot。
Daily Orchestrator 默认仍不联网，只有计划显式设置 `allow_market_snapshot_capture=true` / CLI `--allow-market-snapshot-capture` 才允许 AUCTION/R1/R2/R3 自动抓取。
每个 Frame 失败后冷却 30 秒，最多尝试 3 次；只消费 `FULL + LIVE_NEAR_REALTIME` 快照。
AI/MCP 仍只有 Provider 状态查询，没有 capture/connect/credential 工具。

## 6. 真实网络烟测

2026-09-15 盘中直接从开发机抓取 `sh.600000` 与 `sz.000001`：

- 一次烟测三源均在线，两个证券均由腾讯/东财/新浪 3/3 形成共识。
- 随后一次烟测东财临时无有效返回，腾讯+新浪仍形成两源共识，系统没有把东财静默伪装成在线。
- 浦发银行实测价 9.22；平安银行后续烟测价 11.86。
- read-only CLI 抓取前后 `artifacts` 文件数 `77006 → 77006`。
- Provider Readiness：`READY`，AUCTION/R1/R2/R3 无缺失 live frame。

这验证了三源结构的主要价值：单一公开源短暂异常时仍能继续，但低于两源共识时会停止而不是猜值。

## 7. 测试

- Provider + Public Web + Orchestrator 专项：**28/28 passed**。
- MarketSnapshot / Scanner / PREP / Orchestrator / System Health 相关联合回归：**74/74 passed**。
- 完整仓库：**935 tests / 0 failed / 0 skipped**，耗时 **332.681 秒**。

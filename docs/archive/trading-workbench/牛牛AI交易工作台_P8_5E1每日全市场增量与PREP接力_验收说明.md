# 牛牛 AI 交易工作台 P8.5-E1：每日全市场增量归档与 PREP 接力验收说明

> 历史归档（整理于 2026-09-17）：保留原阶段记录；正文中的“当前、下一步、待完成”和测试/数据数字属于原记录时点。使用与当前进度以 [文档导航](../../README.md)、[当前状态](../../project/status.md) 为准。命令仍从仓库根目录执行。

## 1. 本轮目标

D2 已能从全市场历史日线重建 PREP 候选，但当前 MQC 历史湖可能晚于实际交易日，而且每天重写约 2.5GB / 5215 只单股历史文件不适合作为日常更新方式。

E1 新增独立 **DailyMarket 日增量层**：每天只归档一次当日全 A 股快照，并在 PREP 时与旧 MQC 历史湖叠加，不改写旧历史湖。

## 2. DailyMarketArchive

新增 `src/quantlab/data/daily_market_archive.py`。每个交易日的每个供应商版本保存为不可变目录，包含原始 JSON、规范化 Parquet、manifest 与 SHA256。

数据入口固定为本机 Baostock 0.9.3 的 `query_daily_history_k_AStock(date)`。本机 SDK demo 明确字段包括：`date/code/open/high/low/close/preclose/volume/amount/adjustflag/turn/tradestatus/pctChg/peTTM/pbMRQ/psTTM/pcfNcfTTM/isST`。
## 3. 幂等与历史修订

同一天重复抓到完全相同的数据时按内容 identity 幂等；`fetched_at` 不参与版本 identity，避免只因抓取时刻不同制造假修订。

同日数据内容发生变化时，新版本只进入 `revision_review`，不会覆盖 accepted 版本。只有宿主显式调用 `accept-revision --confirm-revision` 才切换 accepted pointer。

原始响应、manifest、Parquet 或 schema 被篡改都会 fail-closed；历史修订不能静默进入 PREP。

## 4. PREP Overlay

`prep_scanner.py` 现在支持“旧 MQC 历史湖 + accepted DailyMarket 最近交易日快照”合并。DailyMarket 可以推进最新交易日，而无需重写 5215 个旧 Parquet。

当日增量提供 `preclose` 时优先使用供应商明确前收；旧 MQC 没有 `preclose` 时才回退到前一交易行 close。`tradestatus/isST` 也从日增量进入交易状态判断。

如果旧湖与 DailyMarket 在同一证券、同一日期的 close/volume 不一致，直接报 `DATA_REVISION_CONFLICT`，不选择任一版本继续。
## 5. 证据边界

DailyMarket 是“本次抓取可见的供应商市场事实”，不自动等于 Strict PIT。它不能替代 PIT Universe，也不能替代交易所逐日官方涨跌停价 / 停牌规则归档。

因此即使 DailyMarket 补齐 `preclose/tradestatus/isST`，只要 official MarketRules 或 PIT Universe 仍缺失，PREP 继续保持 `PARTIAL / RETROSPECTIVE_REFERENCE`。

## 6. CLI

新增 `niuniu-daily-market`：`overview/list/get` 只读；只有 `capture` 会联网；`accept-revision` 需要日期、snapshot_id 和 `--confirm-revision`。

`niuniu-prep-playbook-scan` 自动读取同一 workspace 中 accepted DailyMarket 快照作为 overlay；默认仍只读，`--save-snapshot` / `--freeze` 权限边界不变。

editable install 已复核，两条 CLI 均真实存在于 `.venv/bin`，帮助和空归档 overview 可运行。
## 7. 测试与发布门槛

新增 DailyMarketArchive 5 项测试：首次接收/幂等、非交易状态、字段合同、revision review + 人工确认、篡改/schema fail-closed。

PREP 新增 2 项 overlay 集成测试：日增量推进过期历史湖；旧湖与增量冲突时 fail-closed。DailyMarket + PREP 联合专项当前 **15/15 passed**。

完整仓库标准 `unittest discover -s tests -v`：**784 tests / 0 failed / 0 skipped**。

## 8. 当前限制与下一步

本轮没有把真实 Baostock 网络可用性当作发布正确性的前提；本次会话中一次真实 provider 请求未成功返回。SDK 函数/字段合同已从本机安装包源码和 demo 固定，网络 capture 路径由可控 SDK fixture 覆盖。

E1 只完成“每日数据可增量归档并供 PREP 使用”。下一阶段才是受控编排：收盘后自动 capture / 数据就绪检查、PREP 自动运行，以及 09:25 AUCTION / 09:35 R1 的定时接力；这些不属于本次提交。

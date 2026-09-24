# DATA → CODE 数据清单

[文档导航](../README.md) · [数据与证据](../guide/data-and-evidence.md) · [当前状态](../project/status.md)

本文件是 **DATA → CODE 的唯一日常数据交接入口**。DATA 负责数据本身；CODE 只负责使用 DATA 已交付的数据。

最近一次 DATA 审查：2026-09-25（开放数据中心三个接口与封存；此前 2026-09-24：开放实时行情 `realtime_quote`、`market_snapshot` 与扶摇 `fuyao_context`；此前 2026-09-23 第 3 批新增公开来源文件数据 17 项、研究查询 API 7 项）。文件型数据的机器可读同源清单是数据根里的 `catalog/dataset_registry.json`（注册表，见[数据与证据 §16](../guide/data-and-evidence.md)）；本表与注册表由 DATA 同步维护，二者不一致时以 DATA 更正为准，CODE 不自行取舍。

## 1. 责任边界

**DATA 全责：** 数据采集、来源选择、版本/修订选择、公司行动裁决、去重/规范化、单位和精度、完整性、覆盖范围、Strict PIT 资格、factor/qfq 重建、影响审计、发布与回滚。DATA 只有在确认某项数据可以给产品使用后，才把状态改为 `READY`。

**CODE 不负责：** 判断哪家供应商正确、重新裁决公司行动、比较多个来源选赢家、重算 factor/qfq 验证 DATA、重新认证 PIT、替 DATA 判断数据是否完整。CODE 不遍历数据根寻找“最新”或备用数据。

**CODE 只负责：** 按本表给出的路径或接口读取 `READY` 数据并实现产品功能。如果路径不存在、权限不足、文件损坏到无法解析、接口调用失败或格式与 reader 不兼容，应明确报技术错误；不能自动换其它来源或自行修数据。

### 1.1 外部数据接口也归 DATA

判断标准只有一条：**一个外部接口的主要用途是给牛牛提供市场、证券、公司、宏观等数据，就归 DATA 维护。** 腾讯/新浪/东财行情、东财板块和龙虎榜、Baostock、TDX、巨潮、同花顺、扶摇都属于这一类。

```text
外部供应商 API → DATA Provider / Gateway → 统一内部数据接口 → CODE
```

DATA 负责接口地址与参数、字段映射、密钥或登录方式、限频/重试/超时、来源优先级与切换、是否允许 fallback、单位和精度、schema 变化、返回数据的正确性和实时性。CODE 只调用 DATA 在本表公布的接口，**不直接绑定任何第三方数据供应商 API**；背后用的是哪家，CODE 不关心。

不属于数据源的外部接口不归 DATA：大模型 API、邮件与通知、支付、券商账户与下单等产品功能接口，由 CODE 维护。

## 2. 状态与交付方式

状态：

- `READY`：DATA 已确认该数据可供 CODE 按本表说明使用；数据正确性和适用范围由 DATA 负责。
- `NOT_READY`：DATA 明确尚不可供 CODE 使用；对应产品能力应保持未就绪/blocked。
- `REVIEW_REQUIRED`：当前已发现数据、路径或接口，但 DATA 尚未完成审查；**等同于不可供 CODE 正式使用**。
- `DEPRECATED`：DATA 已停止该数据；CODE 应迁移到 DATA 指定的替代项，不自行选择替代路径。

交付方式：

- `FILE`：数据根里的文件或目录，按“地址”一列的绝对路径读取。
- `DATABASE`：数据库里的表或视图，“地址”写库文件和表/视图名。
- `API`：DATA 维护的 Python Provider 或服务接口，“地址”写入口（模块与类/函数），CODE 只通过它调用。
- `STREAM`：DATA 提供的实时推送流。目前没有。

`READY` 只表示“可按本表说明使用”，**不等于 Strict PIT**。每项的资格写在“覆盖 / 用途”一列；除非明确写出 Strict PIT，一律是 `research_only` 或回顾性参考。

## 3. 可供 CODE 使用的数据（READY）

| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |
|---|---|---|---|---|---|---|---|
| `bars_daily_baostock_raw` | FILE | Baostock 日K，不复权 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=baostock/stock_kline_daily` | 每只证券一个 `<sh_600000>.parquet`；列 `date, code, open, high, low, close, volume, amount, adjustflag(=3), fetch_ts`；主键 `(code, date)` | 5,222 只在市 A 股（2026-09-23 参考快照 `type=1, status=1`），1990-12-19 至 **2026-09-23**（其中 3 只 9-23 停牌无K线），约 1,714 万行，单一 schema、0 重复。research_only | `READY` | 直接读取。是否可交易必须连接 `security_status_baostock_v2`，不能把“有K线行”当作可交易 |
| `bars_min5_baostock_raw` | FILE | Baostock 5分钟，不复权 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=baostock/stock_kline_min5` | 每只证券一个 parquet；列同日K另加 `time`（`YYYYMMDDHHMMSSmmm`）；主键 `(code, date, time)`；交易日每只 48 根 | 5,222 只，**2020-01-02**（供应商下限）至 **2026-09-23**，约 3.63 亿行。research_only | `READY` | 直接读取；2020 年前没有 5 分钟数据，不要从日K推算 |
| `security_status_baostock_v2` | FILE | 日状态：交易/停牌、ST | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=baostock/daily_status_v2` | 每只证券一个 parquet；列 `date, code, tradestatus, isST`；`tradestatus=0` 为停牌（保留，不删行）；主键 `(code, date)` | 5,222 只，1990-12-19 至 **2026-09-23**，约 1,714 万行。供应商回顾性状态，**不是 Strict PIT** | `READY` | 用于停牌/ST 判断与研究过滤；需要 Strict PIT 时用 `strict_pit_security_status_f26`（未就绪） |
| `reference_snapshot_baostock_20260923` | FILE | 2026-09-23 参考快照：交易日历、证券基础信息、行业、全市场列表、上证50/沪深300/中证500成分 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=baostock/reference_snapshots/snapshot=2026-09-23` | 7 个 parquet（`trade_calendar, stock_basic, industry, all_stock, sz50, hs300, zz500`）+ `manifest.json`（逐文件 SHA256） | 观察日 2026-09-23；在市 A 股 5,222 只；交易日历至 2026-09-23。行业与成分是**观察日当时的快照，不能回填历史**。retrospective_reference | `READY` | 按本表写明的这一个快照日期读取；DATA 发布新快照时会在这里改日期，CODE 不自行找“最新快照” |
| `qfq_published_f24` | FILE | 前复权日线与 5 分钟（正式发布） | 日线 `/Volumes/Lexar/niuniu-data/lake/silver/qfq_kline_daily_v2`；5 分钟 `/Volumes/Lexar/niuniu-data/lake/silver/qfq_kline_min5_v2` | 每只证券一个 parquet，列与旧 qfq 相同：`date(date32), code, open, high, low, close, volume, amount, factor`（5 分钟另有 `time`）；价格 = 原始价 × factor，最后一根 factor=1；volume/amount 为原始值 | 5,222 只至 **2026-09-23**；5 分钟 2020-01-02 起。除权事件须至少两个独立来源一致才采用（共 54,712 个），无法确认的事件不猜：452 只股票只从最后一个未确认事件日起提供。每只的起点与是否截断见日线目录下 `_meta/coverage.parquet`：列 `code, valid_from, history_truncated, rows_raw, rows_qfq, events_accepted, events_blocked`；`history_truncated=True` 的 452 只，`valid_from` 是截断起点；`False` 的 4,770 只，`valid_from` 就是该股第一根K线，历史完整。research_only | `READY` | 直接读取。按 `history_truncated` 区分：为 `True` 且请求早于 `valid_from` 时，报“DATA 未提供该段 qfq”；为 `False` 且请求早于 `valid_from` 时，是该股尚无交易历史（未上市），不是数据缺失。两种情况都不要改读旧 qfq，也不要自己用原始价补 |
| `capture_root` | FILE | 捕获包根目录：回溯日线、DailyMarket、公开证据（涨跌停池、龙虎榜、板块、人气）、前瞻参考、Baostock 导入 | `/Volumes/Lexar/niuniu-data/lake/_market_data` | 各子目录格式不变（`retro_daily/<capture_id>/`、`daily_market/<日期>/`、`public_evidence/<来源>/<日期>/` 等），根目录有 `CAPTURE_ROOT.json` | 2026-09-23 从 `artifacts/_market_data` 复制迁入（1,800 文件逐一核 SHA）；工作空间经 `artifacts/_market_data.redirect.json` 指向这里。research_only | `READY` | 继续通过产品已有的 `capture_root()`/各 Store 读取；不要直接读 `artifacts/_market_data`（已冻结，只为历史路径保留） |

### 3.1 公开来源数据（按日分区，2026-09-23 首采）

下面 17 项来自东财、同花顺、巨潮、交易所、中证指数、申万的公开网页接口，都是 **research_only**，不是 Strict PIT。统一约定：

- 每项是一个目录，目录下每个分区一个 `YYYY-MM-DD.parquet`。“按交易日”“按公告日”分区的文件名是业务日期；“当天观察”的文件名是观察日，内容是那一天供应商给出的当前状态。
- `_empty/YYYY-MM-DD.json` 表示 DATA 已确认该分区供应商没有数据；分区既没有 parquet 也没有 `_empty` 标记，表示 DATA 还没采，不能当作“没有数据”。
- 每个文件都有 `_observed_at`（UTC 采集时间）。有几项保留了供应商原样的列名（东财大写列名），表里已注明；CODE 在产品层自行重命名即可，不要改文件。
- “当天观察”的数据**不能回补**：错过的日子就是没有，CODE 不要用相邻日期冒充。
- 截止日期随每日采集推进，DATA 在这里更新。

| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |
|---|---|---|---|---|---|---|---|
| `limit_up_pool_ths` | FILE | 同花顺涨停池 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=ths/limit_up_pool` | 按交易日；列 `date, code, name, price, pct, reason, board_type, seal_rate, break_times, seal_amount, high_days, first_limit_up_ts, last_limit_up_ts, is_again`，另有 `raw_json` | 2026-09-01 至 09-23，17 个交易日，1,011 行 | `READY` | 涨停原因、连板天数、封板时间研究；更早日期可回补（需 DATA 另行批准采集） |
| `margin_detail_exchange` | FILE | 沪深交易所官方融资融券明细 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=exchange/margin_trading` | 按交易日；列 `date, code, name, exchange, margin_balance, margin_buy, short_balance, short_volume, short_sell_volume, source, source_url`；金额单位元、数量单位股 | 2026-09-01 至 09-22，16 个交易日，65,676 行。**T+1 发布**：某交易日的数据次日才有 | `READY` | 按 `date` 读；当天没有文件是正常的 |
| `block_trades_em` | FILE | 大宗交易明细 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=eastmoney/block_trades` | 按交易日；东财原列名，主要列 `SECURITY_CODE, TRADE_DATE, DEAL_PRICE, DEAL_VOLUME, DEAL_AMT, PREMIUM_RATIO, BUYER_NAME, SELLER_NAME, CLOSE_PRICE` | 2026-09-01 至 09-23，2,158 行 | `READY` | 直接读取 |
| `announcements_cninfo` | FILE | 巨潮全市场公告目录（标题、类型、PDF 地址） | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=cninfo/announcements` | 按公告日（自然日）；列 `date, code, name, org_id, announcement_id, title, type, announcement_time_ms, adjunct_url, adjunct_type`，另有 `raw_json`；PDF 地址 = `https://static.cninfo.com.cn/` + `adjunct_url` | 2026-09-17 至 09-22，5,512 行；09-20 为确认空日。**当天分区当天不采**（晚间还会新增），次日补采 | `READY` | 只有目录，不含正文；单只股票的最新公告用 API `stock_announcements` |
| `institution_survey_em` | FILE | 机构调研明细 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=eastmoney/institution_survey` | 按公告日；每行一家机构：`code, name, notice_date, survey_date, org_count, survey_way, place, receptionist, org_name, org_type, investigators` | 2026-09-01 至 09-23，22,394 行 | `READY` | 直接读取 |
| `holder_trades_em` | FILE | 股东增减持 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=eastmoney/holder_trades` | 按公告日；`code, name, holder, direction, change_shares_10k, change_pct_total, change_pct_float, after_*, avg_price, channel, start_date, end_date, notice_date`；股数单位万股 | 2026-09-01 至 09-23，408 行，另有 3 个确认空日 | `READY` | 直接读取 |
| `lockup_expiry_em` | FILE | 限售解禁 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=eastmoney/lockup_expiry` | 按解禁日；东财原列名，主要列 `SECURITY_CODE, FREE_DATE, FREE_SHARES_TYPE, CURRENT_FREE_SHARES, LIFT_MARKET_CAP, FREE_RATIO, TOTAL_RATIO` | 2026-09-02 至 12-22，559 行，另有 39 个确认空日。**观察日以后的分区是预告**，会随公告变化；DATA 的重采模式尚未做好，目前未来分区保持 2026-09-23 的观察，用 `_observed_at` 判断新旧 | `READY` | 未来日期只能当“计划解禁”，不能当已发生的事实 |
| `earnings_forecast_em` | FILE | 业绩预告 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=eastmoney/earnings_forecast` | 当天观察；`code, name, notice_date, report_date, indicator, forecast_type, amount_lower, amount_upper, change_pct_lower, change_pct_upper, prior_year_amount, content, reason` | 2026-09-23 观察，报告期 2026-06-30 与 2026-09-30，5,030 行 | `READY` | 按 `notice_date` 判断披露时间 |
| `holder_count_em` | FILE | 股东户数（每股最新一期） | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=eastmoney/holder_count_latest` | 当天观察；东财原列名，主要列 `SECURITY_CODE, HOLDER_NUM, PRE_HOLDER_NUM, HOLDER_NUM_RATIO, END_DATE, HOLD_NOTICE_DATE, AVG_HOLD_NUM` | 2026-09-23 观察，5,564 只 | `READY` | 只有每只股票最近一期；历史各期不在这里 |
| `share_buyback_em` | FILE | 股份回购 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=eastmoney/share_buyback` | 当天观察；`code, name, progress, plan_start, plan_end, price_cap, amount_lower, amount_upper, done_shares, done_amount, latest_notice, objective` | 2026-09-23 观察。**只有按最新公告排序的前 5,000 条**（供应商分页上限），更早的回购不在里面 | `READY` | 用于近期回购；不能据此断言“某股从未回购” |
| `equity_pledge_em` | FILE | 股权质押比例 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=eastmoney/equity_pledge` | 当天观察；`date, code, name, industry, pledge_ratio_pct, pledged_shares_10k, pledged_mktcap_10k, pledge_count` | 2026-09-23 观察，2,212 只（只含有质押的股票） | `READY` | 不在表里 = 当日无质押记录 |
| `ipo_calendar_em` | FILE | 新股申购与上市 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=eastmoney/ipo_calendar` | 当天观察；`code, name, apply_code, exchange, board, apply_date, ballot_date, listing_date, issue_price, issue_pe, win_rate_pct, first_close` | 2026-09-23 观察，最新 5,000 条 | `READY` | 直接读取 |
| `index_weights_csindex` | FILE | 指数成分权重（沪深300、中证500、中证1000、上证50、科创50、中证A500、中证2000、创业板指） | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=csindex/index_weights` | 当天观察；`date, index_code, code, name, exchange, weight_percent, source_url`；`date` 是指数公司权重文件的日期 | 2026-09-23 观察，4,500 行 | `READY` | 成分与权重以 `date` 为准；历史成分变更不在这里 |
| `sw_industry_history` | FILE | 申万行业分类变更历史 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=swsresearch/industry_classification_history` | 当天观察的全量表；`code, start_date, industry_code, update_date, l1_code, l2_code` | 12,920 行，每行是一次行业归属的起点 | `READY` | 取某日行业：该股 `start_date <= 该日` 的最后一行 |
| `monitor_pool_em` | FILE | 东财异动监控名单 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=eastmoney/monitor_pool` | 当天观察；`code, name, market, start, end, link, observed_date` | 2026-09-23 观察，16 只 | `READY` | 只能当天观察，不能回补 |
| `price_anomaly_em` | FILE | 股价异常波动（交易所规则触发） | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=eastmoney/price_anomaly_pool` | 当天观察；`code, name, change_pct, deviation, days, board, rule_code, rule, is_today, observed_date` | 2026-09-23 观察，11 只 | `READY` | 同上 |
| `northbound_minute_ths` | FILE | 北向资金分钟净流入 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=ths/northbound_minute` | 当天观察；`date, time, hgt_yi, sgt_yi`（沪股通/深股通，亿元） | 2026-09-23，262 个分钟点 | `READY` | 只能当天收盘后采，不能回补 |

### 3.2 研究查询接口（API）

入口统一是 `quantlab.data.research_provider.ResearchDataProvider`。这些是**按需实时查询**：每次调用直接问供应商，结果不落盘、不缓存，适合问答和研究上下文；不是正式 MarketSnapshot，不是 Strict PIT，也不授权交易。

调用方式：

```python
from quantlab.data.research_provider import (
    ResearchDataProvider, DataProviderError, InvalidRequest, ProviderNotConfigured)

provider = ResearchDataProvider.from_env()   # 进程内建一个，复用
result = provider.financial_statements("300750", statement="income", periods=4)
result.status      # "ok" 或 "empty"（供应商正常回答、确实没有数据）
result.rows        # tuple[dict]，各项字段见下表
result.total       # 供应商报告的总条数（没有则为 None）
result.truncated   # True 表示只返回了一部分
result.fetched_at  # UTC 时间
result.to_dict()   # 可直接 JSON 序列化
```

- 证券代码接受 `300750`、`SZ300750`、`300750.SZ`，只支持 A 股。
- 出错一律抛异常，**不会用空结果冒充“没有数据”**：`InvalidRequest`（参数不对、代码不存在、交易所不支持）、`ProviderNotConfigured`（缺密钥）、`DataProviderError`（网络、HTTP、返回格式不对）。CODE 捕获后告诉用户“数据暂不可用”即可，**不要换别的来源重试**。
- 接口内已做限频（东财每次至少间隔 1.5 秒，其他 1 秒，同一实例串行）。CODE 不要并发调用、不要循环扫全市场；批量需求请 DATA 做成文件数据。
- 问财密钥由 DATA 配置在项目根目录 `.env`（`IWENCAI_API_KEY`、`IWENCAI_BASE_URL`，已被 git 忽略），启动脚本会自动载入。CODE 不读、不打印、不记录密钥。
- 背后用哪家供应商由 DATA 决定，可能调整；CODE 只依赖方法名、参数和下表字段。

| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |
|---|---|---|---|---|---|---|---|
| `research_search` | API | 研报 / 新闻 / 公告语义搜索 | `ResearchDataProvider.research_search(query, channel="report"\|"news"\|"announcement", size=1..50)` | 每行 `channel, title, summary, url, publish_time, source, author, rating, score, doc_id`；`summary` 是正文节选 | 问财语义搜索（需密钥），按相关度排序，单次最多 50 条；研报行常没有 `publish_time` | `READY` | 用自然语言找资料；按 `score`、`publish_time` 决定展示 |
| `stock_research_reports` | API | 单只股票的券商研报列表 | `ResearchDataProvider.stock_research_reports(code, limit=1..500)` | 每行 `publish_date, title, org, authors, rating, last_rating, eps_this_year, eps_next_year, eps_next_two_year, pe_this_year, industry, info_code, pdf_url` | 东财研报库，最新在前；`total` 为该股研报总数 | `READY` | 评级、盈利预测、研报 PDF 链接 |
| `stock_news` | API | 单只股票相关新闻 | `ResearchDataProvider.stock_news(code, limit=1..100)` | 每行 `publish_time, title, snippet, media, url` | 东财资讯，**按代码关键词检索**，偶尔混入只是提到该代码的综合新闻 | `READY` | 展示前可按标题含股票名再过滤 |
| `stock_announcements` | API | 单只股票公告 | `ResearchDataProvider.stock_announcements(code, start=None, end=None, limit=1..300)`，日期 `YYYY-MM-DD` | 每行 `publish_date, publish_time, title, announcement_id, pdf_url, detail_url`（北京时间） | 巨潮，最新在前，含当天刚发布的公告 | `READY` | 单股最新公告；全市场按日目录用文件 `announcements_cninfo` |
| `financial_statements` | API | 三大报表 | `ResearchDataProvider.financial_statements(code, statement="income"\|"balance"\|"cashflow", periods=1..40)` | 长表，每行一个科目：`report_date, publish_date, statement, report_type, audited, currency, item_field, item_title, value, yoy`；金额单位元，`yoy` 为小数（0.05 = 5%） | 新浪财报，合并报表；`publish_date` 是披露日，研究时按它判断“当时能否知道” | `READY` | 按 `item_field`（稳定英文键）取科目，`item_title` 只用于展示 |
| `investor_qa` | API | 投资者互动问答 | `ResearchDataProvider.investor_qa(code, limit=1..100)` | 每行 `ask_time, question, answer, answer_time, answerer, answered` | 巨潮互动易，**只支持深市公司**；沪市、北交所代码会抛 `InvalidRequest` | `READY` | 沪市公司提示“暂不支持” |
| `stock_fund_flow_daily` | API | 个股日级资金流（按单笔大小） | `ResearchDataProvider.stock_fund_flow_daily(code, days=1..120)` | 每行 `date, main_net, small_net, mid_net, large_net, super_net`（元）、`*_pct`（%）、`close, pct_change`；当天一行在收盘前是盘中值 | 东财，最近 120 个交易日 | `REVIEW_REQUIRED` | 暂不使用：接口已写好，但 2026-09-23 晚间复测时东财该服务拒绝了测试出口的连接；DATA 复测通过后改为 `READY` |

### 3.3 实时行情与扶摇接口（API）

2026-09-24 DATA 审查后开放。

**实时报价的来源和一致规则：**

- 扶摇（需凭证）为主源，腾讯、东方财富、新浪三家公开网页行情做交叉校验。
- 扶摇的现价和昨收必须与公开行情一致才输出，对不上的不输出，问题列表里标 `fuyao_public_price_mismatch`。
- 公开行情内部要**至少两家在昨收、开高低收上一致**，容差 max(0.011 元, min(0.03 元, 价格×2bp))。
- 扶摇不可用时，只用公开行情的两源一致结果；公开行情全部不可用时，只用扶摇并在 `market_metrics` 里注明。
- 这些都是研究和自用行情，没有交易所级 SLA，不是 Strict PIT，也不授权交易。

**字段和语义：**

- 单位：价格为元；`volume` 为**股**（扶摇、新浪原始就是股，腾讯、东财原始是手，已×100）；`amount` 为元。扶摇的成交额只精确到约 8 位有效数字，通过校验时改用公开行情的成交额。
- `as_of`：扶摇是响应就绪时间；公开行情取参与一致的各源里最早的时间（北京时间）。
- 停牌或当日零成交的股票不输出价格，问题列表里标 `no_trade_today`、`tradable=false`；有这类股票时 `completeness` 为 `PARTIAL`。
- 除权除息日的 `previous_close` 是交易所的除权参考价，不等于前一日K线收盘价（例：600160 在 2026-09-24 除息，昨收 34.83，不是 35.05）。
- 东方财富对同一出口 IP 请求过密会断开连接，此时靠腾讯、新浪两家仍能形成一致结果。接口内东财按每批 100 只、间隔 1.5 秒串行请求。

**已实测：**收盘后的收盘价，覆盖普通股、科创板、北交所、停牌股、当日除息股，一次最多 200 只。扶摇与三家公开行情的现价、昨收、成交量一致。**盘中（集合竞价、连续竞价、涨跌停封单）尚未实测**，DATA 下一交易日（2026-09-28）开盘后补测，结果写在这里。

| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |
|---|---|---|---|---|---|---|---|
| `realtime_quote` | API | 个股实时报价（问答用） | `quantlab.agent.live_stock_quote.LiveStockQuoteService.query(text)`；行情来自 `quantlab.trading.public_web_market_snapshot.PublicWebConsensusProvider` | 单次有界查询，最多 10 只，不持久化；每只返回 `last, change, change_pct, previous_close, open, high, low, volume, amount, bid1, ask1, agreement_sources, source_times`，外加 `market_status`、`age_seconds`、`completeness`、`consensus_issues` | 问答临时报价；扶摇为主、公开行情校验，扶摇无凭证时只用公开行情 | `READY` | 通过这个服务调用；不要在别处直接请求腾讯/东财/新浪/扶摇；`status` 不是 `OK` 时告诉用户暂时拿不到报价 |
| `market_snapshot` | API | 正式盘中 MarketSnapshot（Daily Orchestrator 各时段） | `quantlab.trading.market_snapshot_provider.MarketSnapshotProviderRegistry`，实时通道 `public-web-consensus-v1`；另有手工导入 `manual-import-v1` | 按交易日 × 时段（AUCTION/R1/R2/R3）× 证券（每次最多 200 只）抓取，保留各源响应哈希 | 盘中研究与复盘输入；非 Strict PIT。`PARTIAL` 快照里缺的证券不要自己补 | `READY` | 通过 Registry 调用；不直接调用底层网页接口 |
| `fuyao_context` | API | 扶摇个股/板块/短线/基本面聚合查询 | `quantlab.agent.fuyao_tools.FuyaoContextService`（`resolve / stock / sector / short_term / fundamental`；聊天里由 `FuyaoResearchAPI` 暴露为 5 个工具） | 按调用返回，不持久化；每次返回结果和扶摇请求凭据（request_id、source_hash）。字段：`volume` 为股、`turnover` 为元（约 8 位有效数字）、日期为 `date_ms`（北京时间 0 点的毫秒时间戳）；财务指标 `value` 为字符串，比率类单位为 % | 研究问答上下文。**板块成分是当前成分，不是历史成分**；个股 K 线是扶摇自己的复权，**回测和统计用 `qfq_published_f24`，不要用这里的 K 线**；龙虎榜、热度、涨跌停池为扶摇口径，与 DATA 文件数据可能有出入。凭证在项目 `.env` 的 `HITHINK_FINANCE_API_KEY`（或 macOS 钥匙串），缺凭证时不可用 | `READY` | 通过该服务调用；CODE 不读取、不打印密钥 |

### 3.4 盘中板块接口（API，2026-09-24 开放）

对应 CODE 需求《盘中板块榜与板块成分行情》。入口：`quantlab.data.sector_intraday.SectorIntradayProvider`，进程内建一个实例，页面复用它。

**刷新规则：**
- 板块榜最小间隔 10 秒，成分股最小间隔 5 秒。CODE 可以随时调用：间隔内调用直接返回上一次的结果（`cache.hit=true`，`cache.age_seconds` 为缓存年龄），不会再去问扶摇。
- 扶摇请求失败会重试一次。仍失败时返回上一次成功的结果并标 `stale=true` 和 `stale_reason`；从来没成功过时抛 `DataProviderError`。
- 页面 10 秒刷板块榜、5 秒刷已打开的板块即可。不要同时刷多个板块的成分股。

**来源和校验：**
- 同花顺板块指数只有扶摇一个来源，无法交叉校验，返回里 `cross_check` 写明单一来源。
- 成分股行情来自扶摇，并用腾讯、新浪核对：每只股票最多 30 秒核一次，每次调用最多核 300 只，大板块在几次刷新内轮流核完。核对当时价格对不上的，本次不输出价格，`status=withheld_source_mismatch`，同时附上公开行情的价格。
- 停牌或当日零成交的股票标 `no_trade_today`。

**涨跌停：**
- 由 DATA 自己推算：涨跌停价 = 昨收 ×（1 ± 比例），四舍五入到分。比例为主板 10%、主板 ST 5%、创业板和科创板 20%、北交所 30%；上市前 5 个交易日不设涨跌停，标 `no_limit_new_listing`。
- `limit_status` 取值：`limit_up`（封涨停）、`limit_down`（封跌停）、`limit_break`（盘中碰过涨停价但现价低于涨停价，即炸板）。
- 推算结果与扶摇的涨停池、跌停池、炸板池对照，结果写在 `limit_check`：`agree`（一致）、`computed_only`（只有推算认定，例如扶摇池不含的 ST 股）、`vendor_only`（只有扶摇池里有）、`differs`（两边不同）。

**成分股只数与板块分类（2026-09-24 追加，响应 CODE 追加需求）：**
- `constituent_count`：该板块当前成分股只数，来自 DATA 每天一次的成分快照 `sector_board_constituents`（取最新一天的完整快照，日期见 `constituent_counts_date`）。当天快照还没做时沿用上一天；某板块不在快照里时为 `null`，页面不要当成 0。
- `board_class`：DATA 给出的板块分类，取值 `industry`（行业）、`theme`（题材概念）、`market_label`（不代表题材的全市场标签）。页面隐藏 `market_label` 即可，不必再按名称过滤。
- `label_reason`：仅 `market_label` 有值，说明为什么不算题材：`trading_access`（融资融券、沪股通、深股通）、`holder_label`（证金持股、国家大基金持股）、`index_selection`（“同花顺”开头的精选指数、高股息精选、中国AI50）、`status_label`（ST板块、摘帽）、`listing_age`（新股与次新股、注册制次新股、科创次新股）、`earnings_label`（“2026中报预增”这类业绩标签，按“年份+报告期+预增/预减/扭亏/预盈/预亏”匹配）。2026-09-24 的 390 个概念里有 19 个是 `market_label`，与 CODE 原先按名称隐藏的 19 个一致。规则由 DATA 维护，改动时 `board_class_version` 会变。

**单位与代码：**成交额为元，成交量为股，涨跌幅为 %。个股代码用牛牛格式 `sh.600000`，板块代码用扶摇格式 `885431.TI`。时间为北京时间；`as_of` 是扶摇响应时间，`age_seconds` 是离现在多少秒。

**分时：**扶摇没有分钟线，DATA 不提供供应商分时。有两种替代：
- `board_series(code)`：返回本进程今天的采样点。每次非缓存的 `board_snapshot` 采一个点，即至少间隔 10 秒，页面开着时才有。
- 盘中记录器：每分钟把全部板块存进数据湖，见表中 `sector_board_intraday`。

**已实测（2026-09-24 收盘后）：**
- 板块榜：概念 390 个加行业 320 个共 710 个，全部返回，约 4 秒。
- 新能源汽车板块 1,065 只成分股：第一次约 7 秒，之后每次 2–5 秒，1,061 只与公开行情一致，4 只当日零成交。
- 涨停、炸板与扶摇池对照一致。
- **尚未实测的只有盘中表现**：交易时段扶摇多久更新一次、集合竞价时返回什么、整天按 10 秒/5 秒刷新是否限流、封板股判断。DATA 于下一交易日（2026-09-28，中秋休市后）盘中实测，结果写在这里；发现问题会修，严重时改回 `REVIEW_REQUIRED`。在此之前页面请照实显示 `as_of`、`age_seconds` 和 `stale`，延迟大时用户能直接看到。

| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |
|---|---|---|---|---|---|---|---|
| `sector_board_snapshot` | API | 同花顺概念、行业板块行情榜 | `SectorIntradayProvider.board_snapshot(types=["concept","industry"])`；采样走势用 `board_series(code)` | 每个板块：`code, name, type(concept/industry), last, change, change_pct, amount, volume, previous_close, open, high, low, as_of, constituent_count, board_class, label_reason`，按涨跌幅从高到低；整体：`as_of, age_seconds, market_status, completeness, missing, counts, cache, stale, constituent_counts_date, board_class_version` | 盘中看盘与 AI 解读。`market_status` 取值：`PREOPEN / OPENING_AUCTION / TRADING / MIDDAY_BREAK / CLOSING_AUCTION / CLOSED / NON_TRADING_DAY`。盘中延迟未实测，见上 | `READY` | 10 秒刷新；显示 `as_of`、`age_seconds`，`stale=true` 时标明是旧数据 |
| `sector_board_members` | API | 单个板块的当前成分股行情 | `SectorIntradayProvider.board_members(code)`，`code` 取自板块榜 | 每只：`symbol, name, last, change_pct, amount, volume, previous_close, open, high, low, as_of, status(trading/no_trade_today/withheld_source_mismatch), limit_status, limit_up_price, limit_down_price, limit_check, cross_check`；整体同上，另有 `counts`（涨停/跌停/炸板/暂不输出只数） | 当前成分，不代表历史成分。盘中延迟未实测，见上 | `READY` | 只刷新用户打开的那个板块，5 秒刷新；`withheld_source_mismatch` 的股票不显示价格 |
| `sector_board_constituents` | FILE | 同花顺概念、行业板块的每日成分快照 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=fuyao/sector_board_constituents/date=YYYY-MM-DD.parquet`，回执在 `_receipts/YYYY-MM-DD.json` | 每行一个（板块, 股票）：`board_code, board_name, board_type, symbol, name, observed_at` | 当天的当前成分，不代表历史成分。2026-09-24 起，710 个板块、80,701 行。由盘中记录器开盘前自动刷新，记录器没运行的日子沿用上一天 | `READY` | 要查“某只股票属于哪些板块”时读这里；板块成分行情仍用 `sector_board_members` |
| `sector_board_intraday` | FILE | 盘中每分钟的全部板块行情记录 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=fuyao/sector_board_intraday/date=YYYY-MM-DD/HHMMSS.parquet`，回执在 `_receipts/YYYY-MM-DD.json` | 每个文件是一分钟的全部板块，列同 `sector_board_snapshot` 的板块行，另有 `market_status, snapshot_as_of, stale` | 需要 Mac 在交易时间运行记录器（`artifacts/run-sector-recorder.command`），没运行的时段没有数据，也不能补 | `NOT_READY` | 有了首日数据并核对后改 `READY` |

### 3.5 数据中心接口（API，2026-09-25 开放）

对应 CODE 需求《数据中心的状态、预览、更新与封存接口》第 2 版。模块 `quantlab.data.data_services`，三个类都用 `data_root` 构造（默认 `NIUNIU_DATA_ROOT`，否则 `/Volumes/Lexar/niuniu-data`）。字段名、返回结构和取值都按需求文档第 3 节，下面只写 DATA 的补充和差异。出错一律抛 `InvalidRequest`（参数错）或 `DataProviderError`（其他），消息是中文。

**接口 A `DataStatusService.list_status()`：**
- 只读状态索引 `catalog/dataset_status.json`、封存清单和当天记录器回执，实测 0.4 秒返回。状态索引由每次更新任务最后一步刷新，所以 `rows`、`files` 是上一次任务结束时的数；还没刷新过的数据集 `health=unknown`。
- 按需求多返回几项：`catalog_status`（清单里的状态）、`status_index_built_at`、`calendar_through`（交易日历覆盖到哪天）；盘中记录器那两行另有 `last_record_at`、`records_today`、`failures_today`。
- `expected_today` 表示今天是不是该更新的日子（交易日为 true）；`health=lagging` 按每类数据的节奏判断：日K等收盘数据 18:00 后应到当天，融资融券应到前一交易日，公告目录应到前一自然日，盘中记录 09:30 后应到当天。
- 交易日历来自最新参考快照，只到快照当天；之后的日子按工作日推断（节假日可能误判），`health_reason` 会注明。
- `seals` 为最近 30 天的封存记录，另有 `revision`（第几版）和 `pending`（待封存的数据集）。

**接口 B `DataPreviewService`：**
- `preview` 只对清单里 `READY` 的 FILE 数据集开放，`filters` 只支持 `code` 和 `date`：按证券存放的数据（日K、5分钟、日状态、前复权）默认取 `sh.600000` 最近几行；按日期分区的默认取最新一天。`capture_root` 由产品已有的 Store 读取，不提供预览。多返回 `source_files`。
- `query_schema` / `query` 开放这些查询接口：`research_search, stock_research_reports, stock_news, stock_announcements, financial_statements, investor_qa, realtime_quote, sector_board_snapshot, sector_board_members`。`market_snapshot`、`fuyao_context`、`stock_fund_flow_daily` 不提供页面试查。同一实例串行，至少间隔 1 秒。

**接口 C `DataUpdateJobs`：**
- 任务：`daily_close_update`、`sector_recorder_start`、`sector_recorder_stop`、`backfill_day`、`seal_day`、`verify_seal`、`revoke_seal`（撤销封存，必须填 `reason`）。
- `plan` 只读、秒级返回；计划 30 分钟后过期。`steps[]` 按需求字段，另有 `kind`、`weight`（进度权重）。已封存、数据盘未连接、同一任务在跑、非交易日、未收盘等情况给 `blocked_reason`。
- `run` 用牛牛当前的 Python 在后台起独立进程（`scripts/collect/job_runner.py`），关掉牛牛不中断；运行记录在数据根 `catalog/jobs/runs/<run_id>/`（`plan.json`、`state.json`、`log.txt`）。后台进程不在了而状态还是运行中时，`status` 返回 `interrupted`。`cancel` 会停止当前子任务，已写完的分区保留、有回执，下次计划会跳过它们。
- 用户确认的任务计划就是批准：任务内部各采集脚本的计划 SHA 由任务自己生成并写进日志。
- **自动启动（用户 2026-09-25 授权，仅限盘中记录器）**：两个启动脚本在打开牛牛时调用 `scripts/collect/autostart.py` → `DataUpdateJobs.autostart()`。今天是交易日、还没到 15:25、记录器没在跑、今天也没被手动停止过或已正常结束时，才在后台启动 `sector_recorder_start`，运行记录的 `trigger` 为 `autostart`；否则什么都不做，结果写到 `artifacts/autostart.log`。开盘前打开也可以，记录器会等到 09:15 才开始。记录器和 5 分钟更新运行时会阻止 Mac 睡眠。其他任务仍然必须先显示计划、由用户确认。
- 已实测：`seal_day`（2026-09-24，24 个文件，核对无误）、`verify_seal`、各任务的 `plan`。`daily_close_update` 和盘中记录器还没有完整跑过一次（前者约 6 小时，后者要等交易日），第一次运行时 DATA 会跟进。
- `daily_close_update` 里的“指数权重”需要 Python 包 `openpyxl` 和 `xlrd`，牛牛当前环境没装时计划里会提示，装法：`/Volumes/Lexar/niuniu/.venv/bin/pip install openpyxl xlrd`。

**封存规则（DATA 定）：**
- 封存范围：按日期分区的数据——§3.1 的公开数据、热度榜、盘中板块记录、全市场个股盘中快照、板块成分快照、参考快照。日K、5 分钟、日状态、前复权按证券存放、逐日追加，不在封存范围，它们可以由供应商重取、由 DATA 重建。
- 封存后采集脚本对这一天的这些数据只读不写。数据盘是 exFAT，不能设只读权限，靠核对发现改动。
- 次日才发布的数据（公告目录、融资融券）和还能补采的按日期数据，在封存清单里标“待封存”；补采后再对同一天执行一次 `seal_day`，就会以新版本加进去，已封存的条目不改。只能当天观察的数据当天没采到，标“无法补回”。
- 撤销：`revoke_seal` 把这一天的封存清单和已封存的文件整份移到 `catalog/seals/_revoked/<日期>-<时间>/`，不删除；之后可以重采、再封存成新的一版。每一版都留在 `catalog/seals/_history/`。
- `daily_close_update` 最后一步自动封存当天，并补封前一交易日待封存的数据。

| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |
|---|---|---|---|---|---|---|---|
| `data_status_service` | API | 各数据集更新状态与封存记录 | `quantlab.data.data_services.DataStatusService(data_root).list_status()` | 见需求文档接口 A 及上方补充 | 数据中心“更新状态” | `READY` | 直接调用；秒级返回，可随页面刷新 |
| `data_preview_service` | API | 文件数据预览与查询接口试查 | `quantlab.data.data_services.DataPreviewService(data_root)`：`preview / query_schema / query` | 见需求文档接口 B 及上方补充 | 数据中心“预览与试查询” | `READY` | 试查会真实联网，按一次一查使用 |
| `data_update_jobs` | API | 更新与封存任务 | `quantlab.data.data_services.DataUpdateJobs(data_root)`：`list_jobs / plan / run / status / log / cancel / list_runs` | 见需求文档接口 C 及上方补充 | 数据中心“更新与封存” | `READY` | 一律先显示 `plan()`、用户确认后 `run()`；不自动触发 |
| `day_seals` | FILE | 每天的封存清单 | `/Volumes/Lexar/niuniu-data/catalog/seals/YYYY-MM-DD.json`，核对结果在 `_verify/`，历次版本在 `_history/`，撤销的在 `_revoked/` | 每个条目：`dataset_id, dir, source, observed_at, receipt, sealed_at, files[path, bytes, sha256, rows]`；另有 `pending, missing, not_in_scope, totals, revision` | 2026-09-24 起 | `READY` | 复现某一天时按清单取文件并核对校验码 |
| `hot_rank_ths` | FILE | 同花顺个股人气榜（日榜前 100） | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=ths/hot_rank_day` | 当天观察；`rank, code, name, heat, change_pct, rank_change, concept_tags(JSON), popularity_tag, analyse_title, analyse` | 2026-09-25 起，由 `daily_close_update` 当天采集，不能回补 | `READY` | 上榜原因是供应商 AI 摘要原文 |
| `hot_rank_em` | FILE | 东财人气榜前 100 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=eastmoney/hot_rank` | 当天观察；`rank, code, market, rank_change, rank_change_history` | 同上 | `READY` | 只有排名，名称和价格请连日K或实时报价 |
| `stock_intraday_snapshot` | FILE | 全市场个股盘中快照 | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=fuyao/stock_intraday_snapshot/date=YYYY-MM-DD/HHMM.parquet`，回执 `_receipts/YYYY-MM-DD.json` | 每个时点一个文件（09:25、10:00、11:30、14:00、14:57、15:00，各在时点后约 30 秒取）；每只：`symbol, last, change, change_pct, previous_close, open, high, low, volume(股), amount(元), as_of, status, slot` | 在市 A 股加北交所约 5,570 只，一次约 10 秒；每次抽 200 只用腾讯核对，结果写在回执。由盘中记录器采集，记录器没开的时点没有数据 | `NOT_READY` | 首个交易日（2026-09-28）有数据并核对后改 `READY` |

## 4. 尚不可用、待审查或只供 DATA 内部使用

| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |
|---|---|---|---|---|---|---|---|
| `qfq_daily_existing` | FILE | 旧前复权日线（旧 MQC 构建） | `/Volumes/Lexar/niuniu-data/lake/silver/qfq_kline_daily` | 每只证券一个 parquet；`date, code, open, high, low, close, volume, amount, factor` | 截止 **2026-09-04**（比原始日K落后 12 个交易日）；来源为东财旧分红，构建脚本不在仓库、不可复现；漏掉早年配股和部分特别分红 | `DEPRECATED` | 替代项为 `qfq_published_f24`（已 READY）。CODE 应把 qfq 读取路径改到替代项；旧目录保留只为历史复算 |
| `qfq_min5_existing` | FILE | 旧前复权 5 分钟 | `/Volumes/Lexar/niuniu-data/lake/silver/qfq_kline_min5` | 同上加 `time` | 截止 2026-09-04；问题同上 | `DEPRECATED` | 同上 |
| `adjustment_factors_v2` | FILE | 逐事件复权因子与来源裁决记录 | `/Volumes/Lexar/niuniu-data/lake/silver/adjustment_factors_v2` | 每只证券一个 parquet；每行一个除权日：现金/送股/转增/配股、来源组合、`factor`、`status`（accepted/blocked/ignored）、`blockers` | `qfq_published_f24` 的审计记录 | `NOT_READY` | 不读取；它是 DATA 的审计记录，不是产品接口 |
| `corporate_actions_allotment_cninfo_v2` | FILE | 巨潮配股（原始） | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=cninfo/corporate_actions_allotment_v2` | 供应商全列，文件间列签名不统一 | 644 只（TDX 历史配股 ∩ 在市） | `NOT_READY` | DATA 内部治理输入，不对 CODE 发布；CODE 需要公司行动时使用 `company_action_decisions_f22` |
| `corporate_actions_dividend_ths_v2` | FILE | 同花顺分红（原始） | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=ths/corporate_actions_dividend_v2` | 供应商全列，含方案原文 | 5,222 只 | `NOT_READY` | 同上 |
| `corporate_actions_dividend_baostock_v2` | FILE | Baostock 分红（原始） | `/Volumes/Lexar/niuniu-data/lake/bronze/provider=baostock/corporate_actions_dividend_v2` | 供应商全列，保留 83 条供应商重复 | 5,222 只，2004 年起 | `NOT_READY` | 同上 |
| `tdx_capital_changes` | DATABASE | TDX 股本变动/除权除息（原始） | `/Volumes/Lexar/niuniu-data/catalog/mqc.duckdb` 视图 `tdx_capital_changes` | 每行一条供应商记录，字段在 `record_json` | 个人研究采集，`vendor_observation_personal_research_not_pit` | `NOT_READY` | 同上 |
| `tdx_archive` | DATABASE | TDX 其余 12 类原始数据（K线、逐笔、竞价、五档、财务、题材、涨停梯队等） | `/Volumes/Lexar/niuniu-data/catalog/mqc.duckdb` 视图 `tdx_*` | 每行一条供应商记录；不同观察版本未合并 | 个人研究采集；全市场全历史未完成 | `NOT_READY` | DATA 内部输入 |
| `auction_tdx_raw` | DATABASE | TDX 集合竞价（原始） | `/Volumes/Lexar/niuniu-data/catalog/mqc.duckdb` 视图 `tdx_auction` | 同一事件多个观察版本，单位未统一 | 沪深采集调度下界 2025-07-22；未治理 | `NOT_READY` | F25 之前不作为 Auction 输入 |
| `company_action_decisions_f22` | FILE | 最终公司行动决策数据 | **由 DATA 填写** | 由 DATA 定义 | F23 输入 | `NOT_READY` | 仅变为 `READY` 后读取 |
| `auction_governed_f25` | FILE | 统一版本/单位后的 Auction | **由 DATA 填写** | 由 DATA 定义 | Auction 产品/研究输入 | `NOT_READY` | 仅变为 `READY` 后读取 |
| `strict_pit_universe_f26` | FILE | Strict PIT Universe | **由 DATA 填写** | 由 DATA 定义 | 严格历史资格 | `NOT_READY` | 仅变为 `READY` 后读取 |
| `strict_pit_security_status_f26` | FILE | Strict PIT Security Status | **由 DATA 填写** | 由 DATA 定义 | ST/停牌/上市状态 | `NOT_READY` | 仅变为 `READY` 后读取 |
| `strict_pit_market_rules_f26` | FILE | Strict PIT Market Rules | **由 DATA 填写** | 由 DATA 定义 | 涨跌停/特殊制度等 | `NOT_READY` | 仅变为 `READY` 后读取 |
| `live_ticks` | STREAM | 实时逐笔/行情推送 | 无 | — | 未规划 | `NOT_READY` | 无 |

旧的零散数据（东财 1 分钟 5 只、新浪/腾讯日K各 14 只、同花顺/巨潮/Baostock 分红的 v1 与试采目录、东财旧分红）已在注册表中标为 superseded 或 legacy，不对 CODE 发布，这里不再列出。

采集侧的外部接口（Baostock、巨潮、同花顺、TDX、东财公开证据、`scripts/collect/public_sources.py` 用到的各公开网页接口，以及其中引用的 a-stock-data 代码）是 DATA 的内部实现，产出落到上面的文件或数据库，不作为 API 对 CODE 发布。对 CODE 发布的 API 只有第 3.2 节和本节列出的入口。

## 5. DATA 更新规则

DATA 新增或修改可供 CODE 使用的数据时，只需要更新对应表项：数据 ID、交付方式、内容、地址、格式/粒度、覆盖范围、状态和必要使用说明。路径或接口变更、版本替换、停用旧数据也在这里改；不要求 CODE 了解 DATA 内部采集脚本、bronze/silver 分层、证据目录或治理过程。

如果同一种业务数据存在多个内部来源或多个历史版本，DATA 应在完成治理后只向 CODE 指定**当前应该使用的那一项**；CODE 不自行在多个目录或接口中选择。需要保留历史版本时可以在 DATA 内部保留，但只有本表明确标为 `READY` 的项属于 CODE 的正式数据接口。

每日增量采集会让 `READY` 数据的“覆盖”末端向后推进；DATA 在每次获批采集完成后更新本表的截止日期。

## 6. CODE 使用规则

CODE 开发或运行前先查本表。需要的数据为 `READY` 时按指定路径或接口读取；为 `NOT_READY` / `REVIEW_REQUIRED` / 未登记时，直接报告“数据侧尚未交付该数据”，不要扫描数据湖补找来源，也不要自己接一个供应商 API 顶上。

CODE 可以为稳定读取实现 reader、缓存和产品层格式转换，但这些只属于消费逻辑；不能因此修改 DATA 状态，也不能把 reader 测试通过写成“数据已验证正确”。如果 CODE 发现实际文件或接口与本表描述不符，应把问题反馈给 DATA，由 DATA 决定修数据、改路径还是更新本表。

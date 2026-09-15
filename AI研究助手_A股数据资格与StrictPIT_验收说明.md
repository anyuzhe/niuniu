# 牛牛 A 股数据资格与 Strict PIT 验收说明

日期：2026-09-12

本轮补齐原设计中的“数据资格分层”：每个研究请求可显式声明 `research_only`、`retrospective_reference`、`strict_pit` 或 `official_rule_covered`。资格是**请求级合同**，不是对整个数据仓库的永久认证。

## 一、执行边界

- `research_only`：允许回溯资料，不声明 PIT 或官方交易规则覆盖。
- `retrospective_reference`：实际读取并校验本地归档，可使用 qfq、Baostock 回溯估值等资料，但必须把 strict PIT 缺口一起报告。
- `strict_pit`：必须通过历史 bar vintage、复权信息、因子外部字段、股票池及中性化控制变量的时点检查；任何缺口直接阻断。
- `official_rule_covered`：在 strict PIT 基础上，还要求 execution 模式的逐证券逐交易日显式交易规则全覆盖，并绑定哈希归档的交易所官方规则原文。

模型不能把被阻断的 `strict_pit` 静默改成 `research_only` 后继续沿用“严格 PIT”的结论名称。
## 二、当前交易所规则资料基准

当前仅把交易所规则原文作为**制度来源与归档证据**，不会根据百分比反推历史每个交易日的 `limit_up / limit_down` 后冒充官方逐日价格界限。

- 上交所《上海证券交易所交易规则（2026年修订）》：2026-07-06 起实施；普通股票价格涨跌幅限制通常为 10%，IPO 上市后的前 5 个交易日等情形不限幅；2026 修订将主板风险警示股票涨跌幅由 5% 调整为 10%。
  - https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml
- 深交所《深圳证券交易所交易规则（2026年修订）》：主板股票 10%，创业板股票 20%，IPO 上市后的前 5 个交易日等情形不限幅。
  - https://docs.static.szse.cn/www/lawrules/rule/stock/trade/W020260424690713155663.pdf
- 北交所交易规则：股票竞价交易通常实行 30% 涨跌幅限制，公开发行上市交易首日等情形不限幅。
  - https://www.bse.cn/jygl_list/200028217.html

这些规则会随日期变化，牛牛不会把“当前规则”倒推覆盖全部历史时期。
## 三、现有 Baostock 数据的真实结论

使用既有真实三股 2024 H1 管理数据集重新验收：

- `retrospective_reference`：通过，可继续作为回顾性研究资料。
- 同一份 qfq 动量研究申请 `strict_pit`：阻断，主要 blocker 为 `historical_bar_vintage_not_certified` 与 `adjusted_price_historical_availability_unverified`。
- `BAO.PE_TTM` 即使显式 lag 1 根，申请 `strict_pit` 仍额外阻断 `factor_first_publication_or_revision_history_unverified`；人工 lag 不能替代真实首次公布/修订时间。
- 显式股票列表只认证“固定 cohort 问题”，不自动认证全市场无幸存者偏差股票池。
- 行业/市值中性化在 strict PIT 下会逐 bar 检查控制变量覆盖、`effective_at / available_at / expires_at` 和权威来源。

巨潮资讯网是深交所信息披露官方网站，可作为后续财报公告/修订时点资料来源；本轮尚未把巨潮公告历史完整接成可认证的财务 revision feed，因此该缺口继续保留。
## 四、官方规则原文归档

新增宿主命令：

```bash
quantlab official-rule-archive \
  --data-root /path/to/data \
  --market-rules market-rules.json \
  --url https://www.sse.com.cn/... \
  --published-at '<host-confirmed ISO-8601 timestamp>' \
  --confirm-publication-time
```

当前 v2 只允许上交所、深交所、北交所 HTTPS 地址；每个 URL 必须提供宿主确认的带时区 `published_at`，未确认时不联网。下载后的原文按 SHA256 保存，每个 snapshot 独立生成 `research/official_market_rules/<rules_snapshot>.json`，同时保存实际 MarketRules records。相同快照重复运行幂等且不重新联网，不同快照可 append-only 并存。record 的 `available_at` 早于来源 `published_at`、原文/record 被篡改或来源缺失均 fail-closed。旧 `official-market-rules-v1` 单文件仍可读，但因没有 publication time 不再通过新的最高资格门。

全部 v2 回执可只读深度审计：

```bash
quantlab official-rule-audit --data-root /path/to/data
```

该命令核对 snapshot、实际 records、publication time、来源映射、content-addressed path 与官方原文字节。输出是全局 archive inventory，不表示任一 CandidateSet 已引用对应 snapshot。

首批真实 v2 数据已归档7份深交所公告对应的7个明确停牌 session；该回执证明“本地规则 records 绑定了所列官方原文及发布时间”，仍不自动证明人工语义映射、复牌日 exact 价格界限或费用假设正确。`official_rule_covered` 继续要求请求内逐证券逐日规则全覆盖且其他 strict PIT 组件同时通过。

## 五、执行链

资格检查已接入 AI 查询工具、Proposal 预检、人工批准重检、JobQueue 入队以及真正执行前后复查。旧版本没有资格字段的任务仅允许按 `research_only` 显式迁移恢复；旧任务不能补造 strict PIT 回执。

本轮资格专项、Proposal/Campaign/JobQueue、桌面与 MCP 联合测试均通过。最终全仓 **681 项通过、0 失败、0 跳过**；真实三股资格验收前后任务数均为 2，**新增研究任务 0**。最终业务源码指纹为 `a3b08e8c6cf181af9970bbf0472a1c23a7c1039a20a59b37b2f6eacfb7bc6d48`。

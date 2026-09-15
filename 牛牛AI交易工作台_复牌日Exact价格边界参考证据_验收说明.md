# 牛牛 AI 交易工作台：复牌日 Exact 价格边界参考证据验收说明

- 验收时间：2026-09-16 00:05（Asia/Shanghai）
- 数据根：`/Volumes/Lexar/niuniu-data`
- 范围：7 个复牌/ST session 的深交所官方前收、适用比例、公式与舍入推导
- 结论：7 组 exact 算术结果已核对并以回顾性参考包留证；因历史开盘前参考价字节及 publication receipt 缺失，**没有**追加 Official MarketRules snapshot

## 1. 本轮为什么不能直接写 MarketRules

已有 7 份公告可以证明停牌、次日复牌、ST 生效以及 5%/20% 日涨跌幅比例，但公告不包含当日最终上下限价格。Strict PIT 不能把公告比例与任意回顾性行情自动拼接后冒充开盘前官方规则。

本轮找到深交所官方历史行情接口并取得 `前收(qss)`，同时取得当时适用的《深圳证券交易所交易规则（2023年修订）》：

- 第 3.3.11 条：A 股最小价格变动单位为 0.01 元；
- 第 3.3.14 条：涨跌幅限制价格 = 前收盘价 ×（1 ± 涨跌幅限制比例）；
- 第 3.3.19 条：结果四舍五入至最小价格变动单位。

因此可以核验 exact 算术值。但历史行情 API 的响应字节与 HTTP `Date` 都是在 2026-09-15 本轮查询时取得；它证明深交所现在返回的历史 `qss`，不证明目标 session 开盘前当时可取得的那一版静态参数/行情字节。故新包固定为 `RETROSPECTIVE_REFERENCE`，不得通过 `official_rule_covered`。

## 2. 官方来源

### 2.1 适用公式

- 通知元数据：`https://www.szse.cn/lawrules/rule/repeal/rules/t20230217_598773.json`
- 规则 PDF：`https://www.szse.cn/lawrules/rule/repeal/rules/W020230217564423808793.pdf`
- 通知 `pubTime=1676563200000`，规范化为 `2023-02-17T00:00:00+08:00`
- 规则 PDF SHA256：`7018114a6e11deb239c2a72e71e49defc6e8841b3e2c093b3bbf809282c67222`
- 通知 JSON SHA256：`58ea091197cc7c95eae9c3a0dab2ae80f45a4d54f26a3755810b8672517cdea9`

该规则在 7 个目标日期均处于适用期。每只证券的 5%/20% 比例继续引用原 14 条已深验 SecurityStatus evidence 中对应的复牌/ST 公告，不改写公告事实。

### 2.2 历史行情

深交所官方接口：

- 2025-08-29 及以前：`CATALOGID=1815_stock`
- 较新日期：`CATALOGID=1815_stock_snapshot`

每个请求均精确限定证券与日期，归档原 JSON 和原 HTTP headers。`qss / ks / zg / zd / ss` 的官方列名分别为前收、开盘、最高、最低、今收。所有响应的服务器 `Date` 为 2026-09-15 23:39:00～23:39:36（Asia/Shanghai），明显晚于目标 session。

## 3. 7 组 exact 算术结果

统一采用 `Decimal + ROUND_HALF_UP + 0.01`，不是二进制浮点近似。

| 证券 | session | 官方前收 | 公告比例 | 推导涨停 | 推导跌停 | 官方当日最低 | 官方当日最高 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `sz.000040` | 2024-07-09 | 2.41 | 5% | 2.53 | 2.29 | 2.29 | 2.29 |
| `sz.300376` | 2024-07-09 | 4.01 | 20% | 4.81 | 3.21 | 3.21 | 3.21 |
| `sz.002055` | 2026-01-06 | 6.74 | 5% | 7.08 | 6.40 | 6.40 | 6.40 |
| `sz.002512` | 2026-03-03 | 6.03 | 5% | 6.33 | 5.73 | 5.73 | 5.73 |
| `sz.002538` | 2026-03-31 | 7.24 | 5% | 7.60 | 6.88 | 6.88 | 6.88 |
| `sz.300081` | 2026-04-08 | 4.39 | 20% | 5.27 | 3.51 | 3.51 | 3.76 |
| `sz.002217` | 2026-06-23 | 2.53 | 5% | 2.66 | 2.40 | 2.40 | 2.40 |

核对结果：7/7 的官方当日最低价等于推导跌停价，7/7 最高价未超过推导涨停价；其中 6 个 session 全天最高/最低均锁在推导跌停价，`sz.300081` 当日最低 3.51 后最高 3.76。

这说明算术和历史结果相互一致，但成交结果仍不能替代开盘前 publication evidence。

## 4. 回顾性参考包

外部数据根新增：

```text
research/official_market_rule_references/<reference_snapshot>.json
research/official_market_rule_references/documents/<sha256>.bin
```

真实身份：

- `reference_snapshot=d8b9c1e9f2874b4f897eb4bf66abd8e146876688584403b6fc32937bf96f4b36`
- receipt SHA256：`772dae7d3573553722fc6c36268a16478eafc6f1e037ff2ad78de050a4faf391`
- records：7
- content-addressed documents：16（7 份 JSON、7 份 headers、规则 PDF、通知 JSON）
- `strict_pit_eligible=false`
- `market_rules_snapshot_appended=false`
- blocker：`historical_reference_price_publication_receipt_missing`

原 7 份公告不重复复制，reference receipt 精确引用已深验 PIT evidence id、路径与 SHA256。

## 5. 新增工具与校验

新增只读/本地导入命令：

```bash
quantlab official-rule-reference-archive \
  --data-root /Volumes/Lexar/niuniu-data \
  --plan /path/to/local-plan.json \
  --confirm-retrospective-only

quantlab official-rule-reference-audit \
  --data-root /Volumes/Lexar/niuniu-data
```

archive 命令不联网，只接受已经下载的深交所响应、headers、规则原文和 verified ST resumption evidence id。未显式确认“仅回顾性参考”时拒绝。

深度审计会核对：

- receipt checksum、snapshot identity 与 append-only 路径；
- 所有内容寻址文档字节与 SHA256；
- 规则通知 `pubTime`、PDF 链接、条款映射；
- 公告 evidence id、证券、ST 与复牌 session；
- ShowReport URL 的证券/日期/catalog 与响应列名/目标行；
- HTTP `Date` 与归档观测时间；
- Decimal 公式、上下限和当日最低价交叉核对；
- 所有记录必须保持 `strict_pit_eligible=false / market_rules_eligible=false`。

真实审计：receipt files=1、verified=1、invalid=0、records=7、Strict PIT eligible records=0、MarketRules snapshots appended=0。重复导入返回 `created=false`。

## 6. 严格边界

1. 本轮没有把 7 个算术结果写入 `research/official_market_rules/`；原 v2 仍只有 snapshot `94b7cf...1a1` 的 7 个停牌 session。
2. 回顾性官方 API 响应不能证明历史开盘前 byte vintage；不能把其 HTTP 抓取时间倒填成历史 `published_at`。
3. 7/7 跌停价被当日最低价命中只是交叉核对，不是 publication-time receipt。
4. archive/audit 不接入 Qualification、PREP、Paper 或 execution，也不改变最新 CandidateSet 的 `PARTIAL / RETROSPECTIVE_REFERENCE`。
5. 公告比例到结构化 rate 的语义摘录仍由宿主复核；代码只核公告 evidence 身份和算术，不声称自动理解 PDF。
6. 费用字段不在本包范围；RealTrade 继续 `BLOCKED`。

## 7. 测试

- Reference + Qualification + Rules Audit + PREP + System Health 专项：**44/44 passed**。
- 完整仓库：**967 tests / 0 failed / 0 skipped**，355.564 秒（运行时临时还原已提交 Agent Memory，以满足其 Git-clean 正式读取门；测试后完整恢复本轮 Memory 修改）。

## 8. 下一步

1. 优先取得目标 session 开盘前发布的 `cashauctionparams_YYYYMMDD.xml`、同等交易所静态参数文件或带可核验 publication time 的官方历史快照；只有届时才把 exact 值追加为 MarketRules v2/后继格式。
2. 在该资料不可得时保持 blocker，不降低标准；开发主线转向当前时点可前瞻留存的 PIT Universe 和连续 SecurityStatus 状态链。
3. 新增任何合格 MarketRules 批次后重跑 `official-rule-audit`、Qualification/PREP/Rules Audit 与完整测试。

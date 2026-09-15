# 牛牛 AI 交易工作台：Official MarketRules Publication Receipt v2 验收说明

- 验收时间：2026-09-15 20:40（Asia/Shanghai）
- 数据根：`/Volumes/Lexar/niuniu-data`
- 范围：官方逐证券/逐 session MarketRules 的发布时间证据、append-only 归档，以及首批真实停牌规则
- 结论：v2 证据合同与首批 7 个停牌 session 已完成；全市场逐日价格边界仍远未完成

## 1. 为什么需要 v2

旧 `official-market-rules-v1` 只在单个 `research/official_market_rules.json` 中保存：

- `MarketRules.snapshot_id`
- 官方文档 URL、抓取时间、本地路径和 SHA256

它有三个不能继续接受的缺口：

1. 没有保存构成 snapshot 的实际规则 records，回执不能独立重建；
2. 没有确认 `published_at`，历史 `available_at` 可能早于文档真正公开时间；
3. 单文件只能保存一个 snapshot，无法按批次持续追加每日规则证据。

v2 不再允许“今天抓到官方网页，就把手填的历史 available_at 当作当时已知”。

## 2. v2 证据合同

新回执格式：`official-market-rules-v2`。

每个 snapshot 独立保存在：

```text
research/official_market_rules/<rules_snapshot>.json
```

回执绑定：

- 完整规范化 MarketRules records；
- records 的 `rules_snapshot` SHA256 身份；
- 每个 record 的官方 source URL；
- 每份官方原文的本地不可变字节和 SHA256；
- 带时区 `published_at`；
- `publication_time_confirmed=true`；
- `fetched_at`；
- `published_at <= record.available_at`。

任何 records、原文、snapshot、来源映射或时间关系被修改，验证均 fail-closed。

旧 v1 文件仍可读取和深度核对原文字节，但因为没有 publication time，只返回：

```text
official_rule_publication_time_unverified
```

它不能再使新的 `official_rule_covered` 请求通过。这是有意的资格收紧，不是把旧记录改写成 v2。

## 3. 宿主命令与权限

`quantlab official-rule-archive` 现在要求每个 URL 都有逐项对应的 `--published-at`，且必须显式提供 `--confirm-publication-time`：

```bash
quantlab official-rule-archive \
  --data-root /path/to/niuniu-data \
  --market-rules market-rules.json \
  --url https://disc.static.szse.cn/.../announcement.PDF \
  --published-at 2026-02-27T20:56:03+08:00 \
  --confirm-publication-time
```

未确认时在联网前拒绝。上交所、深交所、北交所 HTTPS 白名单继续生效，并补入深交所官方 `docs.static / disc.static / reportdocs.static` 文档域名；非交易所域名和非官方跳转继续拒绝。

## 4. 首批真实 MarketRules 数据

本轮只归档 7 份已经由 SecurityStatus receipt 精确核验发布时间的深交所公司公告，并只生成公告明确证明的**停牌 session**：

| 证券 | 停牌 session | `published_at` | 官方原文 SHA256 |
|---|---|---|---|
| `sz.000040` | 2024-07-08 | 2024-07-05 23:02:29 +08 | `15d1b0bb71e4397c5592a52d3c00d18817f4114632230c8c874490de155237f6` |
| `sz.300376` | 2024-07-08 | 2024-07-05 16:45:07 +08 | `882551889d3c6a745e3fdc5ef2bb9255423f961799eeda4451974fca1416355d` |
| `sz.002055` | 2026-01-05 | 2025-12-31 22:09:11 +08 | `2484591f9fec80bf75f7195640d950cf9110b4bd9cdacd4327c3e6734016287e` |
| `sz.002512` | 2026-03-02 | 2026-02-27 20:56:03 +08 | `ad42956516ccd7c828e8df9f63d85a8e63b132f2ea03ea259313c3ab6f9100ec` |
| `sz.002538` | 2026-03-30 | 2026-03-27 22:02:58 +08 | `eec37181693a281bbca4ea60ed6b0da9a1e1b6f7d464e9d5b9b848a7b3960546` |
| `sz.300081` | 2026-04-07 | 2026-04-03 23:15:51 +08 | `2a73267eb5678b6f2dee3b7f41f0896c0e60391a9fd09674011c85ed7cd0ebc3` |
| `sz.002217` | 2026-06-22 | 2026-06-18 20:26:56 +08 | `e63dd91ed839a68fa10a68bb06a5cb9e7df06d49d7ebd685b10e3a77b9a60c65` |

7个完整官方 URL 分别记录在《牛牛AI交易工作台_StrictPITSecurityStatus_验收说明.md》和《牛牛AI交易工作台_StrictPITSecurityStatus第二批验收说明.md》，v2 receipt 也逐项保存 URL；此处不另造简写地址。

结构化身份：

- `rules_snapshot=94b7cfedb136ecd83566ac04d5adaf2776e1b57232537839179005e507bbe1a1`
- records：7
- sources：7
- receipt SHA256：`28ad3f2d81a3286999b0a6960fe73a6f7c12b8415734f3d29dfa5fd6391933f8`
- verifier：`verified_official_rule_publication_receipt`

重新下载后的 7 个 SHA256 与已有 SecurityStatus Evidence Archive 中相同 URL 的 7 个官方 PDF 全部逐项一致。

## 5. 停牌与价格边界语义

7 条 records 均为：

- `suspended=true`
- `st=false`（风险警示从次一复牌 session 起生效）
- `limit_up=null / limit_down=null`
- 费用字段为 0，仅作不参与本批证明的执行占位

这里的 null 不是“该股票可无限价格交易”，而是**停牌 session 没有可执行价格边界**。为避免审计误解，`audit_market_rules` 现在分开统计：

- `suspended_sessions=7`
- `suspended_sessions_without_price_bounds=7`
- `explicitly_unbounded_sessions=0`

逐证券逐 session 审计结果为 7/7 covered。

## 6. 幂等和篡改验证

- 同一 snapshot、URL 和 publication time 重复归档返回 `created=false`，不重新联网。
- 重复归档前后 receipt SHA256 均为 `28ad3f2d81a3286999b0a6960fe73a6f7c12b8415734f3d29dfa5fd6391933f8`，mtime 不变。
- 当前目录为 1 个 v2 receipt、7 份按内容哈希保存的官方原文。
- 测试覆盖：record 篡改、原文哈希、非官方域名、缺宿主确认、`published_at > available_at`、一个工作空间多 snapshot append-only 和重复调用无网络。

## 7. 测试

- Qualification + PREP + Rules Audit 专项：**28/28 passed**。
- 完整仓库：**964 tests / 0 failed / 0 skipped**，367.662 秒。

## 8. 严格边界

本轮**没有**宣称以下事项完成：

1. 7 个复牌/ST session 的 exact `limit_up / limit_down` 尚未归档。公告给出 5%/20% 比例，但百分比和回顾性前收盘不能自动冒充交易所逐日最终价格边界。
2. 只有 7 个停牌 symbol-session，不是任一证券的连续 MarketRules 链，更不是全市场覆盖。
3. 该 snapshot 不覆盖 2026-09-15 的 5,219 只 DailyMarket 证券，因此不会消除当前 PREP 的 `official_market_rules_missing`。
4. v2 验证的是原文字节、发布时间、record 身份和覆盖关系；公告到结构化 record 的语义映射仍需人工复核。
5. 费用字段不属于交易所公告证明范围，真实 Paper/回测必须另行冻结券商费用假设。
6. System Health 现将 v2 archive 作为**全局完整性 inventory**展示；`official_rule_archive_verified_present=true` 不表示最新 CandidateSet 引用了该 snapshot。最新 2026-09-16 PREP 仍没有规则覆盖，继续保持 PARTIAL。
7. 本轮不改变 Playbook 状态、Paper 权限或 RealTrade `BLOCKED`。

## 9. Git 与数据边界

官方 PDF 和 v2 receipt 只保存在 `/Volumes/Lexar/niuniu-data`，不提交 Git。Git 只保存：

- v2 归档/验证/CLI/审计代码；
- 回归测试；
- snapshot、receipt 与官方原文哈希；
- 本验收说明和同步更新的项目文档/Agent Memory。

## 10. 下一步

1. 为 7 个复牌/ST session 建立可核验的官方参考价与最终涨跌停价证据，再增加非停牌 MarketRules records。
2. 按受限股票池和日期逐批追加 snapshot，不覆盖旧 receipt。
3. 建设 PIT Universe 与连续 SecurityStatus 链，避免只补价格规则却仍无法通过完整资格门。
4. 全市场 Daily PREP 只有在目标日期所有证券 session 的官方规则、状态和 Universe 同时认证后才可升级 Strict PIT。

## 11. 后续补强：全局深度审计与 System Health（2026-09-15 22:15）

v2 首批提交后继续补齐只读可观察性：

- 新增 `quantlab official-rule-audit --data-root ...`，逐个重建 snapshot、核对 records、来源映射、发布时间、内容寻址路径和官方原文字节。
- 拒绝重复 source、非法 SHA256、v2 非 `research/official_rules/<sha256>.bin` 路径及文档 symlink；畸形字段必须返回 invalid，不得使 Qualification 崩溃。
- System Health 的 PIT/Playbook 组件显示 `official_rule_archive` 全局 inventory；损坏 receipt 进入 `official_rule_receipts_invalid` WARN。
- 保留 `official_rule_receipt_present` 兼容字段，同时新增语义更明确的 `official_rule_archive_verified_present`；两者均只表示全局存在深度验证通过的 v2 receipt，不证明 case-specific coverage。

真实只读审计结果：

- receipt files=1
- verified=1 / invalid=0
- records=7 / sources=7 / unique documents=7
- legacy receipt present=false
- System Health 中 `official_rule_archive_verified_present=true`
- 最新 CandidateSet 仍为 `PARTIAL / RETROSPECTIVE_REFERENCE`，Research Readiness 仍为 WARN

验证：相关专项 **42/42 passed**；完整仓库 **965 tests / 0 failed / 0 skipped**，336.996 秒。

## 12. 后续复牌价格调查（2026-09-16 00:05）

已从深交所官方历史行情取得7个复牌日的 `qss`，结合对应公告的5%/20%比例及《深圳证券交易所交易规则（2023年修订）》第3.3.11、3.3.14、3.3.19条，核出7组 Decimal exact 上下限；7/7推导跌停均与官方当日最低价一致。

但 ShowReport 原响应与 HTTP `Date` 均在2026-09-15本轮查询时才观察到，无法证明目标 session 开盘前的同一 byte vintage。故只新增 `niuniu-official-market-rule-reference-v1` 回顾性参考包与 `official-rule-reference-audit`，固定 Strict PIT eligible=0、MarketRules appended=0；本 v2 archive 仍只有原7条停牌规则。详见《牛牛AI交易工作台_复牌日Exact价格边界参考证据_验收说明.md》。

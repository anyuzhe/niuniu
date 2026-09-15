# 牛牛 AI 交易工作台 · Strict PIT SecurityStatus 第二批真实证据验收说明

- 日期：2026-09-15
- 数据根：`/Volumes/Lexar/niuniu-data`
- 范围：4 份深交所官方公告、4 只证券、8 条停牌/复牌及 ST 生效 statement
- 结论：第二批证据已完成归档、深度校验和 silver 重新物化；累计为 7 只证券、14 条 verified receipt

## 1. 本批目标

在不修改 Strict PIT / Coverage 引擎、不把稀疏事件冒充完整历史状态链的前提下，继续归档具有明确发布时间的深交所官方证券状态公告，并验证新证据可被现有 `SecurityStatus` 与 PREP 链路读取。

本批只记录公告明确陈述的停牌日、复牌日和 ST 生效状态。公告中出现的 5%/20% 涨跌幅信息没有写入 `SecurityStatus`，仍等待独立的官方逐日 `MarketRules` 证据链。

## 2. 官方来源与 statement

公告发布时间通过深圳证券交易所公告查询接口的精确 `publishTime` 核对；原始 PDF 从 `disc.static.szse.cn` 下载后按 SHA256 归档。每份公告形成停牌日与复牌/ST 生效日各一条 statement。

| 证券 | 官方发布时间（Asia/Shanghai） | 明确状态事件 | 官方 PDF SHA256 | Evidence IDs |
|---|---|---|---|---|
| `sz.000040` 东旭蓝天 | `2024-07-05T23:02:29+08:00` | 2024-07-08 停牌；2024-07-09 复牌并变更为 ST 旭蓝 | `15d1b0bb71e4397c5592a52d3c00d18817f4114632230c8c874490de155237f6` | `7220210a…`、`e0cc7b35…` |
| `sz.300376` 易事特 | `2024-07-05T16:45:07+08:00` | 2024-07-08 停牌；2024-07-09 复牌并变更为 ST 易事特 | `882551889d3c6a745e3fdc5ef2bb9255423f961799eeda4451974fca1416355d` | `385f5906…`、`9ccf71d7…` |
| `sz.002055` 得润电子 | `2025-12-31T22:09:11+08:00` | 2026-01-05 停牌；2026-01-06 复牌并变更为 ST 得润 | `2484591f9fec80bf75f7195640d950cf9110b4bd9cdacd4327c3e6734016287e` | `4f2d0d5c…`、`1ad8627c…` |
| `sz.002217` 合力泰 | `2026-06-18T20:26:56+08:00` | 2026-06-22 停牌；2026-06-23 复牌并变更为 ST 合力泰 | `e63dd91ed839a68fa10a68bb06a5cb9e7df06d49d7ebd685b10e3a77b9a60c65` | `b3990ab7…`、`41520d65…` |

官方 PDF：

- `https://disc.static.szse.cn/download/disc/disk03/finalpage/2024-07-05/ed1cb9c0-934d-4f92-9e7e-08f8090a8926.PDF`
- `https://disc.static.szse.cn/download/disc/disk03/finalpage/2024-07-05/67ac57e3-6a76-4499-9c69-2d56a3d73594.PDF`
- `https://disc.static.szse.cn/download/disc/disk03/finalpage/2025-12-31/56191f55-529a-4fbb-b06e-5606e5055157.PDF`
- `https://disc.static.szse.cn/download/disc/disk03/finalpage/2026-06-18/fb6e89d6-1da0-451a-a7c7-38e32cc7d3f3.PDF`

## 3. 数据落地结果

归档前：

- `security_status=6`
- 3 只证券
- 3 份官方文档

归档后：

- `security_status=14`
- 7 只证券
- 7 份官方文档
- `daily_market_cap / industry_membership / universe_eligibility` 仍均为 0
- 深度审计：`stored=14 / verified=14 / invalid=0`
- 重复归档 smoke：`created=0`，receipt 文件 SHA256 前后均为 `08c05d7f…`，幂等成立

派生表：

- 路径：`lake/silver/security_status/security_status.parquet`
- 行数：14
- 证券数：7
- Table SHA256：`9fb12ec9731d28d5078a878c51bdce9e98a0ee78c642e6968b1fd5dee556b4e1`
- Evidence digest：`e75bd80794ab3651303c7ceb1bf8034bb30e7c248aa080a9492bc55000969bf5`
- Receipt 文件 SHA256：`08c05d7fb61a1ccea95b69c7008ec2bdbf224bba79ff18e65a7ae22f44937437`

官方原文字节和结构化 receipt 位于独立数据根，不提交 Git；Git 只保存本验收结论、边界和可复核哈希。

## 4. PREP 接线烟测

使用 `sz.300376`、`as_of_session=2024-07-09` 运行只读 PREP：

- `strict_security_status_observations=2`
- 两条新 evidence ID 均进入扫描证据
- `security_status_materialized=true`
- 最终仍为 `PARTIAL / RETROSPECTIVE_REFERENCE`

保留的 blocker：

- `official_market_rules_missing`
- `historical_st_tradestatus_missing`
- `pit_universe_not_certified`

该结果符合 fail-closed 合同：两天的状态 statement 不证明整个 lookback 状态链完整，也不证明股票池和逐日价格规则完整。`sz.000040` 当前 raw 日线目录无对应单股文件，因此没有把它计入 PREP 行情烟测；这不影响其官方状态 receipt 的独立有效性。

## 5. 测试与验收

- `test_security_status.py`：3/3 passed
- `test_pit_coverage.py`：5/5 passed
- `test_prep_scanner.py`：12/12 passed
- 相关专项合计：20/20 passed
- 完整仓库：**961 tests / 0 failed / 0 skipped**，354.598 秒
- System Health 真实读取：Runtime=`OK`、SecurityStatus=`14`；Research Readiness 仍因 `no_frozen_playbook_definition` 为 `WARN`
- Qt 输出中的 offscreen capability 提示和 vn.py 空切片 RuntimeWarning 未导致失败

## 6. 仍然不能宣称的内容

- 14 条 receipt 不代表 7 只证券拥有连续状态链；每条只证明明确 `effective_at` 的 session。
- 不代表全市场、任意年份或任意研究区间的 SecurityStatus 完整。
- 不代表 Strict PIT Universe、行业、市值或官方逐日 `MarketRules` 已完成。
- 不生成数据集总覆盖率，也不把大量回顾性 bar 数据当作 Strict PIT 证书。
- 不代表 Playbook 已冻结、Paper 已验证或系统具备真实交易能力。

## 7. 下一步

继续按 Coverage gap 归档可核验的 SecurityStatus 事件，优先形成同一证券的进入、持续与撤销状态链；同时设计并接入独立的官方逐日 `MarketRules` receipt，之后再推进历史行业变更与每日真实市值。所有后续批次继续要求文档同步和独立 Git 提交。

> 2026-09-15 后续：Official MarketRules publication receipt v2 已完成，并用这7份公告归档7个明确停牌 session；复牌/ST session 的 exact 价格上下限仍未补齐，原 PREP blocker 不因此消失。详见《牛牛AI交易工作台_OfficialMarketRulesPublicationReceiptV2_验收说明.md》。

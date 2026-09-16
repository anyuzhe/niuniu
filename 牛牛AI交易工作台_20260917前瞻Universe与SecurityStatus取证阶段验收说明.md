# 牛牛 AI 交易工作台：2026-09-17 前瞻 Universe 与 SecurityStatus 取证阶段验收说明

## 1. 阶段结论

本阶段只完成 **2026-09-17 目标交易日前可安全完成的工作**：

1. 保存 2026-09-16 的三所官方 Universe / 状态响应，形成 review-only 基线；
2. 补齐 SSE、SZSE、BSE 官方技术规范与通知；
3. 对 SZSE 公开批量日状态文件做一次有界排查；
4. 将规范语义、公开响应观察、仍缺证据和目标日执行顺序分层留证；
5. 保持 PIT Universe v1 与完整 SecurityStatus v2 正式 receipt 均为 0。

本阶段**没有**把 2026-09-16 的列表或状态外推为 2026-09-17，没有调用任何 archive 命令，也没有创建、修改或补写历史 receipt。该结果是“前瞻准备已完成、归档门仍关闭”，不是 Strict PIT 覆盖完成。

## 2. 授权与范围

本次联网仅使用用户已授权的 SSE / SZSE / BSE 官方 HTTPS 只读访问，并把响应暂存到独立数据根：

```text
/Volumes/Lexar/niuniu-data/staging/pit_universe_security_status/2026-09-17/
```

该授权只允许读取与暂存，不自动构成以下三项宿主确认：

- publication time 已确认；
- 公共响应字段与官方规范语义已完整映射；
- 目标日 Universe 或逐日状态为完整官方全集。

未访问券商、未下单、未操作资金、未运行训练或回测。BSE 页面曾被网页自行加载一次 `hm.baidu.com` 统计脚本；该第三方请求未主动查询、未暂存、未引用，也不属于证据源。

## 3. 数据根交付物

### 3.1 原始 capture

```text
/Volumes/Lexar/niuniu-data/staging/pit_universe_security_status/2026-09-17/
  capture-20260916T132034+0800/
```

父 capture 保持原样：

| 对象 | SHA256 |
|---|---|
| `manifest.json` | `e3174698d34979ecc474da39582e3b4b94721e80f80c72f23e5d05be9d6714a8` |
| `derived/review.json` | `f2121a56bda4cd33b7ebce32a25193fb90bb5159c55886a88264d1d35b860f37` |
| `derived/universe_members_review_only.json` | `d7a4d87c0ad8d1fb5e35bae1e68dda350072b4ddeb9e6717fd3ef735daf2748f` |

父 capture 共 77 个文件，正文与 headers 保存 URL、抓取时点、字节数和 SHA256；逻辑文件字节数 5,182,339，raw body digest 为：

```text
e820b237339f711a543322270259627e58b75a72b186dff61dfd383e67e869c8
```

### 3.2 追加式语义 addendum

```text
/Volumes/Lexar/niuniu-data/staging/pit_universe_security_status/2026-09-17/
  semantic-addendum-20260916T143747+0800/
```

该目录是独立追加项，没有覆盖父 capture。共 46 个文件、19,660,328 逻辑字节，包含：

- 8 份官方页面、规范或技术通知；
- 3 次 SZSE 官方站内精确检索响应；
- 10 次 `reportdocs.static.szse.cn` 有界常见路径响应；
- 每项原始 body、headers、URL、HTTP Date / Last-Modified 候选、字节数与 SHA256；
- 分交易所结论 `derived/review.json`；
- 目标日执行顺序 `derived/target_day_runbook.json`；
- 人类可读边界说明 `README.md`。

| 对象 | SHA256 |
|---|---|
| `manifest.json` | `3ffccf938c39d39dc4ba52295b027e66bfb2cbfaf290572c78c7281bc117ec41` |
| `README.md` | `158d526503383b5254fe67ef33a818ac7cfebf72592df97463678a10a444add3` |
| `derived/review.json` | `23addf615da8ad92f1e83cef481e834215b26885fc7f5e2321fa32759d49419c` |
| `derived/target_day_runbook.json` | `97005f2288221c1e4a604cd3f2df5d2c7a54f3b94d7bea1250c7713a742f8c37` |
| `materials_digest` | `5b9f6892098c44cc21203e0adce2912f742e6b1037111542b8b607dea537edb1` |

HTTP `Date`、`Last-Modified`、页面日期和文件名日期在 manifest 中只标为候选，不能单独通过 publication-time gate。

## 4. 2026-09-16 review-only Universe 基线

| 交易所 | review-only A_SHARE 数量 | 当前解释 |
|---|---:|---|
| SSE | 2,318 | 主板 1,701 + 科创板 618，再排除官方标识为科创 CDR 的 `689009` |
| SZSE | 2,901 | 主板 1,494 + 创业板 1,407；B 股、CDR 和非 A_SHARE 类型未纳入 |
| BSE | 344 | 18 页去重后的 `92xxxx` A 股候选 |
| 合计 | 5,563 | 三所证券代码唯一，无跨所重复 |

这些成员只用于 2026-09-17 上午的加入、退出、类型、重复与分页差异审计。它们不是 target-session receipt，也不能证明 2026-09-17 09:15 前仍为完整全集。

## 5. 分交易所语义结论

### 5.1 SSE

官方规范材料：

- IS124 3.60；
- IS120 STEP 0.62；
- SSE 交易技术专区索引页。

规范级已证明：

- 盘前 `cpxx0201MMDD / cpxx0202MMDD` 产品文件包含停牌产品；
- 产品状态标志第 4 位 `D` 表示正常交易产品、`S` 表示风险警示产品；
- `TradingPhaseCode` 第 1 位 `P` 表示停牌，第 2 位 `0/1` 表示不可/可正常交易。

仍未证明：

- 目标日公共全量 equity 响应已刷新为 `20260917`；
- 当前公共接口字段与上述规范字段的正式完整映射已由宿主确认；
- 精确 publication time 与目标日全集、全状态完整性。

因此 SSE 已具备目标日上午刷新准备，但不能提前归档。

### 5.2 SZSE

官方 v1.42 数据文件规范和两份风险警示技术通知已证明：

- `pre_securities_YYYYMMDD.xml` 与 `securities_YYYYMMDD.xml` 为证券信息文件；
- 第二次下发的非 `pre_` 文件为准；
- 文件经 FTS、通过交易接入网向用户群发；
- `SecurityStatus=1/4/5` 分别表示停牌、ST、*ST。

公开源有界排查结果：

- 官方站内搜索 `securities_YYYYMMDD.xml`：12 条，全部为技术通知；
- 官方站内搜索 `pre_securities_YYYYMMDD.xml`：8 条，全部为技术通知；
- 精确搜索 `securities_20260917.xml`：0 条；
- 对官方静态域名的 10 个受限常见路径探测：全部 HTTP 404。

该结果只说明“本轮有界公开排查没有找到目标文件”，不证明任何未知路径或私有通道绝对不存在。

现有公开 `getTimeData` 只能逐证券查询，虽有交易阶段字段，但没有形成公开批量能力，也没有明确覆盖全 Universe 的风险警示字段。2,901 个逐证券 URL 超过 SecurityStatus v2 的 200-source 上限，且不能替代官方批量逐日状态文件。因此 SZSE 仍是完整 SecurityStatus v2 的硬阻塞项。

### 5.3 BSE

官方《北京证券交易所、全国中小企业股份转让系统数据文件接口规范（V1.1）》已证明：

- `bj_securityinfo_YYYYMMDD.xml` 覆盖规范声明范围内的全部挂牌证券；
- `SecurityStatus=1/4/5` 分别表示停牌、ST、*ST；
- T 日静态参考信息在 T-1 日结束后发送并放入 T 日文件夹；
- 正常情况下日间不变，特殊情况可重新下发；
- 分发渠道为 FDEP 私有群发。

父 capture 的公开列表共 344 条，均显示业务日期 `20260916`；`xxtpbz` 全为 `F`，名称中可见 3 个 `*ST`，`xxzrzt=Y` 仅出现于 `N腾信`。但官方公开材料中尚未取得 `xxtpbz / xxzrzt` 到完整 `TRADABILITY + RISK_WARNING` 的权威字段字典。不能从简称、`F` 或“没有看到公告”推断其它全部成员为正常状态。

因此 BSE Universe 可在目标日上午刷新，完整公开日状态映射仍未通过。

## 6. 证据分层矩阵

| 事项 | 当前状态 | 能否用于正式归档 |
|---|---|---|
| 2026-09-16 三所公开列表/响应 | 已暂存并校验 | 否，仅目标日前 review baseline |
| SSE 状态字段规范 | 官方规范已取得 | 单独不足；仍需目标日字节、映射与完整性确认 |
| SZSE 私有日文件字段规范 | 官方规范已取得 | 否，未取得目标日实际官方文件字节 |
| SZSE 公开批量日状态 | 有界排查未找到 | 否 |
| BSE 私有日文件字段规范 | 官方规范已取得 | 否，未取得目标日实际官方文件字节 |
| BSE 公开字段完整映射 | 未取得 | 否 |
| publication time | 仅有候选 | 否 |
| 目标日 Universe 全集 | 尚未刷新 | 否 |
| 目标日三所完整状态 | 尚未取得 | 否 |

技术规范能认证字段语义与分发机制，不能替代目标日逐证券实际值或其公开可获得时间。

## 7. Archive gate 与正式目录检查

addendum 固定记录：

```text
archive_invoked=false
receipt_created=false
publication_time_confirmed=false
semantic_mapping_confirmed=false
complete_official_universe_confirmed=false
complete_daily_status_confirmed=false
```

完成阶段校验时，下列正式目录均不存在：

```text
/Volumes/Lexar/niuniu-data/research/pit_universe
/Volumes/Lexar/niuniu-data/research/security_status_coverage
```

这正是本阶段应有结果。staging、规范、诊断或 review-only members 都不能被重命名或复制成正式 receipt。

## 8. 目标日执行顺序

建议在 `2026-09-17 08:00–08:15 Asia/Shanghai` 开始，硬截止为 `09:15`：

1. 重新检查真实 wall clock 和官方目标日 marker；
2. 刷新 SSE 主板/科创、SZSE catalog 1110 与 BSE 全部服务端声明页数；
3. 将目标日 Universe 与 5,563 只基线做加入、退出、证券类型、重复和分页总数审计；
4. 刷新 SSE bulk equity、SZSE 合格批量日状态（若能取得）和 BSE 完整公开响应；
5. 要求状态记录业务日为目标 session，并与 refreshed Universe 精确全连接；
6. 分别向宿主展示 publication time、semantic mapping、completeness 依据；
7. 三项确认齐全且仍早于 09:15 时，先 archive/audit PIT Universe；
8. 只有三所每个 member 都有显式 `TRADABILITY + RISK_WARNING` 时，才 archive SecurityStatus root；
9. 之后才可把 exact Universe snapshot 绑定 Daily Orchestrator 并运行全成员 PREP。

若首次归档已经到达或超过 `2026-09-17T09:15:00+08:00`，必须放弃该 session；`historical backfill is forbidden`。本阶段没有配置后台定时任务，目标日上午必须由用户显式再次启动。

## 9. 验证

本阶段执行了以下只读/结构校验：

- 逐项重算 addendum body 与 headers SHA256；
- 校验 manifest 声明的 21 个 entry 及 3 个 derived 文件；
- 复核父 capture 三个关键文件 SHA256 未变化；
- 复核正式 PIT Universe / SecurityStatus Coverage 目录仍不存在；
- 对 SZSE 10 个受限公开路径保存 HTTP 404 原始响应与 headers；
- 对 3 次官方站内搜索保存 POST 参数、响应正文与 headers。

生产源码未修改，完整测试基线仍以连续 SecurityStatus v2 阶段的 **1000 passed / 0 failed / 0 skipped** 为准。本阶段另执行 PIT Universe、SecurityStatus v2、PREP 与 Daily Orchestrator 聚焦回归：**45 passed / 0 failed / 0 skipped**，耗时 2.947 秒。

## 10. 验收结论

- **通过**：可提前完成的官方规范收集、有界公开源排查、语义分层、原文暂存、哈希校验和目标日 runbook。
- **未通过且保持阻断**：2026-09-17 exact-session PIT Universe receipt。
- **未通过且保持阻断**：2026-09-17 完整 SecurityStatus v2 receipt。
- **无权限变化**：没有新增 AI 下载、archive、审批、交易或资金权限。
- **无成熟度夸大**：本阶段不证明策略有效、Paper 表现、全市场 MarketRules 完整或实盘就绪。

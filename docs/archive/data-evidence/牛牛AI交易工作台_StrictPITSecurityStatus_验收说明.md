# 牛牛AI交易工作台 Strict PIT SecurityStatus v1 验收说明

> 历史归档（整理于 2026-09-17）：保留原阶段记录；正文中的“当前、下一步、待完成”和测试/数据数字属于原记录时点。使用与当前进度以 [文档导航](../../README.md)、[当前状态](../../project/status.md) 为准。命令仍从仓库根目录执行。

日期：2026-09-15

> 后续更新：第二批真实资料已使当前数据根累计达到7只证券、14条 verified receipt；首批验收数字保留为当时基线，新增来源与哈希见《牛牛AI交易工作台_StrictPITSecurityStatus第二批验收说明.md》。

## 目标

把第一批真实官方 ST / 其他风险警示 / 停复牌资料接入牛牛独立数据根，并形成可校验、可物化、可被 PREP Scanner 使用的 Strict PIT `security_status` 证据链。

本阶段不宣称全市场历史状态已经补齐，也不从状态公告推断完整逐日涨跌停规则。

## 数据根

- 牛牛独立数据根：`/Volumes/Lexar/niuniu-data`
- 原 `/Volumes/Lexar/MQC-DATA` 保留为旧数据副本，不再作为牛牛后续新增 Strict PIT 数据写入目标。
- 历史 artifact 中旧绝对路径不重写，继续作为历史来源身份。
## 证据合同

新增 `security_status` 作为第四类 PIT Evidence：

- `symbol`
- `effective_at`
- `available_at`
- `tradable`
- `risk_warning = NONE / ST / STAR_ST / UNKNOWN`
- `source`

每条记录必须绑定权威 HTTPS 公告 URL、本地官方原文字节、SHA256、宿主确认的 `published_at` 和 receipt checksum。`available_at > effective_at` 直接拒绝。

新增派生表：`lake/silver/security_status/security_status.parquet`，manifest 绑定完整 evidence ID 集合和表 SHA256。派生表或 receipt 集变化后，读取必须 fail-closed 并要求重新物化。

宿主 CLI：`niuniu-security-status --call status|materialize`。CLI 不联网下载，也不创建未经 receipt 证明的新事实。
## 第一批真实官方资料

当前已核验并归档 3 份深圳证券交易所官方 PDF：

- `sz.002512 达华智能`：2026-03-02 停牌，2026-03-03 复牌并变更为 ST 达华。
- `sz.002538 司尔特`：2026-03-30 停牌，2026-03-31 复牌并变更为 ST 司特。
- `sz.300081 恒信东方`：2026-04-07 停牌，2026-04-08 复牌并变更为 ST 恒信。

合计形成 6 条 verified `security_status` receipt，materialized table 为 6 行 / 3 只股票。三份原文 SHA256 均与 receipt 一致。

公告同时提及的 5%/20% 涨跌幅信息本阶段没有自动写入 MarketRules。SecurityStatus 只证明证券状态；官方逐日价格上下限仍由独立 MarketRules 证据链负责。
## PREP Scanner 接线

PREP 会优先读取经过 manifest / SHA256 / receipt 集合验证的 `security_status` 派生表，并把命中的 `evidence_id` 带入候选证据。

但当前 receipt archive 不是完整历史事件流，因此严格状态**只在 receipt 明确 `effective_at` 的交易日生效**；禁止把“最新已知 ST 状态”无限传播到其它日期。未覆盖日期继续保留 `historical_st_tradestatus_missing`。

即使状态日全部有 Strict status evidence，只要缺官方逐日 MarketRules，PREP 仍保持 `RETROSPECTIVE_REFERENCE`，质量标记为 `PIT_STATUS_WITH_INFERRED_LIMITS`，不得写成 Strict PIT。

真实 3 日 smoke 中，每只样本只有停牌日和复牌/ST 生效日 2 个 strict observations，整段窗口仍不完整，符合 fail-closed 预期。

## 验收

- SecurityStatus / PREP / Coverage 专项：20/20。
- SecurityStatus / PREP / Coverage / Qualification / Orchestrator / Scanner / System Health / MCP 联合：71/71。
- 完整仓库：**961 tests / 0 failed / 0 skipped**，381.649 秒。
- 下一数据主线：继续扩充官方 security-status 事件覆盖；随后进入历史行业变更和每日真实市值。
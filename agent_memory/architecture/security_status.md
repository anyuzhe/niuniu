# Strict PIT Security Status

`security_status` 用于保存经过官方原文与 publication-time receipt 深度验证的证券状态事件，当前字段为 `symbol / effective_at / available_at / tradable / risk_warning / source`。

## 语义与边界

- `risk_warning` 仅允许 `NONE / ST / STAR_ST / UNKNOWN`。
- `available_at` 不得晚于 `effective_at`；未来才知道的状态禁止回填。
- 真实状态由 `niuniu-pit-evidence-v1` 的 `security_status` receipt 提供，本地官方原文、SHA256、来源 URL、publication time 任一失效均 fail-closed。
- `lake/silver/security_status/security_status.parquet` 只是 verified receipt 的派生表；receipt 集合变化或表被修改后必须重新物化。
- `niuniu-security-status` 只允许宿主执行 `status/materialize`，不联网下载，也不创建事实。
- PREP Scanner 可以消费该派生表，但在没有“完整状态事件链”证明前，只把 receipt 明确 `effective_at` 的交易日视为 Strict 状态证据；不得把最近一次状态无限向前/向后传播成严格覆盖。
- 已验证 ST/停牌状态不等于官方逐日涨跌停规则。缺 MarketRules 时，PREP 即使拥有 Strict status evidence 也保持 `RETROSPECTIVE_REFERENCE`。
- SecurityStatus 不等于 PIT Universe：是否属于研究股票池与是否 ST/停牌是不同维度，禁止自动合并。

## 当前真实数据

当前 `/Volumes/Lexar/niuniu-data` 已归档 3 份深交所官方公告，对应 `sz.002512 / sz.002538 / sz.300081` 共 6 条 security_status evidence，覆盖各自停牌日与复牌/ST 生效日。它们是第一批真实样本，不代表全市场或完整历史状态链。
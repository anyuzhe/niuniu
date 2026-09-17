# 牛牛 AI 交易工作台 P8.5-D：MarketSnapshot、Daily Scanner 与 PREP 全市场扫描验收说明

> 历史归档（整理于 2026-09-17）：保留原阶段记录；正文中的“当前、下一步、待完成”和测试/数据数字属于原记录时点。使用与当前进度以 [文档导航](../../README.md)、[当前状态](../../project/status.md) 为准。命令仍从仓库根目录执行。

## 1. 本轮目标

本轮把 9/14 前瞻实验中临时抓取的竞价/分钟行情，升级为正式可审计业务对象，并把手工 R1 比较升级为确定性 Daily Playbook Scanner。

本轮只完成 **D1：盘中事实冻结 + 已冻结候选内扫描**；尚未把 PREP 的全市场候选生成、市场节点路由完全自动化，那部分进入 D2。

## 2. MarketSnapshot

新增 `MarketSnapshotStore`，正式保存：交易日、Frame、captured_at、provider、provider_ref、字段口径、证券快照、原始 SHA256、创建时间与校验值。

快照 append-only；重复 request_id 内容变化会冲突；SQLite 内容或索引被修改会触发 checksum 校验失败。

证券缺失不会静默删除；每个快照保存 `expected_symbols`，并显式给出 `missing_symbols / full / completeness`。
## 3. 实时资格与防回填

MarketSnapshot 不因“今天的数据”自动成为 STRICT_PIT。只有在 Frame 数据就绪后、允许的近实时窗口内创建且候选完整时，才具备 `live_near_realtime / strict_pit_eligible` 资格。

未来时间快照直接拒绝；超过近实时窗口后补录会保留为 BACKFILL，不能伪装成当时已冻结行情。

PlaybookCase 新增 `market_snapshot_ids`，前瞻 Case 可直接引用正式 MarketSnapshot；旧 Case 不带该字段仍保持可读。

`freeze_forward_snapshot` 会验证所引用快照与交易日/Frame/as_of 的一致性，避免“预测时间正确但行情证据来自以后”。

## 4. Daily Playbook Scanner

新增 `DailyPlaybookScanner`。Scanner 不联网、不自行改变基础 CandidateSet，只消费已经冻结的 CandidateSet 与 MarketSnapshot。

AUCTION 第一版只做确定性观察排序，默认 `NO_AUCTION_ENTRY`；不会把竞价涨停机械等同于买入。

R1 第一版子规则固定为：`STANDARD_ACCESS + R1正收益 + 相对竞价继续主动增强`，缺失任一候选快照时 fail-closed 为 `NO_TRADE`。
## 5. 执行访问语义

Scanner 会把首窗口一字/单一价格且普通账户成交依赖排队的候选标为 `QUEUE_DEPENDENT`。

`QUEUE_DEPENDENT` 仍保留在排名和证据里，但不能因为“最强”自动成为 STANDARD_ACCESS 下的系统选择；这继续贯彻正裕工业负样本得到的结论：执行通道改变成交集合，不自动产生 Selection Alpha。

## 6. 产品接入

新增 CLI：

- `niuniu-market-snapshot`：导入、读取、检索与查看 MarketSnapshot；本身不联网下载行情。
- `niuniu-daily-playbook-scan`：默认只读扫描；只有显式 `--freeze` 才调用既有前瞻闸门写 `SYSTEM_PREDICTION`。

Trading Cockpit 增加当日 MarketSnapshot 摘要；AI Research / Reviewer / 标准 MCP 增加只读 MarketSnapshot 查询，不增加模型写行情、冻结预测、修改 Strategy Intent 或自动下单权限。

## 7. 真实数据烟测

使用 2026-09-14 已归档的真实 AUCTION 与 09:31–09:35 R1 数据做 BACKFILL 重放。由于重放时间已超过实时窗口，快照正确标为 BACKFILL / 非 strict-pit-eligible。
Scanner 在相同基础候选上重放得到：超声电子第一、中新赛克第二、凯盛新能第三、九鼎新材第四；唯一系统选择为超声电子，与 9/14 真实前瞻 R1 当时冻结选择一致。

只读 CLI 重放前后 PlaybookStore 数量不变，证明默认扫描不会创建 Case、CandidateSet 或 Selection。

## 8. 测试与发布门槛

新增 MarketSnapshot/Scanner 核心测试 6 项，覆盖：未来时间阻断、篡改检测、候选缺失 fail-closed、AUCTION 不抢跑、R1 主动性/执行访问选择、Scanner→前瞻冻结整链。

Playbook/Trading Cockpit/AI/MCP 受影响面联合回归通过；一次直接模块点名测试出现旧测试内部 `test_context_experiments` 导入路径错误，经标准 `unittest discover -s tests -v` 运行方式复核后不存在功能回归。

最终全仓：**769 tests / 0 failed / 0 skipped**。

editable install 已重新执行，两个新 CLI 均真实存在于 `.venv/bin` 且 `--help` 可运行。

## 9. D1 结束时边界

D1 不负责自动构造全市场 PREP 候选。下一阶段 P8.5-D2 将处理：逐日 A 股制度资格、全市场连板/身位计算、市场节点路由、目标身位选择和 PREP CandidateSet 自动生成。

D2 必须继续遵守 ST/摘帽/S股/停牌/特殊价格限制等 official-rule 边界；资料不足时保持 PARTIAL/UNKNOWN，不能为了自动化静默删票。

## 10. P8.5-D2：PREP 全市场扫描与节点路由

D2 新增 `prep_scanner.py`，把 PREP 阶段从“人工先给候选池”推进到“读取全市场日线 → 计算涨跌停/连板高度 → 生成市场宽度与高度事实 → 版本化 Router → 目标身位候选”。

第一版 Router 固定为 `market-node-router-v1-20260914`，来源明确标记 `host_engineering_policy_not_expert_rule`。它是牛牛的宿主工程策略，不等于已经提取出的期末50分规则，也不允许用历史结果把同一版本不断调成命中。

Router v1 只自动处理证据较清晰的高风险节点：极端风险可输出 `NO_TRADE`；退潮/高风险且最高板压缩时可路由到 2→3 观察；其余情况返回 `UNKNOWN`，不强行每天推荐股票。

新增 `niuniu-prep-playbook-scan`：默认只读；`--save-snapshot` 才保存 PREP MarketSnapshot；`--freeze` 还必须显式提供 PlaybookDefinition，并继续经过原 PREP wall-clock 闸门。
## 11. PREP 数据资格与 fail-closed

D2 不把“代码前缀对应 10%/20%”冒充逐日官方规则。若提供 MarketRules，要升级为严格口径还必须同时满足：逐日规则无缺口、规则来源属于官方交易所域名、本地 `official_market_rules.json` receipt 与规则快照哈希一致，以及 Universe 的 PIT 资格已由宿主证据确认。

当前 `/Volumes/Lexar/MQC-DATA` 属于旧 MQC 日线湖：5215 个证券文件、约 2.5GB，日线主要保存 OHLCV，缺少完整 `isST/tradestatus`，也没有当前扫描所需的 PIT Universe 认证。因此真实全市场扫描自动降级为 `PARTIAL + RETROSPECTIVE_REFERENCE`，并显式给出 `official_market_rules_missing / historical_st_tradestatus_missing / pit_universe_not_certified` blocker。

显式规则 JSON 但没有官方归档 receipt 时仍不能升级 Strict PIT；专项测试固定覆盖该反向场景。部分证券目标日缺行会记录 `stale_as_of_symbols` 并增加 `as_of_session_data_incomplete`，不会静默从 Universe 删除。

Parquet 元数据新增 fail-fast：若全市场文件的最新日期整体早于请求 `as_of_session`，直接返回 `DATA_NOT_UPDATED` 与实际最新日期，不再读取全部 2.5GB 后才发现数据过期。
## 12. D2 真实工作区验收

真实扫描 2026-09-04：5215 个证券文件全部读取并参与源哈希，约 17.7 秒完成；得到 5215 个目标日证券行、40 个涨停、9 个跌停、最高5板。显式宿主覆盖 `target_streak=2` 时得到6个候选。由于数据资格不足，结果正确保持 `LEGACY_RETROSPECTIVE_ESTIMATE / PARTIAL / RETROSPECTIVE_REFERENCE`。

请求 2026-09-11 时，系统通过 Parquet 元数据约 6.3 秒 fail-fast：当前全市场日线最新日期实际只有 2026-09-04，因此返回 `DATA_NOT_UPDATED`，没有假造9/11市场节点或候选池。

这说明 D2 自动链路已经具备，但当前正式数据更新链仍是下一实际 blocker：若希望以后每天自动 PREP，必须先确保全市场日线在 PREP 前更新到最近交易日，并逐步补齐可审计 ST/停牌/官方价格边界与 PIT Universe。

## 13. D2 测试与发布基线

D2 新增8项专项测试，覆盖：Router UNKNOWN/NO_TRADE/退潮路由、旧 MQC 自动降级、官方规则+PIT Universe 严格路径、缺规则 session 阻断、无官方 receipt 阻断、数据未更新 fail-fast、PREP Snapshot/Forward payload 不提前选股。

D1+D2+Playbook 联合回归：**32/32 passed**。完整仓库回归：**777 tests / 0 failed / 0 skipped**。

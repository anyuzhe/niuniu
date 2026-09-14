# 牛牛 AI 交易工作台 P8.5-D1：MarketSnapshot 与 Daily Playbook Scanner 验收说明

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

## 9. 当前边界 / D2

D1 不负责自动构造全市场 PREP 候选。下一阶段 P8.5-D2 将处理：逐日 A 股制度资格、全市场连板/身位计算、市场节点路由、目标身位选择和 PREP CandidateSet 自动生成。

D2 必须继续遵守 ST/摘帽/S股/停牌/特殊价格限制等 official-rule 边界；资料不足时保持 PARTIAL/UNKNOWN，不能为了自动化静默删票。

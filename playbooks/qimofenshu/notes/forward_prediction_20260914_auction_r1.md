# 2026-09-14 前瞻验证：PREP → AUCTION → R1

本文件记录 `meta-playbook-hypothesis-v3` 在 research cutoff（2026-09-13）之后的第一条真正前瞻链。所有预测均在专家真实交易结果揭晓前写入 PlaybookStore。

## PREP

- as_of：2026-09-13 23:58:01 +08:00
- Case：`43f30fa8-5ac9-4c33-b658-7bf0664c1be4`
- CandidateSet：`db5da244-6a46-491d-a6b0-79eec40e64cc`
- SYSTEM_PREDICTION：`b7fac59f-1da9-4ed3-8b06-ca848ae41862`
- 市场判断：退潮 / 高风险。
- 目标身位：2→3。
- 完整候选：超声电子、九鼎新材、中新赛克、凯盛新能。
- PREP 不预选具体股票，等待竞价与开盘主动确认。

## AUCTION

- 快照抓取：2026-09-14 09:25:46 +08:00
- Case：`e9f90c8a-a614-4cd3-8e74-fe9a7cbc9b9c`
- CandidateSet：`82ff8a41-ce5d-4c98-a356-0155501f6b26`
- Candidate hash：`14a0e7d9656797642b379e8a17d3ec33be7bb9ab1232c9e5e665a5ac5fed0ba0`
- SYSTEM_PREDICTION：`0dc56a3b-bd7f-4fed-a2aa-dada0ef7a5a2`
- 原始竞价快照 SHA256：`882a02fdcf033bb2e3183c8bcf20cf84ceef9893f0a19646e071386fe194a41f`
- 竞价涨跌幅：超声电子 +1.12%、九鼎新材 -5.23%、中新赛克 +10.00%、凯盛新能 +6.21%。
- 观察排序：中新赛克 > 凯盛新能 > 超声电子 > 九鼎新材。
- 具体选择：空。
- 原因：v3 明确不把竞价绝对强度等同买点；中新赛克竞价涨停仍需验证可成交性与开盘主动确认。

## R1

- 首个完整5分钟快照抓取：2026-09-14 09:36:01 +08:00。
- Case：`db6d9322-24c6-4059-a43f-e1d96b8b781f`
- CandidateSet：`4e968095-eed2-4de1-afdc-f6f5e26b96fe`
- Candidate hash：`44f9c906f40963e6bc981c6ca2a68dc3f5f5fd6fd64a2e664b7981fa874f28db`
- SYSTEM_PREDICTION：`26361711-7202-4e47-8722-2523ee14f14c`
- R1 归档 manifest SHA256：`5fbb8a44e6c44d90be247c2a51975811495623c8e34c9337531203a137d6592c`

R1 仅使用 09:35 前可见信息：

- 超声电子：竞价 +1.12%，09:35 收盘约 +6.13%；从竞价开盘继续主动上行，`STANDARD_ACCESS`。
- 中新赛克：竞价 +10%，09:31–09:35 全程一字涨停，`QUEUE_DEPENDENT`。
- 凯盛新能：竞价 +6.21%，09:35 约 +2.53%，竞价强度未兑现。
- 九鼎新材：竞价 -5.23%，虽有回收但 09:35 仍低于前收。

R1 冻结选择：**超声电子（sz.000823）**。
## 证据纪律

- AUCTION / R1 CandidateSet 均为 `FULL + STRICT_PIT`，因为候选全集在当时已冻结，且行情快照在实时窗口内归档并做哈希。
- 当前尚未取得期末50分 2026-09-14 的真实交易结果，因此**没有 OBSERVED_EXPERT 标签、没有 Validation、没有命中结论**。
- 后续无论期末50分是否买超声电子，v3 本次预测都不得修改；失败必须原样保留。
- 中新赛克的一字涨停明确保留为 `QUEUE_DEPENDENT`，不能把普通账户无法可靠取得的成交视为 Selection Alpha。

## 工程证据

前瞻冻结执行器新增5项专项测试；完整仓库回归：**763 passed / 0 failed / 0 skipped**。

执行器提供 `PREP / AUCTION / R1` 时间闸门、10分钟近实时限制、幂等重试和同 Frame 防改写约束。

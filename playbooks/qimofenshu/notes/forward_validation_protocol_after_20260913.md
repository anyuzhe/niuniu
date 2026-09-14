# 期末50分前瞻验证协议（research cutoff: 2026-09-13）

## 目标

从 research cutoff 之后开始，禁止再用已经知道的期末50分答案调整同一版本规则并宣称样本外成功。

## 固定版本

前瞻阶段基准定义：`meta-playbook-hypothesis-v3`。

v3 仍是 DRAFT，不代表已经证明 Alpha；但它的规则形成期到 2026-09-13 为止，后续新数据只能作为评估样本。

## 每个交易日的顺序

1. 在专家交易结果揭晓前冻结市场节点与可见信息。
2. 先决定目标身位或 `NO_TRADE`。
3. 重建该身位的完整 CandidateSet；缺数据必须标 PARTIAL，不能静默删票。
4. 根据 v3 当时规则记录选择、排序、veto 和执行访问等级。
5. 只有真实时间产生的系统记录才允许使用 `SYSTEM_PREDICTION`；历史补录只能是 `HUMAN_RECONSTRUCTION`。
6. 之后再取得期末50分真实交易，写入 `OBSERVED_EXPERT`，比较命中、漏选和误选。
## 评价指标

必须同时记录：

- 是否正确路由到目标身位；
- CandidateSet 是否 FULL；
- 专家真实选择是否在系统 Top-K；
- 精确命中 / 漏选 / 误选；
- `NO_TRADE` 是否正确；
- STANDARD_ACCESS 下是否真实可执行；
- QUEUE_DEPENDENT 成交是否依赖无法复制的排队优势；
- 次日及完整退出结果只能作为 outcome，不得回填选择特征。

## 规则升级

新样本失败时先记失败，不修改 v3。

只有累积到预先约定的一批前瞻样本后，才允许总结失败模式并创建 **v4**；v3 原定义、预测与失败记录永久保留。

FROZEN / HOLDOUT / WALK_FORWARD 仍需满足 Playbook Lab 已有的 VERIFIED 来源、FULL CandidateSet、STRICT_PIT 与执行审计门槛。

## 宿主前瞻冻结命令

生产入口：`niuniu-playbook-forward`。它**不下载行情、不替模型选股**，只负责时间闸门、合同校验与安全续写。

查询当前 Frame 是否允许冻结：

```bash
niuniu-playbook-forward --output artifacts --trading-day 2026-09-14 --frame AUCTION --status
```

AUCTION 虽属于 09:15–09:30 Decision Frame，但前瞻数据必须等到 **09:25** 才视为 ready；R1 必须等到 **09:35** 第一根完整5分钟K线后才视为 ready。

实际冻结使用 `--payload snapshot.json`；payload 必须引用当时已经归档的 ExpertSource，并同时冻结 Case、CandidateSet 与唯一 SYSTEM_PREDICTION。

相同 payload 重试会安全续写；同一 definition/day/frame 若想换另一份候选或预测会被拒绝。快照超过数据时点10分钟才提交也会被拒绝，不能事后冒充前瞻预测。

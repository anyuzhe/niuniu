# 郑希机构投资方法 Research Skill（接入脚手架）

## 当前状态

`SOURCE_REQUIRED`。本目录没有导入外部 `zhengxi-views` 语料、基金持仓数据或抓取脚本，也不把用户提供的二次概述冒充郑希原话。

## 目标行为

取得可核验资料后，按以下顺序工作：

1. 原始公开观点逐份保存 URL、原文字节、SHA256、`published_at` 与牛牛首次可用时间。
2. `DIRECT_QUOTE` 只引用原始观点；方法归纳写成 `METHOD_INFERENCE`；尚未证实的信息写成 `FACT_TO_VERIFY`。
3. 观点资料与季度披露持仓分别保存，再建立“说了什么 / 实际披露做了什么 / 后续结果怎样”的显式 alignment。
4. ROE 低位修复、行业景气、全球竞争优势、产业链利润再分配、流动性等只能先成为 DRAFT 假设和候选特征。
5. 由牛牛自己的财务、行业、价格、因子和持仓变化数据进行 CandidateSet、Holdout、Walk-forward、行业/市值中性及成本后验证。

## 禁止行为

- 不以“郑希风格评分”直接生成 BUY/SELL。
- 不把季度基金持仓用于 AUCTION/R1/R2/R3 的日内事实。
- 不因外部库称“真实数据”而升级 Strict PIT；仍须牛牛 publication-time/original-byte receipt。
- 不自动执行 `scripts/`，不自动联网，不写 StrategySource/Playbook，不创建 Decision、Paper 或订单。
- 不把观点与持仓一致解释为 Alpha，也不把基金业绩解释为某条方法规则的因果证明。

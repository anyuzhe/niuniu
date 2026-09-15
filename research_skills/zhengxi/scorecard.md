# Scorecard 语义合同

本包未来如形成评分，唯一允许的含义是：

> `SOURCE_STYLE_SIMILARITY_ONLY`：某个对象在已明确维度上与来源方法描述的相似度。

它不表示：

- 基金优劣；
- 股票质量的客观总分；
- 预期收益或胜率；
- 已验证 Alpha；
- BUY/SELL；
- Daily Scanner 排名；
- 可成交性或仓位建议。

任何维度权重、阈值和缺失值处理都必须先成为版本化 Playbook DRAFT；历史验证必须使用牛牛自己的 CandidateSet、PIT、Holdout/Walk-forward、行业/市值中性和执行成本合同。不能因“像来源会买”而跳过验证。

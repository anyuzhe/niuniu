# Retail Crowding V1 验证记录

日期：2026-09-27

## 范围与结论边界

本轮是宿主执行的冻结因子回顾性研究，复用 Research Lab 的 Holdout、Bootstrap、Block Sign Permutation、TrialRegistry 与 Holm；不是牛牛原生助手自主发现里程碑，也不是可成交 Alpha 认证。价格标签为收盘到未来收盘的 gross 预测标签，没有费用、滑点、涨跌停成交或真实订单模拟。

V1 只研究价量层面的“拥挤/追涨压力”代理，不把它等同于真实散户行为。真实 BuyImbalance、SmallTradeRatio 与搜索/股吧 Attention 数据留给后续 V2/V3。

## 冻结规格

- 原始 V1.0.0：[docs/reference/retail-crowding-v1.json](../../reference/retail-crowding-v1.json)。
- 当前 V1.0.1：[docs/reference/retail-crowding-v1.0.1.json](../../reference/retail-crowding-v1.0.1.json)，SHA256 db60a1e238cd8673a76785b8f0c663d9ae2b672ef6887d3aafd3f21c7d73ec89。
- 因子：MOM1/3/5/10/20、VolumeShock20、AmountShock20、RC1。
- RC1 = mean(z_prev20(MOM5), z_prev20(volume), z_prev20(amount))，基准窗口都不含当前日。
- 时间：2010-01-01 至 2026-09-23；train ≤ 2018-12-31，valid 2019–2022，test 2023–2026-09-23。
- 标签：T+1 / 3 / 5 / 10 / 20。
- 240 个固定检验槽：8 因子 × 3 阶段 × 5 期限 × IC/Rank IC；缺失槽位不从 Holm 分母移除。
- V1.0.1 的 permutation 为 9,999 次，Monte Carlo 最小 p=0.0001，小于 Holm 首档 0.05/240≈0.0002083。

V1.0.0 的 100 股工程 pilot 使用 999 次 permutation，最小 p 只能到 0.001，因此 240 项全族在数学上不可能通过 5% Holm。该原始结果保留但不作为“无显著性”的负证据；V1.0.1 只修正统计分辨率与固化既有 nullable-volume 研究口径，没有按收益结果修改公式、方向、日期、期限或检验槽。

## 数据与样本

当前扩大验证使用确定性 SHA256 分层样本：四板块各 100 只，共 400 只；symbols_sha256=78ca7b5761b24746a07ad5c5bc86fc05705e066ebfb377e9d623fc93b2ff5b5c。候选池先按 DATA qfq coverage 排除请求起点之后才有效的历史截断证券，再与 stock_basic、实际 qfq 文件及四板块范围取交集；不是 Strict PIT 可交易股票池。

400 股中 86 只有至少一个空量/空成交额日，共 847 行。沿用项目已审计的 research-only nullable-volume 口径：价格/时间/复权错误仍 fail-closed；空量/空额行保留在时间轴、不填 0，但该日不进入信号横截面。生产 MQC Provider 的严格空量拒绝没有放宽。

## V1.0.1 400 股主要结果

权威结果目录：artifacts/retail-crowding-v1.0.1-pilot400-20260927/（本机证据，不随代码推送）。

- TrialRegistry：20a6947cc107d9be8a6e554109013ca083a6fe5a655b2c4f7fd09192e817b709
- RC1 parent run：63e754f7-56b0-46de-b376-150d1db32186
- 240/240 计划检验有可用 p 值；129 项通过全族 Holm 5%，其中 Rank IC 92 项、Pearson IC 37 项。

### RC1

| 阶段 | 期限 | Rank IC | 95% block bootstrap | Q10−Q1 gross | Holm p | 全族拒绝零假设 |
|---|---:|---:|---:|---:|---:|---|
| train | 1 | -0.0615 | [-0.0682, -0.0552] | -0.106% | 0.0240 | 是 |
| train | 3 | -0.0547 | [-0.0633, -0.0476] | -0.343% | 0.0240 | 是 |
| train | 5 | -0.0512 | [-0.0605, -0.0417] | -0.553% | 0.0240 | 是 |
| train | 10 | -0.0298 | [-0.0408, -0.0203] | -0.402% | 0.0240 | 是 |
| train | 20 | -0.0225 | [-0.0323, -0.0127] | -0.500% | 0.0240 | 是 |
| valid | 1 | -0.0415 | [-0.0491, -0.0334] | -0.091% | 0.0240 | 是 |
| valid | 3 | -0.0304 | [-0.0416, -0.0193] | -0.259% | 0.0240 | 是 |
| valid | 5 | -0.0298 | [-0.0418, -0.0162] | -0.432% | 0.0266 | 是 |
| valid | 10 | -0.0213 | [-0.0354, -0.0066] | -0.507% | 0.4224 | 否 |
| valid | 20 | -0.0157 | [-0.0294, -0.0027] | -0.575% | 0.9731 | 否 |
| test | 1 | -0.0372 | [-0.0470, -0.0268] | -0.059% | 0.0240 | 是 |
| test | 3 | -0.0327 | [-0.0453, -0.0194] | -0.193% | 0.0240 | 是 |
| test | 5 | -0.0333 | [-0.0459, -0.0189] | -0.354% | 0.0357 | 是 |
| test | 10 | -0.0381 | [-0.0535, -0.0199] | -0.606% | 0.0357 | 是 |
| test | 20 | -0.0365 | [-0.0533, -0.0188] | -0.886% | 0.0266 | 是 |

Q10−Q1 < 0 表示高拥挤组后续 gross 收益低于低拥挤组。最终 test 段五个期限方向都与预登记“高 RC1 后续收益较弱”一致，并通过当前 240 项全族 Holm。

### 对照因子说明

样本外对照并没有显示 RC1 明显优于简单因子：

- MOM20：T+1/5/20 Rank IC 约 -0.0413 / -0.0611 / -0.0696，Q10−Q1 约 -0.093% / -0.658% / -1.332%。
- VolumeShock20：约 -0.0426 / -0.0353 / -0.0337，Q10−Q1 约 -0.128% / -0.366% / -0.829%。
- AmountShock20：约 -0.0445 / -0.0399 / -0.0420，Q10−Q1 约 -0.118% / -0.415% / -1.052%。
- RC1：约 -0.0372 / -0.0333 / -0.0365，Q10−Q1 约 -0.059% / -0.354% / -0.886%。

因此第一阶段证据支持“近期上涨/异常参与度高的股票随后横截面表现较弱”这一回顾性关联；不能据此把原因归结为散户趋同。第二阶段已按下文冻结控制组检验 RC1 的独立增量。

## 过程失败与修正留痕

1. 第一条 smoke 使用生产 MQC Provider，被真实 qfq 的空 volume/amount 行按设计 fail-closed；没有填 0 或换股票。失败目录 artifacts/retail-crowding-v1-smoke-20260927/ 保留。
2. 接入已有 normalize_research_frame 的 research-only nullable-volume 口径后，12 股 smoke2 完成 8 因子及 240/240 检验槽，仅作工程链路验证。
3. V1.0.0 100 股 pilot 完成后发现 999 次 permutation 与 240 项 Holm 的统计分辨率结构性不相容；原结果保留，不解释为“无效”。
4. V1.0.1 在扩大到 400 股之前冻结，只提高 permutation 至 9,999 并固化数据缺失口径；没有按已经看到的收益方向调因子权重、日期或持有期。

## 尚未验证

- 全 A 股合资格全集；当前是固定 400 股分层样本。
- 市值、行业、波动、ST、涨停制度等中性化/控制。
- 真实逐笔 BuyImbalance / SmallTradeRatio 的多年历史。
- 百度/股吧/雪球等 AttentionShock 历史。
- 成交成本、涨跌停不可成交、容量和组合构建。

所以本阶段是“值得继续验证”的行为金融候选，不是生产因子晋级结论。

最终代码（包含“按同一字节解析并记录SHA”的证据完整性加强）于2026-09-28再次对同一400股样本复跑到 artifacts/retail-crowding-v1.0.1-pilot400-final-20260928/；symbols SHA、240/240槽位、129项Holm拒绝、全部检验签名以及RC1三阶段全部数值与2026-09-27运行完全一致。


## 第二阶段：固定控制后的样本外残差增量

残差规格在读取任何残差结果前冻结为 [retail-crowding-v1.1-residual.json](../../reference/retail-crowding-v1.1-residual.json)：

- 候选：RETAIL.CROWDING_V1。
- 控制：MOM20 + VolumeShock20 + AmountShock20，没有按第一阶段结果更换控制项。
- 控制投影只使用 2010-01-01 至 2022-12-31 的因子值，不接触收益标签来拟合；2023-01-01 至 2026-09-23 只做 held-out 评价。
- 期限仍为 1/3/5/10/20 日，5 个残差 Pearson IC 构成一个 Holm 家族；9,999 次 block sign permutation，block=20日。
- 同一400股样本，4个源因子必须具有完全相同的 data snapshot 与 universe，否则 fail-closed。

最终证据：artifacts/retail-crowding-residual-v1-final-20260928/。四个源因子共享 snapshot 69b8906c1e1cbdbdb8c4e6d5fc6608a95e5072eff25be5e532e0b9914c9cf28b 和同一 historical_listing:quantity_aware_research universe。

| 期限 | 原始 Pearson IC | 残差 IC | raw p | Holm p | 是否支持预登记负方向 |
|---:|---:|---:|---:|---:|---|
| 1 | -0.01059 | +0.01454 | 0.0036 | 0.0180 | 否，且显著反向 |
| 3 | -0.01635 | +0.00481 | 0.4181 | 1.0000 | 否 |
| 5 | -0.02095 | -0.00097 | 0.8881 | 1.0000 | 否 |
| 10 | -0.02594 | -0.00801 | 0.3795 | 1.0000 | 否 |
| 20 | -0.02565 | -0.00868 | 0.2790 | 1.0000 | 否 |

结果非常清楚：没有任何一个期限出现“负残差IC + Holm显著”。T+1 残差甚至显著转正，方向与拥挤反转假说相反；其余期限残差接近0且不显著。

作为不参与检验的描述性诊断，控制投影在训练期解释 RC1 方差约 99.26%，在2023–2026样本外仍解释约 90.76%。这与 RC1 的构造方式一致：它本来就是价量分量的线性组合。这里没有使用完全相同的 z(MOM5) 作为控制，因为那会与另外两个精确分量一起把 RC1 在代数上几乎完全还原；预登记控制使用 MOM20，是在“更一般的中期反转 + 成交活跃度”基线之上问 RC1 是否还有额外信息。

残差结果在加入 source identity fail-closed 与描述性投影诊断后完整重跑，5个检验签名逐项一致。因此 V1 的阶段结论调整为：

> 价量拥挤现象本身存在，但 RC1 不具备已验证的独立增量 Alpha。

这意味着不应继续优化 RC1 权重来追显著性。后续若继续“散户趋同”方向，应转向真正新增信息的数据：逐笔主动买卖、成交笔大小/小单占比，以及独立的关注度历史；这些属于 V2/V3，不是继续调 V1。


## 第三阶段准备：真正逐笔微观结构 V2

V1 残差未显示独立增量后，没有继续调 RC1 权重，而是冻结新的 [Retail Microstructure V2 数据合同](../../reference/retail-microstructure-v2.json)。该阶段只增加真正不同的信息来源，不把价格/成交额重新包装成新因子。

TDX trades 当前合同只认证 volume_unit=lots_provider，逐笔 amount 为空，因此 V2 **不假定 price×volume 是人民币金额**。第一版使用无绝对金额依赖的比例型代理：

- BuyImbalanceProxy = 买方向 price×provider_lots 与卖方向同口径名义值之差 / 和。
- VolumeImbalance = 买卖 provider lots 之差 / 和。
- avg_lots_per_order_proxy = volume / order_count，仅 order_count>0 可用。
- SmallOrderThreshold = 每只股票每天 avg_lots_per_order_proxy 的20%分位。
- SmallOrderNotionalShare 与 SmallOrderBuyImbalance 只在这个底部20%代理子集计算。
- neutral/status side、零量行不参与方向值，但保留质量计数；若没有正 order_count，BuyImbalance 仍保留，小单字段为空。

实现位于 src/quantlab/data/retail_microstructure.py，宿主预览 scripts/research/retail_microstructure_v2.py，只读 catalog/mqc.duckdb，不联网、不写数据湖、不提升 TDX 的 personal-research 资格。

### 当前真实覆盖

2026-09-28 对 canonical 数据根的真实预览：

- tdx_trades_compacted 共 14,043,754 行、5个日期。
- 2026-09-17 原始覆盖 5,562 只，其中 5,553 只有有效 buy/sell 正价正量记录；V2 生成 5,553 行 BuyImbalance 等日特征。
- 其中 344 只当日没有可用的正 order_count 小单阈值，小单字段保持 null，不影响 BuyImbalance。
- 2026-09-16 只有 833 只可算特征；另外三个历史日期都只是单股测试记录。
- 覆盖门按 feature symbols 而不是原始出现证券数判断：当日需 ≥ max(3000, 当期最大feature symbols×90%)，且至少120个合格日。当前只有 **1/120** 个合格日，状态严格为 **INSUFFICIENT_COVERAGE**。
- 最终预览 artifacts/retail-microstructure-v2-preview-final-20260928/ 生成 6,389 行特征；所有 imbalance/share 都在 [-1,1] 或 [0,1] 合法区间；inference_performed=false。

因此现在 **不能** 回答 BuyImbalance / SmallOrderProxy 的未来收益效果。正确下一步不是在1天数据上跑p值，而是继续积累或回补逐笔历史；达到覆盖门后再冻结收益检验方案。

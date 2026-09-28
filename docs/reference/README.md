# 规则与来源参考

[文档导航](../README.md) · [总体架构](../architecture/overview.md)

以下文件是具体版本的规则合同，不是盈利承诺。规则变更须连同对应源码、测试、版本与因果性审查。

## 明确规则

- [Brooks Wedge 三极值收缩反转代理 1.0.0](theories/Brooks三极值收缩反转规则.md)
- [Brooks 突破、回踩与测量目标规则 1.0.0](theories/Brooks突破回踩与测量目标规则.md)
- [Brooks 背景状态规则 1.0.0](theories/Brooks背景状态规则.md)
- [Chan 确认推进规则 1.0.0](theories/Chan确认推进_线段背驰与买卖点规则.md)
- [Wyckoff 价格阶段代理：BCDE 1.0.0](theories/Wyckoff价格阶段_BCDE规则.md)
- [威克夫 A–E：可复现 OHLCV 规则链 v1](theories/威克夫_AE规则与因子链路.md)
- [Chan 包含与 ICT OB：明确规则 1.0.0](theories/理论扩展规则_Chan包含与ICT_OB.md)
- [跨实验固定检验族：本地登记与 Holm 校正 1.1.0](theories/跨实验试验登记与Holm校正规则.md)
- [Retail Crowding V1 冻结规格 1.0.0](retail-crowding-v1.json)：固定 MOM1/3/5/10/20、成交量/成交额异常与 RC1 公式、时间分割和统计检验族；不含逐笔散户流与关注度数据。
- [Retail Crowding V1 冻结规格 1.0.1](retail-crowding-v1.0.1.json)：公式、方向、日期和240项Holm族不变；仅修正999次置换无法达到首档Holm阈值的统计分辨率，并固化既有nullable-volume研究口径。当前执行版本。
- [Retail Crowding V1 残差增量规格 1.0.0](retail-crowding-v1.1-residual.json)：固定 MOM20 + VolumeShock20 + AmountShock20 控制，只用≤2022拟合，2023–2026检验5个残差IC期限。
- [Retail Microstructure V2 数据合同 0.1.0](retail-microstructure-v2.json)：固定逐笔买卖失衡、小单代理与120日覆盖门；当前只构建特征，不做收益推断。
- [Retail Microstructure V2 数据合同 0.2.0](retail-microstructure-v2.0.2.json)：在0.1逐笔特征定义不变的基础上，新增canonical三分片逐日完整度门；任一shard不足即阻断推断。

## DATA / CODE 协作

- [DATA → CODE 数据清单](data-catalog.md)：由数据侧维护“有哪些数据、数据在哪里、覆盖范围与是否可供代码使用”；代码侧按清单读取，不重复承担数据正确性审计。
- 代码侧提给数据侧的需求：[2026-09-25 日内大盘与更多股票数据需求](data-requests/20260925-日内大盘与更多股票数据需求.md)（待数据侧处理）。

## 运行时知识与第三方来源

[Agent 工作记忆](../../agent_memory/README.md)、[Playbooks](../../playbooks/README.md)、[Research Skills](../../research_skills/README.md) 保持原位，因为它们参与程序加载、授权或内容指纹校验。

[Alpha 来源](../../src/quantlab/factors/ALPHA_PROVENANCE.md)、[Alpha 许可证](../../src/quantlab/factors/ALPHA_LICENSE)、[缠论来源](../../src/quantlab/_vendor/chanpy/PROVENANCE.json)、[缠论许可证](../../src/quantlab/_vendor/chanpy/LICENSE) 继续跟随代码，不能归入普通历史文件夹。

# 数据与证据说明

[文档导航](../README.md) · [使用指南](user-guide.md) · [当前状态](../project/status.md)

本文件解释代码采用的数据合同，不签发资料资格证书。某天、某只证券是否具备合格数据，必须检查对应 snapshot、receipt、publication time 和实际字节。

## 1. 三种位置不要混用

| 位置 | 保存内容 | 整理原则 |
|---|---|---|
| `/Volumes/Lexar/niuniu` | 源码、受版本控制的规则、说明 | Git 管理 |
| `/Volumes/Lexar/niuniu-data` | 牛牛独立行情及证据数据根 | 本轮不移动、不重写 |
| 项目 `artifacts/` | 实验、工作空间、Decision、任务与验收日志 | 不入 Git，不当普通文档搬家 |

`/Volumes/Lexar/MQC-DATA` 保留为旧 MQC 来源。历史实验中的旧绝对路径是来源证据，不做批量替换。备份、归档和当前运行根也不能仅凭名称相似而互相覆盖。

## 2. 本地行情适配

[local_data_provider](../../src/quantlab/data/provider.py) 按明确标记选择 approval freeze、Baostock series、Baostock dataset，最后才使用 MQC Parquet 适配器。损坏的显式标记是错误，不能静默回退成另一数据来源。

原 MQC 布局示意：

```text
niuniu-data/lake/
├── bronze/provider=baostock/
│   ├── stock_kline_daily/sh_600000.parquet
│   └── stock_kline_min5/sh_600000.parquet
└── silver/
    ├── qfq_kline_daily/sh_600000.parquet
    └── qfq_kline_min5/sh_600000.parquet
```

该布局不是任意 Parquet/CSV 的自动识别规则。字段与编码以 [mqc.py](../../src/quantlab/data/mqc.py)、[validation.py](../../src/quantlab/data/validation.py) 为准。内部证券编码例如 `sh.600000`；高周期数据须按真实交易时段和 available_at 对齐，不能从 5m 反推真实 1m。

AR 回溯日线还有独立的 pack 合并与读取实现，见 [retro_daily.py](../../src/quantlab/data/retro_daily.py)。历史小文件到 pack 的迁移已记录在 AR 验收中；本轮只整理文档，不重复执行合并或删除数据。前瞻日增量见 [forward_daily.py](../../src/quantlab/data/forward_daily.py)。

## 3. 研究价格和账户价格

客户端及研究 CLI 默认 qfq；底层 `build_runner` / MQC API 默认值不同，直接调用 Python 时须显式指定 adjustment。默认 `execution.price_mode=research` 使用研究价格，不重复记入已体现在复权中的公司行动。

`execution.price_mode=account` 才进入 raw 价格和显式公司行动账户口径。执行费用、交易日规则、T+1、整手、滑点及拒单应由独立执行模块处理，不能拿未来标签收益当作实际账户收益。

| 执行后端 | 作用 |
|---|---|
| `open` | 默认独立成交回测 |
| `vnpy_open` | vn.py 受限共同模型的对照路径 |
| `vnpy_rules` | 与本平台规则及账务适配的离线路径 |

后两者需要可选依赖，不是实盘券商通道。qimo 模拟盘费用合同已在 AR 线升级，既有授权的兼容/重新授权要求以对应控制和验收记录为准，不能擅改历史成交账本。

## 4. 四类资格逐请求判断

| 资格 | 可以表达什么 | 不能据此推出什么 |
|---|---|---|
| `research_only` | 当前材料可用于明确限制下的研究 | 历史当时可得、可成交、Alpha |
| `retrospective_reference` | 事后取得的历史参考 | 当时已存在的完整信息集合 |
| `strict_pit` | 本次请求所用资料通过相应时点证据门 | 所有证券、所有日期都已覆盖 |
| `official_rule_covered` | 本次范围的官方交易规则证据通过要求 | 全市场总资格或真实订单可达性 |

PIT Universe receipt 证明的是 exact session 的声明全集。SecurityStatus v2 要绑定同日全集全部成员；零散 ST/停复牌 statement 不能跨日传播。连续状态变化须有显式相邻 snapshot 链。MarketRules 和历史行业/市值各有独立证据要求。

官方 URL、文件哈希、Git 时间、HTTP Date、事后取得的官方历史价格，都不能单独证明某信息在当时可得。即使价格边界算术正确，也可能只能作为回顾性参考。Coverage 是 presence/inventory，不是可拼出的“数据集总完成率”。

## 5. 问答实时行情与正式快照

| 链路 | 当前实现 | 边界 |
|---|---|---|
| 个股临时问答 | 配置扶摇后主用扶摇，腾讯/东财/新浪两源共识交叉校验或回退 | 不写正式 MarketSnapshot、Decision 或订单 |
| Daily Orchestrator 的正式快照 | Provider Registry、明确 capture 授权、Frame/时钟与冻结合同 | 不是凭一次问答或供应商响应就合格 |
| AR 股池、龙虎榜、主题和盘中材料 | 供应商公开证据归档与研究派生 | 与 Strict PIT/官方规则区分，结果列不得前置使用 |

扶摇能力与实际只读接线见 [fuyao_tools.py](../../src/quantlab/agent/fuyao_tools.py)、[fuyao_market_snapshot.py](../../src/quantlab/trading/fuyao_market_snapshot.py)。没有凭证时仍可使用既有公开网页链路；两侧价格冲突要保留 PARTIAL/consensus_issues，不挑有利数据。

问答层的自动查询范围不等于底层 Provider 最大批量，也不授权持续刷新、全市场下载或真实交易。凭证由环境/钥匙串读取，不写进 Markdown、Git、测试输出或模型提示词。

## 6. 哪份记录说了算

Git Markdown 保存规则、说明、工程经验与架构；结构化归档保存数值、时点、候选集、预测、Decision、成交和持仓。Markdown 可以链接与解释，但不能覆盖后者。

实验常见产物有 `experiment.json`、`observations.parquet`、`report.md`、按需的 `bars.parquet` 与成交/持仓明细；本地索引常用 DuckDB。具体文件以实验类型为准。跨环境复算需匹配配置、源数据和依赖，不能仅凭源码指纹认定所有行情已复制。

原始数量、历史研究结果和当时的证据缺口保留在 [数据验收归档](../archive/README.md) 和 [开发史](../project/changelog.md)。这些数字附属于记录日期；本轮未重新审计外部数据根，不把旧数值换个标题写成最新覆盖率。

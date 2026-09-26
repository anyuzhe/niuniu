# gst_intraday 底仓做T 规律筛选（2026-09-25，人工复算用）

这些脚本是开发者为“日内做T”页挑选策略时做的一次性研究，只用于复算和核对，不是产品入口，也不是牛牛助手的研究工具。结论与数字见 `docs/archive/intraday/20260925-日内做T策略研究.md`。

- 数据：数据侧 `gst_intraday`（清单 §3.6），只读打开；`GST_DB` 可改库路径（默认数据清单给出的路径）。
- `build_grid.py`：把 16 只股票每个可用日的 1 分钟K 排成“股票日 × 240 分钟”的矩阵，存到 `GST_GRID`（默认 `~/research/grid.npz`）。约 30 秒。
- `lib.py`：读矩阵，算前值填充的价格、均价、主动买卖量、涨跌停价、成本（每边 1 个价位 + 佣金 + 印花税 + 过户费）和按日期聚类的 t 值。
- 训练期 = 2022-12-31 及以前。筛选脚本只看训练期：`scan.py`（480 组：15 个指标 × 8 个时点 × 4 个分位）、`down.py`、`refine.py`、`family.py`、`more.py`、`famA.py`、`linear.py`、`ridge2.py`（2019–2021 拟合、2022 留出验证，最后用整个训练期拟合出 `CloseScore` 的系数）。合计约 650 种组合，结论要按多重比较打折看。
- 检验期只在策略和参数固定后，用产品引擎（`quantlab.intraday.backtest`）跑了一次。
- 第二轮（同日）：`auction.py`、`gapdown.py`（两头集合竞价/低开）、`grid.py`（挂单网格）、`breakout.py`（突破）、`scan2.py`（收盘竞价平仓扫描）、`ridge_multi.py`、`combo.py`（多时点打分）、`baseline.py`（每天都先卖的对照）、`wf.py` / `wf2.py` / `wf3.py`（训练期内逐年滚动比较变体）、`stops.py`、`regime.py`、`wf_final.py`（生成 `quantlab/intraday/morning_models.py` 的逐年系数）。
- 第三轮（趋势突破）：`trend.py`（开盘区间 15/30 分钟、昨日高低点、30/60 分钟唐奇安通道 × 两个方向 × 放量/大盘/均价线/主动买卖过滤）、`trend2.py`（大盘门槛与跟踪止损、均价线出场）、`trend3.py`（多日趋势同向/反向）、`trend_test.py`（唯一预先选定的一组在 2023–2024 的一次检验）。
- 第四轮（外部资料与盘口）：`gao.py` / `gao2.py`（大盘日内动量在 16 只平均上的复现，以及用它做个股 T 的扣费结果）；`orderbook/`：`build.py`（五档快照整理，2019-05..2020-06）、`feat.py`、`ic.py`（盘口失衡、微价格、主动流对未来 30 秒到 10 分钟中间价的相关性）、`mm.py`（排队挂单做 T，保守排队成交模型）、`exec.py` / `timing.py`（已有先卖信号的真实盘口成交价、挂单进场与按盘口择时）。
- 第五轮（缠论 + 盘口）：`chan/`：`chanlib.py`（用仓库固定的缠论核心逐根 1 分钟 K 线增量计算，只记录笔已确认的买卖点及确认时刻）、`runchunk.py`（按股票 × 年份分块，前置 10 个交易日预热）、`evalchan.py` / `run_eval1.py`（各类买卖点 × 三种出场）、`run_eval2.py`（大盘同向过滤、线段级买卖点）、`run_eval3.py`（2019-05..2020-06 用盘口失衡与主动成交确认）。
- 第六轮（提前判断一买）：`chan/b1_value.py`、`b1_value2.py`（事后知道一买位置时提前买入的收益上限，多种出场）、`b1_book.py`（2019-05..2020-06 下跌段创新低时用盘口衰竭信号实时买入）。
- 第七轮（全市场 5 分钟）：`market5m/`：`breadth.py`（从 READY 的 `bars_min5_baostock_raw` 按年算全市场每 5 分钟等权涨跌、上涨家数占比，临时口径，只作研究）、`wf_mkt.py`（16 只上午打分换成全市场大盘）、`universe.py`（每年上一年成交额前 500 只、股价 ≥8、非 ST）、`feat5.py`（500 只的 10:00/10:30 特征）、`wf500.py` / `wf500b.py`（逐年滚动：整体模型、大盘择时与个股选择拆开）、`timing.py`（10:00 大盘择时做T）。
- 第八轮（数据侧新数据的样本外检验）：`market5m/oos2026.py`（2020–2024 定下的大盘择时与个股上午打分，原样放到 2026-05-21..09-24 的 `market_intraday_breadth` 与 `tdx_kline_min1` 上）、`market5m/index_mom.py`（`tdx_index_kline_min5` 2024-09 起按半年看“早盘→余下全天”的指数日内动量）。
- 第九轮（正式 5 分钟全市场情绪）：`market5m/timing2.py`（`market_intraday_breadth_5m` 2020–2026 逐年滚动的 10:00 大盘择时，含近 120 日相关开关；需先按 2020–2026 重跑 `universe.py`、`feat5.py`）。
- 第十轮（平台突破、放量突破、大盘随动）：`breakout5m/`：`build5.py`（每年 500 只的 5 分钟矩阵，含上一年末约 30 个交易日作历史）、`lib5.py`（读取、同时段 20 日均量、多日高低点、20 日 β、全市场情绪对齐、正T 成交与出场）、`scan.py`（A 日内平台 / B 多日平台 / C 放量突破 / Z 对照）、`scanD.py`（大盘随动）、`agg.py`（按 2020–22 / 2023–24 / 2025–26 汇总）、`diag.py`（毛收益与次日出场诊断）。
- 第十一轮（突破后波段出场）：`breakout5m/exits.py`（按年、按买点跑止盈/止损/回撤/限时出场，并记录 30 分钟内最大涨跌幅与同日同时点全体对照；内存小时每次 3–5 个买点）、`aggx.py`（汇总）、`m1.py`（`tdx_kline_min1` 2026-05..09 的 1 分钟复核）。
- 第十二轮（反向做法）：`breakout5m/rev.py` + `revagg.py`（开盘先卖按开盘前特征分组、10:00/10:30 横截面反转）、`gapfade.py` + `gfagg.py`（大幅高开先卖，收盘封板则次日开盘买回，多种买回方式）、`sector.py`（申万一级板块补涨；`lib5.py` 增加了昨日涨停、前 2/6 日收盘等字段）。
- 第十三轮（3 秒级冲刺剥头皮）：`tick/scalp.py`（读 `orderbook/build.py` 生成的每只股票盘口数组，按下一张快照卖一买入、买一卖出，扫描放量/平台信号 × 出场）、`scalp_agg.py`（汇总）、`fwd.py` + `fwagg.py`（信号后中间价变动与买一越过买入价的概率）、`fwd2.py`（逐只股票：价位大小、价差、1 分钟后净收益）。
- 第十四轮（隔夜T 与 ETF 做T）：`breakout5m/overnight.py` + `onagg.py`（收盘买、次日卖底仓，按收盘时可知特征分组）、`etf.py`（`python3 etf.py idx` 用 6 个指数 5 分钟线按 ETF 成本测早盘动量与开盘区间突破；`python3 etf.py breadth` 用全市场等权情绪做 2020–2026 参照）。

# 低频抄底（V1 / R2）扣成本重测与 ETF 版（研究，仅手工验证）

- `build.py`：从 `silver/qfq_kline_daily_v2` 和 `bronze/provider=baostock/daily_status_v2` 的已登记路径读全市场日线，存成 `panel.npz`（放在 `$HOME/research/lowfreq/`，不进仓库）。
- `lowfreq.py [最低20日均成交额]`：股票。V1 基准/候选、R2 收盘位置/低波动，另加两条参照；次日开盘买、第 H 天收盘卖，7.2 bp + 每边 1 个价位；三段历史、按月聚类 t、对全市场同期平均的超额。
- `etf_lowfreq.py`：同样的规则和 ETF 尺度规则（5/10 日跌幅、截面反转、截面动量），ETF 佣金 2 bp、无印花税、每边 0.001 元；含分红拆分日的窗口剔除。
- `etfcore.py`：`etf_lowfreq.py` 的数据和信号部分（无打印），供 `etf_robust.py` 引用。
- `etf_robust.py`：去重叠（同一只 ETF 持仓期间不再开仓）、价格≥2 元、分年、分类别、去掉最大贡献者、持有期形状。

只读已登记的数据路径；不联网，不碰实盘客户端。记录见 `docs/archive/testing/20260930-低频抄底扣成本重测与ETF.md`。
- `swing.py`：抄底后“涨到目标就卖”（止盈 +3/5/8%，可加 −8% 止损，最多持有 20 天），与同一批日期随机股票用同一规则比较。
- `swing2.py` / `swing3.py` / `swing4.py`：抄底后“回补前 20 日最高价缺口的 33/50/67/100% 就卖”（最多持有 30 天，可加 −10% 止损）。swing3 加去重叠和对同月份随机股票的超额；swing4 再控制波动率与成交额五分位。
- `dipfeat.py`：抄底候选（20 日跌>10%、非 ST、股价≥3 元、上市满 250 日、流动性≥5,000 万）+ 26 个因子 + 20 日净收益标签，存 `dipfeat.npz`。
- `dipic2.py`：因子筛选（排名 IC、最高/最低 20% 分位差、月聚类 t）；只用 2020–22 选，之后样本外。
- `dipregime.py` / `dipregime2.py`：按“当天市场状态”分组的抄底净收益；恐慌日（全市场 20 日涨跌 ≤ −3.6%）内的候选 vs 随机股票、因子排序。
- `dipbt.py` / `dipwf.py`：恐慌日买分数最高的 K 只的组合回测（路径法，含成本）；`dipwf.py` 为逐年滚动选因子的打分 A，以及假设型“超卖深度”打分 B。
- `mkreg.py` / `etf_panic.py`：把恐慌日信号用到宽基 ETF 上。
- `swing5.py`：`swing4.py` 加股价下限和剔除 4 月中旬到 5 月中旬信号日的稳健性版本。
- `etfpanic_bt.py`：恐慌信号的 ETF 组合回测引擎（复权总收益、分批/按深度加仓、时间/恢复/止损退出、佣金 1bp + 每边 1 个价位、现金 0 收益），直接运行输出参照与三种仓位方案；依赖 `etfcore.py` 和 `mkreg.py` 生成的 `mkreg.npz`。
- `etfpanic_grid.py`（阈值/持有天数/批数/退出/仓位/标的/滚动阈值）、`etfpanic_eps.py`（逐段行情、分年、最大回撤）、`etfpanic_extra.py`（闲置资金收益、把信号换成 ETF 篮子自己的涨跌）。
- `swingbook.py`：买点 × 卖点网格（11 个买点 × 10 个卖点，指标含 MA/RSI/MACD/布林/20 日高低；路径法模拟止损/移动止损/信号出场），以同月份随机买点同卖法为基准，直接运行输出三段超额。`swingbook2.py`：引用 `swingbook.py` 的指标，做布林下轨收复的 10 个变体 × 更长持有，并做日度盯市的组合回测（单票 ≤ 1/N、扣成本）；依赖 `mkreg.py` 生成的 `mkreg.npz`。记录见文档 §11。
- `panic26.py`：恐慌日信号的收益拆分（大盘 + beta 放大 + 选股残差）、2026 年各恐慌段、按恐慌深度分层的大盘 20 日后收益；引用 `swingbook.py`。记录见文档 §11.5。
- `etfpanic_depth.py`：恐慌深度分层的宽基 ETF 事件研究 + 不同阈值/持有天数的组合回测；`etfpanic_t26.py` 列出 −9%/20 天与 −12%/40 天的全部交易。引用 `etfpanic_bt.py`。记录见文档 §12。
- `etfpanic_mk10.py`：用全市场 10 日（对比 20 日）跌幅做信号，ETF 篮子持有 10/20 天的事件研究和组合回测。记录见文档 §13。
- `pp_feat.py`：恐慌日（等权 20 日 ≤ −6%）候选股的 28 个因子行和 10/20 天净收益标签，存 `pp_feat.npz`；`pp_ana.py`：因子排名 IC / 分位差，按段聚合；`pp_ana2.py`：入选因子、反转族打分、前 20% / 前 30 只、大票检验、十分位、深度恐慌日及单次建仓逐笔。引用 `swingbook.py`。记录见文档 §14。
- `build_ext.py`：把个股面板拉到 2007-01-04（float32，存 `panel_ext.npz`）；`mkreg_ext.py`：长样本的市场信号（等权 20 日涨跌，存 `mkreg_ext_liq.npz`）；`etfcore_ext.py` / `etfpanic_bt_ext.py`：从 2007 年起的 ETF 日历和组合引擎（改自 `etfcore.py` / `etfpanic_bt.py`）；`etfpanic_ext_run.py`：分时期事件研究、一次性规则逐笔和分时期组合指标；`etfpanic_ext_cond.py`：反弹确认等条件。记录见文档 §15。
- `etfpanic_regime.py`：深度恐慌日按年份、250 日均线、距高点回撤、连环下跌分层，以及信号后大盘是否继续下跌。记录见文档 §15.4。
- `etfpanic_dyn.py`：动态（波动率标准化 / 滚动分位）恐慌因子和大盘布林下轨收复，ETF 篮子事件研究和可执行规则；`stockdyn.py`：2008–2026 个股布林下轨收复 × 动态市场状态（年代化成本）。记录见文档 §16。
- `stockport.py`：2008–2026 个股布林下轨收复 × 动态市场超卖门的组合回测（日度盯市、年代化成本、N=10/20、多种门和对照、逐年、最新状态）；引用 `stockdyn.py` 的前半段。记录见文档 §17。
- `intra_snap.py`：从 `bars_min5_baostock_raw`（READY）按年抽取 8 个盘中时点的价格快照（时点收盘价、下一根开盘价、当日开盘价），存 `snap_YYYY.parquet`；`intra_e6.py`：用时点价格重算布林下轨收复信号和闸门 z，事件研究、价格路径、并存事件；`intra_port.py`：封顶 20 只的盘中买法组合回测和对照。引用 `lowfreq/panel.npz`、`panel_ext.npz`、`mkreg_ext_liq.npz`。记录见文档 §18。

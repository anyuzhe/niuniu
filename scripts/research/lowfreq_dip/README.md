# 低频抄底（V1 / R2）扣成本重测与 ETF 版（研究，仅手工验证）

- `build.py`：从 `silver/qfq_kline_daily_v2` 和 `bronze/provider=baostock/daily_status_v2` 的已登记路径读全市场日线，存成 `panel.npz`（放在 `$HOME/research/lowfreq/`，不进仓库）。
- `lowfreq.py [最低20日均成交额]`：股票。V1 基准/候选、R2 收盘位置/低波动，另加两条参照；次日开盘买、第 H 天收盘卖，7.2 bp + 每边 1 个价位；三段历史、按月聚类 t、对全市场同期平均的超额。
- `etf_lowfreq.py`：同样的规则和 ETF 尺度规则（5/10 日跌幅、截面反转、截面动量），ETF 佣金 2 bp、无印花税、每边 0.001 元；含分红拆分日的窗口剔除。
- `etfcore.py`：`etf_lowfreq.py` 的数据和信号部分（无打印），供 `etf_robust.py` 引用。
- `etf_robust.py`：去重叠（同一只 ETF 持仓期间不再开仓）、价格≥2 元、分年、分类别、去掉最大贡献者、持有期形状。

只读已登记的数据路径；不联网，不碰实盘客户端。记录见 `docs/archive/testing/20260930-低频抄底扣成本重测与ETF.md`。
- `swing.py`：抄底后“涨到目标就卖”（止盈 +3/5/8%，可加 −8% 止损，最多持有 20 天），与同一批日期随机股票用同一规则比较。
- `swing2.py` / `swing3.py` / `swing4.py`：抄底后“回补前 20 日最高价缺口的 33/50/67/100% 就卖”（最多持有 30 天，可加 −10% 止损）。swing3 加去重叠和对同月份随机股票的超额；swing4 再控制波动率与成交额五分位。

# Chan 包含与 ICT OB：明确规则 1.0.0

> 版本化规则参考：保留原有算法合同与验证记录；本次仅调整文档位置和链接，不更改规则。命令从仓库根目录执行。[文档导航](../../README.md)

这些是平台冻结的 OHLC 可复现变体，不是对某一交易理论所有判图方法的实现。旧 CHAN.*、ICT.* 基础因子保留，新因子使用独立标识。只用已知数据，事件以 available_at 进入研究与回放。

## Chan 包含确认

按证券逐根处理。当前合并条与新条只要一个高低区间包含另一个，即为包含（允许相等边界）。方向尚未知的起始连续包含使用并集包络；方向向上时取 max(high)、max(low)，向下时取 min(high)、min(low)。遇到非包含后继才发布前一合并条，并根据新条的区间方向更新合并方向。

合并条 datetime 为最后一根组成原始条的时间，available_at 为确认它的后继条的可用时间。未完成尾条不发布。保存组成时间、确认条时间及合并边界。合并 open/close 裁剪到合并区间内，volume/turnover 求和；**合并条只供结构算法，不能用于成交价或替换原始行情**。

后续严格左右分型、交替笔、三笔重叠沿用现有 ChanAdapter 的明确规则；left/right/min_separation 现在计数的是已完成合并条，而非原始条。默认 2/2/3。保留先接受的同侧端点，不回写更极端的后续端点；同时高低分型不作笔端点。

| 新因子后缀（完整前缀 CHAN.INCLUSION_） | 事件 |
|---|---|
| BAR | 合并条确认，包括未发生包含的单条 |
| PIVOT_HIGH / PIVOT_LOW | 合并条确认后的严格分型 |
| BI | 确认的交替笔 |
| CENTER | 每个连续三笔窗口的严格重叠，窗口可以重叠 |
| ACTIVE_CENTER | 无活动中枢时，最先形成的三笔重叠创建独立中枢周期 |
| CENTER_EXTENDED | 新确认笔与活动中枢仍有正长度重叠，中枢上下界冻结 |
| CENTER_EXIT_UP / CENTER_EXIT_DOWN | 整笔下沿 ≥ 中枢上沿，或整笔上沿 ≤ 中枢下沿，确认离开 |

CENTER 是滚动窗口统计；ACTIVE_CENTER 是生命周期创建，数量不同，不得混算。离开后清空该周期，至少三笔全新确认笔才可创建下一周期，不复用离开笔。延续不扩张边界；离开不是买卖点。每个后缀都是当根事件 0/1；同根多个同类事件仍输出 1，明细留在事件审计中。

未实现：线段特征序列、背驰、买卖点及其他主观判定。保守发布会增加确认延迟，不能按 occurred_at 回填信号。

## ICT OB 生命周期

向上、向下分别独立跟踪，可同时存在多个区间。创建必须同时满足：

1. 本根收盘发生对应方向的已确认摆动 BOS，且同根满足既有 ATR 实体位移阈值。
2. 在此前 search_bars 根中找到最近反向实体条（向上找 close < open，向下找 close > open；十字星不算）。使用它的完整 low/high 为冻结区间。
3. 创建收盘已经离开区间近端：向上 close > upper，向下 close < lower。
4. 锚点之后、创建之前，没有中间收盘越过区间远端。锚点每方向最多使用一次，即使此前区间已过期也不复用。

默认继承 ICT 参数 lookback=20、left=2、right=2、atr_multiple=1.5、body_fraction=0.7，另加 search_bars=10、max_age_bars=100。已有 max_gap_seconds 参数保留兼容，但 OB 不使用 MSS 序列的时间间隔判定。

创建条不同时触发接触或失效。后续每根按以下固定优先级处理：

| 优先级 | 条件 | 结果 |
|---|---|---|
| 1 | 距创建的已观察证券条数 > max_age_bars | EXPIRED，停止跟踪；等于时仍有效 |
| 2 | 向上 close < lower，向下 close > upper | INVALIDATED，停止跟踪；不再同根报首次接触 |
| 3 | high ≥ lower 且 low ≤ upper，尚未接触过 | TOUCHED，只触发一次，之后仍可失效/超时 |

这只定义收盘可知的优先级，不假定盘中先后路径。缺失交易条不会按日历补计；年龄按该证券实际观察到的 K 线数计算。边界相等算接触，不算收盘失效。

完整因子为 `ICT.OB_CREATED_UP/DOWN`、`ICT.OB_TOUCHED_UP/DOWN`、`ICT.OB_INVALIDATED_UP/DOWN`、`ICT.OB_EXPIRED_UP/DOWN`，均 1.0.0。创建事件存原始锚点、区间、BOS/位移确认依据；生命周期事件不修改历史记录。未完成尾部区间保持开放，不提前写出失效或超时。

这是价格区间代理，不能据此声称观察到机构订单、真实盘口流动性或可成交挂单。

## 研究入口与回放范围

新增模板：RESEARCH.CHAN_INCLUSION_CENTER_MOMENTUM、RESEARCH.ICT_OB_TOUCH_MOMENTUM。均组合当根结构事件与 20 根正动量，复用完整理论研究入口：组件、组合、消融、固定样本外、滚动及预设参数敏感性。

事件保存在 experiment.json.sequence_audit，现有 K 线回放按 available_at 截断，可查看事件及边界元数据。本轮没有新增专用 OB/合并 K 线矩形绘图界面，原始 K 线仍是回放底图。

首批真实验证与限制见 [验收报告](../../../artifacts/theory-extensions-acceptance/report.md)。

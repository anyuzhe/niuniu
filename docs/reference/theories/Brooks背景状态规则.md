# Brooks 背景状态规则 1.0.0

> 版本化规则参考：保留原有算法合同与验证记录；本次仅调整文档位置和链接，不更改规则。命令从仓库根目录执行。[文档导航](../../README.md)

BrooksContextPack 是总体方案 TradingRange、Climax、AlwaysIn 的明确 OHLC 代理定义，使用已有因子、条件研究和事件回放接口。它不实现完整主观 Brooks 判图，不提供持仓建议，也不推断机构活动或成交量高潮。

## 参数与时间

逐证券、单周期独立计算。lookback=N 默认 20，整数 `[2,10000]`。当根索引 i 至少为 N+1 才输出，此前为 null：需要此前 N 个完整真实量程及它们的前收盘。窗口是 `[i-N,i)`，排除当根；用于方向效率的额外收盘锚点为 `i-N-1`。

其余参数均要求有限正数：max_width=0.1；max_efficiency=0.3、climax_body=0.8、breakout_body=0.5 均不大于 1；climax_multiple=2.0 且必须大于 1。拒绝 bool、NaN、无穷及未知参数。重复 symbol/available_at 被拒绝。

## 交易区间状态 CTX_RANGE

此前 N 根最高 high 为 upper、最低 low 为 lower。相对宽度 `(upper-lower)/lower` 不超过 max_width，且方向效率不超过 max_efficiency 时输出 1，否则 0。

方向效率为 `abs(close[i-1]-close[i-N-1]) / sum(abs(close[j]-close[j-1]))`，求和 j 从 i-N 到 i-1；总路径为零时定义为 0。相等边界包括在内。零宽、静止行情可标为区间，但这不证明流动性充足。

这是滞后窗口背景：当根发生巨大突破时，CTX_RANGE 仍可能为 1，因为当根不进入背景窗口。不应将其误读为当根收盘仍在区间内。

## 扩张事件 CTX_CLIMAX_UP / DOWN

真实量程 TR 为 `max(high-low, abs(high-prev_close), abs(low-prev_close))`，包含跨交易日跳空，不按日重置。此前 N 根 TR 的算术平均必须大于零。

当根 TR 至少为此前平均值乘 climax_multiple，并且绝对实体 `abs(close-open)/(high-low)` 至少为 climax_body，发布按实体方向区分的事件。高低跨度为零时实体比例为 0，不触发；大跳空十字星也不因跳空单独触发。连续符合条件的条可连续发布事件。

它只检测放大量程且强实体的价格条，不自动判断趋势耗竭、反转、成交量高潮或真正的 buying/selling climax。

## 持续方向 CTX_ALWAYS_IN 与 FLIP

预热结束后初始为 0。满足以下条件时采用新方向：

- 当根正实体比例至少为 breakout_body，且收盘严格高于此前窗口 upper：方向 +1。
- 当根负实体比例至少为 breakout_body，且收盘严格低于此前窗口 lower：方向 −1。

其余情况保持上次方向。首次从 0 进入 ±1 或反向切换，分别发布 CTX_FLIP_UP/DOWN；同方向再次突破不重复发布 FLIP。方向一旦建立，不因回调、重新进入区间或跨日而归零，直到满足反向突破。每次研究窗口从自身加载历史重新计算，因此不同历史起点可能产生不同初始方向，不能当作跨窗口共享真实账户状态。

方向与区间可同时存在，扩张事件也不必引起方向切换。这些输出分别描述不同规则，不能互相替代。

## 研究和回放

六个注册因子：`BROOKS.CTX_RANGE`、`BROOKS.CTX_CLIMAX_UP/DOWN`、`BROOKS.CTX_ALWAYS_IN`、`BROOKS.CTX_FLIP_UP/DOWN`。ALWAYS_IN 为标量，其他为布尔因子；RANGE 是每根背景状态，CLIMAX/FLIP 为事件。

模板 `RESEARCH.BROOKS_DIRECTION_MOMENTUM` 要求 ALWAYS_IN 等于 +1 且 20 根动量为正。既有全流程展开六组件、动量、完整组合、共同样本消融、固定样本外、滚动和预设参数对照，共 12 项顶层任务。

每个 CLIMAX/FLIP 事件保存来源窗口、效率锚点、区间、相对宽度、效率、此前平均 TR、当根 TR、实体比例、前后方向和确认条；按 available_at 进入已有 K 线回放。背景因子没有有限完成的 SequenceMatch，不伪造完成、超时或 pending 链计数。本轮未新增背景色带或浏览器交互。

完整规则与测试证明的是这些有限算法的实现。Wedge 及完整主观理论仍未完成。实际样本结果见 [验收报告](../../../artifacts/brooks-context-acceptance/report.md)。

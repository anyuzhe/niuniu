# Wyckoff 价格阶段代理：BCDE 1.0.0

> 版本化规则参考：保留原有算法合同与验证记录；本次仅调整文档位置和链接，不更改规则。命令从仓库根目录执行。[文档导航](../../README.md)

本实现是明确的 OHLCV 状态链，复用既有 WYCKOFF.RANGE、SPRING/UPTHRUST、TEST、SOS/SOW。它不识别机构持仓意图，不实现阶段 A 的抛售高潮/自动反弹，也不声称覆盖完整经典吸筹、派发阶段。

## 阶段与可用时间

每只证券、单一周期独立维护一条链；当前链未结束时，不用其他新 Spring/Upthrust 替换它。只在 K 线收盘数据可用后推进。

| 阶段 | 明确判据 | 保存的内容 |
|---|---|---|
| B | 既有 RANGE 判定：此前 lookback 根高低区间宽度相对下沿不超过 max_width | 中性紧凑区间开始事件，不推断吸筹或派发方向 |
| C_UP / C_DOWN | 对应 Spring / Upthrust 扫出并收回 | 冻结该次扫出的区间、极值、方向和来源事件；不沿后来滚动区间改边界 |
| C 内 TEST | 同一个 origin_at 的既有 Test 确认 | 保持 C，保存缩量测试事件 |
| D_UP / D_DOWN | Test 之后另一根 K 线发生同源 SOS / SOW | 冻结突破 K 线高点/低点、成交量和确认时间 |
| D 内 RETEST | 后续低点/高点接近突破边界，收盘守住边界，且相对突破条缩量 | LPS/LPSY 价格代理，记录首次符合条件的回踩；保持 D |
| E_UP / E_DOWN | RETEST 之后另一根收盘严格突破 D 突破条的高点/低点，并且量大于回踩条 | 发布延续确认事件，链标为 completed 并结束 |

B 只表示观察到紧凑区间，不冻结永久区间；若紧凑性消失，发布 PHASE_RESET 并结束中性链。若首个可用条就产生 Spring/Upthrust，可以直接进入 C，不补造一根更早的 B 事件。之后 C 的区间始终来自该次真实已观察扫出。

E 是完成事件，不是无限持续的趋势状态。下一根可以开始新的链，也可以保持空闲。旧链结束的当根不再启动另一条链。

## Test 与回踩阈值

继承参数：lookback=20、max_width=0.15、max_bars=40、test_fraction=0.25。C 内 Test 沿用基础 Pack：扫出极值不破、靠近冻结区间对应边界、量小于扫出条；Test 与 SOS/SOW 不在同一根确认。

新增参数：

- retest_fraction=0.25，范围 `(0,1]`。D 后向上回踩要求 `abs(low - upper) <= width * retest_fraction`；向下反弹对称使用 high 与 lower。
- retest_volume_ratio=1.0，范围 `(0,1]`。回踩量严格小于 D 突破量乘此比率，相等不算缩量。
- follow_bars=60，范围 `[1,100000]` 的整数。D 确认后允许等待的实际观察条数；严格超过才超时，回踩不重置时钟。

向上 D 阶段收盘必须 `close >= upper`；向下必须 `close <= lower`。在此基础上，回踩影线允许进入边界容差范围。首次回踩即使收盘已越过突破条极值，也只能确认 RETEST，不能同根确认 E。

## 失败、超时与优先级

C 阶段：严格超过 max_bars，先超时；否则向上最低价跌破原 Spring 极值，或向下最高价突破原 Upthrust 极值，立即失效。

D 阶段：严格超过 follow_bars，先超时；否则原扫出极值被破坏，或收盘回到突破区间内，立即失效。区间边界相等仍允许继续等待。

先检查超时，再检查结构失败，再确认首次回踩或 E。所有失效/超时都保存事件和 SequenceMatch 终态，不将失败链删除。末尾仍活跃的链保持 active，不提前补写完成或超时。

## 因子与研究接口

WyckoffPhasePack@1.0.0 新增 14 因子，前缀 `WYCKOFF.PHASE_`：

- B：进入 B 的事件，不是每根重复 RANGE。
- C_UP/DOWN、D_UP/DOWN、RETEST_UP/DOWN、E_UP/DOWN：进入或确认事件。
- INVALIDATED_UP/DOWN、EXPIRED_UP/DOWN：有方向链的终止事件。
- CODE：状态标量。0=空闲，1=中性 B，±2=双向 C，±3=双向 D；±4 仅在 E 确认当根出现。准备期为 null，不能把 +1 当成看涨方向。

PHASE_TEST_UP/DOWN、PHASE_RESET 另存为诊断事件，不是新增注册因子。状态和事件在 sequence_audit 中保留同一 episode/match_id；已有审计可汇总完成、失效、超时和 pending_at_end。

新模板 `RESEARCH.WYCKOFF_PHASE_E_MOMENTUM` 组合向上 E 确认与 20 根正动量；已有全流程自动展开阶段组件、组合、消融、样本外、滚动及预设参数对照。CODE 也可通过现有条件组合接口作阶段筛选。

回放沿用原始 K 线底图和按 available_at 截断的事件通道；本轮没有新增专门阶段色带界面。实际证据见 [本轮报告](../../../artifacts/wyckoff-phase-acceptance/report.md)。

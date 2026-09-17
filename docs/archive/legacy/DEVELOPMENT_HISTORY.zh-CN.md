> 历史开发记录：保留各轮实现时的说明，可能包含已变更的默认值、过期状态和本地 `artifacts/` 链接。当前入口、默认口径与已知边界以 [README](../../../README.md) 为准。实验产物不随 GitHub 源码发布。

> 历史归档（整理于 2026-09-17）：保留原阶段记录；正文中的“当前、下一步、待完成”和测试/数据数字属于原记录时点。使用与当前进度以 [文档导航](../../README.md)、[当前状态](../../project/status.md) 为准。命令仍从仓库根目录执行。

# 统一技术交易因子实验平台

**当前默认：前复权研究模式。** 新建研究及策略回测使用数据中心已保存的 qfq 价格，保留手续费和滑点，不重复计算分红/送股/拆并股。只有主动选择 `execution.price_mode=account` 才加载 raw 价格并处理公司行动。见 [本次修改与客户端验证](../../../artifacts/research-price-mode/说明.md)。下方历次验收保留当时口径。

当前版本包含可运行的 Python 命令行研究内核和本地研究工作台，已打通单因子、组合、日线背景筛选、参数扫描及分段/滚动研究。总体方案中的完整交易理论、完整统计检验和实盘交易适配尚未实现；已具备独立成交回测基础版。

## 架构

```text
CLI / 本地研究工作台
       ↓
app.py 组装入口
       ↓
ExperimentRunner ───────────────→ ExperimentStore
       │                          JSON / Parquet / Markdown / DuckDB
       ├─ DataProvider → DataBatch + DataSnapshot
       ├─ UniverseProvider → 历史 eligibility mask
       ├─ FactorRegistry → FactorPack → ExpressionFactor / ComputedFactor
       └─ FactorResearchEngine → 预测统计

后续对象与引擎：
Factor → Event / Zone / Structure / MarketState → Sequence → Theory
                                                        ↓
Signal → PortfolioBuilder → RiskPolicy → ExecutionBacktester
```

依赖方向：共享领域对象不依赖任何具体适配器；因子不依赖实验或交易；研究引擎不依赖订单引擎；具体实现由 `app.py` 注入。第三方交易后端和 GUI 不进入研究核心。

## 已实现的模块

| 模块 | 当前内容 |
|---|---|
| `domain.py` | 事件、区域、结构、状态、序列结果和信号对象；时间先后检查 |
| `structure/pivots.py` | 严格高低拐点；延迟确认，分别保留发生与可用时间、价格 |
| `events/breakout.py` | 收盘突破前 N 根最高价；事件 ID、确认时间、突破幅度和参考价 |
| `events/failed_breakout.py` | 前高/前低越界后收盘回到此前区间；双侧事件、参考区间及越界幅度 |
| `zones/fvg.py` | 双向三根 FVG 创建；追加式触及、回补、跳空失效历史；逐 bar 活跃区域数量 |
| `regime/` | 复用已注册因子的规则状态分类、状态过滤、输入版本记录及过滤前后比较 |
| `sequence/` | 按事件可用时间推进的状态机；顺序匹配、重复步骤、超时、失效与增量重放 |
| `factors/combinations.py` | 注册因子的嵌套条件组合与线性评分；输入版本和参数追踪 |
| `experiments/ablation.py` | 逐输入消融、固定共同样本、完整/删减组合子实验及差值汇总 |
| `experiments/holdout.py` | 固定参数的 train/valid/test 时序分段；历史预热、段尾标签截断与报告 |
| `experiments/walkforward.py` | 固定长度滚动分段，测试窗口不重叠；逐轮报告及未覆盖尾部记录 |
| `experiments/sweep.py` | 显式参数网格扫描；独立、分段及滚动子实验；保留全部配置和失败记录，不自动择优 |
| `experiments/correlation.py` | 多因子截面相关研究；配对样本统计、相关矩阵与完全链接冗余分组 |
| `experiments/correlation_holdout.py` | 固定 train/valid/test 因子关系对比；阶段相关、相对训练段变化和同组状态 |
| `experiments/correlation_walkforward.py` | 固定窗口滚动因子关系对比；测试阶段相关范围、有效轮次、符号与同组次数 |
| `theory/templates.py` | 版本化研究模板基础版；概念到现有因子的映射、固定规则展开及来源追踪 |
| `multitimeframe/` | 日线因子按可用时间映射到 5m，接入背景筛选；多周期快照在研究内复用 |
| `processing/` | 截面排名与标准化；仅使用当前时点股票池，保留原始因子值 |
| `statistics/` | 日期分块 Bootstrap；日均 IC 符号置换、研究内 Holm 校正；固定随机种子及不足样本提示 |
| `workbench/` | 本地实验配置、串行执行与持久化任务状态；实验浏览、比较、报告、观测表和序列审计 |
| `contracts.py` | 各后续引擎、Processor、组合、风控与执行接口；尚无理论算法 |
| `data/` | 数据请求、快照、Universe 接口、MQC 日线/5m 只读适配、基础行情校验 |
| `factors/` | 显式版本注册、Pack 依赖检查、两条计算路径、动量、收盘区间位置、ATR、收益波动率、有符号方向效率 |
| `causal.py` | 截断未来数据一致性检查、按 available_at 向后对齐高周期信息 |
| `experiments/` | 实验编排、未来收益、MFE/MAE、IC/Rank IC、ICIR/Rank ICIR、上涨比例、分位及配对多空差、失败记录 |
| `storage/` | 内容指纹、每次运行独立产物、DuckDB 实验索引、Markdown 报告 |

## 安装与运行

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/quantlab factors
.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 1d --start 2025-01-01 --end 2026-09-04 \
  --lookback 20 --horizons 1 5 20
.venv/bin/python -m unittest discover -s tests -v
```

Parquet/PyArrow 用于读取行情，Polars 用于计算和输出明细，DuckDB 用于实验目录查询。依赖仅装入本项目 `.venv`，不修改原数据项目。

每次运行生成独立目录：`experiment.json`、`observations.parquet`、`report.md`，以及输出根目录的 `experiments.duckdb`。源 MQC 数据及其 catalog 不会被写入。

相同配置、源码、依赖版本、数据文件内容与 Universe mask 产生同一个 `experiment_id`；每次执行有不同 `run_id`。源文件内容哈希用于识别变更，并不复制或冻结源数据：若要重放旧快照，必须保留原始 Parquet。源码内容哈希同时覆盖辅助函数，因子语义版本独立记录。运行记录中的时间与目录自然不同，比较复现结果时应比较实验 ID、指标和明细。

## 数据和研究口径

- 证券编码为 `sh.600519`；内部时间统一为 `Asia/Shanghai`。
- 日线在 15:00 可用；MQC 5m 字符串按 bar 结束时间解释。该约定需要数据供应商语义确认；未建模发布延迟。
- 默认读取 `raw`；前复权可显式选 `--adjustment qfq`。不保证现有 qfq 的历史可用性。raw 的除权跳变也可能影响收益标签。这些实验用于验证架构，不直接形成 Alpha 结论。
- 收盘后因子与 `close[t+h]/close[t]-1` 预测标签配对，不承诺可按 t 时刻收盘成交。
- 时间跨度按每只股票实际存在的 bar 数计算，不自动补齐停牌或缺失数据。
- 因子在所选区间内预热。历史 Point-in-Time 股票池接口已建立，默认显式股票池不解决幸存者偏差、ST 或停牌可交易性。
- IC/Rank IC 按时点做横截面相关，再对有效时点取平均。至少需要 3 个标的；常数相关或不足样本输出 null。
- ICIR/Rank ICIR 是逐时点有效相关系数均值除以样本标准差（ddof=1），不年化；少于两个有效时点或标准差为零时输出 null。
- MFE/MAE 分别为 `max(0, max(high[t+1:t+h])/close[t]-1)` 和 `min(0, min(low[t+1:t+h])/close[t]-1)`，是多头方向的未来路径标签。排除信号当根，包含零基线；未来不足 h 根则为 null，不使用部分窗口。
- 多空差是每个时点顶组减底组，再对两组同时存在的时点取均值；并列导致缺组时不会跨不同时点相减。`long_short_dates` 给出配对时点数。
- 分位按时点排名，同值不强行拆组；要求至少 Q 个标的和 Q 个不同值。先时点内均值再跨时点均值。小样本或大量并列时可缺少分位。
- `positive_return_rate` 是样本未来收益为正的比例，不是带买卖方向的策略胜率。
- 数据校验遇到异常会失败并保留原因，不静默删除、修复或填补数据。

### 基础因子口径

`BaseQuantPack@1.1.0` 包含以下因子，各因子语义版本均为 `1.0.0`：

| factor_id | 定义与边界 |
|---|---|
| `BASE.MOMENTUM` | N 根收盘变化率 |
| `BASE.CLOSE_LOCATION` | 当根收盘区间位置，无参数，零振幅为 0.5 |
| `BASE.ATR` | 真实波幅的 N 根简单平均，不使用 Wilder 平滑；首根缺前收盘为 null |
| `BASE.RETURN_VOLATILITY` | N 个简单收益率的样本标准差，不年化；N ≥ 2 |
| `BASE.DIRECTIONAL_EFFICIENCY` | N 根净价格变化 / 逐根绝对变化之和，保留方向；完整平盘窗口为 0 |

有 lookback 参数的因子默认 N=20；ATR、波动率和方向效率均需 N 根之前的收盘，区间最初 N 行为 null。所有计算按证券独立执行，只读取当前与历史 bar。

### 基础结构与事件

`TechnicalBasePack@1.1.0` 依赖 `BaseQuantPack`，包含四个布尔因子（各因子版本均为 `1.0.0`）：

- `STRUCT.PIVOT_HIGH_CONFIRMED`：候选高点严格高于左侧 L 根和右侧 R 根高价，默认 L=R=2；相等不算。只在右侧窗口完成当根输出 1，非触发为 0，最初 L+R 根为 null。`ConfirmedPivotEngine.detect(bars)` 同时返回严格高点和低点 `Structure`，保留 `occurred_at`、`available_at`、价格和版本；不强制高低交替，不实现缠论笔。
- `EVT.BREAKOUT_HIGH`：收盘严格高于前 N 根最高价，默认 N=20；不把当前高价算入参考区间，相等不触发，连续新高允许连续事件。`BreakoutHighEngine.detect(bars)` 返回 `Event` 对象，包含参考价、参数、方向、突破幅度与确认时间。

- `EVT.FAILED_BREAKOUT_HIGH`：本根 high 严格高于此前 N 根最高价，且收盘落在此前 N 根的最低价至最高价区间内（包含两个边界）。
- `EVT.FAILED_BREAKOUT_LOW`：本根 low 严格低于此前 N 根最低价，且收盘落回同一完整区间。默认 N=20；最初 N 根为 null，仅触及不越过不触发，收盘留在区间外不触发。两侧条件可以在同一根同时成立，不推断盘中先后路径。

`FailedBreakoutEngine(lookback).detect(bars)` 返回两侧 Event，包含参考区间、本根 high/low/close、参数和确认时间。`direction` 分别为高侧回落 -1、低侧收回 +1，仅标示事件朝向；`strength` 是越界距离除以相应参考价，不是反转概率。发生时间为该 bar 时间，可用及确认时间为其 available_at。

检测器只接收单周期标准行情，按证券独立计算。检测对象可通过 Python API 获取；当前实验明细保存布尔触发序列，不额外保存完整 Structure/Event 对象。行情确认后因子不回写候选发生的历史 bar。

布尔实验报告附加 `triggered` 统计，仅对 value=1 计算未来收益、上涨比例和 MFE/MAE，并区分总触发数与具有完整未来窗口的触发数。高点确认没有隐含做空方向，仍使用多头未来收益标签。它们是统一基础规则，不宣称复现任何完整交易理论。

```bash
.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 1d --start 2025-01-01 --end 2026-09-04 \
  --factor STRUCT.PIVOT_HIGH_CONFIRMED --left 2 --right 2
```

例如通过现有命令行运行波动率：

```bash
.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-09-01 --end 2026-09-04 \
  --factor BASE.RETURN_VOLATILITY --lookback 20 --horizons 1 5 20
```

## FVG 价格区域模块（已实现）

`ZoneBasePack@1.0.0` 新增三个无参数因子：`ZONE.FVG_BULL_CREATED`、`ZONE.FVG_BEAR_CREATED`（布尔创建标记）和 `ZONE.FVG_ACTIVE_COUNT`（两个方向的活跃区域总数），因子版本均为 `1.0.0`。

- 向上区域：`low[t] > high[t-2]`，价格区间 `[high[t-2], low[t]]`。
- 向下区域：`high[t] < low[t-2]`，价格区间 `[high[t], low[t-2]]`。
- 相等不创建，第一根和第三根之间的中间 K 线不附加方向/位移条件；允许跨交易时段。仅是基础三根规则，不代表完整 ICT 定义。
- 第三根完成时可用，从下一根开始跟踪。区域边界触及计一次 touch，但进入深度为零；每根相交 bar 计一次，不推断盘中触及次数。
- 向上区域从上边界向下计算进入深度，向下区域反向计算；`filled_ratio` 是历史最大进入深度 / 区域宽度，单调不减，不代表逐价真实成交覆盖率。到达远端边界记为 `filled`，停止跟踪。
- 若 bar 完全跳到区域远端之外而没有相交，记为 `invalidated`，不增加 touch 或假设已成交回补；保留此前已观察的回补比例。
- `FVGZoneEngine.detect(bars)` 返回不可变创建记录；`analyze(bars)` 返回 `zones`、追加式 `updates` 和逐 bar `counts`。`ZoneUpdate.available_at` 是这次状态变化可用时间，查询历史必须截到所需时点，不能使用最终状态回填历史。创建记录的 `invalidated_at` 不被后续改写。
- 计数先更新旧区域，再加入当根新区域。输入最初两根为 null；区域仅来自已加载历史，无自动补充区间外区域、失效时间上限或跨标的合并。活跃数量与数据起点有关，不能直接比较不同历史起点的实验。
- 详细区域对象目前通过 Python API 获取，实验 Parquet 保存对应因子序列；尚未接入区域浏览界面或对象数据库。当前生命周期遍历成本随未结束区域数量增加，尚未进行全市场长期性能验证。

```bash
.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-09-01 --end 2026-09-04 \
  --factor ZONE.FVG_ACTIVE_COUNT
```

## 市场状态与条件实验（已实现）

`RuleBasedRegimeEngine@1.0.0` 使用已有 `BASE.DIRECTIONAL_EFFICIENCY@1.0.0` 和 `BASE.RETURN_VOLATILITY@1.0.0`，不新增重复因子。默认因子窗口 N=20，波动基准窗口 B=20。

| 状态维度 | 默认规则 |
|---|---|
| direction | 效率 ≥ 0.3 为 Bull，≤ -0.3 为 Bear，其余为 Neutral |
| structure | 效率绝对值 ≥ 0.6 为 Trend，≤ 0.2 为 Range，其余为 Transition |
| volatility | 当前波动率 ≤ 此前 B 个波动率均值 × 0.75 为 Low；≥ 均值 × 1.5 为 High；其余为 Medium |
| liquidity | Unknown，尚未实现流动性分类 |

波动基准不含当前 bar，也不使用完整历史拟合。基准为零且当前也为零归 Low；基准为零但当前为正归 High。方向/结构前 N 根为 Unknown，波动状态前 N+B 根为 Unknown。以上是未校准的研究基线规则，不保证适用于所有标的或周期；Python `RegimeConfig` 可指定阈值，所有参数及输入因子版本写入实验记录。

- `--regime` 仅记录状态，不改变原实验样本或指标。
- `--regime-direction`、`--regime-structure`、`--regime-volatility` 任意一个会启用状态过滤；多个条件按 AND 组合，Unknown 不匹配指定条件。未指定的维度不影响筛选。
- 过滤发生在研究样本选择阶段，因子与未来收益仍在完整请求行情上计算，不会把“下一次符合条件的 bar”误当作下一根 bar。
- 记录 `regime_summary` 中过滤前后 eligible bar 数、过滤前状态分布；过滤实验额外保留 `baseline_metrics`。实验明细包含选中样本的状态及对应底层因子值。没有符合条件的样本时保留空明细，样本数为 0，无法计算的指标为 null。
- 同时比较条件样本与原股票池样本只是一项描述性研究，尚未做增量 Alpha 显著性或样本外检验；筛选后标的过少可能无法计算 IC 或分位统计。
- `RuleBasedRegimeEngine.classify(wide_factors)` 可输出带信息时间的 `MarketState` 对象；标准实验通过 `compute_regime` 复用注册因子并保留来源。

```bash
.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-09-01 --end 2026-09-04 \
  --factor BASE.MOMENTUM --lookback 20 \
  --regime-direction Bull --regime-structure Trend \
  --regime-lookback 20 --regime-baseline 20
```

## 事件序列（已实现）

`OrderedSequenceEngine` 实现 `advance(events, as_of)`，返回本次新增的 `SequenceMatch` 状态记录。`SequenceDefinition` 指定有序 `EventSelector`、相邻步骤时间上限和失效事件；Selector 匹配因子 ID、版本及可选方向。状态包括 `active`、`completed`、`timeout`、`invalidated`，同时保存实例 ID、已匹配事件 ID、周期、信息时间和失效事件 ID。

- 以 `available_at` 排序，而非形态发生时刻；同一信息时刻最多匹配一步，不能把同时出现的 A 和 B 当成 A → B。
- 每个证券/周期独立，最多一条进行中的序列。不重叠启动，不把完成事件同时用作下一条序列的起点；同组有多个匹配事件时按事件 ID 确定性选择。
- 每步匹配后重置超时时间。下一事件必须严格早于 `last.available_at + max_gap`；端点时刻先超时。时间是自然经过时间，包含午休、夜间和周末，不是交易 bar 数。
- 超时检查不依赖新事件；调用 `advance([], as_of)` 可推进空闲时钟。失效事件优先于同一时刻的正常匹配，并阻止当时重启。
- 增量调用应一次交齐截至 as_of 的事件。同一 ID、相同内容重复输入是空操作；同 ID 不同内容、未来事件、时钟倒退及水位之前新增迟到事件会报错。整批先验证再推进，拒绝的批次不会部分改变状态。当前无持久化恢复、乱序补录或嵌套/可选步骤。
- `SequenceMatch` 通过 Python API 获取；标准实验保存对应布尔完成标记。可选 `--sequence-audit` 将受支持序列的状态与事件日志保存到实验 JSON，尚无独立对象数据库。

`SequenceBasePack@1.1.0` 包含重复突破与前低失败后确认两个序列。`SEQ.REPEATED_BREAKOUT@1.0.0`：复用前高突破事件，按非重叠方式匹配两次突破，仅第二次可用当根输出 1，其余已预热 bar 为 0。参数为 `lookback`（默认 20）和 `max_gap_seconds`（默认 172800，严格小于两天；范围 1 至 31536000）。该示例没有配置失效事件，失效能力通过通用引擎提供。它不是 Brooks 二次入场或完整 ICT 序列。

```bash
.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-09-01 --end 2026-09-04 \
  --factor SEQ.REPEATED_BREAKOUT --lookback 20 --max-gap-seconds 3600 \
  --regime-direction Bull
```

## 因子组合（已实现）

当前共有 **34 个注册因子**。组合模块使用以下明确参数结构。

`CombinationPack@1.0.0` 提供 `COMB.CONDITION@1.0.0` 和 `COMB.SCORE@1.0.0`。每个输入指定 alias、已注册 `factor_id`、`version`（默认 1.0.0）及自身 `parameters`（省略时使用该因子默认值）。组合必须使用所有声明的输入。

- 条件组合：`rule` 支持嵌套 `all`、`any`、`not`；叶节点使用 `input`、`op`、`value`。比较运算为 `gt/ge/lt/le/eq/ne`，常数必须是有限数值；布尔因子用 0/1 比较。`all/any` 至少两个分支，最多嵌套 32 层，不执行字符串代码。
- 评分：`weights` 为每个输入指定有限权重，可为负数，直接计算 `sum(weight_i * value_i)`。没有自动标准化、权重拟合或阈值交易信号；不同量纲是否可比由实验定义负责。
- 两种组合都要求所有输入非缺失；即使逻辑上已有条件能决定真假，其他输入缺失时仍输出 null。零权重输入也不例外，避免默认把未预热因子当零。
- 组合可用时间是全部输入可用时间的最大值；延迟因子不能被回填，现有收盘研究引擎仍会拒绝延迟输出。
- 可引用基础、结构、事件、区域和序列因子。第一版禁止组合引用其他组合，嵌套逻辑在单个 `rule` 中表达，避免递归依赖。
- 实验 JSON 保存完整规则及每个输入的版本、解析后的参数和代码指纹，Markdown 显示输入表和规则。Parquet 当前保存组合结果，不额外保存每个组件序列。权重/规则变化会生成不同实验 ID。
- 空参数采用可运行的基线：20 根动量和 20 根方向效率；条件为动量 > 0 且效率 > 0.3；评分为两个原始值各乘 1。它们不是经过筛选的推荐策略。

自定义参数通过 `--params-json` 读取，不能与 `--lookback` 等行内因子参数混用。该入口也适用于已有单因子，状态过滤参数可同时使用。

```bash
.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-09-01 --end 2026-09-04 \
  --factor COMB.CONDITION --params-json examples/condition.json \
  --regime-direction Bull

.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 1d --start 2025-01-01 --end 2026-09-04 \
  --factor COMB.SCORE --params-json examples/score.json
```

当前组合输出支持原有 IC、分位和条件统计；布尔组合另有触发样本统计。逐输入消融见下节，自动组合搜索和增量 Alpha 显著性检验尚未实现。

## 组合消融（已实现）

在组合运行命令上增加 `--ablate`，运行完整组合及分别移除一个 alias 的组合。至少需要两个输入；单因子不接受该开关。

- 评分组合删除对应输入和权重，保留其他权重原值，不重新归一化，也不重新拟合。
- 条件组合删除该 alias 的全部叶节点；删除空组，将仅剩一个分支的 AND/OR 简化为该分支，空 NOT 一并删除。此处定义的是规则树结构删减，不以恒 True/False 替换变量；报告会完整展示删减后参数。
- 共同样本由原股票池 eligibility 与完整组合非缺失输出决定，再施加同一个 Regime 条件。完整行情保留用于计算因子和未来标签，避免预热长短和持有期变化导致比较偏差。这里共同样本中的“完整组合”可能与普通未消融运行的 coverage 分母不同。
- 每项指标记录 `full`、`without` 和 `delta_full_minus_without`；不可计算的差值为 null。布尔组合另比较触发数、具备未来窗口的触发数、触发平均未来收益及上涨比例。评分的整体平均未来收益在共同样本上相同是正常现象，主要比较 IC/分位差；布尔条件删除会改变触发样本。
- 一个消融研究只读取一次所选 Parquet 快照，全部子实验复用该数据对象；当前仍分别计算各组合，不声称有完整因子缓存。
- 父实验保存 `kind=ablation`、共同 mask 指纹、原股票池、数据快照、各删减参数及子实验引用。子实验各自保留 JSON、Parquet、Markdown 与 DuckDB 索引。父报告包含子报告链接。
- 相同配置/源码/数据产生相同研究 ID 和对比指标，每次运行使用不同 run ID。失败时保存失败记录，不把未完成的研究报告为成功。
- 该功能是描述性逐输入对照，不是因果贡献或统计显著性证明；可显式启用配对 IC 差异检验，见下文；不做样本外检验或自动挑选最佳删减组合。

```bash
.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-09-01 --end 2026-09-04 \
  --factor COMB.SCORE --params-json examples/score.json --ablate \
  --regime-direction Bull
```

## 固定参数时序分段（已实现）

`HoldoutRunner` 接受 `ChronologicalSplit(train_end, valid_end)`，将请求区间分为三段，日期端点均包含：

- train：数据请求 start 至 train_end；
- valid：train_end 次日至 valid_end；
- test：valid_end 次日至数据请求 end。

要求 `start <= train_end < valid_end < end`。日期按行情的本地日期解释，非交易日不会自动补出 bar。分段使用同一个已声明因子、参数、组合权重和状态规则，当前不会拟合模型、搜索参数或据验证结果自动修改测试参数。

一个研究只读取一次源快照。各子实验仅获得从请求起点至本段结束的行情前缀，再用本段日期筛选统计样本。此前历史用于因子、区域、序列和 Regime 预热；未来行情不会进入该段计算。各段末尾未来不足 h 根的 forward return、MFE、MAE 均为 null，不跨 train/valid/test 边界补齐标签。

父报告比较三段指标并链接独立子实验。父 JSON 保存切分日期与完整数据快照，子快照 ID 由父快照和截断请求生成；保留源文件哈希用于追溯，不另行复制源文件。空统计样本如实显示 0/N/A；如果训练前缀完全没有行情则失败并记录原因。

```bash
.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 1d --start 2025-01-01 --end 2026-09-04 \
  --factor COMB.SCORE --params-json examples/score.json \
  --train-end 2025-12-31 --valid-end 2026-06-30 \
  --regime-direction Bull
```

`--train-end` 与 `--valid-end` 必须同时传入；此版本不能和 `--ablate` 在同一次命令里混用。所有分段都可使用已有单因子、组合和状态过滤。

这提供了固定假设的样本外评估结构，但无法证明用户此前没有查看测试期；是否真正冻结假设仍取决于研究流程。固定参数滚动评估见下节；当前未实现模型训练和参数择优；可选日期块 IC 检验与 Holm 校正见下文，也未消除现有股票池和复权限制。

## 固定参数滚动评估（已实现）

`WalkForwardRunner` 接受 `WalkForwardConfig(train_days, valid_days, test_days)`。三个长度均为正整数自然日，每轮向前移动 `test_days`，只运行能完全放入请求区间的窗口。

- 每轮保留固定长度的 train / valid / test；测试窗口互不重叠，前轮测试日期可以成为后轮已经发生的历史。
- 所有轮次复用同一因子定义、参数和状态规则，不执行逐轮拟合、调参或基于验证期的参数选择。这是固定参数的滚动评估，不是完整自适应训练流程。
- 每轮低周期行情只读取自身训练起点至测试终点的内存视图，再复用 HoldoutRunner 截断各阶段。低周期状态、区域和序列从该轮起点重新计算；窗口应留足预热历史。若启用日线背景，日线单独从显式 `context.start` 预热至各段终点，因此可使用窗口开始前已发生的日线历史。
- 保留每轮完整分段报告、各阶段实验明细和顶层测试期比较表。末尾不足一个完整测试窗口的日期单独标明，不自动缩短最后一轮，也不拼接重叠持有期收益作为策略净值。
- 源 Parquet 只读取一次，各轮复用同一源快照的不同窗口。窗口或因子计算失败时保存失败状态，不静默跳过失败轮次。自然日窗口可能遇到节假日；若训练前缀完全无行情会报错，其他无统计样本情况仍显示 0/N/A。
- 可复用单因子、组合、事件和 Regime 过滤。`--walk-forward` 与固定分段日期、`--ablate` 不能混用。

```bash
.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 1d --start 2025-01-01 --end 2026-09-04 \
  --factor COMB.SCORE --params-json examples/score.json \
  --walk-forward 180 90 90 --regime-direction Bull
```

## 日期分块 Bootstrap（已实现，可选）

实验配置增加 `bootstrap=BootstrapConfig(resamples=1000, block_days=5, confidence=0.95)`，随机种子沿用 `random_seed`。CLI 通过 `--bootstrap-resamples` 启用，至少 20 次；块长默认 5 个日期，置信水平默认 0.95，`--seed` 默认 0。不启用时保留原统计流程。

计算未来收益、IC 和 Rank IC 的日期等权均值区间；布尔因子另计算触发样本的日期等权未来收益区间。分钟线先在同日汇总，每个日期权重相同，因此该点估计可能不同于报告原有的逐条样本均值；IC 先按同一时点的截面计算，再在日期内平均。

采用循环连续日期块重采样和经验百分位区间。日期网格只包含当前 eligible 样本出现的日期，不补齐交易日历；无指标值或无事件的日期保留缺失，不计为零收益。有效日期至少达到两倍块长，否则返回 `unavailable` 和原因，不自动缩短块长。记录实际有效重采样次数；非空重采样少于 20 次时也不生成区间。

参数、种子、有效日期数、点估计、区间与状态写入实验 JSON 和报告。分段、滚动及消融实验的子实验复用配置，各自计算区间；当前不计算消融差值区间，也不为 Regime 过滤前的基准表另算区间。

```bash
.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 1d --start 2025-01-01 --end 2026-09-04 \
  --factor BASE.MOMENTUM --lookback 20 \
  --bootstrap-resamples 1000 --bootstrap-block-days 5 \
  --bootstrap-confidence 0.95 --seed 7
```

块长未按市场和持有期自动校准，尤其长持有期的重叠标签可能仍存在未覆盖的依赖。该区间不是 p 值，未校正多重比较，不自动判定 Alpha 有效；小样本达到计算门槛也不代表区间可靠。

## 截面预处理（已实现，可选）

在因子计算之后、统计评估之前，可通过 `--processor cs_rank` 或 `--processor cs_zscore` 启用独立预处理层。Python 配置为 `processor=CrossSectionConfig("cs_rank")`，配置类位于 `quantlab.processing.cross_section`。

- `cs_rank`：同一时点内按平均秩计算 `(rank - 0.5) / n`，并列值相同，结果落在 0 到 1 之间。这是排名比例，不是正态分位数变换。
- `cs_zscore`：同一时点内计算 `(value - mean) / std`，使用总体标准差（ddof=0）。常数截面或仅一个有效标的时返回 0；排名模式对应返回 0.5。
- 仅当前 eligible 股票池内的非空值参与计算；缺失值不填充，排除标的的输出为空。截面在 Regime 过滤前形成，条件分析与基准分析使用相同处理口径。
- 仅支持标量因子（包括 `COMB.SCORE` 的最终评分）；布尔事件和概率因子拒绝处理，防止改变其语义。当前不处理组合内部各输入。
- 该处理不拟合历史参数，`fit_period=null`；保存处理参数、版本和代码哈希。因子值的可用时间取参与截面的最晚可用时间，不回填延迟信息。
- `observations.parquet` 的 `value` 是处理后值，另存 `raw_value` 和 `raw_available_at`。收益标签不变，报告中的 IC、分位统计和 Bootstrap 使用处理后值。未启用时保留原输出字段。

固定分段、滚动和评分消融的子实验均继承配置，仍按各自股票池及时间范围处理。当前仅实现无历史拟合的截面处理；训练期拟合、去极值、填充及行业/市值中性化尚未实现。

```bash
.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 1d --start 2025-01-01 --end 2026-09-04 \
  --factor BASE.MOMENTUM --lookback 20 --processor cs_rank \
  --bootstrap-resamples 200 --seed 7
```

## 多周期背景对齐（已实现：日线 → 5 分钟线）

独立模块 `quantlab.multitimeframe.engine.MultiTimeframeEngine` 通过现有 DataProvider 分别读取日线和 5 分钟线，在日线上计算已注册的数值因子，再按每个标的的 `available_at` 向后匹配。低周期行数不变，输出 `context_value`、`context_datetime` 和 `context_available_at` 供核查。

- 当天上午无法看到当天 15:00 才可用的日线；信息时间相等时允许使用。延迟确认按实际可用时刻匹配，不按发生日期回填。
- 未匹配或因子预热不足时为空。最新已可用行的因子为空时，不跳过该行回退旧值；日线背景可以跨日沿用，当前无自动过期规则。
- 两个请求须声明相同股票池、同一复权口径，日线区间须覆盖分钟线区间；日线可提前开始以满足预热。重复的高周期 symbol/available_at 会因含义不明确而报错。
- 保存两份请求与源快照、因子定义与参数、代码哈希、输出哈希及确定性 `context_id`。改变未来的源数据会改变快照身份，但不应改变此前对齐值。
- 当前仅支持日线和 5 分钟线，不从分钟线重采样其他周期。已接入 `quantlab run` 的日线背景筛选，可筛选单因子或组合结果；未将跨周期值作为组合内部输入。以下独立示例导出背景数据集，不写入 DuckDB 实验索引；下一节的正式实验会登记索引。

```bash
.venv/bin/python examples/multitimeframe.py \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --daily-start 2026-07-01 --start 2026-09-01 --end 2026-09-04 \
  --lookback 20
```

结果写入新的 `artifacts/context-<uuid>/`，包含 `context.parquet`、`manifest.json` 和 `report.md`。源行情只读。

## 日线背景条件实验（已实现）

`ExperimentConfig.context` 接受 `DailyContextConfig`（`quantlab.multitimeframe.config`），CLI 使用 `--context-json examples/daily_context.json`。背景定义包含日线起点、因子 ID、版本、参数及一个 `gt/ge/lt/le/eq/ne` 比较条件；默认条件为日线动量大于零。只支持低周期为 5m，日线预热起点必须不晚于分钟线开始日期。

执行顺序为：股票池 → 截面预处理 → Regime 过滤 → 日线背景过滤 → 统计与 Bootstrap。背景缺失一律不满足条件，包括 `ne`。报告单独比较背景过滤前后，基准已应用此前股票池及 Regime 条件。过滤只改变统计样本，未来收益仍按原始低周期 bar 序列计算。

正式实验保留日线背景配置、双周期快照、对齐输出哈希、覆盖/筛选行数。筛选后 Parquet 增加 `context_value`、`context_datetime`、`context_available_at`；完整对齐数据可通过上一节独立导出。背景前基准不额外计算 Bootstrap，最终样本可计算区间。

```bash
.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-08-03 --end 2026-09-04 \
  --factor COMB.SCORE --params-json examples/score.json \
  --context-json examples/daily_context.json --regime-direction Bull
```

可与 `--ablate`、固定分段或 `--walk-forward` 配合。整个研究的源分钟线、日线各读取一次；子实验只获得其结束日期前的日线前缀，日线因子从同一显式预热起点重算。固定背景条件不会随主因子消融而删除。当前背景没有过期阈值或交易日历修正，不自动生成交易信号。

## 参数网格扫描（已实现）

`SweepRunner.run(config, ParameterGrid(...), split=..., schedule=...)` 扫描主因子的参数；可选固定分段或滚动评估，两者不能同时使用。CLI 使用 `--sweep-json examples/momentum_grid.json`，示例内容为 `{"lookback": [5, 10, 20]}`。扫描值覆盖基础参数中对应的键，未列出的参数保留；多个键取笛卡尔积，按参数名排序和候选列表顺序执行。

每项候选在读取数据前通过因子参数校验，拒绝空列表、归一化后重复配置及超过 256 项的网格。只扫描主因子参数，不扫描背景配置或股票池；不与 `--ablate` 同时运行。

```bash
.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-08-03 --end 2026-09-04 \
  --factor BASE.MOMENTUM --sweep-json examples/momentum_grid.json \
  --context-json examples/daily_context.json --processor cs_rank \
  --train-end 2026-08-14 --valid-end 2026-08-24 \
  --bootstrap-resamples 100 --bootstrap-block-days 1 --seed 7
```

上例生成 3 个参数配置 × 3 个分段的子实验和参数比较报告。也可移除分段参数，或改用 `--walk-forward 10 5 5`。每次研究共用源快照，子实验仍独立保存；某项失败即停止，父记录保留此前完成的子实验，失败子实验另有自己的记录。

报告保留全部参数、阶段、样本数、收益和 IC，布尔因子另列触发统计。不自动按结果排序择优、不拟合参数。不同参数预热和有效样本可能不同，当前未强制共同样本。对多个配置查看测试表现会引入选择偏差；该功能未提供嵌套择优或多重比较校正，也不证明测试集从未被查看。

## 因子相关矩阵与冗余分组（已实现）

独立入口 `quantlab correlate` 接受 2–64 个已注册叶子因子，支持同一因子的不同参数或别名。通过同一行情快照计算因子面板，支持 Universe、截面预处理、Regime 和日线背景筛选，不计算未来收益。

`--inputs-json examples/correlation_inputs.json` 的格式为别名到因子说明的映射，每项包含 `factor_id`，可选 `version`（默认 `1.0.0`）和 `parameters`。示例比较 5/20 根动量、20 根方向效率、20 根收益波动率和收盘区间位置。

```bash
.venv/bin/quantlab correlate \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 1d --start 2025-01-01 --end 2026-09-04 \
  --inputs-json examples/correlation_inputs.json \
  --min-symbols 3 --min-periods 5 --cluster-threshold 0.8
```

口径与边界：

- 对每对因子，在每个时点使用两者共同非空的标的计算 Pearson 和 Spearman，再对各自有效时点等权平均。分钟线按时点等权，不先按日期平均；不是将所有股票和日期混合后的总体相关。
- 每时点至少 `min_symbols` 个共同标的（不得小于 3），每种相关至少 `min_periods` 个有效时点（不得小于 1），否则显示 N/A。默认分别为 3 和 5；门槛只决定是否报告数值，不代表统计显著。常数截面无相关值，对角线也不会强制写 1。
- 缺失值不填充。报告分别列出每对因子的共同非空行、共同非空时点、达到标的数门槛的时点、两种相关的有效时点。不同配对可能使用不同样本，最终矩阵不保证半正定，不应用作投资组合协方差矩阵。
- 分组使用 `abs(mean_spearman)`，不是 `mean(abs(spearman))`；正负相关随时点切换可能相互抵消。默认阈值 0.8，可设置为 `(0,1]`。
- 完全链接分组每次合并组间最弱相关仍达标的两个组，优先合并最强候选，并列按别名字典序决定。组内每对均须达标，未知配对不合并；反向因子可以同组，正负号保留在矩阵。不会自动删除因子或选代表因子。
- 因子必须在对应 bar 收盘可用，不将延迟信息回填。只进行描述性冗余分析，不检验 Alpha、样本外稳定性或多重比较。

Python 入口为 `CorrelationRunner(runner).run(CorrelationConfig(...))`，定义位于 `quantlab.experiments.correlation`。结果沿用实验存储：`experiment.json` 保存输入版本、参数、代码/数据指纹、覆盖率、配对统计和分组；`observations.parquet` 保存 `factor_<alias>` 原始面板；`report.md` 展示矩阵和分组，并登记 DuckDB 实验索引。

## 条件相关与时序关系对比（已实现）

`correlate` 现在接受 `--processor`、`--regime` / `--regime-direction` / `--regime-structure` / `--regime-volatility`、`--regime-lookback`、`--regime-baseline` 和 `--context-json`，含义与 `run` 一致。执行顺序为股票池 → 各因子截面预处理 → Regime → 日线背景；使用日线背景仍要求主周期为 5m。

启用预处理时所有输入必须为标量因子，面板的 `factor_<alias>` 是处理后值，另存 `raw_factor_<alias>`。状态分类使用原有 Regime 因子；日线背景按可用时间向后匹配，缺失背景不满足条件。面板保留状态字段及日线来源时间，报告列出每步筛选的行数、条件参数和配对有效时点。

同时传入 `--train-end`、`--valid-end` 可生成固定 train/valid/test 对比，两个日期必须成对传入。整个研究只读取一次主周期快照，有背景时另读一次日线快照；各阶段只能获得截至阶段终点的行情前缀，之前的历史用于预热，统计样本限制在本阶段。日线预热起点保持为显式 `context.start`。

```bash
.venv/bin/quantlab correlate \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-08-03 --end 2026-09-04 \
  --inputs-json examples/correlation_inputs.json \
  --processor cs_rank --regime-direction Bull \
  --context-json examples/daily_context.json \
  --train-end 2026-08-14 --valid-end 2026-08-24
```

Python 入口为 `CorrelationHoldoutRunner(runner).run(config, split)`，配置沿用 `CorrelationConfig`，切分沿用 `ChronologicalSplit`。父报告展示各阶段 Pearson/Spearman、相对训练阶段的 Spearman 差值、有效时点及是否同组，JSON 另存 Pearson 差值，并链接三份完整报告。

每个阶段独立计算相关和分组，参数与阈值保持固定；这不是训练、择优或代表因子迁移。同组状态在配对相关不足时为 N/A，不将未知视为已经分离。差值只描述变化，尚无相关差异置信区间、统计稳定性检验或多重比较校正。滚动对比见下节。

## 因子关系滚动评估（已实现）

`correlate --walk-forward TRAIN_DAYS VALID_DAYS TEST_DAYS` 复用自然日滚动窗口，各长度为正整数。每次前移 `TEST_DAYS`，测试日期不重叠，只执行完整窗口并记录未覆盖尾部。不能与固定 `--train-end/--valid-end` 混用。

每轮低周期因子从训练起点重新预热，各阶段只读其结束日期前的数据，日线背景沿用显式 `context.start`。整个研究仅从源头读取一次主周期数据及一次可选日线数据，后续使用内存窗口/前缀；输入因子、参数、条件和分组阈值始终固定。

```bash
.venv/bin/quantlab correlate \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-08-03 --end 2026-09-04 \
  --inputs-json examples/correlation_inputs.json \
  --processor cs_rank --regime-direction Bull \
  --context-json examples/daily_context.json --walk-forward 10 5 5
```

Python 使用 `CorrelationWalkForwardRunner(runner).run(config, WalkForwardConfig(...))`。顶层报告链接每轮三段报告，列出每对因子的测试相关、相对本轮训练段的变化、有效时点和同组状态；另汇总有效/总轮次、等轮次平均 Spearman、最小/最大值、正/负/零相关轮次、同组/可判断轮次。

缺失轮次不填零，均值只对有效测试轮次等权，不是合并所有时点重算的相关；同组比例分母仅包含可判断的轮次，全部未知时比例为 null。各轮训练和验证窗口可能重叠，不能当作独立统计样本。各阶段可选相关置信区间见下节；当前不提供跨轮汇总区间、稳定性显著检验或自动因子淘汰。

## 相关分析的日期分块置信区间（已实现，可选）

`correlate` 支持 `--bootstrap-resamples`、`--bootstrap-block-days`、`--bootstrap-confidence` 和 `--seed`，默认块长 5、置信水平 0.95、种子 0。通过指定至少 20 次重采样启用；Python 对应 `CorrelationConfig.bootstrap` 和 `random_seed`，复用现有 `BootstrapConfig`。

每对因子的 Pearson/Spearman 先按同一时点计算，再在每个日期内平均有效相关；对这些日期均值使用循环连续日期块重采样，输出百分位区间。报告单独显示日期等权点估计，它可能不同于时点等权矩阵，尤其在每天有效分钟时点数量不同的情况下。原矩阵、阈值分组和阶段相关差值保持原口径。

日期网格取当前筛选面板出现的日期，未出现的交易日不补齐；缺失指标不填零。必须先满足 `min_periods`，再满足至少两倍块长的有效日期；非空重采样少于 20 次也不报告区间。不满足时保留点估计（如可计算）、计数和原因，但区间为 null，不自动缩短块。每对因子及相关方法使用由主种子派生的独立随机流。

```bash
.venv/bin/quantlab correlate \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 1d --start 2025-01-01 --end 2026-09-04 \
  --inputs-json examples/correlation_inputs.json \
  --bootstrap-resamples 1000 --bootstrap-block-days 5 --seed 7
```

可与条件筛选、固定分段或滚动评估叠加，各子实验各自计算区间并保存于 `pairs[].bootstrap` 和子报告；父报告仍比较原始时点等权矩阵。不计算跨阶段相关差异区间、跨轮汇总区间或分组置信度，未校正多重比较；默认块长未经校准，区间不是 p 值，也不证明关系在样本外稳定。

## 版本化研究模板（基础版已实现）

`quantlab theories` 列出模板 ID、版本、概念说明、底层因子和明确规则。`quantlab run --theory ID` 将模板展开为已有 `COMB.CONDITION`，无需重新实现底层算法。当前提供：

| 模板 | 固定规则 | 定义边界 |
|---|---|---|
| `RESEARCH.TREND_BREAKOUT@1.0.0` | 20 根有符号方向效率 > 0.6，且收盘突破此前 20 根最高价 | 趋势由方向效率定义；允许连续突破触发 |
| `RESEARCH.BULL_FVG_MOMENTUM@1.0.0` | 本根确认创建看涨三根 FVG，且 20 根动量 > 0 | 同根条件，不含位移、时段、回踩或成交规则 |
| `RESEARCH.FAILED_LOW_POSITIVE_MOMENTUM@1.0.0` | 本根前低突破失败，且 20 根动量 > 0 | 越界后收盘在此前区间内，不推断后续反转 |
| `RESEARCH.RECLAIM_CONFIRMATION@1.0.0` | 前低失败后限时向上突破序列完成，且 20 根动量 > 0 | 等待限时 172800 秒，前高失败取消，不推断可成交性 |

它们是明确的研究假设模板，不是完整 Brooks、ICT、SMC 或缠论实现。概念映射仅覆盖已实现规则，没有将不同理论中的相似术语声明为完全等价。

```bash
.venv/bin/quantlab theories
.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-08-03 --end 2026-09-04 \
  --theory RESEARCH.TREND_BREAKOUT --ablate
```

可叠加已有 Regime、日线背景、Bootstrap，也可将 `--ablate` 换为固定分段或 `--walk-forward`。模板输出是布尔条件，不能应用仅支持标量的 `--processor`。`--theory-version` 默认 `1.0.0`；未知模板或版本报错。

模板模式不接受主因子、参数、因子版本覆盖或参数扫描，防止更改固定定义后仍使用原模板名称。需要探索变体时，可使用列出的组合参数另行运行普通 `COMB.CONDITION` 实验。

Python 可用 `resolve_template(id, registry, version)` 获得独立的参数字典和来源记录，再将 `factor_id="COMB.CONDITION"`、`parameters`、`theory_origin` 传入 `ExperimentConfig`。来源包含模板代码哈希、版本、概念及完整输入版本/参数；每个子实验另存实际参数。消融记录原模板来源，但实际规则会减少输入，报告明确区分两者。

当前未提供动态 Theory Pack 插件、自动理论等价判定、完整交易策略或自动增量 Alpha 显著检验。

## 前低收回后的向上确认序列（已实现）

`SEQ.FAILED_LOW_THEN_BREAKOUT@1.0.0` 复用已实现事件及 `OrderedSequenceEngine`：

1. `EVT.FAILED_BREAKOUT_LOW` 启动等待。
2. 必须在之后不同可用时刻、严格小于 `max_gap_seconds` 的间隔内出现 `EVT.BREAKOUT_HIGH` 才完成。
3. 等待期间出现 `EVT.FAILED_BREAKOUT_HIGH` 则取消，失效优先于启动/完成。同根双侧失败不会启动等待。

默认 `lookback=20`、`max_gap_seconds=172800`，参数约束与重复突破序列相同。各事件使用当时此前 N 根的滚动区间，第二步不是突破第一步冻结的区间。期限按实际秒数，包含夜间和休市；等于截止时间视为超时。重复起点不延长等待，一次完成消耗一个起点，不重叠配对。

前 N 根为 null，其后只有完成当根为 1，起点、等待、取消、超时均为 0。`FailedLowThenBreakout.analyze(bars, parameters)` 返回因子序列和 `SequenceMatch` 记录，便于核查事件链及失效事件 ID；标准实验保存完成标记，可选序列审计保存完整日志。若同标的多个 bar 使用相同 available_at，会因无法唯一定位触发 bar 而报错。

```bash
.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-08-03 --end 2026-09-04 \
  --factor SEQ.FAILED_LOW_THEN_BREAKOUT --lookback 20 --max-gap-seconds 172800
```

模板 `RESEARCH.RECLAIM_CONFIRMATION` 将上述默认序列与完成当根的 20 根正动量组合，可运行消融、分段和滚动研究。该序列只定义确认条件，不自动生成买卖指令或推断反转概率。

## 序列审计持久化（已实现，可选）

`run --sequence-audit`（Python：`ExperimentConfig.sequence_audit=True`）保存两种已实现序列的底层事件及状态变化，也支持组合、模板中的直接序列输入。默认关闭，不改变原有因子计算或统计口径。当前审计会额外重放序列计算，长区间运行应考虑日志体积和计算成本。

完整日志保存在 `experiment.json.sequence_audit`：

- 每个序列输入的别名、因子定义和实际参数。
- `events`：底层事件 ID、类型、时间、参考价格、方向及元数据，包含未被某条序列选中的候选事件。
- `transitions`：实例 `match_id`、启动/完成/失效/超时记录、匹配事件 ID 与失效事件 ID。
- `status_record_counts`：各类历史记录数；`pending_at_end`：审计截止时最后状态仍为 active 的实例数，两者不能混用。
- `completion_selected`：完成事件是否处于最终筛选且主因子非空的样本中；不要求未来标签完整，也不代表整个条件组合已触发。非完成记录该字段为 null。

日志覆盖当前加载历史，包括预热及股票池、Regime、背景条件筛选前的记录。分段和滚动子实验只记录各自可读取的历史前缀，彼此可能有重复预热历史；不能把这些日志直接相加当作全局独立事件。消融删除序列输入后审计列表为空，原模板来源仍按原有方式保存。

```bash
.venv/bin/quantlab run \
  --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-08-03 --end 2026-09-04 \
  --theory RESEARCH.RECLAIM_CONFIRMATION --ablate --sequence-audit
```

子实验报告展示日志状态计数及进入统计的完成数。没有受支持序列的配置也可运行，记录空列表；目前没有独立事件数据库；可配合 --replay 使用下文的 K 线回放。

## 后续开发方向

1. 完善数据口径、历史 Universe、复权与交易日历；扩展基础因子和实验指标。
2. 扩展现有事件、结构、区域、Regime 与 Sequence 算法，加入其他周期和跨周期组合输入。
3. 扩展研究模板的理论概念映射和具体 Theory Pack；补充已有相关分段/滚动对比的统计稳定性检验。
4. 扩展已实现的 IC 符号置换与 Holm 校正，补充增量 Alpha 验证；再接投资组合、风控和交易适配。

后续方向中的新增算法和功能尚未实现；现有基础能力及其边界以上文为准。

## 本地研究工作台

```bash
.venv/bin/quantlab serve --output artifacts --port 8765
```

打开 http://127.0.0.1:8765/ 。不指定数据目录时保持只读：直接读取产物 JSON 和 Parquet，不打开 DuckDB 索引。服务只绑定本机回环地址；实验始终只读 MQC 行情，结果写入指定 output。

- 实验记录：搜索、类型/状态筛选、分页，选择 2–4 个实验比较原始评估结果。
- 实验详情：因子指标、参数扫描各阶段指标、父子实验跳转、研究报告、完整 manifest 及文件下载。
- 观测数据：按股票代码筛选并分页读取，不一次加载完整 Parquet 到页面。
- 序列审计：按序列、状态和股票筛选状态转换，展开关联事件和取消事件；旧记录未保存审计时明确提示缺失。
- 因子目录和研究模板：展示当前注册定义、版本和参数；历史定义以实验自身 manifest 为准。

工作台可以提交下述研究实验，不修改已归档结果。实盘交易下单尚未实现；K 线回放和独立模拟成交见下文。相关性专有统计以可展开结构化结果及原始报告呈现；比较不自动择优、不统一不同实验的统计口径。报告支持标题、表格和代码块等基础展示，原始 Markdown 可下载。创建时间按产物的 UTC 时间展示，观测及审计时间保留原有时区。

### 从界面配置并运行研究

```bash
.venv/bin/quantlab serve --output artifacts --port 8765 --data-root /Volumes/Lexar/MQC-DATA
```

“新建实验”支持单因子/条件/评分组合、固定分段、滚动验证、逐输入消融与参数扫描。因子列表来自当前注册表，也可选固定研究模板。日期和股票初始值取最近实验，提交前可修改；这些值不是可用数据覆盖承诺。相关性研究目前仍由 `quantlab correlate` 发起，结果可在工作台浏览。

1. 设置股票、周期、区间、因子或模板、参数及研究方式。
2. 可选择“校验并预览配置”；校验只验证配置和已注册参数，不读取行情，不能保证源文件或数据范围可用。
3. “提交实验”入队，任务详情自动刷新排队/运行/完成/失败状态，完成后跳转产物。关闭网页不会取消任务。
4. 运行任务页可重新打开历史任务、查看原始提交及解析配置。任务状态记录在 `artifacts/_jobs/`。

可选 JSON 配置沿用内核：

```json
{
  "regime_filter": {"direction": "Bull"},
  "processor": "cs_rank",
  "bootstrap": {"resamples": 100, "block_days": 5, "confidence": 0.95},
  "seed": 0
}
```

`regime_filter` 未附带 `regime` 时自动使用默认状态参数。`processor` 仅支持标量因子。5m 研究可添加 `context`，例如 `{"start":"2026-07-01","factor_id":"BASE.MOMENTUM","parameters":{"lookback":20},"op":"gt","value":0}`。扫描可在可选 JSON 中加入 `split`（train_end/valid_end）或 `schedule`（train_days/valid_days/test_days），二者不能混用。

执行边界：

- 单个服务串行执行。同一 output 下仅允许一个可执行工作台；独立 CLI 仍可能与工作台争用 DuckDB 写锁，不要同时向同一 output 执行研究。
- 提交接口只接受同源 JSON，最大 64 KiB。行情与输出目录由服务启动参数固定，网页不能传入 shell 命令或任意文件路径。
- 同一 job_id 与相同配置重试返回既有任务，不重复执行；不同配置不能复用 ID。
- Ctrl+C 停止接收新请求后会等待已经接收的队列完成。当前没有运行中取消或百分比进度。进程异常退出后，原排队/运行任务在下次启动时标为 interrupted，不自动重跑；请先检查可能已保存的实验及子实验。
- 任务失败显示原因；内核可保存失败实验。因加载/存储失败可能无法建立结果链接，可在实验记录中查看失败记录。
- 日志损坏时服务会启动失败，以保留问题证据；不是自动恢复或分布式任务服务。

核心模块的覆盖情况和未完成项见 [核心功能建设进度](核心功能建设进度.md)。

## 日期块符号置换与 Holm 校正（基础版）

```bash
.venv/bin/quantlab run --data-root /Volumes/Lexar/MQC-DATA --output artifacts \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-08-03 --end 2026-09-04 \
  --factor BASE.MOMENTUM --lookback 5 --horizons 1 5 20 \
  --permutation-resamples 999 --permutation-block-days 5 --seed 0
```

工作台“可选配置 JSON”可添加：

```json
{"permutation":{"resamples":999,"block_days":5,"alpha":0.05},"seed":0}
```

- **检验对象**：日均 IC、Rank IC 相对零的双侧偏离。每时点至少 3 个有限样本；先同日平均，再对有效日期等权，与普通面板的时点等权 IC 口径有区别。此版本不检验收益均值或因子之间相关性的显著性；消融配对 IC 差异需另启用 incremental_test，见下文。
- **零假设前提**：日期块的联合分布对各块独立符号翻转不变。例如独立且关于零对称的块满足该条件。只声明均值为零并不足够。跨块相关、偏斜、重叠未来标签等可能破坏此前提；块长未经自动校准，不保证检验对真实市场数据有效。
- **日期块**：按 eligible 观测中出现的日期顺序，从首日划分不重叠块；不是自然日补齐。缺失 IC 日期保持空位，块整体翻转，末尾短块保留。至少 6 个非空块，否则输出 unavailable 和原因；不填零、不输出假 p 值。
- **抽样**：配置次数达到全部 `2^非空块数` 时精确枚举，p=极端组合数/总组合数；否则均匀有放回抽取符号，p=(极端次数+1)/(抽样次数+1)，避免零 p 值。双侧按统计量绝对值比较，固定 seed、持有期及指标派生随机流。resamples 限制 20–100000。
- **多重检验族**：单实验全部持有期 × 两个 IC 指标；父研究扩展到全部参数、阶段和滚动轮次，并从原始 p 值重新做 Holm FWER 校正。不可检验项保留在计划检验数中，显示 N/A。不能用子实验校正冒充整个扫描校正，也不能跨独立启动的研究宣称控制错误率。
- **持久化**：原始检验位于 `metrics[持有期].permutation`，当前检验族校正位于记录顶层 `inference`；配置及代码指纹进入 manifest。CLI、工作台研究流程均支持，父子报告有检验表。旧实验不自动补算。
- **解读**：`reject_holm=true` 只是在指定 alpha 和假设下拒绝零假设，不是盈利认证、自动因子筛选、增量 Alpha 证明或收益回测。Bootstrap 置信区间未因本功能变成同时置信区间。

方法参考：[SciPy 符号随机化文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html)、[R Holm 校正文档](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/p.adjust.html)。实现使用现有 Polars 与 Python 标准库，未新增 SciPy 依赖。

## 组合消融的配对 IC 差异检验

研究问题：在已配置股票池、背景过滤和预处理后的共同样本上，完整组合的有符号 IC 是否与移除某输入后的组合存在差异？此能力不等于因果贡献或扣成本后的增量收益。

CLI 在原组合/模板消融命令上增加：

```text
--ablate --incremental-test --permutation-resamples 999 --permutation-block-days 2
```

工作台选择“逐输入消融”，在可选配置 JSON 中填写：

```json
{"permutation":{"resamples":999,"block_days":2,"alpha":0.05},"incremental_test":true,"seed":7}
```

- 仅用于消融，并要求显式启用 permutation。普通单实验、分段、扫描不能直接使用 incremental_test。未启用时保持原有描述性消融行为。
- 直接读取本次完整/删减子实验保存的 observations.parquet，沿用实际样本筛选与因子预处理，不重新计算另一套样本。
- 按 symbol/datetime 一对一配对，检查双方匹配键的未来收益标签一致。仅保留双方因子及标签有限的股票，每个截面至少 3 只股票；双方 IC 都有定义时才计算差异。常数截面不填零。
- 对每个时点计算 IC_full − IC_without（Rank IC 同理），再同日平均、日期等权；执行既有日期块符号置换。输出双方配对均值、共同有效时点数和样本数。
- 正差异只表示有符号 IC 更高，不表示绝对 IC 更强；双侧拒绝可能对应负差异。配对均值的样本口径可能不同于各子实验分别平均后相减。
- 父研究以“全部完整/删减子实验 IC 检验 + 全部配对差异检验”作为联合 Holm 检验族。两个输入、三个持有期时，共 `(3×2×3)+(2×2×3)=30` 项计划检验；缺失项仍占名额。
- 原始配对检验保存于 `contrasts[].metrics[持有期].permutation`，同时保存 full_run_id/without_run_id；联合校正结果仍在父记录 `inference`。网页及报告可直接查看。
- 仍依赖日期块联合符号对称假设；不自动证明金融时间序列满足该假设，不校正跨研究探索，不自动选择因子，也不检验收益差异或残差化的独立 Alpha。

## 历史股票池、结构突破、K 线回放与独立成交回测

### 历史股票池

CLI `run` / `correlate` 支持 `--universe explicit|listing|pit`，网页也可选择。三种模式均限定在用户提交的股票列表内，不自动重建全市场历史成分。

- `explicit`：沿用显式列表。
- `listing`：读取数据根目录下 `lake/bronze/provider=baostock/stock_basic/stock_basic.parquet` 的 `code/ipoDate/outDate`。上市日包含、退市日排除；可用 `--min-listed-days N` 排除上市前 N 个自然日。忽略当前 `status`。这是依据当前基础表的**回顾性上市区间**，不声称严格 PIT，也不能消除预选股票列表的幸存者偏差。缺少指定股票或上市日期时失败。
- `pit`：读取数据根目录下 `research/universe_events.parquet`，字段为 `symbol: String`、`effective_at: Datetime(带时区)`、`available_at: Datetime(带时区)`、`eligible: Boolean`。仅使用可用时间不晚于当前行情可用时间的记录；在生效时间不晚于当前 K 线的记录中选择最新生效项。同一生效时间的修订按可用时间更新，不能改写较早回放时点；未知资格排除。同一股票/生效/可用时间重复记录拒绝。

两种历史模式均将文件 SHA256 与规则版本计入实验来源。现有 MQC 只验证了上市基础字段；**尚没有真实历史 ST、停牌等资格流水**，PIT 适配器通过合成时序数据验证。平台不生成虚构流水，也不写入 MQC 数据盘。接入 PIT 时需自行提供真实来源文件。

### 明确规则的理论算法扩展

上一轮新增 `SMC.BOS_UP`、`SMC.BOS_DOWN`，当时共 18 个因子、5 个固定研究模板；本轮已扩至 34 个因子、7 个模板。这是 SMC 启发的确认摆动突破变体，规则如下：

1. 默认 `left=2,right=2`，拐点必须严格高于/低于左右窗口；相等不算。右侧 K 线全部可用后才确认。
2. 每个方向保留最近确认的摆动价。向上要求 `前收盘 <= 高点 < 当前收盘`；向下要求 `前收盘 >= 低点 > 当前收盘`。
3. 同一个摆动价只触发一次，直到有新确认拐点替换。尚无已确认价输出 null；已知价但未触发输出 0；触发输出 1。
4. 事件记录突破时间、可用时间、被突破拐点的发生及确认时间。信号不回填到拐点发生处。

新增模板 `RESEARCH.CONFIRMED_BOS_MOMENTUM`：上述向上突破且 20 根动量为正。未将 CHoCH、Order Block、缠论笔段中枢等未实现概念包含在该名称下。

### K 线审计回放

`run --replay` 保存本次规范化行情为 `bars.parquet`，并保存确认拐点、双向摆动突破和 FVG 追加状态。网页新实验默认勾选保存回放；实验详情的“K 线回放”支持股票切换、前后步进、游标和末根跳转，显示最近 100 根 K 线、事件、已确认结构、当前区域状态及模拟成交。

服务端按游标的 `available_at` 过滤对象及状态更新，早期游标看不到之后才确认的拐点或成交。叠加是明确标注的诊断规则（默认左右 2 根，直接传入 left/right 时沿用），不表示每个组合因子的实际交易条件；嵌套组合参数不会自动解析为全部图形叠加。已有序列审计事件也可叠加。原始完整文件可下载，但回放 API 不返回未来 OHLC 或预测标签。旧实验无行情快照时提示不可回放，不重新读取可能变化的原行情。

### 独立成交回测

```bash
.venv/bin/quantlab run --data-root /Volumes/Lexar/MQC-DATA --output artifacts \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-08-03 --end 2026-09-04 \
  --factor SMC.BOS_UP --left 2 --right 2 --universe listing --backtest
```

可加 `--execution-json 配置文件.json`；网页选择“独立成交回测”，在可选配置 JSON 中填写：

```json
{"execution":{"initial_cash":1000000,"top_n":5,"threshold":0,"exposure":1,"lot_size":100,"t_plus_one":true,"commission_bps":3,"minimum_commission":5,"sell_tax_bps":0,"slippage_bps":2,"limit_pct":null}}
```

以上是模拟参数默认值，非真实市场历史费率或各板块交易制度声明。

- 研究子实验先保存因子及股票池筛选结果；每根收盘选择资格有效、有限且因子值严格超过 threshold 的前 top_n 名（并列按股票代码），等权分配 exposure，无入选则目标全零。只使用因子值与资格，不使用未来标签；`horizons` 不控制交易持仓期限。
- 独立 `OpenExecutionBacktester` 直接接收完整目标权重快照及行情，不依赖因子或标签模块。下一根开盘处理当时最新已知目标，每根按目标重新平衡；卖出先于买入，买入按股票代码顺序受现金约束。5m 前收盘与下根开盘同时间戳允许零延迟执行；日线按下一交易数据日 09:30 模拟。
- 长仓、不融资；目标股数向下取整到 lot_size；T+1 开启时当日买入不能当日卖出。佣金按每笔 `max(最低佣金,金额×费率)`，卖出税与方向滑点单独记录。现金不足或限制导致部分/未成交时保留原因；不声称做了盘口部分成交模拟。
- `limit_pct` 可设置相对上一条已见收盘价的固定比例开盘限制。它不是自动历史涨跌停判定，不处理板块、ST、最小价位舍入或公司行动。
- 仅 raw 日线/5m，要求 K 线在收盘时可用；开盘成交假设不使用当根最终最高、最低或成交量。缺行情的股票不能产生当根成交，持仓用最后已知收盘价估值。没有容量保证、自动停牌识别、股息拆并股处理或期末强平。
- 独立父实验保存成本后净值表 `observations.parquet`、成交及未成交记录 `experiment.json`、报告与行情快照；来源研究以子实验链接保留。最大回撤为非正比例。末尾尚未到可执行开盘的目标保持未执行，末尾持仓按最后已见收盘价估值。

该版本完成确定性目标权重、撮合与现金持仓核算基础能力，未完成实盘适配、模型训练或完整市场成交仿真。

## 按建设顺序新增：Brooks → 理论研究闭环 → ICT/SMC → 组合风控 → vn.py

本轮新增 10 个 Brooks 组件因子、6 个 ICT 组件因子以及 2 个模板，当前共 **34 个注册因子、7 个研究模板**。这里的 H2/L2、Sweep、MSS 均为以下明确 OHLC 规则的基础变体，不宣称复刻完整主观理论。

### 1. Brooks 基础 Pack

`BROOKS.TREND_UP/DOWN`、`PULLBACK_UP/DOWN`、`FIRST_UP/DOWN`、`FAILURE_UP/DOWN`、`SECOND_UP/DOWN` 共享参数：`trend_lookback=10,max_bars=20`。

向上规则（向下全部镜像）：

1. 趋势背景为上一根收盘高于 `trend_lookback` 根之前的收盘，完全排除当前收盘。
2. 无活动形态时，趋势向上且当前收盘低于前收盘，启动回调。背景锚点是前 `trend_lookback+1` 根最低价，启动时收盘不能低于锚点。
3. 后续某根收盘严格高于前根最高价，确认首次入场；锁定这根最低价作为失败价。
4. 再后续某根收盘严格低于首次入场的失败价，确认首次失败。
5. 再后续某根收盘严格高于前根最高价，确认二次入场（H2 收盘变体）；完成后不重复触发。下行对应 L2。
6. 每根最多推进一步；活动期间收盘越过背景锚点优先失效，距启动根数超过 max_bars 时过期。失效/过期当根不重新启动。不根据尚未确认的盘中高低顺序推进状态。

暖启动完成前为 null，未发生事件为 0，发生当根为 1；Trend 为背景状态，其余为阶段事件。事件和追加式状态日志保存 match_id、锚点、参数、发生/可用时间。`--sequence-audit --replay` 可审计所有阶段。模板 `RESEARCH.BROOKS_SECOND_ENTRY` 同时要求 H2 完成和当前滞后趋势仍向上；完整形态的历史依赖不因移除模板的当前趋势输入而消失。

### 2. 理论研究全流程与参数稳定性分析

```bash
.venv/bin/quantlab run --data-root /Volumes/Lexar/MQC-DATA --output artifacts \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-08-03 --end 2026-09-04 --universe listing \
  --theory RESEARCH.BROOKS_SECOND_ENTRY --theory-study-json examples/brooks_study.json
```

`examples/brooks_study.json` 指定固定 split、滚动 schedule、被改变的组合 input 别名以及它的参数 grid。工作台选择“理论研究全流程”，可选 JSON 中使用 `{"theory_study": 上述文件内容}`。日期必须与研究范围相容；它是独立任务方式，不混用外层分段、扫描或回测开关。

一次任务固定加载行情快照，依次保存：各输入（Brooks/ICT 序列还展开其阶段组件）、完整组合、共同样本逐输入消融、固定 train/valid/test、滚动验证、指定输入参数网格的分段研究。行情上下文沿用已有快照机制；所有子研究有独立链接与配置。启用 permutation 时，消融同时计算配对 IC 差异，顶层按所有子研究原始检验重新组成 Holm 检验族。

`stability` 按阶段和持有期汇总各预设参数的 IC、Rank IC、多空差、触发样本收益均值：最小值、最大值、跨度、正/负比例及有效配置数。缺失保留，不填零；少于两个有效配置标记 insufficient_variants。这是**描述性参数敏感性分析**，不是显著性检验、自动择优或稳定性认证。跨参数重复查看测试段属于探索，不能再称该测试段完全未见。Brooks 的阶段组件独立评价与完整形态的逐条件消融回答不同问题，不混为因果贡献。

### 3. ICT/SMC 基础 Pack

- `ICT.SWEEP_UP/DOWN`：分别复用前区间向下/向上扫出且收盘回到区间内的统一失败突破事件。只是 OHLC 扫出收回，不证明存在挂单流动性。
- `ICT.DISPLACEMENT_UP/DOWN`：方向实体 `direction*(close-open) >= atr_multiple*prior_atr`，且非零实体占当前全振幅至少 body_fraction。ATR 为此前 lookback 根真实振幅的简单平均，shift(1) 排除当前根。默认 lookback=20、atr_multiple=1.5、body_fraction=0.7。
- `ICT.MSS_UP/DOWN`：Sweep → 同向 Displacement → 同向已确认摆动突破，必须三个不同可用时点。左右确认默认各 2 根；相邻步骤时间差严格小于 max_gap_seconds（默认 172800）。反向 Sweep 优先取消等待；同根扫出与位移不能冒充先后顺序。这里定义的是序列变体，不泛称所有结构转变。
- 模板 `RESEARCH.ICT_MSS_FVG` 在向上 MSS 完成时要求双向活跃 FVG 总数大于零，沿用已有 FVG 生命周期。未新建 Order Block、Kill Zone、完整 ICT/SMC 理论或真实订单流算法。

可将全流程命令替换为 `--theory RESEARCH.ICT_MSS_FVG --theory-study-json examples/ict_study.json`。

### 4. Signal / Portfolio / Risk

`execution/portfolio.py` 的 `TargetWeightBuilder` 从当时已知因子值和资格生成信号、选股、原始权重、约束后权重。成交引擎只接收最终目标。默认行为保持原先 TopK、Threshold、EqualWeight；新增正分数权重 ScoreWeight。

```json
{"portfolio":{"weighting":"equal","max_position":0.25,"max_exposure":0.8,"max_turnover":0.5}}
```

CLI 使用 `--portfolio-json examples/portfolio_limits.json`，只用于 `--backtest`。分数权重要求入选分数严格为正，不隐式平移负分数。先约束总敞口和单股仓位，截断后的余额保留现金，不重新分配。

换手为相邻目标快照的 `sum(abs(new_weight-old_weight))`，是完整 L1 口径。超预算时在前目标与本次受限目标之间线性缩小调整；资格失效强制目标归零，优先于换手预算，并记录 override 原因。以上是**目标风控**，不是实际成交换手或 T+1 受限实际持仓的硬保证。`target_audit` 保存原始分数、资格、入选名单、原始/仓位敞口约束/最终权重、换手及调整原因。

本轮未增加行业限制或波动率权重，因为它们不属于本轮明确约定的三项风控约束，也尚缺可靠行业历史数据。

### 5. vn.py 离线适配与双引擎核对

可选安装 `.venv/bin/pip install -e '.[vnpy]'`。固定 `vnpy==4.4.0`，另声明 `alphalens-reloaded==0.4.6`，因为该版本的 alpha 包在导入时需要它；不安装整套 alpha ML extras。研究核心可在未安装 vn.py 时单独运行，只有选择该后端才导入第三方模块。

```bash
.venv/bin/quantlab run --data-root /Volumes/Lexar/MQC-DATA --output artifacts \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-08-03 --end 2026-09-04 --universe listing \
  --theory RESEARCH.BROOKS_SECOND_ENTRY --backtest \
  --execution-backend vnpy_open --execution-json examples/vnpy_execution.json \
  --portfolio-json examples/portfolio_limits.json
```

网页选择“独立成交回测”，可选 JSON 中设置 execution_backend=vnpy_open、execution 与 portfolio 对象。**vnpy_open 要求 minimum_commission=0、slippage_bps=0、limit_pct=0.1**；不支持的设置明确失败，不静默忽略。示例费率只是对账参数，不代表实际税费。

适配器使用原生 `vnpy.alpha.strategy.backtesting.BacktestingEngine` 的 send_order、cross_order、TradeData、持仓回调和现金核算。上游整根回放会使用最终高低价，因此这里用明确的开盘时钟传入 O=H=L=C=当时开盘价、volume=0 的撮合切片；收盘后才更新估值。它是**原生撮合内核的开盘驱动适配**，不是原封不动调用上游 new_bars/run_backtesting，也没有复制改写上游撮合源码。[官方实现](https://github.com/vnpy/vnpy/blob/4.4.0/vnpy/alpha/strategy/backtesting.py)

适配边界：sh/sz 代码转 SSE/SZSE，合约乘数 1，数值价格网格 1e-8（不声明历史最小价位），原生固定 10% 前收盘限制。平台负责开盘时目标转股数、现金预算、整手和 T+1 可卖数量；原生引擎产生成交并更新现金/持仓。未成交订单本次撮合后取消，下一根按新目标重建；缺行情不制造成交。首次缺前收盘报价或限价舍入边界可能与自研模型不同，必须看核对结果。

每次 vnpy_open 实验同时在自研引擎执行**完全相同的已保存目标、行情和费用配置**，记录逐笔成交差异、现金/持仓市值/净值最大差、期末仓位和双方汇总，状态为 matched 或 different。原生订单、交易 ID 和逐日结果保留在 backend_details。出现差异不会覆盖任一结果或伪装一致。不连接 Gateway，不进行模拟账户或实盘下单。

## Wyckoff 基础研究闭环（2026-09-09）

新增 `WYCKOFF.RANGE/SPRING/UPTHRUST/TEST_UP/TEST_DOWN/SOS/SOW`，版本 `1.0.0`。
`lookback=20` 的前区间满足 `(high-low)/low <= max_width=0.15` 时具备区间背景。Spring/Upthrust 为扫出后收盘回到区间；同时扫出两端不推断盘中方向。首次事件冻结上下沿及扫出极值。后续独立 K 线在边界附近 `test_fraction=0.25` 内、未破极值且成交量低于首次事件时确认 Test，再于后续 K 线收盘突破冻结对侧确认 SOS/SOW。跌破/升破初始极值或超过 `max_bars=40` 失效；失效当根不重新启动。这是明确 OHLC 变体，不是完整吸筹/派发阶段识别。

```bash
.venv/bin/quantlab run --data-root /Volumes/Lexar/MQC-DATA --output artifacts \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-08-03 --end 2026-09-04 \
  --theory RESEARCH.WYCKOFF_SOS_MOMENTUM \
  --theory-study-json examples/wyckoff_study.json --horizons 1 5 --regime
```

全流程会展开 7 个 Wyckoff 组件及动量输入，再运行组合、消融、固定样本外、滚动和固定网格敏感性；保存事件来源及可回放行情。

## Chan 结构接口

`adapters/chan.py` 的 `ChanStructureAdapter.analyze(bars)` 返回带 `structure_id/kind/symbol/timeframe/occurred_at/available_at/components/version` 的追加式记录；笔和中枢另带上下价格边界。算法版本 `confirmed_alternating_v1`。

默认严格分型左右各 2 根确认。笔保留首个已接受端点，只接受相反类型、间隔至少 3 根且价格方向一致的确认端点；同侧新分型不会回写旧笔。同根兼具高低分型时不选为端点。连续三笔的价格区间存在严格正宽重叠时创建中枢；其可用时刻为第三笔末端确认时刻。注册 `CHAN.PIVOT_HIGH/PIVOT_LOW/BI/CENTER`，可用普通研究、参数 JSON、审计和回放入口。没有包含 K 线合并、线段、背驰和买卖点；不能把此变体当作完整缠论实现。

## 研究视图与样本外残差 IC

工作台 `FactorExplorer` 支持检索当前定义及关联历史实验；`TheoryLab` 展示概念映射并关联全流程及子实验；`RegimeViewer` 从保存的观测按状态展示数量、条件收益及组内合并 IC，保留 Unknown，不把合并 IC 称为日均截面 IC。历史实验以各自 manifest 为准。

新增 `residual-alpha` 命令，候选与控制因子必须来自相同数据快照和股票池的已完成单因子产物，按完整信息键对齐并检查标签一致性。最多 20 个控制输入。仅用训练期因子值拟合带截距的标准化 OLS 投影，再冻结系数计算样本外残差 IC 和日期块符号检验；训练不使用收益标签。常量、共线或不足的训练样本报错，测试日期块不足返回 unavailable。只检验相对指定线性控制的增量信息，不是因果归因、收益回归 alpha 或统计独立性证明；不做自动择优或跨研究多重校正。

```bash
.venv/bin/quantlab residual-alpha \
  --candidate artifacts/2a20f50b-6953-4b27-911f-be05f1214001 \
  --controls artifacts/a0b492b2-5111-44f2-ace3-6213ed6e23aa \
  --train-end 2026-08-14 --horizon 5 --output artifacts
```

## 逐时点交易规则、费用与实际持仓风险

回测新增 `--market-rules <JSON>`；网页独立回测高级配置使用 `market_rules: [...]`。每项必须包含：

- `symbol`、`effective_at`、`available_at`、`expires_at`：后三者是显式时区 ISO 时间。
- `suspended`、`st`：显式布尔值。
- `limit_up`、`limit_down`：当天实际价格上下限；两者均为 null 表示来源明确给出的无上下限会话，不推断板块规则。
- `commission_bps`、`minimum_commission`、`sell_tax_bps`、`transfer_bps`：明确的该时段模拟费率及最低佣金。
- `source`：非空来源说明。

开盘时仅选择已生效、已可用、未到期的最近记录。未知规则阻止下单；停牌阻止买卖；默认 ST 阻止买入；方向价格限制作用于观察到的开盘报价，不使用本根最终高低价或成交量决定开盘成交。规则支持修订但不会提前使用修订信息。官方价格上下限应由可靠数据源提供，不能用当日最高/最低价替代。

`ExecutionConfig` 新增 `transfer_bps/fee_decimals/max_actual_position/max_actual_exposure/allow_st`。费用按每笔订单计算，可按指定小数位四舍五入（ROUND_HALF_UP）；未配置精度时保留旧行为。买单按扣费和滑点后的实际账户权益检查单股及总敞口；T+1、停牌或行情变动造成的实际超限保留在 `risk_audit`，不会伪造强平成交。示例 `examples/rule_aware_execution.json` 只是模拟参数，不自动代表真实券商或法定历史费率。

`vnpy_open` 保留原有受限模型。新增 `vnpy_rules`：平台准备满足规则、费用和风险的订单，交由 vn.py 原生 `cross_order` 和现金/持仓回调；每笔核对原生现金。用含配置滑点的模型报价中和上游固定 10% 检查，逐单费率表达已舍入费用。双方共享订单准备，所以此路径验证原生撮合记账，不是两套独立市场规则实现的互证，也不使用上游日盈亏汇总宣称动态费用正确。

```bash
.venv/bin/quantlab run --data-root /Volumes/Lexar/MQC-DATA --output artifacts \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-08-03 --end 2026-09-04 \
  --factor BASE.MOMENTUM --lookback 5 --backtest --execution-backend vnpy_rules \
  --execution-json examples/rule_aware_execution.json \
  --market-rules artifacts/acceptance-inputs/synthetic-market-rules.json
```

上面规则文件是 **SYNTHETIC_ACCEPTANCE_ONLY**，明确假设可交易且无价格上下限，不能用于宣称历史 A 股规则已覆盖。真实 MQC 数据目前缺完整历史 ST/停牌/价格上下限流水；公司行动也未接入。

## Paper Trading：可恢复的 K 线模拟账户

新增 `paper-step` / `paper-status`。使用上述回测生成的 `bars.parquet` 和 `targets.parquet`，配合显式交易规则交付到模拟账户；账户文件在工作台 `artifacts/paper/*.json` 可查看。保存订单、成交、拒绝原因、费用、现金、持仓、净值、风险和处理游标；锁与原子替换保障同机并发及重启恢复，重复完整快照幂等。历史输入修订、规则删除、迟到输入导致账本变化、引擎代码或账户配置变化都会拒绝更新。需要更换算法或配置时创建新账户。

```bash
.venv/bin/quantlab paper-step \
  --account artifacts/paper/mqc-synthetic-rules.json \
  --bars artifacts/acceptance-inputs/paper-bars.parquet \
  --targets artifacts/acceptance-inputs/paper-targets.parquet \
  --market-rules artifacts/acceptance-inputs/synthetic-market-rules.json \
  --execution-json examples/rule_aware_execution.json --backend vnpy_rules
.venv/bin/quantlab paper-status --account artifacts/paper/mqc-synthetic-rules.json
```

`paper-step --follow --poll-seconds 5` 持续读取文件生产者发布的完整快照，Ctrl-C 停止。生产者必须先原子发布规则及目标快照，再原子发布 K 线快照（K 线作为本次交付完成标志）；不得就地写正在读取的 Parquet。证券集合固定，目标权重每个时点必须覆盖该集合。处理时检查数据可用时间不晚于当前时钟；按上海时区执行 A 股日线开盘时钟。进程出错退出，已提交账户仍可恢复；不悄悄忽略损坏或迟到数据。

此版本是基于已完成 K 线交付、模型化下一开盘成交的模拟账户，适合研究和回放。恢复通过完整历史重算实现，尚非低延迟逐笔账户；没有自动接入实时行情订阅、券商 Gateway、真实订单队列、公司行动或容量模型。本轮只完成历史行情分批交付验收，没有宣称连续实时模拟运行。

## 数据底座与历史来源验收（2026-09-09，后续一轮）

新增以下入口，所有命令只读原始 MQC，输出写到平台目录；已有输出文件不会覆盖：

```bash
.venv/bin/quantlab data-query --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 --timeframe 1d --start 2026-08-03 --end 2026-09-04 \
  --output artifacts/my-query.parquet
.venv/bin/quantlab data-audit --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 --timeframe 5m --start 2025-01-01 --end 2026-09-04 \
  --output artifacts/my-audit.json
.venv/bin/quantlab data-coverage --data-root /Volumes/Lexar/MQC-DATA --output artifacts/my-coverage.json
.venv/bin/quantlab metadata-import --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600519 sz.000001 --output artifacts/my-metadata.json
```

`data-query` 使用 DuckDB 参数化 `read_parquet` 查询源文件，按指定证券文件、日期及周期读取原始字段，并保存文件哈希、查询范围和行数。查询期间源文件发生变化会报错，不把不同文件状态拼成一次快照。

`data-audit` 检查重复、OHLCV 非法值、日期/时间戳、非交易日、5m 会话时点及每个交易日 48 个时点的完整性；报告区间内日历缺口、观测覆盖之外的日期及源文件空日期行。停牌、上市区间和数据丢失尚需额外证据解释，不能从“缺 K 线”推断停牌或可交易。当前实际审计为五只股票、2025-01-01 至 2026-09-04，并非全市场全历史审计。

真实 MQC 包含交易日历、2026-08-31 单次行业快照和分红记录。`metadata-import` 保留原始公司行动字段及来源哈希；行业只从本次实际观测时间起可用。分红记录尚未用于账户权益登记、到账或股份变化，不把保留原始记录称为公司行动处理完成。

### 补存真实历史 ST / 交易状态

供应商发布的 [Baostock PyPI 说明](https://pypi.org/project/baostock/)列出日线的 `isST`、`tradestatus` 等字段。本轮已实际调用成功，新增可选依赖 `market_data = ["baostock==0.9.3"]`；没有升级其他依赖。

```bash
.venv/bin/quantlab fetch-status --symbols sh.600519 sz.000001 \
  --start 2025-01-01 --end 2026-09-04 --output artifacts/my-historical-status
```

结果按证券保存原始返回字段、抓取时间和哈希，失败保留 manifest 及已取得的部分文件。当前已补存 20 只股票、8,140 条真实历史状态记录，见 `artifacts/data-acceptance/baostock-status`。这些是回溯数据，`historical_available_at` 保持 null；缺少历史首次发布时间和官方逐日价格上下限，不能直接转换成严格 PIT 的开盘规则。原有模拟规则文件仍明确标注模拟，未用回溯字段伪造历史可用时间。

## 扩大样本及净收益增量

`examples/expanded_validation.py` 在运行前以排他写入保存固定研究计划：20 只明确选定的股票、2025-01-01 至 2026-09-04、训练至 2025-08-31、验证至 2025-12-31、随后为测试。运行 Brooks、ICT、Wyckoff 全流程并保留失败结果；固定比较动量窗口 5 和 20 的相同波动率组合与成本模型，没有自动择优。重复运行应使用新的计划输出位置；不能覆盖已固定的计划。

新增命令：

```bash
.venv/bin/quantlab return-increment \
  --candidate artifacts/c77403dd-b955-4648-b698-84146ad3e4ee \
  --baseline artifacts/85966023-2e29-4bf2-886a-41f1e8f1d8cb \
  --start 2026-01-01 --output artifacts
```

要求两个已完成执行产物的数据快照、股票池、费用、组合约束、后端、市场规则及估值时钟完全一致。比较每天收盘后的净值收益差，执行日期块 Bootstrap 和符号检验。评估起点继承此前持仓，不自动清仓或训练；结果不是风险调整后的回归 alpha。真实验收包含 164 个样本外交易日，95% 区间包含零，符号检验 p=0.376。样本是预选股票，仍有选择/幸存者偏差；raw 执行未处理公司行动，市场规则也未获得真实完整覆盖，不能作为实盘表现结论。

## 波动率权重、行业目标与实际持仓限制

`PortfolioConfig.weighting` 新增 `inverse_volatility`，使用截至决策收盘的 `volatility_lookback`（默认 20）根收益样本标准差倒数分配已选股票。样本不足、零波动或非有限波动率不参与新分配；不读取未来数据。

目标配置新增 `sector_limit`、`industry_events`。每个行业事件包含 `symbol/sector/effective_at/available_at/source`；两个时间必须带时区。未知行业不分配，行业变更后的行业上限优先于目标换手预算，调整记录留在审计中。

实际执行配置新增 `max_actual_sector` 和 `industry_events`。买入前使用当前实际持仓及扣费后的权益检查行业敞口；未知行业阻止买入。收盘因行情、分类变更或未成交造成的超限记录在 `risk_audit.sector_weights`，不伪造平仓。目标限制与实际限制分别配置，应向两者提供同一份有效历史行业记录；目标限制不自动替代实际限制。原有 `vnpy_open` 拒绝此增强配置，应使用 `open` 或 `vnpy_rules`。

## 持续 MQC 接收与逐日账户核对

新增 `paper-mqc` 将数据加载、已完成 K 线筛选、因子计算、目标权重及持久账户串联。外部程序仍负责维护源 MQC；本命令不回写源文件、不自动下载实时报价。

```bash
.venv/bin/quantlab paper-mqc --data-root /Volumes/Lexar/MQC-DATA \
  --account artifacts/paper/my-new-feed-account.json \
  --symbols sh.600519 sz.000001 sz.000858 sh.601318 sz.300750 \
  --timeframe 5m --start 2026-08-03 --factor BASE.MOMENTUM \
  --parameters-json examples/feed_momentum.json \
  --execution-json examples/rule_aware_execution.json \
  --market-rules artifacts/acceptance-inputs/synthetic-market-rules.json \
  --backend vnpy_rules --follow --poll-seconds 30
.venv/bin/quantlab paper-reconcile --account artifacts/paper/my-new-feed-account.json \
  --output artifacts/my-daily-reconciliation.json
```

示例规则仍为模拟假设。`paper-mqc` 将生产者配置和代码绑定到新账户；变更因子、参数或相关代码需要新账户。重复快照幂等；源读取或配置错误在 follow 模式中明确报错，保留账户提交边界并在下一轮重试；恢复后按完整数据补齐未处理部分。输出每只股票最后行情的墙钟年龄，超过 900 秒标为 `stale_source`，该年龄包含闭市时间，不是交易时段 SLA。

`paper-reconcile` 从已提交成交逐笔重建现金、持仓和收盘估值，输出逐日结果及每个净值时点的差异。实际验收：25 个交易日、1,200 个净值时点、278 笔成交一致。它是内部账本核对，没有券商对账单。

截至本轮探测，现有 MQC 最后行情为 2026-09-04，Baostock 当日 5m 查询返回零行（具体探测时间见 `artifacts/data-acceptance/live-probe.json`）。因此只验证了真实历史行情的接收及恢复链路，**连续实时数据更新、真实历史价格上下限和严格 PIT 来源的验收仍未完成**。需要可持续更新的行情来源及所需历史数据权限/文件后才能继续这部分。

## 训练期 Processor Pipeline 与现金分红账务（2026-09-09）

`examples/pipeline.json` 按顺序配置 `replace_inf`、`fill_na`、`winsorize`、`robust_zscore`、`clip`、`cs_rank`；也支持 `cs_zscore`。`fill_na` 未指定 `value` 时只用训练样本中位数，去极值使用训练分位数，稳健标准化使用训练中位数和 MAD×1.4826（零尺度使用 1）。不做向后填充。行业/市值中性化尚未实现，需相应历史数据。

```bash
.venv/bin/quantlab run --data-root /Volumes/Lexar/MQC-DATA --output artifacts \
  --symbols sh.600519 sz.000001 sz.000858 --start 2025-01-01 --end 2026-09-04 \
  --factor BASE.MOMENTUM --lookback 20 --pipeline-json examples/pipeline.json \
  --train-end 2025-08-31 --valid-end 2025-12-31
```

OOS 自动使用 train 段拟合，Walk-forward 每折独立拟合。训练前的历史输出置空，不能用事后拟合参数计算历史可执行信号；因此 train 段处理后统计不应当作训练期策略表现。验证/测试共用相同训练参数，原始值仍归档。单次研究必须在 JSON 中指定 `fit_start`、`fit_end`，且完全落在请求范围内。处理器版本、代码哈希、训练区间、参数和状态哈希保存在 `manifest.processor`。工作台已有高级配置 `processor` 可直接填入该 JSON 对象；原有字符串 `cs_rank` / `cs_zscore` 兼容。

现金分红入口：

```bash
.venv/bin/quantlab dividend-import --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600000 sz.300750 sz.002938 --tax-rate 0 --output /tmp/dividends.json
```

输出的 `corporate_actions` 列表可放入 `--execution-json` 对应字段。每条记录包含 `action_id`、`symbol`、`record_at`、`ex_at`、`pay_at`、`available_at`、`cash_per_share`、`tax_rate`、`source`，所有时间必须带时区。

账务在登记收盘记录持仓，除息时增加应收分红，派息时将应收转为现金，权益含应收而可买入资金不含应收。登记后卖出不会丢失分红权益。缺少登记日收盘或持仓除息估值行情会报错。税率是显式固定假设，不提供个人持有期递延税计算。送转拆并股尚不支持；导入器将相关记录列入 `unresolved`，不能把部分导入视为完整公司行动覆盖。

默认 `corporate_action_mode="strict"` 要求分红信息在除息时已可用。现有 MQC 数据保留实际观察/获取时间，过去时段只能显式使用 `"retrospective"` 进行事后账务核算，不能标注为严格 PIT。日期型派息按当日 15:00 入账，不能据此假设上午资金可用。`tax_rate=0` 仅是示例的税前假设。

`open`、`vnpy_rules` 和 Paper 账户共用这些账务事件；vn.py 现金分配由平台适配器同步，核对不等于 vn.py 独立实现了公司行动。旧 `vnpy_open` 明确拒绝含公司行动的配置。Paper 引擎代码变更需新账户，旧账户保留可查，不自动重写旧账。

## 历史规则覆盖与新鲜行情检查

```bash
.venv/bin/quantlab market-rules-audit --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600000 --start 2025-01-01 --end 2026-09-04 \
  --market-rules /path/to/official-rules.json --output /tmp/rule-coverage.json
```

按 MQC 交易日历逐证券检查开盘可用、有效期覆盖整日的规则，包含没有下单的日期。`covered` 仅表示所提供记录满足时间覆盖，不认证来源权威性。缺失官方涨跌停价格不能通过固定百分比或两个 null 假装补齐；两个 null 表示来源明确声明不设价格限制。

持续模拟的 `paper-mqc` 可加 `--require-fresh`：当最后行情超过 900 秒或最新证券截面不齐时，拒绝推进账户。时间差含休市时间，因此休市时也会暂停交付；这不是交易日历感知的在线状态判断。`--follow` 保留原有持续读取与错误反馈。需要外部程序实际更新 MQC，该命令本身不订阅行情。

本轮真实运行、测试和未完成项见 `artifacts/phase4-acceptance/report.md`。当前没有官方历史规则数据及连续当日行情，第四版真实交易验收尚未完成。

## 行业、市值及联合中性化（2026-09-09 续建）

Pipeline 现支持 `industry_neutralization`、`size_neutralization`、`neutralization`，分别计算行业内去均值、对数市值截面回归残差，以及行业固定效应加对数市值的联合回归残差。联合处理同时对因子和对数市值做行业内去均值，再做回归；不是依次回归两个变量。它们使用当根收盘时 eligible 股票池的已知控制变量，不拟合未来收益。训练期去极值等历史参数仍按原 OOS/Walk-forward 边界冻结。

`examples/neutralization_pipeline.json` 展示联合处理配置。事件列表故意为空，需要填入真实资料；空列表会产生缺失结果，不会自动下载或猜测。通过原有 `--pipeline-json` 或工作台高级 `processor` 配置提交。行业事件沿用 `symbol/sector/effective_at/available_at/source`；市值事件如下：

```json
{
  "symbol": "sh.600000",
  "market_cap": 100000000000,
  "effective_at": "2025-01-02T15:00:00+08:00",
  "available_at": "2025-01-02T15:00:00+08:00",
  "expires_at": "2025-01-03T00:00:00+08:00",
  "source": "SCHEMA_EXAMPLE_ONLY — 示例数值，不是真实市值记录"
}
```

市值必须正数且使用一致币种、单位及总市值/流通市值口径。按生效时间与实际可用时间选择最新已知记录，并检查过期时间；过期不会回退到更旧记录。不得将当前行业、市值快照回填为历史事件。

缺控制变量的股票输出 null；截面自由度不足或市值与行业共线时，该次残差不可用。完全线性关系的浮点误差归零，避免产生虚假排名。中性化后禁止 `fill_na`，因为这会给缺控制资料的证券伪造残差；需要最终保持中性时，将中性化放在流水线末尾，后续非线性处理可能重新引入暴露。

每步逐时点统计、缺资料数量、可计算状态和市值斜率记录在 `experiment.json.processor_audit`，Markdown 报告展示覆盖汇总。审计计数是步骤计算结果，最终研究还会屏蔽拟合前输出。

现有 MQC 无可验证的历史市值序列，行业资料也只有事后快照。算法及接线已验证，真实历史中性化有效性仍未验收。详见 `artifacts/neutralization-acceptance/report.md`。

## 送转股账务与待上市股份（2026-09-09）

现金分红记录可选增加以下三个字段，必须一起提供：

```json
{
  "stock_per_share": 0.3,
  "list_at": "2017-05-26T09:30:00+08:00",
  "fractional_policy": "reject"
}
```

`stock_per_share` 为每股新增股份数，送股和转增比例按明确来源相加。`list_at` 是配置指定的首次可交易时点。上述片段是字段示例，完整记录仍需 action_id/symbol/record_at/ex_at/pay_at/available_at/cash_per_share/tax_rate/source。

登记日固定持仓权益；除权后新增股份进入待上市状态，按当时股价计入净值和实际风险敞口，但不可卖出。目标数量扣除已持有及待上市股份，避免重复买入。到 list_at 后转入可卖持仓，同一时点不作为新买入再附加 T+1。上市前卖掉原股不会丢失待上市权益。

零碎股默认 `reject`：权益不是整数即报错。显式 `floor` 才向下取整，并在账务事件中保存 `fractional_discarded`；这不是对登记结算分配规则的认证。现有模拟卖单允许非整手数量，真实券商零股卖出限制未验收。上一笔送转尚未上市又遇新的权益登记时，可通过 `entitled_pending_actions` 明确指定参与的待上市送转事件（空列表为明确排除），未提供则继续拒绝猜测；拆并股、配股、现金替代、个人持有期税及送股税尚未实现。

```bash
.venv/bin/quantlab dividend-import --data-root /Volumes/Lexar/MQC-DATA \
  --symbols sh.600000 sz.300750 sz.002938 --tax-rate 0 \
  --include-stock-distributions --output /tmp/corporate-actions.json
```

不加新参数时保留原现金分红导入行为。原有 7 条送转记录现在可规范化导入；缺上市日期、无效比例等仍列入 unresolved。来源仅含上市日期时，明确采用 09:30 可卖模型；实际获取时间不倒填，历史回溯仍需显式 retrospective。零税率为示例假设。

`nav.position_value` 包含待上市股份市值，`pending_stock_value` 单列其中部分；`summary.ending_positions` 为已到账持仓，`pending_stock_positions` 为待到账股份。逐日对账同时重建两类持仓。vn.py 适配器在上市时同步可交易股份；公司行动规则与应收资产仍由平台准备，不声称 vn.py 独立实现了登记结算规则。

验证脚本：`examples/verify_stock_acceptance.py --output <新目录>`，目录内先放 `corporate-actions.json`；脚本保存固定账务计划，再运行历史回放及 Paper 恢复。`examples/check_research_sample.py` 保存拟研究样本的资料审查，缺官方规则时保持 blocked，不把合成规则或事后快照标为真实验收完成。详见 `artifacts/stock-acceptance/report.md`。

## 历史行情增量与固定版本（2026-09-09）

使用现有可选 BaoStock SDK 获取历史 raw 行情，保存到新的工作目录，不覆盖 MQC。以下输出目录必须尚不存在；5m 将 timeframe 改为 `5m`。

```bash
.venv/bin/quantlab fetch-bars --symbols sh.600000 sz.300750 \
  --timeframe 1d --start 2026-09-01 --end 2026-09-09 \
  --output artifacts/new-daily-delivery
.venv/bin/quantlab archive-bars \
  --bars artifacts/new-daily-delivery/bars.parquet \
  --source-json artifacts/new-daily-delivery/source.json \
  --archive-root artifacts/my-daily-archive
```

归档命令返回不可变版本的 manifest 路径。后续导入必须用 `--parent <该归档的父版本 manifest>`，证券集合、周期及规范化 schema 必须一致。完全重复返回 unchanged；历史值变化默认拒绝，只有显式 `--accept-revisions` 才另存新版本及前后值审计，旧版本保留。输入来源必须声明 `adjustment: raw`。无数据时抓取仅保存 source.json，不产生 bars.parquet。

已有 `run` 命令加 `--snapshot-manifest <manifest>`，即可用该行情版本研究；仍须提供 data-root 以读取股票池元数据，不兼容 qfq。复制版本目录不会改变行情快照标识，但未打包元数据与完整运行环境，不能据此声称整套研究跨机器可复现。

`paper-mqc` 加 `--archive-root <归档根目录>` 后，选择交付时已观察到的最新版本；`--follow` 可继续消费之后发布的版本。抓取、发布和消费是显式操作，follow 本身不联网更新。已有账户继续拒绝已入账历史被修订；不要直接修改账户 JSON。`--require-fresh` 原有过期检查仍生效。

归档 observed_at 默认当前观察时间；`--observed-at` 仅用于有依据的观察时间导入。归档版本时间不证明历史行情在名义收盘时已首次发布，也不认证历史 PIT 股票池。当前只支持 raw、单周期固定证券集合；没有工作台归档选择界面。

本轮真实更新、固定版本研究及 24 项定向验证见 `artifacts/roadmap-acceptance/report.md`；九步后续工作见 `docs/archive/legacy/非机器学习与实盘_推进清单.md`。

### 逐交易日覆盖与独立日历

`data-audit` 现在可指定 `--snapshot-manifest <manifest>` 审计不可变版本，以及 `--calendar-file <calendar.parquet>` 采用显式日历；不指定时保持原 MQC 读取。日历要求 `calendar_date` 为日期或 ISO 日期字符串、`is_trading_day` 为 0/1，日期唯一，不自动推断休市。

结果包含逐证券 `session_coverage`、5m 具体 `missing_slots`、`calendar_missing_dates`、期望和完整股票交易日数量、日历路径/内容哈希。完整时段与有效 OHLCV 分别检查，最终以总体 `status` 和问题明细判断。无行情区间输出缺口，日历缺日期标记未知；缺行情不自动解释为停牌或未上市。

`examples/verify_data_coverage.py --help` 可查看扩大样本审计参数。实际 20 证券审计、独立日历获取与历史增量更新见 `artifacts/coverage-acceptance/report.md`。新归档仅含 09-01 至 09-08 的接入验收区间，历史全量仍保留于原 MQC。

## 执行偏差、重试、实际换手与容量代理

`open` 和 `vnpy_rules` 回测现在保存 `experiment.json.execution_audit`，Paper 同样保存 `execution_audit`。汇总在 `execution.execution_diagnostics`（Paper 为 `summary.execution_diagnostics`），Markdown 报告增加逐日实际换手表。旧产物不补造诊断，`vnpy_open` 不提供这些增强诊断。

- `bars`：按收盘估值的实际经济持仓权重（包括待上市股份）、本根开盘已采用的目标、两者偏差、现金/应收权重及持仓缺当根报价标记。尚无可执行目标时，偏差为 null；不提前采用当根收盘才生成的目标。股票偏差 L1 不包含现金和应收。
- `attempts`：请求/成交/未成交数量、最后实际收紧数量的约束原因、决策时间及 retry_of。只有同一决策、同一方向且前次仍未成交完才关联重试；每根开盘重新计算需求，不是挂单队列。新目标时间戳会替换旧决策，即使权重相同，也不算旧决策重试。已达到目标则结束重试链。
- `daily_turnover`：实际买入加卖出成交金额（不含费用），除以上一交易日收盘净值；首日用初始资金。不除以二，不等同于目标换手预算；非正分母输出不可用。

可在 `--execution-json examples/execution_capacity.json` 或工作台已有 execution JSON 中设置 `max_volume_participation`，默认 null 保持不限量模型。范围 `(0,1]`：用上一根已完成、同周期、同证券 K 线的成交量（股）乘该比例限制本次数量；买单按整手向下取整，卖单按整数股限制，仍沿用现有零股卖出模型。没有上一根量或量为零时阻止成交。缺失中间 K 线时使用最近已观察量，其参考时点保存在 attempt.capacity.reference。

不使用当根最终量/高低价决定开盘容量。日线使用上一交易日全天成交量，因此只是显式滞后量代理；5m 也不代表下一根开盘真实可成交量、盘口队列或市场冲击。`vnpy_open` 明确拒绝此参数，需用 `open` 或 `vnpy_rules`。容量限制在价格/交易规则之后、账户现金和风险限制之前应用。

本轮更新了执行引擎及其指纹。既有 Paper 账户按原有保护机制拒绝在新引擎下继续推进，须使用新账户路径重放冻结输入；不得直接改旧账户 identity。真实样本、双引擎与恢复验证见 `artifacts/execution-diagnostics-acceptance/report.md`。

## Chan 包含与 ICT OB 新规则包

新增 ChanInclusionPack（9 因子）和 ICTOrderBlockPack（8 因子），总计 62 因子、10 研究模板；旧因子标识与定义保留。Chan 使用后继非包含条确认合并条，再确认分型/笔/三笔中枢，并支持冻结中枢的创建、延续、上下离开。ICT OB 明确定义双向创建、首次接触、失效和超时；不推断机构订单或盘中成交路径。

新增模板 `RESEARCH.CHAN_INCLUSION_CENTER_MOMENTUM`、`RESEARCH.ICT_OB_TOUCH_MOMENTUM`，可通过原理论模板入口提交；理论全流程自动包含相应组件、消融、样本外、滚动及参数敏感性。事件与区间边界保存在 sequence_audit，可通过现有 K 线回放事件通道按确认时间查看；本轮没有添加专用 OB 矩形或合并 K 线绘图界面。

完整因子标识、包含合并方向、延迟、边界相等、生命周期优先级和未完成范围见 `docs/reference/theories/理论扩展规则_Chan包含与ICT_OB.md`。默认参数下 20 证券真实 5m 研究和 43 项相关测试见 `artifacts/theory-extensions-acceptance/report.md`；复现命令在报告内。样本只有六个交易日，流程运行不等于预测有效性或统计稳定性证明。

## Chan 确认推进、速度背驰与三类点

新增 ChanProgressionPack@1.0.0，共十个 `CHAN.RULE_*` 因子：SEGMENT_UP/DOWN、DIVERGENCE_UP/DOWN、BUY1/SELL1、BUY2/SELL2、BUY3/SELL3。该轮注册表共 72 因子、11 模板。新模板为 `RESEARCH.CHAN_RULE_BUY2_MOMENTUM`，原有理论研究入口会自动展开十个组件及完整验证流程。

这是包含确认笔上的保守规则代理：至少三笔推进，反向笔突破前一反向端点才确认；新同向极值的单位原始条归一化涨跌幅减弱才判速度背驰；一类点使用反向确认，二/三类点还需首次回踩再突破。它不等同于完整经典缠论的特征序列、缺口或 MACD 背驰口径。

继承 left/right/min_separation，新增 divergence_ratio（默认 0.8）、max_follow_strokes（默认 12）。严格相等边界、确认延迟、等待失效/超时/替换优先级和所有标识见 `docs/reference/theories/Chan确认推进_线段背驰与买卖点规则.md`。确认事件进入已有 sequence_audit 和回放事件通道；不回填到极值日，也不作为当时可成交的证明。

20 证券、24,000 根真实 5m 的研究及 47 项相关测试见 `artifacts/chan-progression-acceptance/report.md`。一、二类点样本稀少，当前是实现与流程验收，不能宣称预测有效性。

## Wyckoff BCDE 价格阶段

新增 `WyckoffPhasePack@1.0.0`，14 个 `WYCKOFF.PHASE_*` 因子及模板 `RESEARCH.WYCKOFF_PHASE_E_MOMENTUM`；当前共 86 因子、12 模板。B 区间、C 扫出/Test、D 突破/缩量回踩、E 再次突破使用不同确认 K 线，保存失败、超时及未完成链，并接入已有理论全流程和回放事件接口。

`PHASE_CODE` 为阶段标量：0 空闲、1 中性 B、±2 双向 C、±3 双向 D、±4 当根 E 完成；预热为 null。E 不延伸为持久趋势。具体锚点、参数、优先级及因子标识见 [规则](../../reference/theories/Wyckoff价格阶段_BCDE规则.md)。这是价格行为代理，阶段 A 和完整经典吸筹/派发判断尚未实现。

```sh
.venv/bin/python examples/verify_wyckoff_phases.py --output artifacts/wyckoff-phase-recheck
```

输出目录须为新目录。49 项相关测试、20 证券 24,000 根真实历史 5m、20 项组件与研究任务、3 组前缀及 48 次回放游标检查见 [验收报告](../../../artifacts/wyckoff-phase-acceptance/report.md)。E 确认向上 8 次、向下 14 次，当前证明实现与研究流程可运行，尚未证明预测有效性。

## Brooks 突破回踩与测量目标

`BrooksBreakoutPack@1.0.0` 新增 14 个双向布尔事件因子：`BROOKS.BP_` + `BREAKOUT/PULLBACK/RESUMED/MEASURED_MOVE/FAILED/INVALIDATED/EXPIRED` + `_UP/_DOWN`。当前注册表共 100 因子、13 模板。

`RESEARCH.BROOKS_BREAKOUT_PULLBACK` 将向上再启动事件与正动量组合，复用理论全流程、组件消融、样本外、滚动和参数对照。序列完成表示再启动后另根收盘达到冻结的一倍区间目标，不能和再启动事件或可成交订单混淆。失败、超时与未完成链均进入审计及现有回放事件接口。

前区间排除当根；默认 lookback=20、body_fraction=0.5、retest_fraction=0.1、max_bars=40。具体边界、优先级、目标确认及未实现范围见 [规则说明](../../reference/theories/Brooks突破回踩与测量目标规则.md)。原有 Brooks H2/L2 定义不变，新增规则不等于完整主观 Brooks 判图。

```sh
.venv/bin/python examples/verify_brooks_breakout.py --output artifacts/brooks-breakout-recheck
```

输出须为新目录。44 项相关测试通过，真实 20 证券、24,000 根 5m 的研究及全部双向组件前缀验证见 [验收报告](../../../artifacts/brooks-breakout-acceptance/report.md)。本轮完成实现和流程验证，未证明统计稳定性或收益增量。

## Brooks 背景状态代理

`BrooksContextPack@1.0.0` 提供 `BROOKS.CTX_RANGE`、`CTX_CLIMAX_UP/DOWN`、`CTX_ALWAYS_IN`、`CTX_FLIP_UP/DOWN` 六因子，模板为 `RESEARCH.BROOKS_DIRECTION_MOMENTUM`。当前共 106 因子、14 模板。

区间背景使用此前窗口宽度和方向效率；Climax 为相对此前平均 TR 的强实体扩张代理；AlwaysIn 为强实体区间突破后的持续方向，直到反向突破才切换。它们各自描述不同现象，区间和方向可以同时存在。源窗口、阈值与确认条进入既有审计回放；背景不伪造序列完成计数。

完整参数、预热、跨日处理及边界见 [规则](../../reference/theories/Brooks背景状态规则.md)。新模板复用六组件、组合、消融、样本外、滚动和固定参数对照。

```sh
.venv/bin/python examples/verify_brooks_context.py --output artifacts/brooks-context-recheck
```

输出目录须为新目录。44 项相关测试与 20 证券、24,000 根真实 5m 全流程验收见 [报告](../../../artifacts/brooks-context-acceptance/report.md)。这是明确价格规则的实现与流程验证，不证明完整理论、预测有效性或可成交收益。

## Brooks Wedge 三极值收缩反转代理

`BrooksWedgePack@1.0.0` 新增八个双向事件因子：`BROOKS.WEDGE_` + `SETUP/CONFIRMED/INVALIDATED/EXPIRED` + `_UP/_DOWN`。新模板 `RESEARCH.BROOKS_WEDGE_REVERSAL` 组合向上确认与正动量，当前共 114 因子、15 模板。

使用五个交替已确认极值，三次同向新极值且末次推进增量缩小才建立形态，再等待后续条收盘突破冻结颈线。复用严格拐点确认、序列审计与回放，失败/超时/未完成形态保留。完整边界与未实现范围见 [规则](../../reference/theories/Brooks三极值收缩反转规则.md)。

```sh
.venv/bin/python examples/verify_brooks_wedge.py --output artifacts/brooks-wedge-recheck
```

输出须为新目录。52 项相关测试、20 证券 24,000 根真实 5m、10 项研究任务及双向因子前缀检查见 [验收报告](../../../artifacts/brooks-wedge-acceptance/report.md)。本规则不拟合趋势线/角度，不等同所有主观楔形定义，也未证明收益有效性。

## 跨实验固定检验族登记

新增 `trials-create`、`trials-bind`、`trials-report`：先冻结多个完整单实验配置及全部持有期 IC/Rank IC 假设，再一次性绑定结果，从原始 p 值计算统一 Holm。失败、未运行、不可检验项保留计划名额；同一结果重复绑定 unchanged，不同结果替换拒绝。报告保存计划和结果副本，来源删除不改变报告。

```sh
.venv/bin/quantlab trials-create --plan plan.json --output artifacts/my-trials
.venv/bin/quantlab trials-bind --registry artifacts/my-trials --trial-id momentum10 --artifact artifacts/RUN_ID
.venv/bin/quantlab trials-report --registry artifacts/my-trials --output artifacts/my-trials-report
```

plan 包含 name、alpha、trials；每个 trial 包含 trial_id 和完整序列化 ExperimentConfig 的 config。可运行 `examples/verify_trial_registry.py --output artifacts/trial-registry-recheck` 生成可复现计划与真实研究。完整 schema、时间关系和限制见 [规则](../../reference/theories/跨实验试验登记与Holm校正规则.md)，28 项相关测试及真实 CLI 验收见 [报告](../../../artifacts/trial-registry-acceptance/report.md)。

本地登记不是可信第三方预注册。现支持单实验及下文四类父研究与配对 IC 差异；登记之外的探索、重复查看及择时停止未控制。既有单份研究的 Holm 口径不变。

## 父研究登记与配对 IC 差异

固定族登记 1.1 兼容原单实验，新增 `study: {kind, design}` 支持 ablation、holdout、walkforward、sweep；按原有枚举器自动冻结全部子项、阶段和原始检验名额。消融启用 incremental_test 后，配对 IC/Rank IC 差异和各子项原始 IC 同族校正。

绑定时拒绝设计变化、漏项、重复/额外子项；部分失败保留已产生的检验，剩余项继续占名额。报告拒绝同一根/后代 run_id 在多个登记条目重复计入。原 `trials-create/bind/report` 命令复用，父结果直接传 --artifact。

```sh
.venv/bin/python examples/verify_parent_trials.py --output artifacts/parent-trial-recheck
```

使用新目录。完整 design 字段和边界见 [规则](../../reference/theories/跨实验试验登记与Holm校正规则.md)；32 项相关测试、四类真实父研究及 88 项固定名额验证见 [验收报告](../../../artifacts/parent-trial-acceptance/report.md)。theory_study 最外层和执行净收益族仍不支持；本地登记不证明未见数据，不控制登记外探索或反复查看。

显式公司行动叠加的字段、边界和测试证据见 [说明与验收](../../../artifacts/overlapping-actions-acceptance/说明与验收.md)。

### 独立成交归档复算

在 PyQt 实验详情中点击“使用归档 K 线复算并核对”，可对本版本的因子与独立成交回测归档重新计算。执行归档分别读取冻结的信号 K 线和 raw 成交 K 线，全量核对信号、目标、成交、拒单、执行汇总与净值，并保存 `reproduction.json`。要求匹配源码/运行指纹和完整本地输入；历史股票池、多周期 context 与常规父级研究支持范围见下节，老归档缺失依赖时仍拒绝复算。导出包内 `tools/reproduce.py` 使用相同流程，须自行提供匹配解释器及依赖。见 [实现和真实客户端验收](../../../artifacts/execution-reproduction-acceptance/说明与验收.md)。

### 冻结历史依赖与父研究复算

开启行情回放归档后，研究会同时冻结实际使用的各周期行情及股票池资料。因子、独立成交、OOS、Walk Forward、参数扫描、消融、理论全流程与相关性及其分段/滚动研究可在匹配环境下整体复算；不需要原行情目录。PyQt 实验详情的“复算核对”页显示持久核对结果及父子 run 对应。旧归档缺失输入时会明确拒绝，不补造历史状态。衍生比较、固定净收益族及指定平台离线环境的后续交付见下节；此轮原始证据见 [本轮完整范围与验收](../../../artifacts/research-reproduction-completion/说明与验收.md)。

### 衍生比较与离线环境交付

当前客户端支持残差、净收益增量、稳定性和固定净收益族复算；保留原计划与随机种子、失败名额及 Holm 范围。系统设置可导出当前 macOS arm64 / Python 3.13.5 环境，含独立解释器、87 个当前固定版本依赖及校验安装脚本；首次导出需要联网，安装使用本地 wheels。实际禁止联网/读取 Homebrew 的安装及包内源码复算已通过，同机隔离不等于第二台机器验收。通用 `trial_registry` 外部登记仍待纳入。见 [范围、命令与客户端证据](../../../artifacts/derived-reproduction-completion/说明与验收.md)。

### 通用登记族复现

PyQt 原固定族报告入口现会创建常规归档并打开详情，支持检验表与持久复算结果。CLI 原命令可加 `--archive-output RUNS_DIRECTORY`，将原登记、绑定、报告及成功来源纳入复现包。复算保留原时间证据，重算成功来源及全计划 Holm；失败/未运行项保留并报告 `available_results_matched`。旧来源丢失时不补造。见 [真实客户端与离线验收](../../../artifacts/trial-reproduction-completion/说明与验收.md)。

### 显式拆股与并股

执行扩展配置 `execution.stock_splits` 支持准确生效时点的新/旧股数比例，保留原持仓批次日期，同步 vnpy_rules 和 Paper 账务；归档可独立复算。当前仅接受整数批次转换，零碎股与送转待上市叠加明确拒绝。旧 vnpy_open 不支持且会报错。完整 schema、合成案例及客户端证据见 [拆并股验收](../../../artifacts/stock-split-completion/说明与验收.md)。第二台物理机器验收已按用户要求排除，不再作为推进条件。

### 显式配股指令

通过原实验 JSON 的 `execution.rights_issues` 指定登记资格比例、认购股数、价格、缴款/除权/上市时点和资金不足策略。缴款后按成本记认购款资产，除权后记待上市股份，上市才可卖出；支持 open/vnpy_rules、Paper 恢复和归档复算。未行使权利估值为零，不模拟可转让配股权，零碎股和未明确叠加拒绝。取消退款与额外认购税费仍待实现。见 [完整字段和验收证据](../../../artifacts/rights-issue-completion/说明与验收.md)。


### 公司行动生命周期与费用（2026-09-10 更新）

本节更新前述历史能力边界：新增配股 `subscription_fee`、上市前 `cancellation` 与延后退款；`floor` 配股资格；送转及拆并股 `fractional_settlement`；明确登记基数 `entitlement_quantity` 下的叠加权益。独立对账按 FIFO 重建批次、重新计算时点费用和事件金额。PyQt 执行归档新增“公司行动与费用”页签，可选择流水查看现金、应收、股份与来源。

字段、时间顺序、结算假设与拒绝范围见 [明确规则合同](../../../artifacts/corporate-actions-module-completion/规则说明.md)；测试和实际客户端/离线复算证据见 [模块验收](../../../artifacts/corporate-actions-module-completion/说明与验收.md)。合成验收不能替代官方历史资料。待上市权益的拆并换算、可转让配股权、个人递延税等仍未实现。

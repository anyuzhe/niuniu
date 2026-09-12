# 牛牛 AI 交易工作台 P7 今日交易驾驶舱验收说明

日期：2026-09-13
阶段：P7 Trading Cockpit
前置稳定基线：`1c3b81f`

## 一、目标

把牛牛默认首页从“实验统计入口”升级成个人 A 股交易研究驾驶舱，同时保持所有信息来自正式持久化证据，不用模型现场编数字。

首页统一聚合：

- 当前 Strategy Intent / 候选股票
- 当前计划与持有意图
- Theme Matrix / 正式市场事实
- 已保存 AI Thesis
- Risk Review / 失效条件
- Research Agenda
- Watch / 跟踪状态

打开首页本身不调用模型、不刷新 Watch、不下载数据、不运行研究。
## 二、日期与 Frame 语义

驾驶舱不会根据自然时钟猜“当前正在 R1/R2/R3”。

- 用户显式选日期时，只读取该日正式证据。
- 未显式选择时，优先使用工作空间中最新有 Decision / Theme Snapshot 的业务日。
- 如果工作空间完全没有业务证据，才退回上海时区自然日，并明确标记为 fallback。
- `latest_saved_frame` 只表示该业务日已经保存的最晚 Decision Frame，不代表实时交易阶段。

因此周末打开牛牛时，不会伪装成“周末也有盘中 A 股数据”。

## 三、市场事实边界

首页只展示正式 Theme Snapshot 中已经保存并带来源/时点的 facts。

- 不把 AI Thesis 当市场事实。
- 不用 Decision 标签推导主线强弱。
- 不跨主题相加涨停数、成交额等字段，避免同一股票多主题归属造成重复计数。
- 无正式 facts 时显示“未提供正式市场事实”。

这延续 P4 的 UNKNOWN / provenance 合同。
## 四、界面

默认首页现在包含：

- 业务日期选择与刷新
- 候选 / 计划 / 主线快照 / Agenda / Watch / 风险 KPI
- 主线 / 市场事实表
- 候选股票表，可下钻 Stock Dossier
- 当前计划 / 持有意图表
- 已保存 AI Thesis
- Decision / Theme 风险复核
- Research Agenda
- Watch / 跟踪

快捷入口保留 `＋ Decision`、AI 助手和 Research Agenda。

## 五、隔离端到端验收

证据：`artifacts/trading-cockpit-p7-20260913/acceptance-latest.json`

验收级别：`isolated_host_fixture_no_live_market_no_model_call`。
实际结果：

- 默认业务日 = 2026-09-11，来源 = latest workspace evidence。
- 最新已保存 Frame = R2。
- 候选 = `sh.600000`。
- 当前计划 = `sz.000001`。
- 当日正式 Theme = 银行，facts 来源 = `fixture:p7-e2e`。
- Agenda = 2 项。
- Watch = 1 项。
- 风险项 = 3 项。
- 失败任务归档前后字节一致。
- Watch state 前后字节一致。
- 新增研究任务 = 0。
- automatic execution = false。

本验收没有实时 A 股行情，也没有调用模型；fixture 只验证聚合和权限边界。

## 六、测试结果

扩大桌面/交易/研究回归：138 项通过。
最终全仓：**724 passed / 0 failed / 0 skipped**，exit code = 0。

下一阶段：**P8 AI Team / Peer Review**。
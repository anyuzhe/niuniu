# 牛牛 AI 交易工作台 P3 Stock Dossier 验收说明

日期：2026-09-12

基线提交：`5a8159f`（P1/P2 已完成）

本阶段完成总计划 P3：以股票为中心聚合已有研究证据，不重跑实验、不刷新 Watch、不创建新研究任务。

## 一、聚合内容

每个 Stock Dossier 当前可统一展示：

- 当前未被 revision 替代的 Decision。
- 完整 Decision 历史 / revision 时间线。
- Decision 中出现过的主题标签。
- 明确把该证券列入 `data.symbols` 的已保存实验。
- 明确把该证券列入冻结规则数据范围的 Factor Watch。
- 当前 Strategy Intent；仍明确标注“不等于真实成交或真实账户持仓”。

实验关联采用证券列表精确匹配，不按研究问题文本或股票名称相似度猜关联。
## 二、桌面使用形态

“股票中心”继续显示每只证券的最近主题、角色、交易日、Frame、状态和最近判断。

双击股票后打开原生 Stock Dossier，包含四个页签：

1. `当前概览`：当前 Decision、主题和证据数量。
2. `Decision 时间线`：原判与 revision 全部保留，可打开具体 Decision。
3. `研究证据`：相关实验，可直接打开原实验归档。
4. `Watch / 跟踪`：相关 Watch，可进入原跟踪池继续人工管理。

打开股票档案是只读聚合动作，不会提交实验、生成刷新提案或改变 Watch 状态。

## 三、验收

P3 核心 + UI + P1/P2 联合专项：11 项通过。

全部桌面相关联合回归：98 项通过。

最终全仓：**692 项通过，0 失败，0 跳过，exit=0**。
独立端到端工作区实际建立：1 条当前 Decision + 1 条旧 revision、1 个相关实验、1 个相关 Watch。

Stock Dossier 聚合结果：当前动作 `READY`、Decision current=1、Decision history=2、experiments=1、watches=1、research jobs created=0。

最终业务源码指纹：`deb974c1ced588473324bfa7f301e3217cbf24fbb9e0460d896cff25c9c9fb2f`。

证据目录：`artifacts/stock-dossier-p3-20260912/`。

## 四、明确边界

P3 没有把 Stock Dossier 宣称为完整实时行情终端。以下按总计划继续留给后续阶段：

- P4：正式 A 股 Theme Matrix 与市场事实输入。
- P5：交易日历驱动的 PREP/AUCTION/R1/R2/R3/D1/D2/D3+。
- P6：正式策略动作状态机和 Paper Position 联动。
- P8：AI Team / Peer Review。

下一阶段：**P4 A 股主线市场 / Theme Matrix**。

# 牛牛 AI 交易工作台 P5 Decision Frame 验收说明

日期：2026-09-13
阶段：P5 Decision Frame
前置稳定基线：`4f361ad`

## 一、目标

P5 将 `PREP / AUCTION / R1 / R2 / R3 / D1 / D2 / D3_PLUS` 从普通标签升级为可审计的时间合同。

核心要求：后来的行情和判断不能覆盖当时记录；迟交、补录必须留下证据；缺失轮次保持 missing。

## 二、已实现

- Frame Policy 可配置并有独立版本号。
- 默认时区为 `Asia/Shanghai`。
- PREP、AUCTION、R1、R2、R3 有明确时间窗口。
- Decision 由宿主写入真实 `submitted_at`，用户/模型不能自行伪造。
- 每条新 Decision 保存 policy version、窗口起止与本地提交时间。
- 提交状态区分 `EARLY / ON_TIME / LATE / BACKFILL / UNBOUNDED`。
- `effective_at` 如晚于真实提交时点会被拒绝。
- D1/D2/D3+ 必须关联更早交易日的同一证券原始 Decision。
- 原始 Decision 只允许来自 PREP/AUCTION/R1/R2/R3，不能串联另一个 D1/D2/D3+ 冒充原判。
- Revision 仍保持 append-only，不覆盖旧 Decision。
- 旧版没有 P5 字段的 Decision 保持可读，并在界面显示 `legacy`。

## 三、跨轮复盘

新增跨轮对比：

- 顺序固定为 PREP → AUCTION → R1 → R2 → R3。
- 某轮没有 Decision 时保持 `missing`。
- 不拿后续轮次或 revision 回填缺失轮次。
- 比较动作、主题、主题角色、Machine State 与 AI Thesis 是否变化。

Stock Dossier 的 Decision 时间线同步显示实际提交时间与提交状态。
## 四、Frame Policy

默认窗口：

- PREP：前一自然日 15:00 → 当日 09:15
- AUCTION：09:15 → 09:30
- R1：09:30 → 10:30
- R2：10:30 → 13:30
- R3：13:30 → 15:30
- D1/D2/D3+：本阶段不绑定盘中具体时间窗口，保存为 `UNBOUNDED` 或按补录日期标记 `BACKFILL`

Frame Policy 是牛牛自身的研究/决策规则，不冒充交易所官方规则。
修改窗口内容时必须同时更换 policy version；同版本静默改口径会被拒绝。

## 五、隔离端到端验收

证据：`artifacts/decision-frame-p5-20260913/acceptance-latest.json`

验收创建 PREP、R1、R3、LATE、BACKFILL 与 D1 记录：

- PREP / R1 / R3 = `ON_TIME`
- 明确迟交 R3 = `LATE`
- 次日补录 R1 = `BACKFILL`
- AUCTION / R2 缺失保持 `missing`
- R1 动作变化从 WATCH → READY 被正确保留
- D1 正确关联原始 R3 Decision
- 新增研究任务：0
## 六、测试结果

最终全仓：**710 passed / 0 failed / 0 skipped**，exit code = 0。

P5 与桌面/Stock Dossier/Theme Matrix 联合回归均通过。

## 七、边界

- 本阶段不认证某个 D1 一定是交易所意义上的“下一个交易日”；精确 D1/D2 距离仍需交易日历绑定后才能认证。
- Frame Policy 不等于交易所交易规则，也不改变 Strict PIT / official-rule 资格。
- Decision 是策略判断记录，不等于 Paper 或真实账户成交。
- 本阶段不授予模型写 Decision 的新权限。

下一阶段：**P6 策略动作状态机**，把 DISCOVERED → WATCH → READY → PLAN_OPEN → OPEN → ADD → HOLD → REDUCE → EXIT 与失效/拒绝/过期正式做成状态转移合同。
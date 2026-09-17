# 牛牛 AI 交易工作台 P4 · 主线市场 Theme Matrix 验收说明

> 历史归档（整理于 2026-09-17）：保留原阶段记录；正文中的“当前、下一步、待完成”和测试/数据数字属于原记录时点。使用与当前进度以 [文档导航](../../README.md)、[当前状态](../../project/status.md) 为准。命令仍从仓库根目录执行。

日期：2026-09-12

本阶段对应《牛牛AI交易助手_A股交易工作台改造总计划.md》的 P4：A 股主线市场 / Theme Matrix。

目标不是做一个“AI 自己打分的题材榜”，而是建立可审计的：

> **主题 × 交易日 × Decision Frame**

并严格分开：市场事实、Machine Rule、量化证据、AI Thesis、Risk Review。

## 一、核心数据合同

新增 append-only `Theme Snapshot`：

- `theme / trading_day / frame`
- `machine_state / ai_state`
- `facts / facts_source / facts_as_of`
- `machine_rule / machine_rule_version`
- `quant_evidence_ids / decision_ids`
- `ai_thesis / risk_review`
- `revision_of / submitted_at / frozen_at`

主题状态第一版：

`UNKNOWN / PREHEAT / START / MAIN_RISE / DIVERGENCE / REPAIR / ACCELERATION / OVERHEAT / DECLINE`

关键边界：

- 没有正式 Theme Snapshot 的格子保持 `UNKNOWN`。
- 不从 Decision 主题标签推导主线强弱。
- market facts 只允许白名单字段；不存在“score=85 即 85% 概率”。
- 只要填写 market facts，就必须同时保存 `facts_source` 和带时区 `facts_as_of`。
- 旧 Snapshot 不覆盖，只能创建同主题、同交易日、同 Frame 的 revision。
- 内容和索引均有 checksum，篡改会被检测。

## 二、桌面工作台

“主线市场”一级入口现在直接使用 Theme Matrix，而不是普通列表。

矩阵按主题为行、`交易日 + Frame` 为列；每格显示 Machine 状态、AI 状态及事实字段数量。双击有正式 Snapshot 的格子可查看完整证据、关联 Decision 与量化实验，并可基于当前版本建立 revision。

Decision 中只有主题标签而没有正式 Theme Snapshot 时，仅用于显示坐标轴，格子仍显示未知。

## 三、AI / MCP 权限边界

模型新增只读工具：

- `list_theme_snapshots`
- `get_theme_snapshot`

模型没有 `create/revise/write/save theme` 工具。Theme Snapshot 的写入仍然是宿主动作；模型只读取正式归档，不能把聊天结论直接写成主线事实。

`get_capabilities` 明确返回 `theme_matrix_available=true` 与 `theme_snapshot_write_model=false`。

## 四、端到端验收

隔离工作区完成：

`Decision → Theme Snapshot → revision → Matrix → 模型只读查询`

结果：

- revision 后当前 Machine 状态正确替换为 `MAIN_RISE`；旧 Snapshot 保留且 `superseded_by` 指向新版本。
- 没有 Snapshot 的“农业 / R2”格子保持 UNKNOWN。
- 模型 list/get 成功；模型写入尝试被拒绝。
- 研究任务数 `0 → 0`，新增任务 0。

本次 market facts 为显式 fixture，**不是实时 A 股行情**。P4 验收的是存储、界面、revision 与权限边界；实时主线事实接入属于后续数据集成。

## 五、测试结果

专项：Theme core/UI/Agent/MCP 均通过。

最终全仓：

- `700 passed`
- `0 failed`
- `0 skipped`
- `exit=0`
- 用时约 299 秒

最终代码指纹和 Git SHA 以本阶段交付回执为准。

证据：

- `artifacts/theme-matrix-p4-20260912/e2e-acceptance.json`
- `artifacts/theme-matrix-p4-final.log`
- `artifacts/theme-matrix-p4-final.exit`

## 六、仍未完成

P4 并不等于已经获得完整实时主线行情、题材成员历史或自动主线识别。当前正式合同已经具备，但 live facts 的来源、历史 PIT 与自动生成规则仍需后续接入。

下一阶段按总计划进入 P5：Decision Frame 的时间合同与跨轮比较。

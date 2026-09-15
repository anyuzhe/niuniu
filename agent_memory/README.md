# 牛牛 Agent Operating Memory

这是牛牛智能体的 Git-first 长期工作记忆入口。每个 Agent 开工前必须先读取本文件，再读取 `rules/`、对应 `roles/` 与相关 `architecture/` Markdown。

## 权威边界

- 本目录保存：角色规则、权限边界、工作流程、工程经验、事故复盘与架构决策。
- 实验数值、PIT 资格、Decision、Theme Snapshot、Watch、成交与统计检验仍以结构化归档为权威源。
- Markdown 可以引用研究 ID，但不能用文字覆盖原始数值证据。
- 不使用向量库作为权威记忆；未来索引只能是可删除、可重建的检索缓存。
- 当前交易知识架构必须同时读取 `architecture/trading_knowledge.md`；任何任务不得把单一交易者当系统一级模块。
- Agent 评价/模型比较任务必须读取 `architecture/agent_scorecard.md`；Scorecard 不产生模型总分，也不得自动调权。
- Dev Studio / 开发 Agent 任务必须读取 `architecture/dev_studio.md`；所有写入只能发生在隔离 worktree + path lease 内，Human Merge 不自动 push。
- System Health / 系统可观察性任务必须读取 `architecture/system_health.md`；运行在线与研究正确必须分轴表达，不允许自动修复或伪造健康总分。
- Mobile / Bot 任务必须读取 `architecture/mobile.md`；手机/机器人只复用现有状态源，禁止建立第二份 Decision、持仓、记忆或移动端数据库。

## 固定读取顺序

1. `README.md`
2. `rules/*.md`
3. `architecture/*.md`
4. 当前角色 `roles/<role_id>.md`
5. 任务明确相关的 `experience/` 或 `incidents/`

任何记忆修改都必须保留 Git diff；Research Agent 默认只读。
## 长期开发史

牛牛的产品开发过程、功能变更、阶段时间、测试基线和关键 Git 提交统一记录在仓库根目录：`牛牛AI交易助手_开发历程与功能变更总档案.md`。

所有 Agent 必须遵守 `rules/development_history.md`；完成有意义的功能/架构/权限/研究语义/部署变更后，应在任务收尾前同步追加开发史。

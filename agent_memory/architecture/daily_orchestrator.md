# Daily Playbook Orchestrator

P8.7 v1 只负责编排，不定义新交易规则，也不充当实时行情供应商。

固定复用链路：`DailyMarket → PrepScanner → MarketSnapshot → DailyPlaybookScanner → Forward Freeze`。任何子模块 fail-closed 时，Orchestrator 不得绕过它。

## 关键边界

- 默认不联网；只有宿主计划显式授权 DailyMarket capture。
- DailyMarket revision_review 必须宿主确认，Orchestrator 不自动接受修订。
- PREP / AUCTION / R1 错过实时窗口后只记录 MISSED，不补写 SYSTEM_PREDICTION。
- AUCTION 只消费 09:25–09:30 LIVE_NEAR_REALTIME 快照；R1 v1 只消费 09:35–09:40 首窗口快照。
- BACKFILL MarketSnapshot 永远不能被 Orchestrator 当实时预测输入。
- CandidateSet/PIT 不完整时允许正常冻结 NO_TRADE；自动化不是降低证据门槛的理由。
- AI/Reviewer/MCP 无 init/tick/run 权限；宿主负责计划和运行授权。
- v1 只支持 PREP/AUCTION/R1。R2/R3 在对应确定性 Scanner/Forward 合同实现前不得宣称自动编排完成。
- 当前正式实时 MarketSnapshot provider 尚未产品化；不得用临时网页抓取偷偷替代。

状态必须 checksum、原子持久化并可重启恢复；同一计划重复 tick 不得重复 Case、CandidateSet、Prediction 或 MarketSnapshot。

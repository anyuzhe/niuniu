# Daily Playbook Orchestrator

P8.7 当前版只负责编排，不定义新交易规则；实时行情由独立 MarketSnapshot Provider 提供。

固定复用链路：`DailyMarket → PrepScanner → MarketSnapshot → DailyPlaybookScanner → Forward Freeze`。任何子模块 fail-closed 时，Orchestrator 不得绕过它。

## 关键边界

- 默认不联网；DailyMarket 与实时 MarketSnapshot 分别需要宿主计划显式授权。实时三源抓取开关为 `allow_market_snapshot_capture=true`。
- DailyMarket revision_review 必须宿主确认，Orchestrator 不自动接受修订。
- PREP / AUCTION / R1 / R2 / R3 错过实时窗口后只记录 MISSED，不补写 SYSTEM_PREDICTION。
- AUCTION 只消费 09:25–09:30 LIVE_NEAR_REALTIME；R1 只消费 09:35–09:40 首窗口快照。
- R2 以 11:30 午间收盘为数据就绪点，11:30–11:40 冻结；R3 以 15:00 收盘为数据就绪点，15:00–15:10 冻结。
- R2/R3 只做 continuation review：必须引用前一阶段真实冻结的 SYSTEM_PREDICTION，只能延续其中 selected 的股票，禁止在盘中后段自动新增标的。
- BACKFILL MarketSnapshot 永远不能被 Orchestrator 当实时预测输入。
- CandidateSet/PIT 不完整时允许正常冻结 NO_TRADE；自动化不是降低证据门槛的理由。
- AI/Reviewer/MCP 无 init/tick/run 权限；宿主负责计划和运行授权。
- 当前 live Provider 为 `public-web-consensus-v1`（腾讯主源、东财第二源、新浪备用校验）；只消费 FULL + LIVE_NEAR_REALTIME，共识不足或网页端点异常时等待/错过，不降级成单源猜值。

状态必须 checksum、原子持久化并可重启恢复；同一计划重复 tick 不得重复 Case、CandidateSet、Prediction 或 MarketSnapshot。

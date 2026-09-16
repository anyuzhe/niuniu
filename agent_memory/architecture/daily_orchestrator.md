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
- 计划可固定目标交易日 `universe_snapshot`；PREP 必须深验该 `niuniu-pit-universe-v1` receipt 的 `effective_session == trading_day` 并扫描全部 members。缺 snapshot 时保持 PARTIAL；旧 `universe_pit_verified` 布尔值无认证权。
- PREP的ST/停复牌状态只消费exact effective-session证据；SecurityStatus v2行必须来自全Universe逐日receipt，稀疏statement和v2 snapshot都不得跨日传播。Orchestrator绑定Universe不自动证明状态或MarketRules完整。
- PREP 已冻结且 CandidateSet 为空时，不存在可供后续 Frame 抓取的证券：可先落 Trading Desk NO_TRADE receipt，再进入终态 `COMPLETE_NO_TRADE`，AUCTION/R1/R2/R3 标记 `SKIPPED_NO_TRADE / EMPTY_PREP_CANDIDATE_SET`。
- 必须区分“空 CandidateSet”和“非空 CandidateSet 但 PREP `selected_symbols=[]`”：后者只是盘前不提前选具体股票，仍应等待 AUCTION，不能提前终止。
- AI/Reviewer/MCP 无 init/tick/run 权限；宿主负责计划和运行授权。
- 当前 live Provider 为 `public-web-consensus-v1`（腾讯主源、东财第二源、新浪备用校验）；只消费 FULL + LIVE_NEAR_REALTIME，共识不足或网页端点异常时等待/错过，不降级成单源猜值。
- 当前没有后台定时任务。任何目标日08:00刷新或09:15前PIT归档都必须由宿主当日显式启动；runbook不是scheduler，也不授予联网、确认或archive权限。错过cutoff后Orchestrator不得推动历史补档。

状态必须 checksum、原子持久化并可重启恢复；同一计划重复 tick 不得重复 Case、CandidateSet、Prediction 或 MarketSnapshot。

2026-09-15 首次以 5,219 行 accepted DailyMarket 为 2026-09-16 冻结真实时钟 PREP：Router 输出 `EXTREME_RISK / NO_TRADE`，CandidateSet 为 `PARTIAL / RETROSPECTIVE_REFERENCE` 且为空，计划最终为 `COMPLETE_NO_TRADE`。该样本没有生成股票 Decision、PaperPlan 或成交，不能称为 Strict PIT 或策略有效性证明。

# Strict PIT Evidence Archive

Strict PIT 不是“记录里写了官方 URL”就成立。任何历史资格、证券状态、行业或市值控制要升级为严格 PIT，必须同时保留可审计的 publication evidence。

## v1 证据合同

- 支持 `universe_eligibility / security_status / industry_membership / daily_market_cap` 四类 statement。
- 每条 statement 必须有明确 `effective_at` 与 `available_at`；security-status / industry / market-cap 还必须引用权威 HTTPS source。
- Receipt 必须绑定：规范化 statement digest、权威 source URL、宿主明确确认的 `published_at`、本地官方原文字节、SHA256 与 `fetched_at`。
- `published_at` 不得晚于 statement 的 `available_at`；禁止通过事后抓取时间反推历史可用时间。
- 官方原文或 receipt checksum 任一被修改，验证必须 fail-closed。
- 同一 statement + source + publication_at + document SHA 重复归档必须幂等，`fetched_at` 不参与 evidence identity。

## Complete daily SecurityStatus v2

- 稀疏 `security_status` statement 只证明一条事实。完整逐日状态必须另有 `niuniu-security-status-coverage-v2`，精确绑定同 session PIT Universe 并覆盖全部 members 的 `TRADABILITY + RISK_WARNING`。
- 时间链、官方原文字节、source/exchange、三项宿主确认和09:15 cutoff均 fail-closed；`UNKNOWN`不通过 Strict。
- 进入/持续/撤销只从显式 `previous_status_snapshot` 且宿主确认相邻交易session的两份完整snapshot推导；root、断链、Universe进出、同日歧义或分叉不得冒充状态变化。
- 真实数据根当前v2 receipt=0；14条稀疏statement不得升级或跨日传播。

## Official MarketRules publication receipt v2

Official MarketRules 不计入上面四类 PIT statement 数量，但其最高资格门同样必须阻断未来信息：

- 新回执按 `research/official_market_rules/<rules_snapshot>.json` append-only 保存实际规则 records、官方原文字节 SHA256、`published_at`、`fetched_at` 与宿主 publication-time confirmation。
- 每个 record 的 `available_at` 不得早于其 source `published_at`；旧 v1 单文件没有 publication time，只可读，不再通过新的 `official_rule_covered` gate。
- 同一 snapshot 重试幂等且不重新联网；不同 snapshot 可在同一数据根并存，禁止覆盖旧回执。
- `official-rule-audit` 只读深度核对所有 v2 receipt、records、source、content-addressed path 与官方原文字节；System Health 展示的是全局 archive inventory，不是 CandidateSet 已绑定该 snapshot 的证明。
- v2 证明来源字节、发布时间、record 身份和请求覆盖，不自动证明人工语义映射或券商费用假设正确。
- 停牌 session 可显式保存无价格边界，但 RulesAudit 必须将其统计为 suspended，不得写成可无限价格交易。

## Official MarketRules derivation reference

- `research/official_market_rule_references/<reference_snapshot>.json` 只保存回顾性推导参考，不属于 PIT Evidence 或 Official MarketRules receipt。
- 本地导入必须显式确认 `--confirm-retrospective-only`，不联网；receipt 绑定已验证公告 evidence、交易规则 PDF/通知元数据、深交所 ShowReport JSON 与 HTTP headers，并重算 Decimal exact 上下限。
- 历史行情响应若在目标 session 后才被观察，必须固定 `historical_reference_publication_verified_before_open=false / market_rules_eligible=false`，blocker 为 `historical_reference_price_publication_receipt_missing`。
- `official-rule-reference-audit` 只核完整性与算术；任何 reference record 永不进入 Qualification、PREP 或 execution，不得借“官方历史值正确”冒充历史开盘前 byte vintage。

## Qualification / Freeze 边界

- 零散 PIT Universe eligibility statement 即使逐条有 publication receipt，也只能证明对应 statement；完整市场人口必须另有 `niuniu-pit-universe-v1` exact-session receipt。每个请求 session 要求唯一完整 snapshot，否则只能是 `timing_contract_only/incomplete`。
- SecurityStatus / Industry / daily market cap 的 Strict PIT 都不能只检查 URL 域名；缺 receipt 时不得升级。SecurityStatus 同时受 `security_status.md` 的稀疏statement与完整逐日v2边界约束。
- `research_only / retrospective_reference` 不因 v1 证据门变严而失效；它们继续按原口径使用回顾性资料。
- Approval-time Actual-byte Freeze 会冻结已验证的 universe metadata 与资格回执，执行/恢复不得重新解释成更高或更低等级。
- `niuniu-pit-evidence` 是宿主工具；archive 必须显式 `--confirm-publication-time`，CLI 不自动下载官方网页。
- System Health 的 PIT/Playbook 组件显示 receipt 数量；receipt 损坏显示 WARN，不能静默当作空库。

当前独立数据根 `/Volumes/Lexar/niuniu-data` 已有 14 条 `security_status` verified sparse receipt（7只深市股票的明确停牌/复牌及 ST 生效事件）；其它三类 statement、PIT Universe v1 与 SecurityStatus v2 完整逐日 snapshot 均为0。另有1个 MarketRules v2 snapshot，覆盖同7只股票各1个明确停牌 session，共7条规则。7个复牌 session 已有1个深验通过的回顾性 reference snapshot，但 Strict PIT eligible records=0、MarketRules appended=0。禁止把这些稀疏事件或参考值写成完整历史覆盖。

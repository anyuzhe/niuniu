# 代码地图

[文档导航](../README.md) · [总体架构](../architecture/overview.md) · [开发规范](contributing.md)

清点基线：2026-09-17，`5a381e8`。全部 711 个受 Git 管理的 Python 文件已解析 AST，0 个解析错误；源码共 57,250 行。完整文件、类、函数、行数与指纹见 [代码清单](../_meta/code-inventory.json)。这是一份结构索引，不是对每行业务逻辑的正确性证明。

## 建议阅读顺序

[app.py](../../src/quantlab/app.py) 的注册/组装 → [桌面导航](../../src/quantlab/desktop/trading_pages.py) → [ChatRuntime](../../src/quantlab/agent/chat_runtime.py) → [数据路由](../../src/quantlab/data/provider.py) → trading/experiments → execution → storage。涉及权限时先阅读 agent_memory 对应合同。

## 全部源码包

| 包或模块 | Python 文件数 | 行数 |
|---|---:|---:|
| [__init__.py](../../src/quantlab/__init__.py) | 1 | 3 |
| [_vendor](../../src/quantlab/_vendor) | 48 | 4014 |
| [adapters](../../src/quantlab/adapters) | 8 | 650 |
| [agent](../../src/quantlab/agent) | 109 | 11313 |
| [app.py](../../src/quantlab/app.py) | 1 | 74 |
| [broker](../../src/quantlab/broker) | 5 | 416 |
| [causal.py](../../src/quantlab/causal.py) | 1 | 29 |
| [cli.py](../../src/quantlab/cli.py) | 1 | 628 |
| [contracts.py](../../src/quantlab/contracts.py) | 1 | 65 |
| [data](../../src/quantlab/data) | 36 | 6537 |
| [desktop](../../src/quantlab/desktop) | 62 | 7274 |
| [devstudio](../../src/quantlab/devstudio) | 7 | 1050 |
| [domain.py](../../src/quantlab/domain.py) | 1 | 159 |
| [events](../../src/quantlab/events) | 3 | 75 |
| [execution](../../src/quantlab/execution) | 16 | 2251 |
| [experiments](../../src/quantlab/experiments) | 24 | 2603 |
| [factors](../../src/quantlab/factors) | 32 | 2727 |
| [knowledge](../../src/quantlab/knowledge) | 4 | 1640 |
| [multitimeframe](../../src/quantlab/multitimeframe) | 5 | 191 |
| [processing](../../src/quantlab/processing) | 4 | 254 |
| [progress.py](../../src/quantlab/progress.py) | 1 | 18 |
| [regime](../../src/quantlab/regime) | 4 | 167 |
| [sequence](../../src/quantlab/sequence) | 6 | 405 |
| [statistics](../../src/quantlab/statistics) | 8 | 594 |
| [storage](../../src/quantlab/storage) | 12 | 2043 |
| [structure](../../src/quantlab/structure) | 3 | 83 |
| [theory](../../src/quantlab/theory) | 2 | 123 |
| [trading](../../src/quantlab/trading) | 45 | 10915 |
| [workbench](../../src/quantlab/workbench) | 5 | 855 |
| [zones](../../src/quantlab/zones) | 2 | 94 |

## CLI 入口

下表直接提取自 [pyproject.toml](../../pyproject.toml)。参数使用各命令 --help 查询；列出入口不代表相应服务已经启动或取得授权。

| 命令 | Python 入口 |
|---|---|
| `quantlab` | [quantlab.cli:main](../../src/quantlab/cli.py) |
| `niuniu-mcp` | [quantlab.agent.mcp_server:main](../../src/quantlab/agent/mcp_server.py) |
| `niuniu-tracking-daemon` | [quantlab.agent.tracking_daemon:main](../../src/quantlab/agent/tracking_daemon.py) |
| `niuniu-playbook-forward` | [quantlab.agent.playbook_forward_cli:main](../../src/quantlab/agent/playbook_forward_cli.py) |
| `niuniu-market-snapshot` | [quantlab.agent.market_snapshot_cli:main](../../src/quantlab/agent/market_snapshot_cli.py) |
| `niuniu-market-provider-status` | [quantlab.agent.market_snapshot_provider_cli:main](../../src/quantlab/agent/market_snapshot_provider_cli.py) |
| `niuniu-market-snapshot-live` | [quantlab.agent.market_snapshot_live_cli:main](../../src/quantlab/agent/market_snapshot_live_cli.py) |
| `niuniu-pit-evidence` | [quantlab.agent.pit_evidence_cli:main](../../src/quantlab/agent/pit_evidence_cli.py) |
| `niuniu-pit-universe` | [quantlab.agent.pit_universe_cli:main](../../src/quantlab/agent/pit_universe_cli.py) |
| `niuniu-pit-coverage` | [quantlab.agent.pit_coverage_cli:main](../../src/quantlab/agent/pit_coverage_cli.py) |
| `niuniu-security-status` | [quantlab.agent.security_status_cli:main](../../src/quantlab/agent/security_status_cli.py) |
| `niuniu-security-status-coverage` | [quantlab.agent.security_status_coverage_cli:main](../../src/quantlab/agent/security_status_coverage_cli.py) |
| `niuniu-daily-playbook-scan` | [quantlab.agent.playbook_scan_cli:main](../../src/quantlab/agent/playbook_scan_cli.py) |
| `niuniu-prep-playbook-scan` | [quantlab.agent.prep_scan_cli:main](../../src/quantlab/agent/prep_scan_cli.py) |
| `niuniu-daily-market` | [quantlab.agent.daily_market_cli:main](../../src/quantlab/agent/daily_market_cli.py) |
| `niuniu-retro-daily` | [quantlab.agent.retro_daily_cli:main](../../src/quantlab/agent/retro_daily_cli.py) |
| `niuniu-limit-events` | [quantlab.agent.limit_events_cli:main](../../src/quantlab/agent/limit_events_cli.py) |
| `niuniu-market-sentiment` | [quantlab.agent.market_sentiment_cli:main](../../src/quantlab/agent/market_sentiment_cli.py) |
| `niuniu-sentiment-cycle` | [quantlab.agent.sentiment_cycle_cli:main](../../src/quantlab/agent/sentiment_cycle_cli.py) |
| `niuniu-public-evidence` | [quantlab.agent.public_evidence_cli:main](../../src/quantlab/agent/public_evidence_cli.py) |
| `niuniu-evidence-scheduler` | [quantlab.agent.evidence_scheduler_cli:main](../../src/quantlab/agent/evidence_scheduler_cli.py) |
| `niuniu-event-study` | [quantlab.agent.event_study_cli:main](../../src/quantlab/agent/event_study_cli.py) |
| `niuniu-theme-facts` | [quantlab.agent.theme_facts_cli:main](../../src/quantlab/agent/theme_facts_cli.py) |
| `niuniu-event-details` | [quantlab.agent.event_details_cli:main](../../src/quantlab/agent/event_details_cli.py) |
| `niuniu-daily-review` | [quantlab.agent.daily_review_cli:main](../../src/quantlab/agent/daily_review_cli.py) |
| `niuniu-limit-forecast` | [quantlab.agent.limit_forecast_cli:main](../../src/quantlab/agent/limit_forecast_cli.py) |
| `niuniu-auto-research` | [quantlab.agent.auto_research_cli:main](../../src/quantlab/agent/auto_research_cli.py) |
| `niuniu-premarket-brief` | [quantlab.agent.premarket_brief_cli:main](../../src/quantlab/agent/premarket_brief_cli.py) |
| `niuniu-daily-orchestrator` | [quantlab.agent.daily_orchestrator_cli:main](../../src/quantlab/agent/daily_orchestrator_cli.py) |
| `niuniu-playbook-decision-bridge` | [quantlab.agent.playbook_decision_bridge_cli:main](../../src/quantlab/agent/playbook_decision_bridge_cli.py) |
| `niuniu-playbook-paper-plan` | [quantlab.agent.playbook_paper_plan_cli:main](../../src/quantlab/agent/playbook_paper_plan_cli.py) |
| `niuniu-paper-fill-intent` | [quantlab.agent.paper_fill_intent_cli:main](../../src/quantlab/agent/paper_fill_intent_cli.py) |
| `niuniu-paper-review` | [quantlab.agent.paper_review_cli:main](../../src/quantlab/agent/paper_review_cli.py) |
| `niuniu-paper-lifecycle` | [quantlab.agent.paper_lifecycle_cli:main](../../src/quantlab/agent/paper_lifecycle_cli.py) |
| `niuniu-agent-scorecard` | [quantlab.agent.scorecard_cli:main](../../src/quantlab/agent/scorecard_cli.py) |
| `niuniu-dev-studio` | [quantlab.agent.dev_studio_cli:main](../../src/quantlab/agent/dev_studio_cli.py) |
| `niuniu-system-health` | [quantlab.agent.system_health_cli:main](../../src/quantlab/agent/system_health_cli.py) |
| `niuniu-mobile-brief` | [quantlab.agent.mobile_brief_cli:main](../../src/quantlab/agent/mobile_brief_cli.py) |
| `niuniu-broker-shadow` | [quantlab.agent.broker_shadow_cli:main](../../src/quantlab/agent/broker_shadow_cli.py) |
| `niuniu-real-trade-readiness` | [quantlab.agent.real_trade_readiness_cli:main](../../src/quantlab/agent/real_trade_readiness_cli.py) |
| `niuniu-research-session-grant` | [quantlab.agent.research_session_grant_cli:main](../../src/quantlab/agent/research_session_grant_cli.py) |
| `niuniu-paper-rebalance` | [quantlab.agent.paper_rebalance_cli:main](../../src/quantlab/agent/paper_rebalance_cli.py) |
| `niuniu-paper-rebalance-outcome` | [quantlab.agent.paper_rebalance_outcome_cli:main](../../src/quantlab/agent/paper_rebalance_outcome_cli.py) |

## 测试与示例

[tests](../../tests) 的 222 个测试模块及 [examples](../../examples) 的全部 Python 文件也包含在 JSON 清单中。历史 verify 脚本可能依赖实际数据、特定实验 ID 或可选组件，不能仅凭名称默认无条件运行。实际测试结果与限制见 [整理验收](documentation-cleanup.md)。

## 维护

新增或移动模块后更新相应导航与清单；清单明确保留生成基线，不作为自动生成的实时指标。类与函数完整名称在 JSON 中检索，具体行为以源码及测试为准。

## 2026-09-17 增量入口：冻结候选验证

[统计与分层模块](../../src/quantlab/experiments/frozen_candidate_validation.py)、[capture/run/verify 后台脚本](../../scripts/validate_frozen_candidates.py)、[边界回归](../../tests/test_frozen_candidate_validation.py)。复用原因子计算、标签、Bootstrap、符号检验与Holm；新增的是已冻结候选的样本扩展、分期/分板块统计和留证，不是新模型或实盘执行器。原JSON清单仍明确属于其生成基线。

原生本地行情发现/检查工具：[local_data_tools.py](../../src/quantlab/agent/local_data_tools.py)，共同接线：[proposal_tools.py](../../src/quantlab/agent/proposal_tools.py)。工具不允许任意文件路径，不替代管理数据合同或统计研究。

## 原始规格监督入口（2026-09-17）

[research_specs.py](../../src/quantlab/agent/research_specs.py) 固定原始文件与60项定义定位；[research_spec_tools.py](../../src/quantlab/agent/research_spec_tools.py) 提供原生模型工具和禁止替代边界；[spec_test_service.py](../../src/quantlab/agent/spec_test_service.py) 保存实际测试请求/结果。[qm50_contract.py](../../src/quantlab/trading/qm50_contract.py) 仅是合成测试使用的纯组件，[spec_p07_diagnostic.py](../../src/quantlab/agent/spec_p07_diagnostic.py) 仅诊断原始成交额字段；二者不能作为完整策略调用。对应 [test_research_spec_fidelity.py](../../tests/test_research_spec_fidelity.py)。

### QM50基础依赖（2026-09-18）

[qm50_base_coverage.py](../../src/quantlab/agent/qm50_base_coverage.py) 复用既有正式回执验证器，分离全局完整性与请求覆盖，按真实日历建立D/D-1/D-2矩阵；[qm50_base_contract.py](../../src/quantlab/trading/qm50_base_contract.py) 是不签发资格、不接入真实候选生产的纯组件。原生规格工具接线和持久结果仍在research_spec_tools/spec_test_service中，对应 [test_qm50_base_coverage.py](../../tests/test_qm50_base_coverage.py)。

get_strict_pit_coverage曾仅加入白名单而未实际注册到ChatRuntime，真实牛牛调用发现后改为显式工具。回归必须构造真实headless_chat_runtime，不能只用伪造inner证明接线完成。

已归档原始输入接入：[qm50_archived_inputs.py](../../src/quantlab/agent/qm50_archived_inputs.py)，负责宿主选定来源的capture读取、原JSON/typed核对、D-1输入物化和冻结复算；对应 [test_qm50_archived_inputs.py](../../tests/test_qm50_archived_inputs.py)。不包含价格制度推算、候选选择或收益研究。

TDX个人研究原始页/Parquet/原DuckDB接入：[tdx_lake.py](../../src/quantlab/data/tdx_lake.py)；显式采集/暂停/恢复：[tdx_collection_cli.py](../../src/quantlab/agent/tdx_collection_cli.py)；只读模型接线复用ResearchSpecAPI。验证：[test_tdx_lake.py](../../tests/test_tdx_lake.py)。采集依赖隔离且不加载到普通只读工具，不与QM50规则或交易授权混用。

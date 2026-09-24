# 代码地图

[文档导航](../README.md) · [总体架构](../architecture/overview.md) · [开发规范](contributing.md)

包行数表更新于 2026-09-24（`4195ad2` 之后的代码侧修复）：受 Git 管理的 Python 文件 851 个，`src/quantlab` 共 505 个文件、73,251 行，测试模块 293 个。[代码清单](../_meta/code-inventory.json) 仍是 2026-09-17 `5a381e8` 的逐文件/类/函数快照（当时 711 个文件、源码 57,250 行），未随本次重新生成。这是一份结构索引，不是对每行业务逻辑的正确性证明。

## 建议阅读顺序

[app.py](../../src/quantlab/app.py) 的注册/组装 → [桌面导航](../../src/quantlab/desktop/trading_pages.py) → [ChatRuntime](../../src/quantlab/agent/chat_runtime.py) → [数据路由](../../src/quantlab/data/provider.py) → trading/experiments → execution → storage。涉及权限时先阅读 agent_memory 对应合同。

## 全部源码包

| 包或模块 | Python 文件数 | 行数 |
|---|---:|---:|
| [__init__.py](../../src/quantlab/__init__.py) | 1 | 3 |
| [_vendor](../../src/quantlab/_vendor) | 48 | 4014 |
| [adapters](../../src/quantlab/adapters) | 8 | 652 |
| [agent](../../src/quantlab/agent) | 131 | 16573 |
| [app.py](../../src/quantlab/app.py) | 1 | 74 |
| [broker](../../src/quantlab/broker) | 5 | 416 |
| [causal.py](../../src/quantlab/causal.py) | 1 | 29 |
| [cli.py](../../src/quantlab/cli.py) | 1 | 631 |
| [contracts.py](../../src/quantlab/contracts.py) | 1 | 65 |
| [data](../../src/quantlab/data) | 51 | 12818 |
| [desktop](../../src/quantlab/desktop) | 66 | 9137 |
| [devstudio](../../src/quantlab/devstudio) | 7 | 1050 |
| [domain.py](../../src/quantlab/domain.py) | 1 | 159 |
| [events](../../src/quantlab/events) | 3 | 75 |
| [execution](../../src/quantlab/execution) | 16 | 2314 |
| [experiments](../../src/quantlab/experiments) | 25 | 2863 |
| [factors](../../src/quantlab/factors) | 32 | 2727 |
| [knowledge](../../src/quantlab/knowledge) | 4 | 1642 |
| [multitimeframe](../../src/quantlab/multitimeframe) | 5 | 191 |
| [processing](../../src/quantlab/processing) | 4 | 254 |
| [progress.py](../../src/quantlab/progress.py) | 1 | 18 |
| [regime](../../src/quantlab/regime) | 4 | 167 |
| [sequence](../../src/quantlab/sequence) | 6 | 405 |
| [statistics](../../src/quantlab/statistics) | 8 | 594 |
| [storage](../../src/quantlab/storage) | 12 | 2079 |
| [structure](../../src/quantlab/structure) | 3 | 83 |
| [theory](../../src/quantlab/theory) | 2 | 123 |
| [trading](../../src/quantlab/trading) | 51 | 13127 |
| [workbench](../../src/quantlab/workbench) | 5 | 874 |
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
| `niuniu-selection-outcomes` | [quantlab.agent.selection_outcomes_cli:main](../../src/quantlab/agent/selection_outcomes_cli.py) |
| `niuniu-strategy-package` | [quantlab.agent.strategy_package_cli:main](../../src/quantlab/agent/strategy_package_cli.py) |
| `niuniu-market-overview` | [quantlab.agent.market_overview_cli:main](../../src/quantlab/agent/market_overview_cli.py) |
| `niuniu-paper-lifecycle` | [quantlab.agent.paper_lifecycle_cli:main](../../src/quantlab/agent/paper_lifecycle_cli.py) |
| `niuniu-agent-scorecard` | [quantlab.agent.scorecard_cli:main](../../src/quantlab/agent/scorecard_cli.py) |
| `niuniu-dev-studio` | [quantlab.agent.dev_studio_cli:main](../../src/quantlab/agent/dev_studio_cli.py) |
| `niuniu-system-health` | [quantlab.agent.system_health_cli:main](../../src/quantlab/agent/system_health_cli.py) |
| `niuniu-mobile-brief` | [quantlab.agent.mobile_brief_cli:main](../../src/quantlab/agent/mobile_brief_cli.py) |
| `niuniu-broker-shadow` | [quantlab.agent.broker_shadow_cli:main](../../src/quantlab/agent/broker_shadow_cli.py) |
| `niuniu-real-trade-readiness` | [quantlab.agent.real_trade_readiness_cli:main](../../src/quantlab/agent/real_trade_readiness_cli.py) |
| `niuniu-research-session-grant` | [quantlab.agent.research_session_grant_cli:main](../../src/quantlab/agent/research_session_grant_cli.py) |
| `niuniu-research-data` | [quantlab.agent.research_data_cli:main](../../src/quantlab/agent/research_data_cli.py) |
| `niuniu-paper-rebalance` | [quantlab.agent.paper_rebalance_cli:main](../../src/quantlab/agent/paper_rebalance_cli.py) |
| `niuniu-paper-rebalance-outcome` | [quantlab.agent.paper_rebalance_outcome_cli:main](../../src/quantlab/agent/paper_rebalance_outcome_cli.py) |

## 测试与示例

[tests](../../tests) 的 293 个测试模块（2026-09-24）及 [examples](../../examples) 的全部 Python 文件也包含在 JSON 清单中。历史 verify 脚本可能依赖实际数据、特定实验 ID 或可选组件，不能仅凭名称默认无条件运行。实际测试结果与限制见 [整理验收](documentation-cleanup.md)。

## 六职责开发工作台（2026-09-25）

[team.py](../../src/quantlab/devstudio/team.py) 是 LEAD/DATA/CORE/AI/APP/QA 的归属和模型合同；[planning.py](../../src/quantlab/devstudio/planning.py) 实现需求只读规划、基线绑定和计划确认；原 `devstudio/contracts/store/service/runtime/tools/workspace` 复用 P10 增加专业域校验、受控并行、失败返工、独立 QA 和最终合并复核。桌面入口在 [dev_studio.py](../../src/quantlab/desktop/dev_studio.py)，需求与六角色配置在 [dev_team.py](../../src/quantlab/desktop/dev_team.py)；同源 [CLI](../../src/quantlab/agent/dev_studio_cli.py) 保持无自动 push。新增 [后端闭环测试](../../tests/test_dev_team.py) 与 [离屏入口测试](../../tests/test_dev_team_desktop.py)，使用临时 Git 仓库、真实测试执行和脚本化模型，不能当作付费模型验收。文件归属与现有限制见 [ownership.md](ownership.md)。上方目录数量表仍保留其标明的旧基线，不作为实时统计。

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

TDX个人研究原始页/Parquet/原DuckDB接入：[tdx_lake.py](../../src/quantlab/data/tdx_lake.py)；显式采集/暂停/恢复、瞬时错误重试、主站轮换、冷却/autoresume及`collection-scope.json`持久范围保护：[tdx_collection_cli.py](../../src/quantlab/agent/tdx_collection_cli.py)。scope独立于scheduler policy，恢复后会在触网前再次跳过excluded family并写审计；只读模型接线复用ResearchSpecAPI。验证：[test_tdx_lake.py](../../tests/test_tdx_lake.py)。采集依赖隔离且不加载到普通只读工具，不与QM50规则或交易授权混用；本机LaunchAgent部署属于运行环境，不提交到仓库。

TDX固定分片合同：[tdx_sharding.py](../../src/quantlab/data/tdx_sharding.py)；最小断点包/原始页验证汇总/总状态：[tdx_distributed.py](../../src/quantlab/agent/tdx_distributed.py)及[宿主CLI](../../src/quantlab/agent/tdx_distributed_cli.py)；loopback文件数据面：[tdx_transfer.py](../../src/quantlab/agent/tdx_transfer.py)；不清除STOP/AUTO_HALT的有限采集、outbox与回执：[tdx_worker_service.py](../../src/quantlab/agent/tdx_worker_service.py)。[分布式测试](../../tests/test_tdx_distributed.py)、[真实本机HTTP传输测试](../../tests/test_tdx_transfer.py)和[平台验收入口](../../scripts/test_tdx_worker.py)明确区分独立worker与完整应用。操作见[三机采集指南](../guide/tdx-distributed.md)，代码存在不代表远端已部署。

## 版本化市场数据采集（2026-09-22/23）

入口统一在 [`scripts/collect/`](../../scripts/collect/README.md)：`scan_gaps.py` 只读生成行情缺口计划，`bars_incremental.py` 只消费绑定SHA的已批准计划；`ths_dividend.py`、`cninfo_allotment.py`、`baostock_dividend.py`、`baostock_daily_status.py` 和 `baostock_reference_snapshot.py` 分别采集独立bronze批次。`envelope.py` 提供默认仅审阅、显式apply、原子文件、逐证券回执、空结果marker和schema稽核；`migrate_empty_parquet.py` 仅迁移已由来源回执证明的零行占位文件。对应离线测试为 [`test_collect_envelope.py`](../../tests/test_collect_envelope.py) 和 [`test_collect_gaps.py`](../../tests/test_collect_gaps.py)，真实全量结果见[2026-09-22/23全量交验](../archive/data-evidence/20260923-全量数据采集与交验.md)。代码存在不等于已更新catalog或已获未来联网授权。每日只读审阅入口 [`daily_plan.py`](../../scripts/collect/daily_plan.py) 先固定参考快照计划，获单独批准且快照完成后再产生行情/状态/公司行动的独立计划；[`status_incremental.py`](../../scripts/collect/status_incremental.py) 和 [`corporate_actions_daily.py`](../../scripts/collect/corporate_actions_daily.py) 分别处理状态尾部和公司行动内容变化，公共SHA/备份辅助见 [`daily_common.py`](../../scripts/collect/daily_common.py)。新增离线回归在 [`test_collect_daily.py`](../../tests/test_collect_daily.py)。

## 产品化改造：日常工作台（2026-09-24）

桌面导航改为 [app.py](../../src/quantlab/desktop/app.py) 中的 `PAGES`（key、标题、图标、是否专业模式），`navigate_page(key)` 按 key 跳转；日常页面在 [home_pages.py](../../src/quantlab/desktop/home_pages.py) 与 [market_pages.py](../../src/quantlab/desktop/market_pages.py)，专业模式开关存于 [ui_settings.py](../../src/quantlab/desktop/ui_settings.py)。今日市场/主线方向的计算在 [market_overview.py](../../src/quantlab/trading/market_overview.py)，只经数据清单读取 READY 文件；测试见 [test_market_overview.py](../../tests/test_market_overview.py)。个股报告与我的股票见 [stock_report.py](../../src/quantlab/trading/stock_report.py)、[my_stocks.py](../../src/quantlab/trading/my_stocks.py)、[stock_pages.py](../../src/quantlab/desktop/stock_pages.py)；助手日常模式与页面只读工具见 [home_tools.py](../../src/quantlab/agent/home_tools.py)。

## 数据侧整改（2026-09-23）

[dataset_registry.py](../../src/quantlab/data/dataset_registry.py) 读取并校验 `catalog/dataset_registry.json`，提供 `resolve`/`verify`；[registry.py](../../scripts/collect/registry.py) 负责 draft/verify/apply 与 `reg_*` 视图计划，映射清单在 [registry_spec.json](../../scripts/collect/registry_spec.json)；[inventory.py](../../scripts/collect/inventory.py) 只读盘点数据根；[paths.py](../../scripts/collect/paths.py) 是采集脚本唯一的数据根来源。测试：[test_dataset_registry.py](../../tests/test_dataset_registry.py)、[test_collect_inventory.py](../../tests/test_collect_inventory.py)。

[capture_root.py](../../src/quantlab/data/capture_root.py) 解析工作空间捕获包位置（重定向到数据根 `lake/_market_data`）；迁移脚本 [migrate_captures.py](../../scripts/collect/migrate_captures.py)；测试 [test_capture_root.py](../../tests/test_capture_root.py)。 今日候选规则与历史验证见 [candidates.py](../../src/quantlab/trading/candidates.py)，测试 [test_candidates.py](../../tests/test_candidates.py)。复盘验证（保存判断与自动核对）见 [judgments.py](../../src/quantlab/trading/judgments.py)，测试 [test_judgments.py](../../tests/test_judgments.py)。大V复盘（文章、观点提炼与核对）见 [kol.py](../../src/quantlab/trading/kol.py) 与 [kol_pages.py](../../src/quantlab/desktop/kol_pages.py)，测试 [test_kol.py](../../tests/test_kol.py)。盘中板块页见 [sector_pages.py](../../src/quantlab/desktop/sector_pages.py) 与 [intraday_sectors.py](../../src/quantlab/trading/intraday_sectors.py)（读取数据侧 `SectorIntradayProvider`），测试 [test_intraday_sectors.py](../../tests/test_intraday_sectors.py)。数据中心页见 [data_center_page.py](../../src/quantlab/desktop/data_center_page.py) 与 [data_center.py](../../src/quantlab/workbench/data_center.py)，测试 [test_data_center.py](../../tests/test_data_center.py)；更新状态/预览/任务三个分区见 [data_services_ui.py](../../src/quantlab/desktop/data_services_ui.py)，测试 [test_data_center_services.py](../../tests/test_data_center_services.py)。

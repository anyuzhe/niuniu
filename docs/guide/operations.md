# 运行与运维

[文档导航](../README.md) · [使用指南](user-guide.md) · [数据与证据](data-and-evidence.md)

所有命令默认从仓库根目录执行。示例中的 `/path/to/niuniu-data` 要替换成实际数据根。本文是操作说明，整理文档本身不会启动服务、下载、加载 LaunchAgent 或建立授权。

## 1. 各入口的职责

| 入口 | 用途 |
|---|---|
| `quantlab desktop` | 完整 PyQt 桌面工作台 |
| `python -m quantlab.agent.chat_cli --gui` | AI 对话助手 |
| `quantlab serve` | 本地 Web 工作台，同源移动只读页面 |
| `niuniu-mcp` | 牛牛产品的标准研究 MCP |
| `niuniu-tracking-daemon` | 只执行已有宿主跟踪授权的守护进程 |
| `niuniu-daily-orchestrator` | 单交易日冻结计划的 PREP/AUCTION/R1/R2/R3 编排 |
| `niuniu-evidence-scheduler` | 公开证据、研究派生和已授权研究任务的调度工具 |

完整 CLI 清单从 [代码地图](../development/code-map.md) 的入口表查询；参数以对应 `--help` 和 `pyproject.toml` 为准，不从过期验收命令猜测。

## 2. 本地 MCP 和 Web

```bash
niuniu-mcp --output ./artifacts --data-root /path/to/niuniu-data
```

默认 stdio。确需 HTTP 时可以显式使用回环地址：

```bash
niuniu-mcp --output ./artifacts --data-root /path/to/niuniu-data \
  --transport streamable-http --host 127.0.0.1 --port 8766
```

程序拒绝非回环监听。跨机访问需独立配置 SSH 隧道或受认证反向代理，不能靠把监听改成公网地址绕过边界。8766 是该程序默认值，**不代表本机该端口空闲**；和其他 Agent 服务冲突时，应检查现有配置并选择明确端口，不终止未知进程。

```bash
quantlab serve --data-root /path/to/niuniu-data --output ./artifacts
quantlab serve --help
```

Mobile/Bot 复用同一工作空间，不另建 Decision、持仓或记忆数据库。MCP 协议也不自动扩大模型的批准、执行、下载和交易权限。

## 3. 跟踪、日内编排和证据调度是三条链

**Watch 跟踪**：守护进程只消费已保存的跟踪授权，和桌面共享 JobQueue 的 worker 边界；退出界面不等于授权自动取消。创建/撤销授权、通知策略和基准换版分别处理。

```bash
niuniu-tracking-daemon --output ./artifacts --data-root /path/to/niuniu-data
quantlab tracking-launchd-write --help
```

生成 plist 不等于已经加载，也不等于创建授权。

**Daily Orchestrator**：宿主先为单个交易日建立计划并冻结定义、交易日等输入，再 tick/run。显式联网选项与既有快照模式不同；错过窗口不回填。空 PREP CandidateSet 可合法进入 NO_TRADE 终态。

```bash
niuniu-daily-orchestrator --help
niuniu-market-provider-status --help
```

**AR 公开证据与自主研究**：有独立收盘/盘中调度及研究预算。AR 代码完成不证明 LaunchAgent 已安装、机器未休眠或今日采集已成功。盘中快照、夜间研究和模拟盘授权不可互相代替。

```bash
niuniu-evidence-scheduler --help
niuniu-auto-research --help
niuniu-premarket-brief --help
```

本轮不复用或重新执行历史文档中针对某一交易日的一次性授权。2026-09-17 PIT 取证窗口属于该日期的历史运行记录，不是现在应重复安装的定时任务。

## 4. 扶摇与模型凭证

扶摇读取 `HITHINK_FINANCE_API_KEY` 或 macOS 钥匙串服务 `cn.niuniu.fuyao.api-key`；代码侧只暴露白名单聚合工具。不要把密钥粘贴到 README、Git、报告或模型消息里。

启用扶摇后的能力与回退行为见 [数据与证据](data-and-evidence.md) 和 [专项验收](../archive/integrations/牛牛AI交易助手_扶摇MCP接入与验收说明.md)。本轮没有读取、导出或修改任何凭证，也没有发起付费模型问答。

模型配置和已保存会话属于实际工作空间，不能通过移动文档替它们“升级”模型。外部 Research Skill 的 Git-clean 授权表和包指纹同样不可随意改变。

## 5. 状态、失败与恢复

先检查 System Health 的 Runtime / Research Readiness 两个轴，再读本次任务日志与证据。重点区分：程序在线但无合格数据、任务失败但历史产物仍完整、资料已下载但尚未确认发布时点、代码已实现但真实授权/部署未完成。

恢复使用原任务/计划的既有恢复入口，避免复制状态库或另造新的正式预测。重新查询和重试不应覆盖旧 receipt、Decision、未选候选和失败样本。

历史运行清单包含机器专属路径与状态，完整保存在 [AR 规划与验收原文](../archive/autonomous-research/牛牛AI交易助手_自主研究与打板情绪研究_规划与进度.md)。其中的“待安装”“已启用”属于各自记录时点，当前状态需在宿主实际查询，本轮未重新部署或验证那些后台服务。

## 6. 测试与文档维护

本项目测试使用 unittest。当前 Mac 全量同进程离屏测试出现过 Qt 原生崩溃；应保留日志，并可逐测试模块在独立进程中定位，而不是修改业务规则使其通过。操作方法和本轮结果入口见 [开发规范](../development/contributing.md) 与 [文档整理记录](../development/documentation-cleanup.md)。

日常维护只更新对应主题文档和开发史；复杂验收才另存 dated archive。历史产物路径、外部数据根和机器可读知识包不属于普通文档清理对象。

## 7. 无界面授权研究入口（2026-09-17）

已有有效 Research Session Grant 时，可显式把后台聊天连接到同一任务队列：

```bash
python -m quantlab.agent.chat_cli \
  --output /path/to/isolated-workspace --data-root /path/to/local-data \
  --allow-granted-research --accept-model-service \
  --ask "核对已有授权，只执行范围内已经冻结的研究配置，并引用真实任务结果。"
```

`--allow-granted-research` 仅接线，不创建或扩大授权；没有有效 Grant 仍然拒绝执行。默认不启用此开关。任务队列按需创建并在后台对话退出时关闭；已提交研究等待完成，不把关闭对话冒充撤销授权。

上述开关不是“禁用所有市场联网”的通用模式，原有模型发送/明确证券实时报价规则不变。本次隔离验收另通过测试适配器关闭行情网络，并冻结最多三个候选，未触及日常工作空间。

真实三候选模型试跑及限制见 [2026-09-17 后台实测](../archive/testing/20260917-自主因子后台实测.md)。单批次通过不代表已部署每日自动研究调度。

## 冻结候选100股验证（2026-09-17）

本轮已固定三个模型候选与100只证券，验证不调用模型、不下载、不打开客户端、不注册正式因子。证据在 `artifacts/frozen-candidate-validation-20260917-211359/`。复算使用该目录的原始 protocol、候选文件、snapshot 和 bars，不能看结果后改公式/方向/股票池：

```bash
PYTHONPATH=src .venv/bin/python scripts/validate_frozen_candidates.py verify \
  --case-dir artifacts/frozen-candidate-validation-20260917-211359
```

`capture` 需要预先冻结的 protocol.json、selected-universe.json 与原始 frozen-candidates.json，并显式提供 --data-root；按冻结股票清单读取本地原字节，禁止替换股票。`run` 仅首次执行并保留启动标记，拒绝覆盖已有结果；`verify` 重新比对因子、标签、日度统计与结论，相同核验不覆盖首份回执。失败输入、不可检验项和反向结果不得删除后重试显著性。

这是研究专用 nullable-volume 路径：保留空量/时点，屏蔽相应信号，不放宽生产数据校验。时间块检验、样本选择、Strict PIT和成本限制见[完整实测](../archive/testing/20260917-自主因子后台实测.md)。

## 正式助手的本地数据研究与观察

后台原生入口新增 `--local-data-only`：禁用宿主实时报价及扶摇工具，不读取其凭证；这不表示模型离线，模型服务仍须 `--accept-model-service`。普通启动行为不变。例：

```bash
python -m quantlab.agent.chat_cli --output ./artifacts --data-root /path/to/niuniu-data \
  --local-data-only --allow-granted-research --accept-model-service \
  --ask "自行检查本地资料，在已有授权范围内研究并保存有证据的结论草稿。"
```

必须事先有有效 Grant；上述开关不建立授权。没有执行需求时去掉 `--allow-granted-research`。模型通过正式的 `list_local_market_data` / `inspect_local_market_data` 发现证券、日期、来源哈希、字段质量和截面数量，不再依赖测试脚本提供行情摘要。当前发现/检查入口覆盖原始 MQC 目录的 1d/5m、raw/qfq；遇到管理批次/更新通道/冻结标记会明确拒绝回退，应走既有批次/通道工具，不宣称所有数据格式已覆盖。

`describe_factor` 对 DSL.RESTRICTED 返回实际表达式白名单和限制；假设的 parameters 只存因子参数，研究 spec 的版本键是 version。局部数据检查不会填空、删行、修改原行情或签发PIT资格。客户端与MCP的研究提案API也复用这两个本地只读工具。

助手自主功能的验收由正式模型选择与调用驱动；开发者不代选研究内容。2026-09-17 实际记录见 [自主助手实测](../archive/testing/20260917-自主因子后台实测.md) 第三阶段。


## 从两份原文件监督规格测试

对于用户明确指定的研究说明，先由宿主导入并固定原始MD/JSON，模型只能通过规格ID和分组读取，不能任意读盘。导入不注册策略，也不授予模型Shell权限。

```bash
python -m quantlab.agent.research_specs \
  --output /path/to/test-workspace \
  --markdown /path/to/source.md --dictionary /path/to/source.json --confirm
```

保存返回的 `spec_id`，然后使用正式后台助手：

```bash
python -m quantlab.agent.chat_cli \
  --output /path/to/test-workspace --data-root /path/to/niuniu-data \
  --research-spec <spec_id> --local-data-only --allow-spec-tests \
  --accept-model-service --ask "读取原始全局规则和全部字段，严格检查并测试；不支持项明确报告，禁止替代。"
```

`--research-spec` 绑定会话中的规格版本，并禁止通用因子研究/旧qimo代理替代；它与GUI、通用 `--allow-granted-research` 互斥。`--allow-spec-tests` 只许可本次进程至多3次固定测试，不建立持续授权。省略该选项只读规格/已有记录。两份原件发生变化后不能沿用旧哈希执行，即使标题、model_id和版本字符串看起来相同。

当前精确适配只识别已审核的QM50-SCLA v0.2两份字节版本，提供原文读取、60项一致性审计、合成组件逻辑检查和P07原始字段诊断；不是通用文本自动执行器，也不是完整60字段回测。其他规格不能自动执行。旧qimo-source-rules-v2保持原有独立用途，不能按名字相似自动映射。

结果存入测试工作空间的 `_research_spec_tests/`，每次包括规格哈希、实际参数、运行代码指纹、状态和数值文件指纹。完整资料不足时真实分数/Q/交易保持空，组件合成测试中的示例分数不作为市场结果。该入口尚不是新增客户端的一键规格导入面板。

本轮实际轨迹和限制见 [QM50严格规格验收](../archive/testing/20260917-QM50-SCLA-v0.2-严格规格验收.md)。

## QM50基础数据依赖核查（2026-09-18）

绑定规格的原生会话可使用 `get_strict_pit_coverage` 只读查询既有PIT审计，并单列正式规则和回顾性参考；`qualify_research_data` 保持原请求级资格边界。工具可调用不代表请求已合格，全球存档数量也不是具体证券、日期的覆盖率。

`inspect_qm50_base_rules_coverage` 接收同一spec_id、实际沪深证券（1–10只）及日期范围（1–31自然日），按归档交易日历求D/D-1/D-2，核对五类既有归档、证券身份/成员、规则时间和原始行情存在性，并保留未支持字段、未知高度和候选。该工具只读，不修复数据或创建receipt。

`run_research_spec_test` 的 `kind=BASE_RULES_COVERAGE` 保存上述请求与完整coverage.parquet；状态 `AUDIT_COMPLETED_INPUTS_BLOCKED` 表示审计执行成功但真实输入仍阻断，不是完整回测成功。`kind=BASE_RULES_GUARDS` 运行25项纯组件边界案例，symbols/start/end应留空。总测试次数仍受本次宿主进程最多3次限制。

发现某个历史session缺回执时，不要重新签一个旧日期回执、把当前状态回填、或把规范/回顾性参考变成正式逐日值。需要原始时点数据或另行设计前瞻采集；现有归档的确认要求没有被这些查询工具改变。检查缺口输出的data_requests是具体接受条件，不是已执行下载授权。

测试入口沿用上一节 `--research-spec / --allow-spec-tests / --local-data-only`，不操作客户端。对已有结果使用get_research_spec_test读回，避免重复计算。实际记录见 [QM50原始规格验收](../archive/testing/20260917-QM50-SCLA-v0.2-严格规格验收.md) 第二阶段。


## 使用已有合并归档作为规格输入来源

当测试输出目录与日常行情归档不在同一工作空间时，由宿主显式指定只读来源，避免模型只查旧MQC目录或误以为空测试目录就是全部资料：

```bash
python -m quantlab.agent.chat_cli \
  --output /path/to/test-workspace --data-root /path/to/niuniu-data \
  --research-spec <已导入的规格ID> \
  --spec-source-workspace /path/to/production-artifacts \
  --local-data-only --allow-spec-tests --accept-model-service \
  --ask "先查已归档capture，选择少量真实样本，接入原始日线并冻结复算；不得推算缺失价格规则或生成交易。"
```

`--spec-source-workspace` 只用于规格会话，仅读取来源中的既有 `_market_data/retro_daily/`，包括pack形式；不迁移或修改来源，不允许模型给任意路径。省略时只看当前输出工作空间。通过实际capture_id调用 `list_qm50_archived_symbols` 和 `inspect_qm50_archived_daily`，可以发现并深验preclose/turn/isST/tradestatus等原始字段，不需要重复下载。

`run_qm50_archived_inputs` 只接入1–10只证券、最多371自然日的回顾性输入；冻结原始响应与typed Parquet，保留D-1映射和缺失值，产生真实输入表。它不是完整QM50回测，不将供应商turn当作流通股本，不将preclose当作已认证参考价，也不生成价格上下限或候选。

`replay_qm50_archived_inputs` 复算同一test_id，只需输出目录内的冻结字节，不再依赖外部来源；该计算也消耗本进程固定测试预算。原始请求股票顺序必须保留。示例样本的ST/停牌筛选用于功能诊断，不能作为历史策略候选池。

完整实测和复算排序问题见 [QM50验收第三阶段](../archive/testing/20260917-QM50-SCLA-v0.2-严格规格验收.md)。客户端尚没有新增的跨工作空间导入按钮，不把后台入口冒充界面已接通。


## TDX新增数据入库与断点采集（个人研究）

新增数据与原日线/5m共享 `niuniu-data/catalog/mqc.duckdb`，但使用独立的 `tdx_*` 视图和 `lake/bronze/provider=tdx/` 来源目录，不覆盖原Baostock数据。原始响应、Parquet、采集时间、单位、请求和哈希一并保存；`catalog/tdx_ingestion.sqlite3` 管理断点队列，不是另一套行情业务数据库。

本机查看状态、暂停、继续：

```bash
/bin/sh /Volumes/Lexar/niuniu-data/automation/tdx/tdx.sh status
/bin/sh /Volumes/Lexar/niuniu-data/automation/tdx/tdx.sh stop
/bin/sh /Volumes/Lexar/niuniu-data/automation/tdx/tdx.sh resume --personal-research-only \
  --seconds 86400 --max-requests 200000 --max-new-gib 200
```

恢复用resume，不要重复prepare。当前全量计划含5,809个证券标识、13类数据，初始58,091个任务，后续历史页按需展开。开始时间与计划下界不代表对应历史已取得；全量尚未完成。双并发、请求间隔、单轮时间/请求/磁盘预算和30GiB余量保护均保持，错误与空数据分开。报价、盘口、题材和财务为观察时点快照，不能凭今天的接口倒推完整历史。

牛牛可用 `get_tdx_data_status` / `read_tdx_data` 只读查询，模型不能启动采集或任意写库。采集库保存在数据根automation中的隔离研究运行目录，未成为主程序默认依赖；ELTDX Research-Only许可仍限制商业、生产服务、行情转售和自动交易。完整目录、表名及限制见 [TDX实测与入库记录](../archive/integrations/20260918-TDX-数据源可行性实测.md)。

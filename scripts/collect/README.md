# scripts/collect —— 受版本管理的数据采集器

本目录是数据采集脚本的**唯一正式落脚点**。用户于 2026-09-22 明确：数据采集一律写成脚本，
助手负责监控脚本运行，而不是在会话里手工逐条拉取。既然复核由独立的代码维护侧进行，
采集脚本必须自身可读、可重跑、可审计——所以它们进版本库，而不是留在 `artifacts/`（已被 gitignore）。

## 两段式运行：先扫描，再凭批准计划采集

产品 CLI 已有按显式证券和日期取数的底层能力，但没有全市场缺口发现与批准计划绑定。
本目录补的是这一层调度，不替换产品 Provider：

1. `scan_gaps.py` 只读归档交易日历、`stock_basic` 与现有 parquet，排除退市股，分别找出
   **整只未采**与**末尾日期落后**；18:00（北京时间）前默认只追到上一个交易日，之后含当日。
2. 扫描结果是确定性 JSON，带 `plan_sha256`。可以用 `--limit` 先形成有限计划供用户审阅。
3. `bars_incremental.py` 只有同时收到 `--apply --plan ... --approve-sha256 ...` 才登录供应商；
   批准哈希、日历/证券表指纹、每个既有文件指纹任一不符都会在联网前拒绝。
4. 写入前逐文件备份并核对 SHA256；返回日期只能落在获批区间，合并后校验 schema 和主键，
   临时文件回读成功后才原子替换。

中间缺失交易日可能是停牌，不自动补。baostock 5 分钟数据在 2020-01-02 以前的全市场
硬边界标为 `known_vendor_limit`，不作为可重试缺口。

## 采集器

| 脚本 | 来源/功能 | 默认清单或目标 |
|---|---|---|
| `scan_gaps.py` | 只读发现日线/5m 缺口并生成批准计划 | `stocks-listed`，退市股排除 |
| `bars_incremental.py` | 按已批准计划补日线/5m | 只执行计划内证券与日期 |
| `ths_dividend.py` | `akshare.stock_fhps_detail_ths` | `stocks-listed`，退市股排除 |
| `cninfo_allotment.py` | `akshare.stock_allotment_cninfo` | `tdx-rights-listed`，退市股排除 |
| `baostock_dividend.py` | Baostock逐年历史分红 | `stocks-listed`，全历史写新目录 |
| `baostock_daily_status.py` | Baostock交易/停牌/ST日状态 | `stocks-listed`，保留`tradestatus=0` |
| `baostock_reference_snapshot.py` | 日历、证券、行业和三大指数成分 | 不可变日期批次，不切产品指针 |
| `migrate_empty_parquet.py` | 将旧零行占位Parquet迁为有类型空标记 | 先备份和核SHA，再移除混合schema |
| `daily_plan.py` | 每日只读计划包，参考快照先行、其余计划随后 | 各计划分别批准，不能一键自动采集 |
| `status_incremental.py` | Baostock交易/ST状态缺整只和尾部增量 | 状态表单独更新，历史内部洞仅报告 |
| `corporate_actions_daily.py` | 同花顺/巨潮/Baostock分红每日再观察 | 内容SHA比较，变更备份、逐证券回执 |
| `inventory.py` | 只读盘点数据根：文件、行数、列签名、日期范围、指纹 | 报告必须写在数据根外；`--deep-hash` 才算内容 SHA |
| `migrate_captures.py` | 把工作空间 `_market_data` 捕获包复制到数据根并重定向 | plan→apply→redirect→pointer，每步需计划 SHA；源文件不动 |
| `registry.py` | 数据集注册表 draft/verify/apply 与 `reg_*` 视图计划 | 写入须带草稿或视图计划的完整 SHA |
| `public_sources.py` | 17 项公开来源数据（东财/同花顺/巨潮/交易所/中证/申万，a-stock-data 代码） | `list` 看清单；`plan --dataset ...` → `apply --plan ... --approve-sha256 ...`，每项单独批准 |

## 数据根与注册表

- **数据根**：所有脚本经 `paths.py` 取数据根。设置 `NIUNIU_DATA_ROOT`（绝对路径）可改到隔离目录；不设时使用历史路径 `/Volumes/Lexar/niuniu-data`。脚本里不再写死数据根，测试会检查这一点。
- **全量公司行动采集必须显式 `--dest`**：`ths_dividend.py` 与 `cninfo_allotment.py` 不再默认指向已被替代的 v1 目录。当前目录以注册表为准（同花顺 `corporate_actions_dividend_v2`、巨潮 `corporate_actions_allotment_v2`）。
- **注册表**：`catalog/dataset_registry.json` 声明每个逻辑数据集的当前目录，映射清单是人工审阅的 `registry_spec.json`。更新流程：

```bash
python3 scripts/collect/registry.py draft --out <数据根外>/registry-draft.json   # 只读，打印草稿 SHA
python3 scripts/collect/registry.py apply --draft <草稿> --approve-sha256 <草稿SHA>
python3 scripts/collect/registry.py verify                                      # 只读，报告目录漂移
python3 scripts/collect/registry.py views                                       # 只读，打印 reg_* 视图计划 SHA
python3 scripts/collect/registry.py views --apply --approve-sha256 <计划SHA>   # 写 catalog，需先确认无其他进程在用
```

草稿之后目录若有变化，apply 会拒绝，需要重新 draft。旧注册表先复制到 `catalog/registry_history/` 再替换。`views` 只创建或替换 `reg_` 前缀视图，不碰表和其他视图。

## 采集信封（`envelope.py`）

所有采集器共用同一套约束，目的是让「采了什么、漏了什么」能从回执读出来，
而不依赖助手的口头汇报：

- **目标目录非空即拒绝**，除非显式 `--resume`；续采只增不改已校验通过的文件。
- **`--dry-run` 不发起任何供应商请求**，只打印计划（清单来源、全集、已存在、待采集、节流）。
- **原子写入**：先写 `.parquet.tmp` 再 `os.replace`，中途断电不会留下半个 parquet。
- **逐符号回读校验**：行数与列名必须与写入前一致，否则该符号算失败。
- **保留供应商全部列**。`REQUIRED` 只是「这些列必须在」的存在性门槛，**不是投影白名单**。
- **不做全表 `astype(str)`**。只有 parquet 写不下的列才逐列降级为字符串，
  并在回执 `coerced_to_string` 里逐列点名。
- **四态分明**：`ok` / `empty` / `failed` / `schema_issue` 各自可数。
  失败**不写文件**，所以「文件不在 + 出现在 failed」和「文件不在 + 压根没采」不会混淆；
  空结果写入 `_empty/<symbol>.json` 有类型标记，不写缺列的零行Parquet，避免污染数据集schema；
  `--resume` 会校验并跳过该标记，不会反复请求。
- **列签名稽核**：运行前后都把目标目录按列签名分组。出现两种以上签名会告警，
  并写进回执的 `column_signatures` / `schema_is_uniform`。
- **逐证券检查点**：每处理一只就原子更新回执；进程被终止时，已完成/失败边界仍可复核。
- **硬超时**：行情、分红和状态的Baostock会话运行在可杀掉并重启的独立worker中；
  Akshare采集至少受单请求SIGALRM和持久回执保护，卡住时可按回执续采。

公司行动采集器共用参数：`--dest --receipt --universe --universe-preset --limit --throttle
--retries --resume --dry-run --apply --fail-fast`。**不加 `--apply` 永远只展示计划**。
退出码：`0` 成功，`1` 有失败或提前停止，`2` 拒绝执行。

## 证券清单（`universe.py`）

清单必须来自具名预设或 `--universe` 显式文件，**不得**再从某个分析产物里顺手取。
旧 cninfo 脚本的清单取自 `d4/rights-issue-adjustment-gaps.csv`（一份带上游筛选的分析结果），
口径因此比目标总体少 114 只——这是这轮整改要根除的那类问题。

| 预设 | 含义 |
|---|---|
| `stocks` | baostock `stock_basic` 中 `type=1` 的全部 A 股，含已退市 |
| `stocks-listed` | 同上但只取 `status=1` 在市标的 |
| `tdx-rights` | TDX `c4>0` 的历史证券，含退市，只能显式选用 |
| `tdx-rights-listed` | TDX `c4>0` 与当前在市 A 股的交集（巨潮默认） |

已知局限：`stock_basic` 的退市股只有 337 只，1990 年代摘牌的标的多半不在内。
要覆盖早年退市股请用 `--universe` 给显式清单，不要假设预设即全集。

## 已知的既有数据问题（整改不会自动修复）

`provider=cninfo/corporate_actions_allotment` 现有 592 个文件是旧脚本写的：

- 588 个是 **16 列**（15 列白名单 + `plan_symbol`），供应商另外约 40 列已被丢弃且未记录；
- 4 个是 **15 列**（旧脚本写空结果时用的 `pd.DataFrame(columns=KEEP)` 少了 `plan_symbol`）；
- 缺的列里包含停牌起始日、缴款日期、大股东认购数量等**判定 19 条未决配股事件所需的证据**。

因此对这个目录**不要用 `--resume` 补那 114 只**：那只会得到三种列宽混在一起的数据集。
正确做法是采到一个全新目录、全宽重来，再由代码维护侧决定如何替换指针。
`--dry-run --resume` 可以安全地先看到这个局面（信封会告警），它不写任何东西。

## 每日运行边界

先执行只读 `daily_plan.py --date YYYY-MM-DD --out-dir artifacts/<审阅目录>`。如果当日参考快照不存在，它**只输出参考快照计划**；单独审阅并批准 `baostock_reference_snapshot.py --snapshot-date ... --dest ... --apply --approve-sha256 ...` 后重新运行，才输出行情、状态、公司行动各自的JSON和SHA。`index.json` 不是总批准凭证；不能凭一次授权一键启动全部采集。计划输出在可审阅目录，不写数据湖也不联网。

- `scan_gaps.py` → `bars_incremental.py` 按最新已验SHA的参考日历与stock_basic自动发现新上市证券、末尾缺口/5分钟不足48根；计划绑定所选快照，快照在批准后变化则联网前拒绝。若独立状态文件证明尾部每个交易日均`tradestatus=0`，列为`suspended_tail`、绑定状态文件SHA而不进入重试动作；内部无bar日期仍只报告不自动补。
- `status_incremental.py` 从原状态文件真实末日之后采集完整交易日状态，逐证券备份、原子合并和回执；内部缺日单列 `interior_gaps`，不自动补。`--apply --plan <状态计划> --approve-sha256 <完整SHA>` 才联网；失败用相同计划和 `--resume-run` 续跑。默认计划在参考日历落后于当天时拒绝，不把旧日历末日当今天。
- `corporate_actions_daily.py` 对同花顺分红、巨潮配股按全供应商历史重新观察；Baostock分红默认重查最近3个报告年度并保留更早原始行，`--lookback-years` 可扩大至60（需要更多请求）。结果按字段和行内容做顺序无关、保留重复的摘要比较；不变文件不改字节，新增/修订先备份旧文件及空结果标记再替换，供应商把已有历史整段返回空值时拒绝擦除。每证券持久回执、可续跑，需单独 `--dataset ... --apply --plan ... --approve-sha256 ...`。Baostock超出批准回看窗口的旧年修订**不会自动发现**；仅生成bronze观察版本，不自动裁决事件、重算因子。
- `baostock_reference_snapshot.py` 按日期建立新不可变快照；没有快照时下游使用旧归档源并在计划中绑定其SHA。优先使用最新不晚于目标日期的完成快照，必须验证manifest与实际证券文件SHA；最新快照损坏或不完整会拒绝而非回退旧版。参考快照中的在市口径可能不同于2026-09-22首采所用旧stock_basic，差异应单列审阅，不得暗改旧验收总体。
- **频率（2026-09-23 起）**：公司行动历史记录不再每日全量复查。2026-09-23 全量再观察三家合计 6,451 只、真实修订 0 条，详见[再观察结果与采集频率](../../docs/archive/data-evidence/20260923-公司行动再观察结果与采集频率.md)。全量复查只在发布新版 qfq 前做一次（平时最多每季度一次）；每日只采新事件和新上市证券（待实现的子集模式做好前，每周一次）。Baostock 请求间隔不低于 1 秒、单次登录，过密会被封禁。`--resume`（全量首采脚本）仍只跳过已有文件，不等于上述增量命令。
- **公开来源数据**（`public_sources.py`，2026-09-23 起）：“当天观察”的 9 项（`em_monitor, em_anomaly, index_weights, holder_count, northbound_minute, earnings_forecast, share_buyback, equity_pledge, ipo_calendar`）只能当天采，错过不能回补，北向分钟须收盘后采；`sw_industry_history` 本身是全量变更历史，每周采一次即可；按交易日的 `ths_limit_up, block_trades` 当天收盘后采，`margin_official` 是 T+1，次日采前一交易日；按公告日的 `institution_survey, holder_trades` 当天或次日采，`cninfo_announcements` 次日采前一天（当天晚间仍会新增）；`lockup_expiry` 的未来分区是预告，应每周重采；**脚本目前会跳过已有分区，重采模式尚未实现**，做好之前未来分区保持首采时的观察。每项 `plan` 后单独批准；东财请求间隔不低于 1.5 秒，不并行。
- 每日真实联网仍须当次授权；未取得当次批准时只允许生成计划，不因调度自动执行。

## 授权边界

脚本写好不等于可以跑。**真正发起采集需要用户每次单独授权**：

- 公司行动采集器必须显式加 `--apply`；默认和 `--dry-run` 都不会初始化供应商请求。
- 行情增量采集还必须提交用户已审阅计划的完整 `--approve-sha256`；不能扩大日期或证券范围。

按 `AGENTS.md`：不直接操作真实客户端，不启动可见窗口，缺数据不填零、不伪造。

## 测试

`tests/test_collect_envelope.py`、`tests/test_collect_gaps.py` 与 `tests/test_collect_daily.py` 共 58 个用例，注入假 fetcher，
覆盖无授权不联网、计划哈希防篡改、退市排除、周末过滤、18:00 截止、供应商历史下限、
整只未采/末尾落后、5m 末日不足 48 根重取、旧文件指纹变化拒绝、整日替换与 schema/主键校验。
全程离线，只写临时目录。

运行：`.venv/bin/python -m unittest tests.test_collect_gaps tests.test_collect_envelope tests.test_collect_daily -q`

## 被替代的旧脚本

`artifacts/data-governance-20260922-D1D3/logs/` 下的 `ths-collect.py`、`ths-pilot.py`、
`cninfo-collect.py`、`cninfo-pilot.py` 已作废，保留仅供追溯既有数据是怎么来的，不要再运行。
同目录 `d4-min5-backfill.py` 走的是 baostock，应改用产品 CLI `quantlab fetch-bars`。

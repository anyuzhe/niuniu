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

- `scan_gaps.py` → `bars_incremental.py` 支持每日重新扫描、生成新计划SHA，并在当次批准后增量补行情。
- `baostock_reference_snapshot.py` 支持按日期建立新的不可变快照，不覆盖旧日期批次。
- 同花顺、巨潮、Baostock分红及日状态当前用于**全量基线和中断续采**；`--resume` 会跳过已有文件，不能发现已有证券后来新增或修订的事件，尚不能当每日智能更新器。
- 每日真实联网仍须当次授权；脚本不会因为被调度就绕过 `--apply` 或行情计划SHA。

## 授权边界

脚本写好不等于可以跑。**真正发起采集需要用户每次单独授权**：

- 公司行动采集器必须显式加 `--apply`；默认和 `--dry-run` 都不会初始化供应商请求。
- 行情增量采集还必须提交用户已审阅计划的完整 `--approve-sha256`；不能扩大日期或证券范围。

按 `AGENTS.md`：不直接操作真实客户端，不启动可见窗口，缺数据不填零、不伪造。

## 测试

`tests/test_collect_envelope.py` 与 `tests/test_collect_gaps.py` 共 40 个用例，注入假 fetcher，
覆盖无授权不联网、计划哈希防篡改、退市排除、周末过滤、18:00 截止、供应商历史下限、
整只未采/末尾落后、5m 末日不足 48 根重取、旧文件指纹变化拒绝、整日替换与 schema/主键校验。
全程离线，只写临时目录。

运行：`.venv/bin/python -m unittest tests.test_collect_gaps tests.test_collect_envelope -q`

## 被替代的旧脚本

`artifacts/data-governance-20260922-D1D3/logs/` 下的 `ths-collect.py`、`ths-pilot.py`、
`cninfo-collect.py`、`cninfo-pilot.py` 已作废，保留仅供追溯既有数据是怎么来的，不要再运行。
同目录 `d4-min5-backfill.py` 走的是 baostock，应改用产品 CLI `quantlab fetch-bars`。

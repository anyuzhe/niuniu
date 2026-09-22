# scripts/collect —— 受版本管理的数据采集器

本目录是数据采集脚本的**唯一正式落脚点**。用户于 2026-09-22 明确：数据采集一律写成脚本，
助手负责监控脚本运行，而不是在会话里手工逐条拉取。既然复核由独立的代码维护侧进行，
采集脚本必须自身可读、可重跑、可审计——所以它们进版本库，而不是留在 `artifacts/`（已被 gitignore）。

## 先去产品 CLI 找，找不到再写这里

baostock 系的采集**产品里已经有**，不要在本目录重复实现：

| 需求 | 用这个 |
|---|---|
| 日线 / 5 分钟历史原始行情 | `quantlab fetch-bars` |
| ST / 交易状态 | `quantlab fetch-status` |
| 行业、季度股本、历史 ST、停牌 | `quantlab fetch-reference` |
| 分红导入 | `quantlab dividend-import` |
| 元数据导入 | `quantlab metadata-import` |

本目录只承载**产品 CLI 尚未覆盖**的供应商，目前是 akshare 下的同花顺分红与巨潮配股。

## 采集器

| 脚本 | 来源 | 默认清单 | 默认目标 |
|---|---|---|---|
| `ths_dividend.py` | `akshare.stock_fhps_detail_ths` | `stocks`（5552 只） | `lake/bronze/provider=ths/corporate_actions_dividend` |
| `cninfo_allotment.py` | `akshare.stock_allotment_cninfo` | `tdx-rights`（706 只） | `lake/bronze/provider=cninfo/corporate_actions_allotment` |

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
- **三态分明**：`ok` / `empty` / `failed` / `schema_issue` 各自可数。
  失败**不写文件**，所以「文件不在 + 出现在 failed」和「文件不在 + 压根没采」不会混淆；
  空结果**写零行文件**，这样续采不会反复去问同一只。
- **列签名稽核**：运行前后都把目标目录按列签名分组。出现两种以上签名会告警，
  并写进回执的 `column_signatures` / `schema_is_uniform`。

共用参数：`--dest --receipt --universe --universe-preset --limit --throttle --retries
--resume --dry-run --fail-fast`。退出码：`0` 成功，`1` 有失败或提前停止，`2` 拒绝执行。

## 证券清单（`universe.py`）

清单必须来自具名预设或 `--universe` 显式文件，**不得**再从某个分析产物里顺手取。
旧 cninfo 脚本的清单取自 `d4/rights-issue-adjustment-gaps.csv`（一份带上游筛选的分析结果），
口径因此比目标总体少 114 只——这是这轮整改要根除的那类问题。

| 预设 | 含义 |
|---|---|
| `stocks` | baostock `stock_basic` 中 `type=1` 的全部 A 股，含已退市 |
| `stocks-listed` | 同上但只取 `status=1` 在市标的 |
| `tdx-rights` | TDX 除权除息记录中 `c4`（配股比例）> 0 的证券，即历史上确有配股的标的 |

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

## 授权边界

脚本写好不等于可以跑。**真正发起采集需要用户单独授权**；未获授权时只使用 `--dry-run`。
按 `AGENTS.md`：不直接操作真实客户端，不启动可见窗口，缺数据不填零、不伪造。

## 测试

`tests/test_collect_envelope.py`，15 个用例，注入假 fetcher，全程离线、只写临时目录。
运行：`cd tests && ../.venv/bin/python -m unittest test_collect_envelope`

## 被替代的旧脚本

`artifacts/data-governance-20260922-D1D3/logs/` 下的 `ths-collect.py`、`ths-pilot.py`、
`cninfo-collect.py`、`cninfo-pilot.py` 已作废，保留仅供追溯既有数据是怎么来的，不要再运行。
同目录 `d4-min5-backfill.py` 走的是 baostock，应改用产品 CLI `quantlab fetch-bars`。

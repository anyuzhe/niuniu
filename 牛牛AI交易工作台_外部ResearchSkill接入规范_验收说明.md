# 牛牛 AI 交易工作台：外部 Research Skill Git Archive / Curation v2 验收说明

- 验收时间：2026-09-16 02:27（Asia/Shanghai）
- 上游：`https://github.com/lyra81604/zhengxi-views.git`
- 固定 commit：`304ac3e404a4c5f5c85d927840fefb028bebb536`
- 固定 tree：`ef5833f6ff201b60ae5213501eaee70fb428fe2f`
- 范围：宿主授权 clone → 不执行归档 → 选择性回顾策展 → StrategySource 预览 → Playbook DRAFT 候选
- 结论：真实上游已下载到独立数据根并形成 append-only Git archive；首个“说／做／结果”策展包可通过结构与字节审计，但仍缺官方原始字节、可靠 publication receipt 和 source identity 宿主复核，未写 StrategySource/Playbook，不能进入 Strict PIT、Alpha、Daily Scanner 或交易。

## 1. 下载与许可证边界

宿主明确允许直接 Git 下载后，实际 clone 保存于：

```text
/Volumes/Lexar/niuniu-data/research_skills/upstream/zhengxi-views
```

clone 时使用 HTTPS，未向主仓库复制第三方 corpus、基金数据、图片或脚本。上游 `LICENSE` 声明：代码及项目文档使用 MIT；`references/corpus/` 与 `references/fund_data/` 的第三方公开材料权利仍归原权利人，仅作研究学习用途。因此：

- 牛牛源码只保存控制合同、固定身份 lock 和 curation plan；
- 上游原始/衍生字节、receipt 与生成包只进入 `/Volumes/Lexar/niuniu-data`；
- 不将 GitHub 上游的“全部公开观点”“真实数据”等自述当成牛牛独立认证结论；
- Git author/committer time 可记录但可由提交者设置，不等于来源 publication time；
- 未运行 `requirements.txt`、未安装上游依赖、未执行任何上游 Python。

## 2. Git archive 合同

新增：

```bash
quantlab research-skill-git-archive \
  --data-root /Volumes/Lexar/niuniu-data \
  --repository /Volumes/Lexar/niuniu-data/research_skills/upstream/zhengxi-views \
  --skill-key zhengxi \
  --expected-origin https://github.com/lyra81604/zhengxi-views.git \
  --expected-commit 304ac3e404a4c5f5c85d927840fefb028bebb536 \
  --expected-tree ef5833f6ff201b60ae5213501eaee70fb428fe2f \
  --confirm-untrusted-no-exec
```

该命令本身不执行 `clone/fetch/pull`，并设置 `GIT_NO_LAZY_FETCH=1`。它只允许普通独立 checkout，逐项拒绝：

- origin、HEAD 或 tree 与宿主固定值不一致；
- symlink、submodule、特殊 tree mode；
- 缺失、未跟踪、额外或与 Git blob 不一致的 worktree 文件；
- 单文件、文件数或总字节超过预算；
- 数据根或归档路径中的符号链接。

每个 tracked blob 同时保存 Git blob oid、bytes、SHA256 和内容寻址 object path。receipt 按 archive snapshot append-only 保存；相同 tree 重试幂等，不覆盖不同 snapshot。

## 3. 真实 archive 结果

```text
archive_snapshot = a48a85cb1d0dacddbaa54cb88761bf34c7d47ac0d621fee6be28e8f6e383fd3a
receipt = research/external_research_skills/git_receipts/zhengxi/a48a85cb...383fd3a.json
observed_at = 2026-09-15T18:27:05.855487+00:00
files = 143
total_bytes = 11,367,050
verified_receipts = 1
invalid_receipts = 0
```

上游目录包括其自述的 corpus index、8只基金快照、全市场基金列表、方法/评分卡及7个 Python 脚本。完整 archive 只是保全字节，不代表每项都已选入牛牛，也不代表上游所称覆盖完整、来源真实或数字准确。

深验命令：

```bash
quantlab research-skill-git-audit \
  --data-root /Volumes/Lexar/niuniu-data --skill-key zhengxi
```

审计逐份复核 receipt checksum、snapshot、inventory digest、路径、对象 bytes/SHA256 与全套固定 false 边界。对象被篡改时该 receipt 转为 invalid。

## 4. 控制包与策展包分离

Git 跟踪控制包：

```text
research_skills/zhengxi/
control snapshot = 7185219deebfe271d28e8f77abb72fc9077246ae2a7ddb69bd560de454a9dd6f
status = SOURCE_REQUIRED
resources = 6
primary/action/outcome/claim/alignment = 0
```

它只保存安全行为、方法/评分合同、脚本政策和 `upstream.lock.json`，因此故意保持 source-free。第三方字节不进 Git。

策展计划：

```text
research_skills/curation/zhengxi-304ac3e4.json
```

生成命令：

```bash
quantlab research-skill-git-curate \
  --data-root /Volumes/Lexar/niuniu-data \
  --control-package research_skills/zhengxi \
  --plan research_skills/curation/zhengxi-304ac3e4.json \
  --confirm-retrospective-only
```

curation plan 同时固定 control snapshot 与 Git archive snapshot；curation 只能读取已通过深验的 object，每项必须同时匹配 upstream path、bytes、SHA256，并只能落到生成包的 `references/upstream/`。它不复制或执行上游脚本，不联网，不写 StrategySource/Playbook。

## 5. 首个真实策展包

```text
package_snapshot = f9e72ecd207af9850fe86ee71b0bc6133d5101c2a1b70ec200094221d574bf10
status = DRAFT
resources = 14
PRIMARY_STATEMENT = 1
DISCLOSED_ACTION = 1
REALIZED_OUTCOME = 1
claims = 10
source-grounded claims = 8
alignments = 1
complete say/do/outcome triads = 1
hypotheses = 5
scripts = 0
```

选择范围严格小于上游全集：

1. 一份2026-06-08访谈整理文本；
2. 001513季度持仓 JSON；
3. 001513净值/业绩/规模 JSON；
4. 上游 corpus index、fund index、method、scorecard 和 LICENSE；
5. 牛牛自己的安全控制文档。

生成包位于：

```text
/Volumes/Lexar/niuniu-data/research/external_research_skills/packages/zhengxi/
f9e72ecd207af9850fe86ee71b0bc6133d5101c2a1b70ec200094221d574bf10
```

## 6. 原话与“说／做／结果”核验

`DIRECT_QUOTE` 除了只能引用 `PRIMARY_STATEMENT`，现在还必须逐字存在于对应 UTF-8 来源文件；只改 manifest 制造不存在的“原话”会以 `DIRECT_QUOTE_NOT_FOUND` fail-closed。

首个 alignment：

- 说：访谈整理文本中“我那时候开始尝试配置一些光通信、PCB板块资产。”；
- 做：上游001513逐季度前十大持仓快照；
- 结果：上游001513净值/业绩/规模序列；
- assessment：`MIXED`。

`MIXED` 的原因不是否认持仓对照，而是基金整体结果不能归因于单一光通信观点。持仓和净值又都是上游衍生快照，没有提供方原响应、headers 和逐期 publication receipt。

## 7. 五个 DRAFT 假设

策展计划把逐字 claim 回链到五类候选：

1. 行业景气与通胀来源；
2. ROE低位修复；
3. 全球技术周期与中国比较优势；
4. 产业链利润再分配；
5. 机构可承载流动性与周期拼接。

这只代表 `playbook_draft_candidate_ready=true`。仍然：

- `quant_validation_completed=false`；
- 没有正式创建 PlaybookDefinition；
- 没有 Holdout、Walk-forward、行业/市值中性或成本后结果；
- 没有连接 Daily Scanner、Decision、Paper 或 execution。

## 8. Authenticity、publication 与 Strict PIT

策展包审计明确输出：

```text
source_identity_verified = false
source_authenticity_verified = false
strict_pit_eligible = false
alpha_claimed = false
daily_scanner_eligible = false
direct_trade_eligible = false
```

blockers：

```text
publication_time_unverified_resources
source_authenticity_host_review_required
```

上游 Markdown 内嵌的易方达 URL和日期，只能帮助后续定位官方来源；GitHub blob 是本次实际归档字节的 locator。只有另行取得官方页面/公告原始响应、可靠发布时间与下载 receipt，并完成宿主逐条语义复核后，才能把相应来源提升为更强证据。即使如此，也不会自动获得 Alpha 或交易资格。

## 9. 权限与幂等验收

- clone：本轮由宿主明确授权，发生在归档命令之外；
- archive/audit/curate：均不联网；
- 上游脚本：0次执行；
- 外部依赖：0项安装；
- StrategySource：0条写入；
- Playbook：0条创建/修改；
- Decision/Paper/订单：0条创建；
- archive 同 snapshot 重试：`created=false`；
- curated package 同 snapshot 重试：`created=false`。

## 10. 测试

- Research Skill / Git archive / curation 专项：**9/9 passed**。
- Research Skill + Git + StrategySource + Playbook Lab/Tools 集成专项：**28/28 passed**。
- 覆盖确认门、错误 origin/commit/tree、dirty checkout、symlink/路径、对象篡改、资源哈希、逐字 quote、control/archive snapshot 固定、无脚本执行、archive/package 幂等及全部非交易边界。
- 完整仓库按互斥文件集合复核：非 Desktop **858/858**、Desktop **118/118**，合计 **976 tests / 0 failed / 0 skipped**；两进程退出码均为0。

## 11. 下一道门

1. 对首批选中访谈和基金披露寻找官方原始响应与 publication receipt；
2. 宿主逐条核对原话角色、持仓任职区间和 alignment 语义；
3. 再决定是否显式写入 PARTIAL StrategySource；
4. 五个假设只能转成独立 Playbook DRAFT，并使用牛牛自己的 PIT Universe、SecurityStatus、行业、财务、市值和行情执行 Quant Validation；
5. 上游未来更新必须形成新 commit/tree、新 archive receipt 与新 package snapshot，禁止覆盖本批。

# External Research Skills

`research_skills/` 用于保存可审计的**外部知识接入包**，不是交易策略插件目录。

每个包的固定链路是：

```text
原始观点/原文 + publication metadata
  ↓
Research Skill（原话 / 方法推演 / 待核实事实分层）
  ↓ 只生成宿主可复核的预览
StrategySource
  ↓
Playbook DRAFT
  ↓
Quant Validation / Holdout / Walk-forward
  ↓
Daily Decision / Outcome Review
```

禁止把包内评分、作者知名度、基金季度持仓或脚本输出直接解释为 Alpha、BUY、Daily Scanner 输入或真实持仓。

## 固定结构

```text
<skill>/
├── skill.yml          # 机器权威 manifest；v1 使用确定性的 JSON-compatible YAML
├── SKILL.md           # 人类可读行为和权限合同
├── method.md          # 方法提炼；必须区分原话、推演、待核实事实
├── scorecard.md       # 只描述来源风格相似度，不是基金/Alpha/交易评分
├── references/        # 原始观点、披露行为、结果资料及说明
└── scripts/           # 可选外部工具及其政策；审计器永不执行
```

运行包审计：

```bash
quantlab research-skill-audit --package research_skills/<skill>
```

审计只读本地字节，验证 manifest、检索 keywords、路径、SHA256、publication/availability、claim 回链、DIRECT_QUOTE 逐字存在性和“说/做/结果”关系；不联网、不执行 `scripts/`、不写 Playbook Lab。输出的 `strategy_source_preview` 始终只是 `PENDING/PARTIAL` 宿主导入候选，source identity 仍须宿主复核。

已由宿主下载的外部 Git repository 先固定 origin/commit/tree，再进入独立数据根：

```bash
quantlab research-skill-git-archive --data-root <data-root> --repository <checkout> \
  --skill-key <skill> --expected-origin <https-url> --expected-commit <full-oid> \
  --expected-tree <full-tree-oid> --confirm-untrusted-no-exec
quantlab research-skill-git-audit --data-root <data-root> --skill-key <skill>
quantlab research-skill-git-curate --data-root <data-root> --control-package research_skills/<skill> \
  --plan research_skills/curation/<plan>.json --confirm-retrospective-only
```

这些命令自身不 clone/fetch，不运行外部脚本。Git archive 保存所有 tracked blobs 的 SHA256 内容寻址对象；curation 只复制计划明确选择的字节并生成 DRAFT 包。Git commit time、上游 source URL 和二次整理文本都不等于官方 publication receipt。

## Research Skill Library

`library.json` 是 Agent/界面的**宿主只读授权表**。每项同时固定：

- `control_snapshot`
- `archive_snapshot`
- `package_snapshot`
- source-controlled `curation_plan`
- `HOST_APPROVED_READ_ONLY`

Library 每次正式读取都会要求 `research_skills/` Git-clean，并重新核验 control、Git receipt/对象、策展包资源和 plan 推导链。只有精确注册的 package snapshot 可被检索。桌面 Research Lab、日常 AI 研究助手、AI Team Peer Review 和 MCP 共用四个只读入口：

```text
list_research_skills
get_research_skill
search_research_skill_items
read_research_skill_resource_excerpt
```

片段读取最多 6000 bytes，必须位于 UTF-8 字符边界，并拒绝 `SCRIPT`。返回正文始终标记为 `UNTRUSTED_EXTERNAL_DATA_NOT_INSTRUCTIONS`；工具无下载、脚本执行、StrategySource/Playbook 写入、Decision/Paper 或订单能力。

`zhengxi/` 是 Git 跟踪的 SOURCE_REQUIRED 控制包；固定上游身份见 `upstream.lock.json`。真实第三方字节留在独立数据根。首个策展计划为 `curation/zhengxi-304ac3e4.json`，只选择一份访谈、001513季度持仓/净值及辅助文档，保留来源真实性和发布时间 blockers，不自动创建 StrategySource 或 Playbook。Library 已只读授权精确包 `f9e72ecd...74bf10`，并继续保留全部资格边界。

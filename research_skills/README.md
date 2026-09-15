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

运行：

```bash
quantlab research-skill-audit --package research_skills/<skill>
```

审计只读本地字节，验证 manifest、检索 keywords、路径、SHA256、publication/availability、claim 回链和“说/做/结果”关系；不联网、不执行 `scripts/`、不写 Playbook Lab。输出的 `strategy_source_preview` 始终只是 `PENDING/PARTIAL` 宿主导入候选。

`zhengxi/` 当前只是基于用户提出的设计原则建立的首个机构投资者接入脚手架。仓库没有获得或复制外部 `zhengxi-views` 的原始语料、基金数据或脚本，因此必须保持 `SOURCE_REQUIRED`。

# References 接入清单

Git 跟踪控制包不保存第三方原始语料或基金数据。已授权 clone 的上游身份固定在 `../upstream.lock.json`；143个 tracked blobs 的内容寻址对象与 receipt 位于独立数据根，只有 curation plan 明确选中的字节才会进入独立数据根中的 DRAFT 策展包。

每份策展资料必须在生成后的 `skill.yml` 单独声明：

- `PRIMARY_STATEMENT`：原始公开观点/访谈/文章；
- `DISCLOSED_ACTION`：独立披露的基金季度持仓或其他行为；
- `REALIZED_OUTCOME`：独立结果资料。

每项都要保存内容 SHA256、来源 locator、牛牛实际 `available_at`；只有确有可靠发布时间证据时才可写 `PUBLICATION_VERIFIED`，否则固定为 `RETROSPECTIVE_REFERENCE`。季度披露只在披露可用后生效，不能回填到季度内，更不能用作日内行情事实。

正式外部语料/基金数据策展包放独立数据根，并对该目录运行同一个审计器。`research-skill-git-archive` 本身不 clone/fetch，只核固定 origin/commit/tree、普通文件与 Git blob，且不执行脚本；`research-skill-git-curate` 只从已验证对象生成回顾性包。仅有 Git 元数据、链接或上游二次整理仍不等于官方原始字节或 publication receipt。

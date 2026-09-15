# References 待接入清单

当前没有原始语料或基金数据文件。

未来每份资料必须在 `skill.yml` 单独声明：

- `PRIMARY_STATEMENT`：原始公开观点/访谈/文章；
- `DISCLOSED_ACTION`：独立披露的基金季度持仓或其他行为；
- `REALIZED_OUTCOME`：独立结果资料。

每项都要保存内容 SHA256、来源 locator、牛牛实际 `available_at`；只有确有可靠发布时间证据时才可写 `PUBLICATION_VERIFIED`，否则固定为 `RETROSPECTIVE_REFERENCE`。季度披露只在披露可用后生效，不能回填到季度内，更不能用作日内行情事实。

正式外部语料/基金数据包优先放独立数据根，并对该目录运行同一个审计器；若仅在仓库开发机临时组包，原文放 Git 忽略的 `references/source_raw/` 且仍须在本机 manifest 逐项声明。v1 只读取 package 内普通文件，不跟随 symlink，也不把外部绝对路径伪装成已归档资源。仅有链接或二次摘要不算已接入原始资料。

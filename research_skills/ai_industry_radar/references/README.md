# References 接入清单

Git 跟踪控制包不保存第三方原始语料。已授权 clone 的上游身份固定在 `../upstream.lock.json`；164 个 tracked blobs（含 4 个空文件）的内容寻址对象与 receipt 位于独立数据根，只有 curation plan 明确选中的字节才会进入独立数据根中的 DRAFT 策展包。

首个策展计划只选择：

- `PRIMARY_STATEMENT`：视频二精校逐字稿（二次转写，经同音错字校勘）；
- `DOCUMENTATION`：视频二原始 ASR 转写、校勘说明与错词表、雷达仓库 README、系统复刻与演进说明、手写产业链配置示例、GPL-3.0 许可证文本。

所有证据资源固定为 `RETROSPECTIVE_REFERENCE`：`available_at` 只是牛牛取得字节的时间。视频发布时间、博主身份和原始音视频字节均未取得，不能写成 `PUBLICATION_VERIFIED`。上游应用代码、`scripts/` 与测试只作为未经信任的 Git blob 留在对象库，不进入策展包。

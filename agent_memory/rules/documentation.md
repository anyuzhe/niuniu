# 文档治理

普通文档统一从 `docs/README.md` 进入；当前状态只维护 `docs/project/status.md`，稳定架构维护 `docs/architecture/overview.md`，开发事件追加 `docs/project/changelog.md`。

根目录只保留 README.md、README.en.md、AGENTS.md 三个 Markdown 入口。普通小修改更新既有主题文档，不新增“最新版/本轮收尾/最终版”；大型阶段验收才放 `docs/archive/<主题>/` 并标日期。

历史验收中的测试、数量和未完成项只属于记录时点。当前使用说明应依据源码与实际验证更新，不能用后来状态覆盖历史证据。

`agent_memory/`、`playbooks/`、`research_skills/`、第三方来源与许可证不随普通文档移动。机器授权/内容指纹不得因排版整理失效。Markdown 不覆盖结构化证据，也不批量改写历史 artifacts/MQC 来源路径。

迁移必须保留可追溯映射、复核本地链接，并运行 `scripts/check_docs.py` 与 `git diff --check`。本文件不扩大任何 Research Agent 或 Developer 的权限；提交和发布继续遵循既有规则。

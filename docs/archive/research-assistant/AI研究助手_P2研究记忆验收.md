# 牛牛 AI 研究助手：P2 结构化研究记忆

> 历史归档（整理于 2026-09-17）：保留原阶段记录；正文中的“当前、下一步、待完成”和测试/数据数字属于原记录时点。使用与当前进度以 [文档导航](../../README.md)、[当前状态](../../project/status.md) 为准。命令仍从仓库根目录执行。

日期：2026-09-11。实施基线：`ac12962`。项目：`/Volumes/Lexar/niuniu`。

## 本轮交付范围

本轮完成 P2 的核心：与聊天分开的研究假设、带实际归档证据的结论草稿、修订链、检索、当前来源复核，以及聊天工具和桌面读取入口。不把它称为全部研究知识管理、自动因子追踪或新因子工厂已完成。

此前 P1A/P1B 共46个文件已提交为 `ac12962d4cd5e6a4e5021c051cbdee246b7f635a` 并推送至既有 `origin/main`，远端提交号已核对。本轮 P2 单独形成后续提交，实验产物和个人研究记忆不上传 Git。

## 已实现

| 能力 | 实际行为 |
|---|---|
| 研究假设 | 绑定真实注册因子、版本和规范化参数，保存机制与可证伪条件 |
| 结论草稿 | 关联假设，保留支持、反对、无定论、不可检验和实现失败分类 |
| 实际证据 | 只接受 run_id、JSON Pointer、关系；字段值由程序从原归档读取 |
| 来源上下文 | 保存股票、区间、周期、参数、复权、快照和实验状态，不省略口径 |
| 修订 | 新记录引用 supersedes；旧记录不覆盖，冲突分支被拒绝 |
| 检索 | 中文文本、类型、因子、结论分类、分页和是否包含旧版本 |
| 复核 | 每次详细读取检查原归档SHA256、字段值和当前因子定义 |
| 模型写入 | 同一轮重复保存相同内容使用稳定请求编号；不创建研究任务 |
| 桌面 | 顶栏研究记忆入口、旧/新版本跳转、来源核对与打开实际实验 |

所有解释均保存为 `review_state=draft`、`claim_verified=false`。`source_integrity=verified` 仅表示引用与当前归档一致，不表示统计假设、文字解释、机制或未来盈利已获验证。

## 数据存储与权限

数据位于当前产物目录 `_assistant/research_memory.sqlite3`，与会话及原数值归档分离。使用SQLite事务和唯一请求号保证写入幂等，接口只追加研究记录，不提供删除或覆盖。

只读检索不会创建空数据库。记录请求不得携带任意文件路径；引用通过当前工作空间的实验UUID解析。数据、旧实验、Codex全局配置和模型连接设置未被此模块修改。

来源被修改时返回 `source_changed`，来源被移走或无法核验时返回 `unavailable`，保存的旧数值保持不变。空指标仍为null，不填零；仅有失败状态或空值不能创建“支持/反对”的数值结论草稿。

## 工具与使用

聊天新增5项工具，总计14项（配置行情目录时）：`record_hypothesis`、`record_finding`、`search_research_memory`、`get_research_memory`、`inspect_research_evidence`。不增加批准、直接执行、Shell或交易工具。

可以对助手说：

> 先检索已有的动量研究记忆。把已有真实实验的5根Rank IC整理为结论草稿，关联相应假设，写清适用样本、反对证据和下一步。只保存笔记，不执行研究。

> 在新会话中找回之前的动量结论，核对来源是否仍一致；若已改变，不要继续沿用旧结论。

> 查看该结论旧版本，保存一份新修订，不覆盖原记录。

桌面重启后使用顶栏“研究记忆”。主工作台的内置研究助手也支持点击实际memory引用进入对应记录。独立启动助手时也可通过其主工作台顶栏进入记忆面板。

额外提供统一记忆CLI（旧查询CLI仍保留）：

```bash
.venv/bin/python -m quantlab.agent.memory_cli --output artifacts --schemas
.venv/bin/python -m quantlab.agent.memory_cli --output artifacts --call search_research_memory --arguments '{"query":"动量","kind":"","factor_id":"","status":"","include_superseded":false,"offset":0,"limit":10}'
```

## 自动化验收

全仓 `QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -q`：458项通过，0失败、0跳过，比本轮基线新增18项。日志：`artifacts/agent-memory-20260911/full-tests.log`。

覆盖：重复请求与冲突、四线程首次并发保存、空库只读、Unicode检索、失败归档、空指标、非法字段与UUID、注入值拒绝、来源改动/删除、损坏记忆、隔离工作空间、旧版本与冲突修订、跨会话读取、Qt迟到回调隔离和具体memory引用跳转。

初轮并发测试发现第二个请求可能看到尚未提交表结构的新数据库；现已修复，后续事务会等待并再次核对请求号。保留初轮失败日志，没有放宽该测试断言。

## 真实 Codex 与真实研究归档验收

`codex_cli / gpt-5.5` 已完成两段全新会话、两个独立Python进程的验证。

第一段真实调用 `describe_factor → inspect_research_evidence → record_hypothesis → record_finding`，只保存一个假设和一个无定论结论草稿。第二段新会话调用 `search_research_memory → get_research_memory → inspect_research_evidence`，按标题找到同一结论，再与原字段核对。第二段没有带入第一段聊天上下文。

引用来源为既有六股十年真实前复权研究归档的字节一致副本，不是本轮重新回测。源run：`bd322f8b-4a14-49ff-857f-d4a072fa04ed`；字段 `/metrics/5/rank_ic`；值 **0.0035311265761560915**。因子为 `BASE.MOMENTUM 1.0.0`，lookback=20，研究请求2016-09-04至2026-09-04，日线，指定股票池。

假设ID：`d8962894-42fb-4766-a09c-e43d38aecc04`。结论ID：`e9180438-654f-4ce8-9a5f-f73b9e971379`。记忆仍为两条，结论为inconclusive草稿。原归档及副本SHA256一致且未改变，新增研究job数量为0。

验收工作空间：`artifacts/agent-memory-20260911/real-memory-fd3df362-df83-4f5c-835d-57701db29e8c`；完整证据见 `live-memory-acceptance.json` 与 `live-memory.log`。这些测试记忆没有放入正常 `artifacts/_assistant` 记忆库。

## 当前边界与后续顺序

目前假设必须绑定已注册因子；检索为结构化过滤和文本匹配，不含论文/RAG向量库、跨工作空间聚合、自动历史实验批量归纳或用户偏好库。未提供结论人工认证工作流，所有解释保持草稿。证据关系的语义相关性与统计解释仍需审查。

单记录最多8个证据字段；单字段8KiB、单完整记录128KiB、单源归档128MiB；记忆总数上限10000。超过预算明确拒绝，不丢弃失败项。来源SHA256是本地完整性核对，不是第三方签名或篡改防护证明。

GUI验证是隔离Qt功能测试，不冒称全套原生人工点击验收。没有新增依赖，没有改动因子公式、交易规则、原行情、全局Codex配置或现有模型设置。

下一步按路线进入有限研究包编排与登记；追踪、跨交易日水位、模型自动生成新算法仍未完成。新代码改变运行指纹后，旧待批提案可能需重新生成；不绕过原有批准时的环境一致性校验。

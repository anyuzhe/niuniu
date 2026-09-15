# Research Session Grant

Research Session Grant 是宿主显式授权的**有限自主研究沙箱**，不是通用 Agent 权限，也不是自动交易授权。

## 固定边界

- Grant 只能由宿主预览、确认、创建和撤销；模型没有 authorize/revoke 工具。
- Grant 精确绑定 output、data_root、代码/依赖 runtime、有效期和预算。
- v1 只允许本地已有数据；禁止 Shell、联网下载、代码写入、Dev Studio、Broker、真实订单和资金操作。
- v1 禁止 Campaign、Execution、Theory/Context；只允许显式证券池和白名单 `factor_id@version`。
- 证券、日期、K线周期、复权口径、qualification、mode、factor 都不得超出宿主授权范围。
- 每个授权任务必须 `replay=true`，并在入队前使用 Approval Input Freeze 冻结实际研究输入。
## 预算与生命周期

- 任务数、并行任务数、单任务叶子研究、总叶子研究、总 K 线评价量、总重采样量和单任务合作式时限都有硬上限。
- 失败、取消和被 Grant 撤销的任务仍消耗已预留预算；禁止通过反复失败/重试筛显著结果。
- request_id 由宿主从对话 turn + spec 确定性生成，模型不能利用自定义 ID 绕过幂等与预算。
- Grant 撤销/过期后：禁止新任务；运行任务在下一个 cooperative checkpoint 取消。
- 有未终止任务时不得用新 Grant 覆盖旧 Grant；旧 Grant 在安全切换前归档到 history。
- JobQueue 必须仍是宿主共享的唯一队列，不允许 Session Grant 创建第二 worker 或第二任务状态源。

Grant 只表示“允许在这些边界内做研究”，不表示研究结果正确、Alpha 成立，更不表示实盘权限。

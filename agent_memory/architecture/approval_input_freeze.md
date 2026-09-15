# Approval-time Actual-byte Freeze

宿主批准研究 Proposal 时，必须先冻结该次执行实际使用的规范化输入字节，再把 Proposal 标记为 approved / submitted。

- 权威目录：`_approval_input_freezes/<proposal_id>/`；一个 Proposal 对应一个 append-only 冻结包。
- 冻结内容覆盖主行情、Context、高精账户模式所需 qfq/raw 双价格输入，以及 Universe eligibility mask。
- Campaign 各 node 共享同一 approval bundle，但 manifest 保留 node/role 关联；Holdout/Walk-forward 可从已冻结的大区间只读切片。
- 冻结包保存源 `DataSnapshot` 身份与原文件校验信息，同时对冻结 Parquet/Universe 文件保存独立 SHA256。
- 执行产物继续保留原 provider / adjustment 语义；`approval_time_frozen=true` 放在文件元数据与 approval receipt 中，不伪造新的行情来源口径。
- 原数据在批准后变化、下线或目录暂时不可用，不改变已批准任务；submit/resume/run 必须读取同一冻结包。
- 冻结文件、manifest、spec digest 任一变化都必须 fail-closed；不能回退到 live data。
- 模型只能 propose / query，不能 approve、创建/替换冻结包或修改 JobQueue guard。
- 旧的 direct JobQueue / tracking `input_signature` 合同继续保留；只有走 Proposal host approval 的任务获得 approval-time actual-byte freeze。
- 旧 approved Proposal 若没有冻结包，不允许静默升级执行，必须重新生成 Proposal 并重新批准。
- System Health 只做冻结包 manifest/文件存在性轻量检查；提交、恢复、执行前后才做完整 SHA256 校验。

这条规则解决的是“批准 A、执行时数据变成 B”的证据一致性，不代表 Strict PIT 原始资料本身已经完整，也不替代研究结果复算归档。

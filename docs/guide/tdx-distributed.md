# TDX 三机个人研究采集

[当前状态](../project/status.md) · [总体架构](../architecture/overview.md)

## 范围与数据合同

沿用原 TDX plan 和 scheduler-policy v2，不重新 prepare、不修改旧 Baostock 日线/5m。用途仍为 ELTDX Research-Only 许可下的个人非商业研究，不能用于行情转售、生产或自动交易。

主数据根是唯一 canonical coordinator；另建 Mac worker 0、HomePc worker 1、601 worker 2 的独立根。每根有自己的 SQLite/DuckDB，不能经 SMB/NAS 共享 writer。`sha256-utf8-symbol-mod-v1` 使用完整 SHA256 对规范证券代码取模。全市场公共任务只属 worker 0，opening_match 跟随同节点 trades 原样派生。

canonical 写入 coordinator role 后拒绝旧未分片的 run/resume。旧 STOP 保留。各 worker 安装 bootstrap 后也默认 STOP，需完成对应节点验收再显式启动。

## Bootstrap 与汇总

`tdx_distributed.py` 导出计划、完整交易日历、精确 policy/assignment、当前未完成 frontier 和必要的上一页原始证据；不传所有已采历史，不从头重下。同一个 bootstrap 重装不重置进度。安装逐页验证原始响应、Parquet 和请求/分片身份，只保留 manifest 常驻内存。

未提交页放 `_stored`，不进入正常视图。SAVED 的持久提交先登记 pending_promotions，再完成文件发布；重启按相同字节恢复。EMPTY 是该精确请求的空响应，不是全历史为空。

结果包包含递增 sequence_no。Mac 在所有页验证通过、分页前驱与开盘撮合父页核对完毕后才导入。source_id 相同而字节不同、错误分片、坏包均拒绝并 QUARANTINE；乱序包 DEFERRED，不能越过缺失包。重复包幂等导入。

`tdx_transfer.py` 只监听 127.0.0.1，必须处于既有、经过主机密钥核验的 SSH 隧道内。它不创建密钥、不开放公网端口、不传递命令。中继只转发流量，不落盘行情；不使用聊天/MCP 文本搬运行情包。

上传先写 .part、核对传输 SHA 后原子发布；传输成功不等于已入库。只有 canonical 的 MERGED 回执且 bundle_id/SHA/sequence_no/machine 全部一致，worker 才确认 ack 并删除传输副本。原始页和错误记录不删除。Bootstrap 下载支持 HTTP Range 续传并最终全文件 SHA 核对。

## 宿主命令

从代码仓库运行；Windows 使用 `.venv/Scripts/python.exe`，Mac 使用 `.venv/bin/python`。`DATA_ROOT` 必须明确是 canonical 还是对应 worker，不可混用。

```bash
python -m quantlab.agent.tdx_distributed_cli --data-root DATA_ROOT status
python -m quantlab.agent.tdx_distributed_cli --data-root WORKER_ROOT worker-status
python -m quantlab.agent.tdx_distributed_cli --data-root WORKER_ROOT stop

# 原 canonical 必须先 STOP；只建立一次 cluster。
python -m quantlab.agent.tdx_distributed_cli --data-root CANONICAL_ROOT --personal-research-only bootstrap --output EXCHANGE_DIR

# 必须使用 bootstrap 返回的真实 SHA。
python -m quantlab.agent.tdx_distributed_cli --data-root WORKER_ROOT --personal-research-only install --bundle BOOTSTRAP_TAR --sha256 EXPECTED_SHA256
```

先小规模显式 resume 验收，然后启动不清除停止标志的 worker service。每节点初始 2 workers、0.35 秒间隔不变。

```bash
python -m quantlab.agent.tdx_collection_cli --data-root WORKER_ROOT resume --personal-research-only --seconds 90 --max-requests 60 --max-new-gib 1

# Mac worker 本地汇总，依然经过同一套验证。
python -m quantlab.agent.tdx_worker_service --data-root MAC_WORKER_ROOT --canonical-root CANONICAL_ROOT --personal-research-only

# Windows 连接既有、已验证 SSH 本地转发端口。
python -m quantlab.agent.tdx_worker_service --data-root WINDOWS_WORKER_ROOT --server-url http://127.0.0.1:18943 --personal-research-only

# Canonical 文件接收/合并进程，不是未分片采集器。
python -m quantlab.agent.tdx_transfer --data-root CANONICAL_ROOT --exchange EXCHANGE_DIR --personal-research-only
```

worker service 单次最多 24 小时、200,000 顶层任务、默认新增 100 GiB，并保留 30 GiB。每轮有限采集后释放 writer、导出增量、发送和确认；未确认积压有容量保护。`STOP`/`AUTO_HALT` 永远优先；OS 计划任务只启动 service，不能带自动清除停止的 resume。Mac 用 LaunchAgent，Windows 用用户计划任务；实际安装/启动状态以每台回执为准，代码存在不是部署证明。

## 验收与平台范围

```bash
# Mac：采集核心 + 原生助手只读接线。
python scripts/test_tdx_worker.py --include-native-app
# Windows worker：独立采集、分片、原始页、汇总和传输。
python scripts/test_tdx_worker.py
```

portable-collector 明确打印不在该 profile 的单个原生完整应用接线测试；不是隐蔽跳过或宣称完整 Windows 客户端已移植。旧应用多个非采集模块依赖 fcntl，超出独立 worker 部署范围。Windows 路径安全测试在无 symlink 权限时创建真实 junction，验证数据根和内部路径拒绝重定向，不模拟通过或提升系统权限。

状态分开报告各 worker 的新采任务/原基线、待传包、canonical 已合并页和最近报告时间。RECENT_REPORT 不自动等于进程 ONLINE；进程需本机证据。canonical 原待采任务已委派，不再作为另一组可运行队列累加。快照时间、股票数、单周期请求速度都不能代替全历史资格；history_complete 始终为 false，直到全部范围、页链和错误另行审计。

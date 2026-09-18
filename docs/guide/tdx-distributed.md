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

## 2026-09-18 实际部署位置与限制

| 节点 | 代码根 | worker数据根 | 分片证券数 | 本轮部署结果 |
|---|---|---|---:|---|
| Mac | `/Volumes/Lexar/niuniu` | `/Volumes/Lexar/niuniu-data/workers/worker-0` | 1951 | 已安装、真实续采/幂等汇总/STOP验收，LaunchAgent已启动 |
| HomePc | `E:\testData\niuniu` | `E:\testData\niuniu-data`（已选定，未安装） | 1953 | 69项worker测试通过；现有SSH未获中继认证 |
| 601 | `D:\AI\testData\niuniu` | `D:\AI\testData\niuniu-data`（已选定，未安装） | 1905 | 69项worker测试通过；计划任务权限失败，隧道工具启动被安全检查拦截 |

canonical仍为 `/Volumes/Lexar/niuniu-data`。三份已生成bootstrap存于 `automation/tdx-exchange/bootstraps/fbe957f355eb036c497981e5cb73e5be88743db715bb9c3ab2e9277092c42046/`。Windows未有任何正式下载，不应把未报告状态解释成0错误或已完成。

Mac新采集服务名为 `com.anyuzhe.niuniu.tdx-worker0`，使用同一代码仓库及隔离eltdx运行环境。旧 `com.anyuzhe.niuniu.tdx-autoresume` 已卸载、原plist保存在数据根 `automation/tdx-exchange/launchagents/legacy-tdx-autoresume.plist`，不可重新启用旧全量入口。新worker每次用户登录后加载，停止标志优先；没有声称未登录系统阶段也会运行。

```bash
cd /Volumes/Lexar/niuniu

# 新worker的持久停止；不应再对canonical旧tdx.sh执行resume。
.venv/bin/python -m quantlab.agent.tdx_distributed_cli --data-root /Volumes/Lexar/niuniu-data/workers/worker-0 stop

# 只读查看新worker或总汇总状态。
.venv/bin/python -m quantlab.agent.tdx_distributed_cli --data-root /Volumes/Lexar/niuniu-data/workers/worker-0 worker-status
.venv/bin/python -m quantlab.agent.tdx_distributed_cli --data-root /Volumes/Lexar/niuniu-data status
```

Mac日志位于 `automation/tdx-exchange/logs/com.anyuzhe.niuniu.tdx-worker0.*.log`，新worker心跳在自己的 `lake/bronze/provider=tdx/progress.json` 与 `_service/state.json`。协调库的旧progress不是worker 0的实时进度。外部节点的数据通道尚未建立；闲置reverse SSH已关闭，未因安全拦截改走其他启动方式或增加服务器权限。

### Windows 当前用户监督入口（后续部署增量）

`scripts/tdx_windows_worker.py --config LOCAL_CONFIG_JSON` 只运行独立worker；配置须绑定机器、分片、cluster和本地代码/数据/控制路径。当前用户运行，不提升Windows权限。启动前检查SUPERVISOR_STOP、worker STOP/AUTO_HALT；缺bootstrap不连接网络。监督器具有独立单实例锁，仅管理自己创建的子进程，worker仍沿原断点、预算、outbox和确认回执运行。

2026-09-18后续授权下，中继增加独立tdx-transfer账号，仅公钥认证、禁止Shell/PTY/Agent转发、禁止远端及Unix socket转发，只允许到127.0.0.1:18943的本地转发。两台现有公钥原地使用，未复制私钥；旧root与ollama-tunnel的effective sshd配置逐值比较不变。601的新作用域隧道获得WebCodex Job并完成health身份检查，bootstrap仍须传完并逐页安装后才能验收。

HomePc的新隧道启动调用仍被平台安全检查阻止，没有Job/PID；不得用计划任务或监督器代为启动同一被拒绝的隧道。其allow_tunnel_start固定为false，仅允许操作员本机启动已提供的Start-TDX-Transfer-Manual.cmd；原生监督器保留WAITING_FOR_OPERATOR_TUNNEL状态。准备好脚本/账号不是节点已经上线，实际启动和数据验收另记。

### 远端分页校验凭据（保留主库原始页）

慢速中继不必重复运送数千份仅用于检查前驱的原始/Parquet副本。`tdx_checkpoint_witness.py` 从原bootstrap精确SHA和逐页raw/Parquet/manifest SHA核验后，派生版本化凭据：原请求身份、行数、source_id、各原文件SHA与剔除index/absolute_index后的整页内容摘要。整个凭据包再以独立SHA固定，同时绑定原bootstrap SHA、原计划/策略/分片及全部原frontier。

仅在frontier不含尚需重放的已保存chunk时允许此模式；存在未完成页字节时仍要求原完整包。凭据只存worker队列独立表和冻结checksum清单，CHECKPOINT不进入任何正常行情视图，不被export当作新数据。缺凭据、被重签的伪凭据、错分片、重复页和断开的offset仍拒绝。真实回传的SAVED/EMPTY页继续由canonical读取其实际前驱原始页重新核验；不是以worker摘要代替主库的源字节审计。

两份真实包由原910,673,920/876,800,000字节降至4,763,945/4,606,132字节；原包和主库源文件保留。接收仍使用原loopback HTTP/Range/SHA通道，不经聊天搬运行情。安装函数为`install_witness_bootstrap(destination, path, expected_transfer_sha, expected_original_bootstrap_sha)`，同一包重装不重置进度。核心新增10项保护及锁竞争等待测试；跨节点本地汇总抢占writer锁时保留outbox并等待，不把它当内容冲突。

文件服务采用HTTP接收与单独合并线程，避免逐页校验/写库期间阻塞新health和receipt请求。合并线程仍只有一个且遵守canonical writer lease；文件已上传不等于MERGED。遇到网络超时保留同一outbox和sequence，再查询/发送同一包，不重新采集或重新导出替代版本。`EXCHANGE_DIR/SYNC_STOP` 请求文件服务优雅结束；错误回执绝不当确认。

### Windows 长期运行改为离线采集

用户于2026-09-18明确要求Windows不要边采边回传Mac。当前长期配置因此使用`offline_only=true`：计划任务只启动各自独立worker的`tdx_collection_cli autoresume`，不启动SSH、不检查Mac health、不导出每轮结果包。每个worker继续使用自己的SQLite、page lake、STOP/AUTO_HALT和30GiB磁盘保护；Mac canonical不会被Windows长跑直接写入。

完成后采用物理介质一次性交接：先保持worker停止，复制完整worker数据根或在该副本上批量`export`，再在Mac按原sequence/source_id/SHA/前驱页规则逐批`import`。因此“最后一次搬盘”只改变运输方式，不降低校验门槛，也不把未确认页直接复制进canonical视图。

601的D盘当前空间足以开始长期离线采集。HomePc的E盘只有约382GiB空闲，按随机历史成交日抽样（完整日均约2.39个请求、约96KiB逻辑文件）估计完整分片很可能超过当前单盘容量；它可以先安全运行，达到30GiB保留阈值会AUTO_HALT。要完成该分片，需要后续接入约1TiB级外接盘或重新分配部分工作，不能通过关闭磁盘保护来硬写满系统。

# 牛牛 AI · 个人 A 股交易研究助手

**简体中文** | [English](README.en.md) | [文档导航](docs/README.md)

<p align="center"><img src="src/quantlab/desktop/assets/niuniu_mascot_banner.png" alt="牛牛 AI" width="480"></p>

牛牛把多来源交易知识转为可版本化的规则和假设，通过数据验证、每日扫描、AI 研究、决策留证和模拟复盘形成研究闭环。原有因子、理论实验和成交回测内核继续保留在 Research Lab。

**当前是研究与模拟系统，不是已开放的自动实盘交易系统。** 研究结论、Decision、Strategy Intent 和真实成交不能混为一谈；工程测试通过不证明策略具有 Alpha。

## 从哪里开始

| 你要做什么 | 入口 |
|---|---|
| 启动软件、了解页面、走通一次研究 | [使用指南](docs/guide/user-guide.md) |
| 查看现在完成了什么、还有什么没完成 | [当前状态与后续路线](docs/project/status.md) |
| 了解数据目录、复权、PIT 与证据边界 | [数据与证据说明](docs/guide/data-and-evidence.md) |
| 配置 MCP、跟踪与日常研究任务 | [运行与运维](docs/guide/operations.md) |
| 继续开发或让 Agent 接手 | [AGENTS.md](AGENTS.md) → [开发与文档规范](docs/development/contributing.md) |
| 了解模块和查找源码 | [总体架构](docs/architecture/overview.md) → [代码地图](docs/development/code-map.md) |
| 追溯一次修改、规则或验收 | [开发史](docs/project/changelog.md) / [规则参考](docs/reference/README.md) / [历史归档](docs/archive/README.md) |

## 本机启动

在当前 Mac 的 `/Volumes/Lexar/niuniu` 中双击：

- `启动牛牛平台.command`：完整桌面工作台。
- `启动牛牛AI研究助手.command`：AI 对话助手。

这两个入口使用本项目 `.venv`，数据根为 `/Volumes/Lexar/niuniu-data`，实验和工作空间输出为项目内 `artifacts/`。旧 `MQC-DATA` 及历史产物中的来源路径不在本轮迁移范围内。

新环境需要 Python 3.11+；在仓库根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[desktop]"
quantlab desktop --data-root /path/to/niuniu-data --output ./artifacts
```

Windows PowerShell 用 `.venv\Scripts\Activate.ps1` 激活环境。CLI、数据和 MCP 可选依赖见 [安装说明](docs/guide/user-guide.md) 与 [pyproject.toml](pyproject.toml)。

## 核心能力

| 层 | 功能 |
|---|---|
| Trading Desk | 今日交易、主题、股票档案、Decision、策略意图、Paper 与复盘 |
| AI Team | Chief、Scanner、Skeptic、Quant Researcher；独立研究后综合，保留分歧 |
| Trading Knowledge | 多类 StrategySource、Playbook、Git-first 规则和只读外部 Research Skill |
| Research Lab | 因子/理论、事件研究、样本外验证、统计、执行回测、Campaign、Watch |
| 打板与情绪研究 | 涨停事件、市场情绪、题材、公开证据、预测校准、受限自主研究和简报 |
| 系统与开发 | 数据与 PIT、任务队列、MCP、System Health、隔离 Dev Studio、只读移动入口 |

个股问答的实时报价代码已实现（**扶摇主源 + 公开网页共识交叉校验/回退**），但按 DATA → CODE 数据清单，`realtime_quote`、`fuyao_context` 目前为 `REVIEW_REQUIRED`，所以**当前未启用**；DATA 标为 `READY` 后才会开启，届时是否用扶摇还取决于宿主凭证配置。临时报价不是正式 MarketSnapshot，更不自动获得 Strict PIT 或交易权限。详见 [数据与证据说明](docs/guide/data-and-evidence.md)。

## 目录约定

```text
niuniu/
├── README.md / README.en.md   项目入口
├── AGENTS.md                 开发 Agent 入口
├── docs/                     人类文档：当前说明、规则、历史
├── src/quantlab/             产品源码（包路径保持不变）
├── tests/                    自动化测试
├── examples/                 参数示例与历史验收脚本
├── agent_memory/             运行时读取的 Git-first 工作记忆
├── playbooks/                可被机器校验的交易规则包
├── research_skills/          外部知识控制包与只读授权表
└── artifacts/                本机运行产物，不提交 Git
```

不要为了整理文档而搬动 `agent_memory`、`playbooks`、`research_skills`、许可证或包资源。历史方案和验收不再作为“最新使用说明”，新增说明请按 [文档规范](docs/development/contributing.md) 维护现有主题文档。

## 许可与来源

项目自身尚未另行声明统一开源许可证。第三方来源及授权分别见 [缠论来源记录](src/quantlab/_vendor/chanpy/PROVENANCE.json)、[缠论许可证](src/quantlab/_vendor/chanpy/LICENSE)、[Alpha 来源与限制](src/quantlab/factors/ALPHA_PROVENANCE.md) 和 [Alpha 上游许可证](src/quantlab/factors/ALPHA_LICENSE)。第三方许可证不自动授权整个项目。

import argparse
import sys
from contextlib import redirect_stdout
import json
from datetime import date
from pathlib import Path

from quantlab.data.universe import UniverseConfig
from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.portfolio import PortfolioConfig
from quantlab.experiments.execution import ExecutionStudy
from quantlab.experiments.theory_study import TheoryStudyPlan, TheoryStudyRunner
from quantlab.app import build_runner, default_registry
from quantlab.data.base import DataRequest
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.ablation import AblationRunner
from quantlab.experiments.holdout import ChronologicalSplit, HoldoutRunner
from quantlab.experiments.walkforward import WalkForwardConfig, WalkForwardRunner
from quantlab.regime.config import RegimeConfig, RegimeFilter
from quantlab.storage.codec import encode
from quantlab.statistics.bootstrap import BootstrapConfig
from quantlab.statistics.permutation import PermutationConfig
from quantlab.processing.cross_section import CrossSectionConfig
from quantlab.multitimeframe.config import DailyContextConfig
from quantlab.experiments.sweep import ParameterGrid, SweepRunner
from quantlab.experiments.correlation import CorrelationConfig, CorrelationRunner
from quantlab.experiments.correlation_holdout import CorrelationHoldoutRunner
from quantlab.experiments.correlation_walkforward import CorrelationWalkForwardRunner
from quantlab.theory.templates import templates, resolve_template


def main() -> None:
    parser = argparse.ArgumentParser(description="统一技术交易因子研究内核")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("factors", help="列出已注册因子")
    commands.add_parser("theories", help="列出版本化研究模板及概念映射")
    workbench = commands.add_parser('serve',help='启动本地研究工作台；指定数据目录以启用实验执行')
    workbench.add_argument('--output',type=Path,default=Path('artifacts'))
    workbench.add_argument('--port',type=int,default=8765)
    workbench.add_argument('--data-root',type=Path,help='启用实验执行的 MQC 只读数据目录')
    desktop = commands.add_parser('desktop', help='启动牛牛 PyQt6 原生桌面平台')
    desktop.add_argument('--output',type=Path,default=Path('artifacts'))
    desktop.add_argument('--data-root',type=Path,help='MQC 只读行情目录')
    mcp_cmd=commands.add_parser('mcp',help='启动标准MCP服务；stdio或回环Streamable HTTP')
    mcp_cmd.add_argument('--output',type=Path,default=Path('artifacts'));mcp_cmd.add_argument('--data-root',type=Path)
    mcp_cmd.add_argument('--transport',choices=['stdio','streamable-http'],default='stdio')
    mcp_cmd.add_argument('--host',default='127.0.0.1');mcp_cmd.add_argument('--port',type=int,default=8766)
    daemon_cmd=commands.add_parser('tracking-daemon',help='常驻执行已经由宿主授权的跟踪计划')
    daemon_cmd.add_argument('--output',type=Path,default=Path('artifacts'));daemon_cmd.add_argument('--data-root',type=Path,required=True)
    daemon_cmd.add_argument('--poll-seconds',type=float,default=60);daemon_cmd.add_argument('--once',action='store_true')
    daemon_status_cmd=commands.add_parser('tracking-daemon-status',help='读取跟踪守护进程最后回执')
    daemon_status_cmd.add_argument('--output',type=Path,default=Path('artifacts'))
    launchd_cmd=commands.add_parser('tracking-launchd-write',help='生成但不加载macOS LaunchAgent配置')
    launchd_cmd.add_argument('--output',type=Path,default=Path('artifacts'));launchd_cmd.add_argument('--data-root',type=Path,required=True)
    launchd_cmd.add_argument('--path',type=Path,required=True);launchd_cmd.add_argument('--poll-seconds',type=float,default=60)
    correlate = commands.add_parser("correlate", help="因子截面相关矩阵及冗余分组，不计算收益标签")
    correlate.add_argument("--data-root", type=Path, required=True)
    correlate.add_argument("--output", type=Path, default=Path("artifacts"))
    correlate.add_argument("--symbols", nargs="+", required=True)
    correlate.add_argument("--timeframe", choices=[t.value for t in Timeframe], default="1d")
    correlate.add_argument("--start", type=date.fromisoformat, required=True)
    correlate.add_argument("--end", type=date.fromisoformat, required=True)
    correlate.add_argument("--adjustment", choices=["raw", "qfq"], default="qfq")
    correlate.add_argument("--inputs-json", type=Path, required=True)
    correlate.add_argument("--min-symbols", type=int, default=3)
    correlate.add_argument("--min-periods", type=int, default=5)
    correlate.add_argument("--cluster-threshold", type=float, default=0.8)
    correlate.add_argument("--question", default="所选因子的截面相似性与冗余分组")
    correlate.add_argument("--processor", choices=["cs_rank", "cs_zscore"])
    correlate.add_argument("--regime", action="store_true")
    correlate.add_argument("--regime-lookback", type=int, default=20)
    correlate.add_argument("--regime-baseline", type=int, default=20)
    correlate.add_argument("--regime-direction", choices=["Bull", "Bear", "Neutral"])
    correlate.add_argument("--regime-structure", choices=["Trend", "Range", "Transition"])
    correlate.add_argument("--regime-volatility", choices=["Low", "Medium", "High"])
    correlate.add_argument("--context-json", type=Path)
    correlate.add_argument("--train-end", type=date.fromisoformat)
    correlate.add_argument("--valid-end", type=date.fromisoformat)
    correlate.add_argument("--walk-forward", type=int, nargs=3, metavar=("TRAIN_DAYS", "VALID_DAYS", "TEST_DAYS"))
    correlate.add_argument("--bootstrap-resamples", type=int)
    correlate.add_argument("--bootstrap-block-days", type=int, default=5)
    correlate.add_argument("--bootstrap-confidence", type=float, default=0.95)
    correlate.add_argument("--seed", type=int, default=0)
    run = commands.add_parser("run", help="运行未扣成本的单因子研究实验")
    run.add_argument("--snapshot-manifest",type=Path,help="固定版本行情 manifest，替代 MQC 行情读取；元数据仍来自 data-root")
    run.add_argument("--data-root", type=Path, required=True)
    run.add_argument("--output", type=Path, default=Path("artifacts"))
    run.add_argument("--symbols", nargs="+", required=True)
    run.add_argument("--timeframe", choices=[t.value for t in Timeframe], default="1d")
    run.add_argument("--start", type=date.fromisoformat, required=True)
    run.add_argument("--end", type=date.fromisoformat, required=True)
    run.add_argument("--factor")
    run.add_argument("--theory", help="版本化研究模板 ID；展开为 COMB.CONDITION")
    run.add_argument("--theory-version", default="1.0.0")
    run.add_argument("--sequence-audit", action="store_true", help="保存序列及组合内序列输入的事件与状态日志")
    run.add_argument("--version", default="1.0.0")
    run.add_argument("--lookback", type=int)
    run.add_argument("--left", type=int, help="拐点左侧窗口")
    run.add_argument("--right", type=int, help="拐点右侧确认窗口")
    run.add_argument("--max-gap-seconds", type=int, help="序列相邻步骤的实际时间上限（不含端点）")
    run.add_argument("--params-json", type=Path, help="读取因子参数 JSON；组合规则也由此传入")
    run.add_argument('--incremental-test', action='store_true', help='组合消融的配对 IC 差异检验；需要 --ablate 和 --permutation-resamples')
    run.add_argument("--ablate", action="store_true", help="对组合逐个移除输入，使用共同样本比较")
    run.add_argument("--train-end", type=date.fromisoformat, help="训练段最后日期；与 --valid-end 同时使用")
    run.add_argument("--valid-end", type=date.fromisoformat, help="验证段最后日期，其后至 --end 为测试段")
    run.add_argument("--walk-forward", type=int, nargs=3, metavar=("TRAIN_DAYS", "VALID_DAYS", "TEST_DAYS"), help="按自然日长度滚动评估，测试窗口不重叠")
    run.add_argument("--horizons", type=int, nargs="+", default=[1, 5, 20])
    run.add_argument("--quantiles", type=int, default=5)
    run.add_argument("--adjustment", choices=["raw", "qfq"], default="qfq")
    run.add_argument("--question", default="基础因子在所选股票与周期上的预测统计")
    run.add_argument("--regime", action="store_true", help="记录市场状态")
    run.add_argument("--regime-lookback", type=int, default=20)
    run.add_argument("--regime-baseline", type=int, default=20)
    run.add_argument("--regime-direction", choices=["Bull", "Bear", "Neutral"])
    run.add_argument("--regime-structure", choices=["Trend", "Range", "Transition"])
    run.add_argument("--regime-volatility", choices=["Low", "Medium", "High"])
    run.add_argument("--bootstrap-resamples", type=int, help="启用日期分块 Bootstrap，至少 20 次")
    run.add_argument("--bootstrap-block-days", type=int, default=5)
    run.add_argument("--bootstrap-confidence", type=float, default=0.95)
    run.add_argument('--permutation-resamples', type=int, help='日均 IC 日期块符号置换，20–100000 次')
    run.add_argument('--permutation-block-days', type=int, default=5)
    run.add_argument('--permutation-alpha', type=float, default=0.05)
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--pipeline-json", type=Path, help="训练期处理流水线 JSON；OOS/滚动自动使用各训练段")
    run.add_argument("--processor", choices=["cs_rank", "cs_zscore"], help="标量因子的同一时点截面预处理")
    run.add_argument("--context-json", type=Path, help="日线背景因子、预热起点和筛选条件 JSON；仅用于 5m")
    run.add_argument("--sweep-json", type=Path, help="参数名到候选列表的 JSON；可与时序分段或滚动评估配合")
    for command in (run,correlate):
        command.add_argument('--universe',choices=['explicit','listing','pit'],default='explicit')
        command.add_argument('--min-listed-days',type=int,default=0)
    run.add_argument('--replay',action='store_true',help='保存 K 线及可用时间审计快照')
    run.add_argument('--backtest',action='store_true',help='独立下一根开盘成交模拟')
    run.add_argument('--execution-backend',choices=['open','vnpy_open','vnpy_rules'],default='open')
    run.add_argument('--market-rules',type=Path,help='带生效/可用/到期时间的逐证券交易规则 JSON')
    run.add_argument('--portfolio-json',type=Path,help='目标权重及风控配置 JSON')
    run.add_argument('--execution-json',type=Path,help='独立回测参数 JSON')
    run.add_argument('--theory-study-json',type=Path,help='组件/消融/OOS/滚动/敏感性全流程配置')
    residual=commands.add_parser('residual-alpha',help='训练期拟合控制因子投影，样本外检验候选因子残差 IC')
    residual.add_argument('--candidate',type=Path,required=True)
    residual.add_argument('--controls',type=Path,nargs='+',required=True)
    residual.add_argument('--train-end',type=date.fromisoformat,required=True)
    residual.add_argument('--horizon',type=int,default=1)
    residual.add_argument('--output',type=Path,default=Path('artifacts'))
    paper=commands.add_parser('paper-step',help='向持久模拟账户交付 K 线及目标权重快照；重复交付幂等')
    paper.add_argument('--follow',action='store_true',help='持续读取外部生产者更新的完整 Parquet/规则快照，Ctrl-C 停止')
    paper.add_argument('--poll-seconds',type=float,default=5)
    paper.add_argument('--account',type=Path,required=True)
    paper.add_argument('--bars',type=Path,required=True)
    paper.add_argument('--targets',type=Path,required=True)
    paper.add_argument('--market-rules',type=Path,required=True)
    paper.add_argument('--execution-json',type=Path)
    paper.add_argument('--backend',choices=['open','vnpy_rules'],default='open')
    inspect=commands.add_parser('paper-status',help='查看恢复后的模拟账户资金、持仓及游标')
    inspect.add_argument('--account',type=Path,required=True)
    for name in ('data-query','data-audit'):
        data_command=commands.add_parser(name,help='DuckDB 原始行情查询 / 指定范围质量审计')
        data_command.add_argument('--data-root',type=Path,required=True)
        data_command.add_argument('--symbols',nargs='+',required=True)
        data_command.add_argument('--timeframe',choices=['1d','5m'],required=True)
        data_command.add_argument('--start',type=date.fromisoformat,required=True)
        data_command.add_argument('--end',type=date.fromisoformat,required=True)
        data_command.add_argument('--output',type=Path,required=True)
        if name=='data-audit':
            data_command.add_argument('--snapshot-manifest',type=Path,help='审计不可变行情版本')
            data_command.add_argument('--calendar-file',type=Path,help='显式交易日历 Parquet，默认读取 data-root')
    coverage=commands.add_parser('data-coverage',help='历史规则及元数据来源覆盖清单')
    coverage.add_argument('--data-root',type=Path,required=True)
    coverage.add_argument('--output',type=Path,required=True)
    increment=commands.add_parser('return-increment',help='比较可比执行产物的样本外日净收益增量')
    increment.add_argument('--candidate',type=Path,required=True)
    increment.add_argument('--baseline',type=Path,required=True)
    increment.add_argument('--start',type=date.fromisoformat,required=True)
    increment.add_argument('--output',type=Path,default=Path('artifacts'))
    metadata=commands.add_parser('metadata-import',help='只读导入已有行业及分红来源，保留观测时间')
    metadata.add_argument('--data-root',type=Path,required=True)
    metadata.add_argument('--symbols',nargs='+',required=True)
    metadata.add_argument('--output',type=Path,required=True)
    feed=commands.add_parser('paper-mqc',help='读取持续更新的 MQC，计算因子和目标并交付模拟账户')
    feed.add_argument('--archive-root',type=Path,help='从该行情归档选择当前已观测版本，支持新增版本连续交付')
    feed.add_argument('--data-root',type=Path,required=True)
    feed.add_argument('--account',type=Path,required=True)
    feed.add_argument('--symbols',nargs='+',required=True)
    feed.add_argument('--timeframe',choices=[t.value for t in Timeframe],default='5m')
    feed.add_argument('--start',type=date.fromisoformat,required=True)
    feed.add_argument('--factor',required=True)
    feed.add_argument('--parameters-json',type=Path)
    feed.add_argument('--execution-json',type=Path)
    feed.add_argument('--portfolio-json',type=Path)
    feed.add_argument('--market-rules',type=Path,required=True)
    feed.add_argument('--backend',choices=['open','vnpy_rules'],default='open')
    feed.add_argument('--adjustment',choices=['qfq','raw'],default='qfq',help='模拟研究默认前复权；仅 price_mode=account 使用 raw 成交。原始归档须主动选择 raw')
    feed.add_argument('--follow',action='store_true')
    feed.add_argument('--poll-seconds',type=float,default=30)
    status=commands.add_parser('fetch-status',help='补存 Baostock 真实历史 ST/交易状态；不伪造历史可用时间')
    status.add_argument('--symbols',nargs='+',required=True)
    status.add_argument('--start',type=date.fromisoformat,required=True)
    status.add_argument('--end',type=date.fromisoformat,required=True)
    status.add_argument('--output',type=Path,required=True)
    reference=commands.add_parser('fetch-reference',help='归档 Baostock 指定日期行业、季度股本、历史ST/停牌；不伪造PIT发布时间')
    reference.add_argument('--symbols',nargs='+',required=True)
    reference.add_argument('--start',type=date.fromisoformat,required=True)
    reference.add_argument('--end',type=date.fromisoformat,required=True)
    reference.add_argument('--industry-dates',nargs='*',type=date.fromisoformat,default=[])
    reference.add_argument('--output',type=Path,required=True)
    reconcile=commands.add_parser('paper-reconcile',help='逐日重建模拟账户账本并核对现金/持仓/净值')
    reconcile.add_argument('--account',type=Path,required=True)
    reconcile.add_argument('--output',type=Path,required=True)
    dividends=commands.add_parser('dividend-import',help='规范化现金分红，保留事后获取时间及不支持的公司行动')
    dividends.add_argument('--data-root',type=Path,required=True)
    dividends.add_argument('--symbols',nargs='+',required=True)
    dividends.add_argument('--include-stock-distributions',action='store_true',help='导入送转比例和上市时间，零碎股默认拒绝')
    dividends.add_argument('--tax-rate',type=float,required=True,help='显式固定税率假设，不是个人税法计算')
    dividends.add_argument('--output',type=Path,required=True)
    pit_universe_archive=commands.add_parser('pit-universe-archive',help='离线归档目标交易日完整官方证券全集；禁止历史回填')
    pit_universe_archive.add_argument('--data-root',type=Path,required=True)
    pit_universe_archive.add_argument('--plan',type=Path,required=True)
    pit_universe_archive.add_argument('--confirm-publication-times',action='store_true')
    pit_universe_archive.add_argument('--confirm-semantic-mapping',action='store_true')
    pit_universe_archive.add_argument('--confirm-complete-official-universe',action='store_true')
    pit_universe_audit=commands.add_parser('pit-universe-audit',help='只读深验全部PIT Universe v1回执、成员和官方原文字节')
    pit_universe_audit.add_argument('--data-root',type=Path,required=True)
    status_coverage_archive=commands.add_parser('security-status-coverage-archive',help='离线归档目标交易日全Universe SecurityStatus v2；禁止稀疏状态跨日传播')
    status_coverage_archive.add_argument('--data-root',type=Path,required=True)
    status_coverage_archive.add_argument('--plan',type=Path,required=True)
    status_coverage_archive.add_argument('--confirm-publication-times',action='store_true')
    status_coverage_archive.add_argument('--confirm-semantic-mapping',action='store_true')
    status_coverage_archive.add_argument('--confirm-complete-daily-status',action='store_true')
    status_coverage_archive.add_argument('--confirm-previous-session-continuity',action='store_true')
    status_coverage_audit=commands.add_parser('security-status-coverage-audit',help='只读深验SecurityStatus v2逐日覆盖、Universe绑定与连续状态链')
    status_coverage_audit.add_argument('--data-root',type=Path,required=True)
    status_chain=commands.add_parser('security-status-chain',help='只读输出单证券进入、持续、撤销状态链')
    status_chain.add_argument('--data-root',type=Path,required=True);status_chain.add_argument('--symbol',required=True)
    rules_audit=commands.add_parser('market-rules-audit',help='按请求交易日检查规则覆盖，包含无订单日期')
    rules_audit.add_argument('--data-root',type=Path,required=True)
    rules_audit.add_argument('--symbols',nargs='+',required=True)
    rules_audit.add_argument('--start',type=date.fromisoformat,required=True)
    rules_audit.add_argument('--end',type=date.fromisoformat,required=True)
    rules_audit.add_argument('--market-rules',type=Path,required=True)
    rules_audit.add_argument('--output',type=Path,required=True)
    official_archive=commands.add_parser('official-rule-archive',help='下载并归档交易所规则原文，绑定显式MarketRules快照；不推断缺失逐日价格界限')
    official_archive.add_argument('--data-root',type=Path,required=True)
    official_archive.add_argument('--market-rules',type=Path,required=True)
    official_archive.add_argument('--url',action='append',required=True,help='上交所/深交所/北交所HTTPS规则原文URL，可重复')
    official_archive.add_argument('--published-at',action='append',required=True,help='与--url逐项对应的带时区publication time，可重复')
    official_archive.add_argument('--confirm-publication-time',action='store_true',help='宿主确认所填publication time；未确认不联网')
    official_audit=commands.add_parser('official-rule-audit',help='只读深度校验全部Official MarketRules v2回执、records和官方原文字节')
    official_audit.add_argument('--data-root',type=Path,required=True)
    reference_archive=commands.add_parser('official-rule-reference-archive',help='从已下载的深交所字节归档复牌日价格推导参考；固定为回顾性且不生成MarketRules')
    reference_archive.add_argument('--data-root',type=Path,required=True)
    reference_archive.add_argument('--plan',type=Path,required=True,help='公式原文、已验证公告evidence id、行情响应及HTTP headers的本地导入计划')
    reference_archive.add_argument('--confirm-retrospective-only',action='store_true',help='宿主确认只能作为回顾性推导参考')
    reference_audit=commands.add_parser('official-rule-reference-audit',help='只读深验复牌日价格推导参考；结果永不通过Strict PIT/Official MarketRules')
    reference_audit.add_argument('--data-root',type=Path,required=True)
    skill_audit=commands.add_parser('research-skill-audit',help='只读审计外部Research Skill知识包；不执行脚本、不联网、不写StrategySource/Playbook')
    skill_audit.add_argument('--package',type=Path,required=True,help='包含skill.yml、SKILL.md、method.md、scorecard.md的本地知识包')
    skill_git_archive=commands.add_parser('research-skill-git-archive',help='归档宿主已下载并固定commit/tree的外部Git字节；命令本身不联网、不执行外部脚本')
    skill_git_archive.add_argument('--data-root',type=Path,required=True)
    skill_git_archive.add_argument('--repository',type=Path,required=True)
    skill_git_archive.add_argument('--skill-key',required=True)
    skill_git_archive.add_argument('--expected-origin',required=True)
    skill_git_archive.add_argument('--expected-commit',required=True)
    skill_git_archive.add_argument('--expected-tree',required=True)
    skill_git_archive.add_argument('--confirm-untrusted-no-exec',action='store_true')
    skill_git_audit=commands.add_parser('research-skill-git-audit',help='只读深验外部Research Skill Git receipts及全部内容寻址对象')
    skill_git_audit.add_argument('--data-root',type=Path,required=True)
    skill_git_audit.add_argument('--skill-key')
    skill_git_curate=commands.add_parser('research-skill-git-curate',help='由已验证Git receipt生成回顾性Research Skill包；不写StrategySource/Playbook')
    skill_git_curate.add_argument('--data-root',type=Path,required=True)
    skill_git_curate.add_argument('--control-package',type=Path,required=True)
    skill_git_curate.add_argument('--plan',type=Path,required=True)
    skill_git_curate.add_argument('--confirm-retrospective-only',action='store_true')
    feed.add_argument('--require-fresh',action='store_true',help='行情过期或最新截面不齐时拒绝推进账户')
    archive=commands.add_parser('archive-bars',help='在独立工作目录保存不可变行情版本，显式处理修订')
    archive.add_argument('--bars',type=Path,required=True,help='规范化行情 Parquet')
    archive.add_argument('--source-json',type=Path,required=True)
    archive.add_argument('--archive-root',type=Path,required=True)
    archive.add_argument('--parent',type=Path)
    archive.add_argument('--accept-revisions',action='store_true')
    archive.add_argument('--observed-at',type=str)
    fetch=commands.add_parser('fetch-bars',help='抓取日线/5m 历史原始行情到新工作目录，不改写 MQC')
    fetch.add_argument('--symbols',nargs='+',required=True)
    fetch.add_argument('--timeframe',choices=['1d','5m'],required=True)
    fetch.add_argument('--start',type=date.fromisoformat,required=True)
    fetch.add_argument('--end',type=date.fromisoformat,required=True)
    fetch.add_argument('--output',type=Path,required=True)
    registry_create=commands.add_parser('trials-create',help='冻结单实验或父研究设计检验族，不运行研究')
    registry_create.add_argument('--plan',type=Path,required=True)
    registry_create.add_argument('--output',type=Path,required=True)
    registry_bind=commands.add_parser('trials-bind',help='一次性绑定已登记试验的完成或失败产物')
    registry_bind.add_argument('--registry',type=Path,required=True)
    registry_bind.add_argument('--trial-id',required=True)
    registry_bind.add_argument('--artifact',type=Path,required=True)
    registry_report=commands.add_parser('trials-report',help='从原始 p 值生成跨实验固定族 Holm 报告')
    registry_report.add_argument('--registry',type=Path,required=True)
    registry_report.add_argument('--output',type=Path,required=True)
    registry_report.add_argument('--archive-output',type=Path,help='将登记报告和成功来源实验纳入常规复现归档')
    args = parser.parse_args()
    if args.command=='mcp':
        from quantlab.agent.mcp_server import run_mcp
        run_mcp(args.output,args.data_root,args.transport,args.host,args.port);return
    if args.command=='tracking-daemon':
        from quantlab.agent.tracking_daemon import TrackingDaemon
        daemon=TrackingDaemon(args.output,args.data_root,args.poll_seconds)
        result=daemon.once() if args.once else daemon.run_forever()
        if result is not None:print(encode(result))
        return
    if args.command=='tracking-daemon-status':
        from quantlab.agent.tracking_daemon import daemon_status
        print(encode(daemon_status(args.output)));return
    if args.command=='tracking-launchd-write':
        from quantlab.agent.tracking_daemon import write_launchd
        print(encode(write_launchd(args.path,args.output,args.data_root,args.poll_seconds)));return
    if args.command in ('trials-create','trials-bind','trials-report'):
        from quantlab.experiments.trial_registry import create_registry,bind_result,report_registry
        if args.command=='trials-create':result=create_registry(json.loads(args.plan.read_text()),args.output)
        elif args.command=='trials-bind':result=bind_result(args.registry,args.trial_id,args.artifact)
        else:
            result=report_registry(args.registry,args.output)
            if args.archive_output:
                from quantlab.storage.trial_reproduction import archive_registry
                result={'report':result,**archive_registry(args.output,args.archive_output)}
        print(encode(result));return
    if args.command=='fetch-bars':
        from quantlab.data.baostock_bars import fetch_raw_bars
        if args.output.exists():raise FileExistsError(args.output)
        args.output.mkdir(parents=True)
        try:
            with redirect_stdout(sys.stderr):frame,source=fetch_raw_bars(args.symbols,args.timeframe,args.start,args.end)
            if frame is not None:frame.write_parquet(args.output/'bars.parquet')
            source['status']='received' if frame is not None else 'no_data'
            (args.output/'source.json').write_text(encode(source));print(encode(source))
        except Exception as error:
            (args.output/'failure.json').write_text(encode({'status':'failed','error':str(error)}));raise
        return
    if args.command=='archive-bars':
        from datetime import datetime
        import polars as pl
        from quantlab.data.archive import BarArchive
        print(encode(BarArchive(args.archive_root).publish(pl.read_parquet(args.bars),json.loads(args.source_json.read_text()),
            args.parent,args.accept_revisions,datetime.fromisoformat(args.observed_at) if args.observed_at else None)));return
    if args.command=='dividend-import':
        from quantlab.data.dividends import import_cash_dividends
        if args.output.exists():raise FileExistsError(args.output)
        result=import_cash_dividends(args.data_root,args.symbols,args.tax_rate,include_stock=args.include_stock_distributions)
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(encode(result))
        print(encode({'path':args.output,'cash_actions':len(result['corporate_actions']),'unresolved':len(result['unresolved']),'strict_pit_ready':False}));return
    if args.command=='pit-universe-archive':
        from quantlab.data.pit_universe import archive_pit_universe
        if args.plan.is_symlink() or not args.plan.is_file() or args.plan.stat().st_size>10_000_000:
            raise ValueError('PIT Universe plan缺失、为符号链接或超过10MB')
        plan=json.loads(args.plan.read_text())
        print(encode(archive_pit_universe(args.data_root,plan,
            confirm_publication_times=args.confirm_publication_times,
            confirm_semantic_mapping=args.confirm_semantic_mapping,
            confirm_complete_official_universe=args.confirm_complete_official_universe)));return
    if args.command=='pit-universe-audit':
        from quantlab.data.pit_universe import audit_pit_universe
        print(encode(audit_pit_universe(args.data_root)));return
    if args.command=='security-status-coverage-archive':
        from quantlab.data.security_status_coverage import archive_security_status_coverage
        if args.plan.is_symlink() or not args.plan.is_file() or args.plan.stat().st_size>20_000_000:
            raise ValueError('SecurityStatus coverage plan缺失、为符号链接或超过20MB')
        plan=json.loads(args.plan.read_text())
        print(encode(archive_security_status_coverage(args.data_root,plan,
            confirm_publication_times=args.confirm_publication_times,
            confirm_semantic_mapping=args.confirm_semantic_mapping,
            confirm_complete_daily_status=args.confirm_complete_daily_status,
            confirm_previous_session_continuity=args.confirm_previous_session_continuity)));return
    if args.command=='security-status-coverage-audit':
        from quantlab.data.security_status_coverage import audit_security_status_coverage
        print(encode(audit_security_status_coverage(args.data_root)));return
    if args.command=='security-status-chain':
        from quantlab.data.security_status_coverage import security_status_chain
        print(encode(security_status_chain(args.data_root,args.symbol)));return
    if args.command=='market-rules-audit':
        import polars as pl
        from quantlab.execution.rules import MarketRules
        from quantlab.execution.rules_audit import audit_market_rules
        if args.output.exists():raise FileExistsError(args.output)
        calendar=pl.read_parquet(args.data_root/'lake/bronze/provider=baostock/trade_calendar/calendar.parquet')
        dates=calendar.filter(pl.col('is_trading_day').cast(pl.String)=='1')['calendar_date'].cast(pl.Date).to_list()
        result=audit_market_rules(MarketRules(json.loads(args.market_rules.read_text())),args.symbols,[d for d in dates if args.start<=d<=args.end])
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(encode(result))
        print(encode({'path':args.output,'status':result['status'],'covered':result['covered_symbol_sessions'],'expected':result['expected_symbol_sessions']}));return
    if args.command=='official-rule-archive':
        from quantlab.data.official_rule_archive import archive_official_rules
        records=json.loads(args.market_rules.read_text())
        if not isinstance(records,list):raise ValueError('market-rules JSON须为数组')
        if len(args.url)!=len(args.published_at):raise ValueError('--url与--published-at数量必须一致')
        publications={}
        for url,published in zip(args.url,args.published_at):
            if url in publications and publications[url]!=published:raise ValueError('同一URL不能提供不同published_at')
            publications[url]=published
        print(encode(archive_official_rules(args.data_root,records,args.url,publications,
            confirm_publication_time=args.confirm_publication_time)));return
    if args.command=='official-rule-audit':
        from quantlab.data.official_rule_archive import audit_official_rule_archive
        print(encode(audit_official_rule_archive(args.data_root)));return
    if args.command=='official-rule-reference-archive':
        from quantlab.data.official_rule_reference import archive_official_rule_references
        if args.plan.is_symlink() or not args.plan.is_file() or args.plan.stat().st_size>1_000_000:
            raise ValueError('reference plan缺失、为符号链接或超过1MB')
        plan=json.loads(args.plan.read_text())
        print(encode(archive_official_rule_references(args.data_root,plan,
            confirm_retrospective_only=args.confirm_retrospective_only)));return
    if args.command=='official-rule-reference-audit':
        from quantlab.data.official_rule_reference import audit_official_rule_references
        print(encode(audit_official_rule_references(args.data_root)));return
    if args.command=='research-skill-audit':
        from quantlab.knowledge.research_skill import audit_research_skill
        print(encode(audit_research_skill(args.package)));return
    if args.command=='research-skill-git-archive':
        from quantlab.knowledge.research_skill_git import archive_git_research_skill
        print(encode(archive_git_research_skill(args.data_root,args.repository,args.skill_key,
            args.expected_origin,args.expected_commit,args.expected_tree,
            confirm_untrusted_no_exec=args.confirm_untrusted_no_exec)));return
    if args.command=='research-skill-git-audit':
        from quantlab.knowledge.research_skill_git import audit_git_research_skill_archives
        print(encode(audit_git_research_skill_archives(args.data_root,args.skill_key)));return
    if args.command=='research-skill-git-curate':
        from quantlab.knowledge.research_skill_git import materialize_git_research_skill
        print(encode(materialize_git_research_skill(args.data_root,args.control_package,args.plan,
            confirm_retrospective_only=args.confirm_retrospective_only)));return
    if args.command=='paper-reconcile':
        from quantlab.execution.reconcile import reconcile_account
        if args.output.exists():raise FileExistsError(args.output)
        result=reconcile_account(args.account);args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(encode(result));print(encode({'status':result['status'],'path':args.output}));return
    if args.command=='fetch-status':
        from quantlab.data.baostock_status import fetch_status
        with redirect_stdout(sys.stderr):result=fetch_status(args.symbols,args.start,args.end,args.output)
        print(encode(result));return
    if args.command=='fetch-reference':
        from quantlab.data.baostock_reference import fetch_reference
        with redirect_stdout(sys.stderr):result=fetch_reference(args.symbols,args.start,args.end,args.output,args.industry_dates)
        print(encode(result));return
    if args.command=='paper-mqc':
        import math,time
        from quantlab.execution.feed import MQCPaperFeed
        if not math.isfinite(args.poll_seconds) or args.poll_seconds<1:parser.error('poll-seconds must be >= 1')
        reader=lambda path:json.loads(path.read_text()) if path else {}
        source=MQCPaperFeed(args.data_root,args.account,args.symbols,Timeframe(args.timeframe),args.start,args.factor,
            reader(args.parameters_json),ExecutionConfig(**reader(args.execution_json)),PortfolioConfig(**reader(args.portfolio_json)),args.backend,args.archive_root,args.adjustment)
        try:
            while True:
                try:
                    with redirect_stdout(sys.stderr):result=source.poll(args.market_rules,require_fresh=args.require_fresh)
                    print(encode(result),flush=True)
                except (OSError,ValueError) as error:
                    if not args.follow:raise
                    print(encode({'status':'source_or_account_error','error':str(error),'action':'account commit remains atomic; next poll will retry'}),flush=True)
                if not args.follow:break
                time.sleep(args.poll_seconds)
        except KeyboardInterrupt:pass
        return
    if args.command=='return-increment':
        from quantlab.experiments.return_increment import compare_returns
        print(encode(compare_returns(args.candidate,args.baseline,args.start,args.output)));return
    if args.command=='metadata-import':
        from quantlab.data.metadata import import_metadata
        if args.output.exists():raise FileExistsError(args.output)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(encode(import_metadata(args.data_root,args.symbols)))
        print(encode({'path':args.output}));return
    if args.command in ('data-query','data-audit','data-coverage'):
        args.output.parent.mkdir(parents=True,exist_ok=True)
        if args.output.exists():raise FileExistsError(args.output)
        if args.command=='data-coverage':
            from quantlab.data.coverage import historical_coverage
            result=historical_coverage(args.data_root)
        else:
            request=DataRequest(tuple(args.symbols),Timeframe(args.timeframe),args.start,args.end)
            if args.command=='data-query':
                from quantlab.data.query import query_bars
                result,files=query_bars(args.data_root,request)
                if args.output.with_suffix('.manifest.json').exists():raise FileExistsError(args.output.with_suffix('.manifest.json'))
                result.write_parquet(args.output)
                args.output.with_suffix('.manifest.json').write_text(encode({'request':request,'files':files,'rows':result.height}))
                print(encode({'path':args.output,'rows':result.height}));return
            from quantlab.data.audit import audit_market
            result=audit_market(args.data_root,request,args.snapshot_manifest,args.calendar_file)
        args.output.write_text(encode(result))
        print(encode({'path':args.output}));return
    if args.command=='paper-status':
        from quantlab.execution.paper import PaperAccount
        state=PaperAccount(args.account).read()
        print(encode({k:state[k] for k in ('mode','revision','watermark','summary','limitations')}))
        return
    if args.command=='paper-step':
        import time
        import math
        from quantlab.execution.paper import advance_from_files
        if not math.isfinite(args.poll_seconds) or args.poll_seconds<1:parser.error('--poll-seconds must be >= 1')
        last_revision=None
        try:
            while True:
                with redirect_stdout(sys.stderr):
                    result=advance_from_files(args.account,args.bars,args.targets,args.market_rules,
                        ExecutionConfig(**json.loads(args.execution_json.read_text())) if args.execution_json else None,args.backend)
                if result['revision']!=last_revision:
                    print(encode(result),flush=True);last_revision=result['revision']
                if not args.follow:break
                time.sleep(args.poll_seconds)
        except KeyboardInterrupt:
            pass
        return
    if args.command=='residual-alpha':
        from quantlab.experiments.residual import run_residual
        print(encode(run_residual(args.candidate,args.controls,args.train_end,args.output,args.horizon)))
        return
    if args.command == 'serve':
        from quantlab.workbench.server import serve
        serve(args.output,args.port,args.data_root)
        return
    if args.command == 'desktop':
        from quantlab.desktop.app import launch
        raise SystemExit(launch(args.output,args.data_root))
    if args.command == 'theories':
        print(encode(templates()))
        return
    if args.command == "factors":
        print(encode(default_registry().describe()))
        return
    if args.command == "correlate":
        symbols = tuple(args.symbols)
        if (args.train_end is None) != (args.valid_end is None):
            parser.error('--train-end and --valid-end must be provided together')
        if args.walk_forward is not None and args.train_end is not None:
            parser.error('--walk-forward cannot be combined with fixed split dates')
        selection = RegimeFilter(args.regime_direction, args.regime_structure, args.regime_volatility) if any((args.regime_direction, args.regime_structure, args.regime_volatility)) else None
        regime = RegimeConfig(args.regime_lookback, args.regime_baseline) if args.regime or selection is not None else None
        context = None
        if args.context_json is not None:
            spec = json.loads(args.context_json.read_text(encoding='utf-8'))
            if not isinstance(spec, dict) or 'start' not in spec:
                parser.error('Daily context JSON requires an object with start')
            context = DailyContextConfig(**{**spec, 'start':date.fromisoformat(spec['start'])})
        config = CorrelationConfig(args.question, DataRequest(symbols, Timeframe(args.timeframe), args.start, args.end),
            json.loads(args.inputs_json.read_text(encoding="utf-8")), args.min_symbols, args.min_periods, args.cluster_threshold,
            processor=CrossSectionConfig(args.processor) if args.processor is not None else None,
            regime=regime, regime_filter=selection, context=context, random_seed=args.seed,
            bootstrap=BootstrapConfig(args.bootstrap_resamples,args.bootstrap_block_days,args.bootstrap_confidence) if args.bootstrap_resamples is not None else None)
        runner = build_runner(args.data_root, args.output, symbols, args.adjustment, UniverseConfig(args.universe,args.min_listed_days),getattr(args,'snapshot_manifest',None))
        if args.walk_forward is not None:
            result = CorrelationWalkForwardRunner(runner).run(config, WalkForwardConfig(*args.walk_forward))
        else:
            result = CorrelationHoldoutRunner(runner).run(config, ChronologicalSplit(args.train_end, args.valid_end)) if args.train_end is not None else CorrelationRunner(runner).run(config)
        print(encode(result))
        return
    symbols = tuple(args.symbols)
    if args.theory_study_json and (args.backtest or args.ablate or args.sweep_json or args.walk_forward or args.train_end or args.incremental_test):
        parser.error('--theory-study-json is a separate study mode')
    if args.backtest and (args.ablate or args.sweep_json or args.walk_forward or args.train_end or args.incremental_test):
        parser.error('--backtest cannot be combined with ablation/sweep/split/walkforward')
    if (args.execution_json or args.portfolio_json or args.market_rules or args.execution_backend!='open') and not args.backtest:
        parser.error('--execution-json requires --backtest')
    if args.incremental_test and (not args.ablate or args.permutation_resamples is None):
        parser.error('--incremental-test requires --ablate and --permutation-resamples')
    if args.theory is not None and (args.factor is not None or args.params_json is not None or args.sweep_json is not None or
            any(getattr(args, k) is not None for k in ('lookback','left','right','max_gap_seconds')) or args.version != '1.0.0'):
        parser.error('--theory cannot be combined with factor/parameter/version overrides or a parameter sweep')
    if args.sweep_json is not None and args.ablate:
        parser.error("Run parameter sweep and ablation as separate studies")
    if (args.train_end is None) != (args.valid_end is None):
        parser.error("--train-end and --valid-end must be provided together")
    if args.ablate and args.train_end is not None:
        parser.error("Run holdout and ablation as separate studies in this version")
    if args.walk_forward is not None and (args.ablate or args.train_end is not None):
        parser.error("--walk-forward cannot be combined with --ablate or fixed split dates")
    parameters = {key: getattr(args, key) for key in ("lookback", "left", "right", "max_gap_seconds") if getattr(args, key) is not None}
    if args.params_json is not None:
        if parameters:
            parser.error("--params-json cannot be mixed with inline factor parameters")
        parameters = json.loads(args.params_json.read_text(encoding="utf-8"))
        if not isinstance(parameters, dict):
            parser.error("Factor parameters JSON must be an object")
    selection = RegimeFilter(args.regime_direction, args.regime_structure, args.regime_volatility) if any((args.regime_direction, args.regime_structure, args.regime_volatility)) else None
    regime = RegimeConfig(args.regime_lookback, args.regime_baseline) if args.regime or selection is not None else None
    context = None
    if args.context_json is not None:
        spec = json.loads(args.context_json.read_text(encoding="utf-8"))
        if not isinstance(spec, dict) or "start" not in spec:
            parser.error("Daily context JSON requires an object with start")
        context = DailyContextConfig(**{**spec, "start": date.fromisoformat(spec["start"])})
    theory_origin = None
    factor_id = args.factor or 'BASE.MOMENTUM'
    if args.theory is not None:
        parameters, theory_origin = resolve_template(args.theory, default_registry(), args.theory_version)
        factor_id = 'COMB.CONDITION'
    from quantlab.processing.pipeline import PipelineConfig
    if args.pipeline_json and args.processor:parser.error('Use either pipeline-json or processor')
    pipeline = PipelineConfig(**json.loads(args.pipeline_json.read_text())) if args.pipeline_json else None
    config = ExperimentConfig(args.question, DataRequest(symbols, Timeframe(args.timeframe), args.start, args.end), factor_id, args.version, parameters, tuple(args.horizons), args.quantiles,
        permutation=PermutationConfig(args.permutation_resamples,args.permutation_block_days,args.permutation_alpha) if args.permutation_resamples is not None else None,
        incremental_test=args.incremental_test, replay=args.replay,
        theory_origin=theory_origin,
        sequence_audit=args.sequence_audit,
        regime=regime, regime_filter=selection, random_seed=args.seed,
        context=context,
        processor=pipeline or (CrossSectionConfig(args.processor) if args.processor is not None else None),
        bootstrap=BootstrapConfig(args.bootstrap_resamples, args.bootstrap_block_days, args.bootstrap_confidence) if args.bootstrap_resamples is not None else None)
    runner = build_runner(args.data_root, args.output, symbols, args.adjustment, UniverseConfig(args.universe,args.min_listed_days),getattr(args,'snapshot_manifest',None))
    if args.theory_study_json:
        result=TheoryStudyRunner(runner).run(config,TheoryStudyPlan.parse(json.loads(args.theory_study_json.read_text())))
    elif args.backtest:
        # vn.py alpha binds its logger to stdout when first imported. Keep CLI stdout JSON-only.
        from quantlab.execution.rules import MarketRules
        rules=MarketRules(json.loads(args.market_rules.read_text())) if args.market_rules else None
        with redirect_stdout(sys.stderr):
            result = ExecutionStudy(runner).run(config,ExecutionConfig(**json.loads(args.execution_json.read_text()) if args.execution_json else {}),
                PortfolioConfig(**json.loads(args.portfolio_json.read_text()) if args.portfolio_json else {}),args.execution_backend,rules)
        from quantlab.storage.experiments import load_record_fields
        for warning in load_record_fields(result.artifact_path/'experiment.json',{'cost_model_warnings'}).get('cost_model_warnings',[]):
            print('提示：'+warning,file=sys.stderr)
    elif args.sweep_json is not None:
        grid = ParameterGrid(json.loads(args.sweep_json.read_text(encoding="utf-8")))
        result = SweepRunner(runner).run(config, grid,
            split=ChronologicalSplit(args.train_end, args.valid_end) if args.train_end is not None else None,
            schedule=WalkForwardConfig(*args.walk_forward) if args.walk_forward is not None else None)
    elif args.walk_forward is not None:
        result = WalkForwardRunner(runner).run(config, WalkForwardConfig(*args.walk_forward))
    elif args.train_end is not None:
        result = HoldoutRunner(runner).run(config, ChronologicalSplit(args.train_end, args.valid_end))
    else:
        result = AblationRunner(runner).run(config) if args.ablate else runner.run(config)
    print(encode(result))


if __name__ == "__main__":
    main()

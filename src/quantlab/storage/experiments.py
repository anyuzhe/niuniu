"""Immutable per-run artifacts with a local DuckDB catalog."""

import json
import mmap
import re
import shutil
import tempfile
from pathlib import Path
from typing import Protocol

import duckdb
import polars as pl

from quantlab.storage.codec import encode
from quantlab.statistics.permutation import inference_report


def listing_summary(record, source):
    """Small immutable companion for listings; never substitutes detailed evidence."""
    config=record['manifest'].get('config',{})
    stat=source.stat()
    return {'record':{k:record[k] for k in ('run_id','experiment_id','created_at','status','kind') if k in record},
        'config':{k:config[k] for k in ('research_question','factor_id','theory_origin','data') if k in config},
        'source_size':stat.st_size,'source_mtime_ns':stat.st_mtime_ns}


def detail_summary(record, source):
    """Bounded display copy; full audit/replay remain in the immutable source."""
    omitted = {'sequence_audit', 'replay', 'execution_audit', 'target_audit', 'targets', 'backend_details'}
    counts = {}
    def compact(value, path=''):
        if isinstance(value, dict):
            return {k: compact(v, path+'/'+k) for k,v in value.items() if k not in omitted}
        if isinstance(value, list):
            if len(value) > 200:
                counts[path] = len(value)
            return [compact(v, path+'/'+str(i)) for i,v in enumerate(value[:200])]
        return value
    result = compact(record)
    result['_display_summary'] = {'counts': counts, 'omitted': sorted(omitted), 'source': str(source)}
    stat = source.stat()
    return {'record': result, 'source_size': stat.st_size, 'source_mtime_ns': stat.st_mtime_ns}


def identity_summary(record, source):
    """Complete research identity without massive replay/ledger payloads."""
    children=[]
    def visit(node):
        if not isinstance(node,dict):return
        if 'artifact_path' in node and 'run_id' in node:
            children.append({k:node[k] for k in ('run_id','artifact_path','name') if k in node})
        for key in ('children','periods','folds','evaluations'):
            for child in node.get(key,[]):visit(child)
    visit(record)
    stat=source.stat()
    return {'record':{**{k:record[k] for k in ('run_id','experiment_id','created_at','status','kind','manifest') if k in record},'children':children},
        'source_size':stat.st_size,'source_mtime_ns':stat.st_mtime_ns}


def load_identity(path):
    path=Path(path);stat=path.stat()
    try:
        saved=json.loads(path.with_name('identity.json').read_text())
        if (saved['source_size'],saved['source_mtime_ns'])==(stat.st_size,stat.st_mtime_ns):return saved['record']
    except (OSError,ValueError,KeyError,TypeError):pass
    return identity_summary(load_record_fields(path, {'run_id','experiment_id','created_at','status','kind','manifest','children','periods','folds','evaluations'}),path)['record']


def load_record_fields(path, fields):
    """Project our indent-2 archives without materializing multi-GB audit arrays.

    Other JSON layouts retain the ordinary decoder fallback. This relies only
    on the archive writer's formatting, never a truncated display manifest.
    """
    with Path(path).open('rb') as stream:
        if not stream.seek(0, 2):raise ValueError('Empty experiment archive')
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            if data[:2] != b'{\n' or data[-2:] != b'\n}':
                return {k:v for k,v in json.loads(data[:]).items() if k in fields}
            matches=list(re.finditer(rb'^  "([^"\\]+)": ', data, re.MULTILINE))
            if not matches:
                return {k:v for k,v in json.loads(data[:]).items() if k in fields}
            result={}
            for index,match in enumerate(matches):
                key=match[1].decode('utf-8')
                if key not in fields:continue
                end=matches[index+1].start() if index+1<len(matches) else len(data)-1
                result[key]=json.loads(data[match.end():end].rstrip().removesuffix(b','))
            return result


class ExperimentStore(Protocol):
    def save(self, run_id: str, record: dict, observations: pl.DataFrame | None, *, bars: pl.DataFrame | None = None, targets: pl.DataFrame | None = None, inputs: dict[str, pl.DataFrame] | None = None) -> Path: ...


class LocalExperimentStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, run_id: str, record: dict, observations: pl.DataFrame | None, *, bars: pl.DataFrame | None = None, targets: pl.DataFrame | None = None, inputs: dict[str, pl.DataFrame] | None = None) -> Path:
        if not run_id or any(c not in "0123456789abcdef-" for c in run_id):
            raise ValueError("Invalid run id")
        destination = self.root / run_id
        if destination.exists():
            raise FileExistsError(destination)
        staging = Path(tempfile.mkdtemp(prefix=".pending-", dir=self.root))
        try:
            (staging / "experiment.json").write_text(encode(record), encoding="utf-8")
            (staging / 'summary.json').write_text(encode(listing_summary(record,staging/'experiment.json')),encoding='utf-8')
            (staging / 'detail.json').write_text(encode(detail_summary(record,staging/'experiment.json')),encoding='utf-8')
            (staging / 'identity.json').write_text(encode(identity_summary(record,staging/'experiment.json')),encoding='utf-8')
            for name,frame in (inputs or {}).items():
                if Path(name).name!=name or not name.startswith('input-') or not name.endswith('.parquet'):raise ValueError('Invalid frozen input filename')
                frame.write_parquet(staging/name)
            if bars is not None:
                bars.write_parquet(staging / 'bars.parquet')
            if targets is not None:
                targets.write_parquet(staging / 'targets.parquet')
            if observations is not None:
                observations.write_parquet(staging / "observations.parquet")
            (staging / "report.md").write_text(self._report(record), encoding="utf-8")
            staging.rename(destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        # Artifact is the source of truth. If indexing fails, the complete
        # artifact remains available; propagate the error rather than hide it.
        with duckdb.connect(str(self.root / "experiments.duckdb")) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS experiments (run_id VARCHAR PRIMARY KEY, experiment_id VARCHAR, status VARCHAR, created_at VARCHAR, artifact_path VARCHAR)")
            connection.execute("INSERT INTO experiments VALUES (?, ?, ?, ?, ?)", [run_id, record["experiment_id"], record["status"], record["created_at"], str(destination)])
        return destination

    @staticmethod
    def _report(record: dict) -> str:
        report = LocalExperimentStore._base_report(record)
        metrics = record.get('metrics', {})
        if any('decay' in m for m in metrics.values()):
            report += '\n\n## 衰减与信号组合换手\n\n```json\n' + encode({h: {k: m[k] for k in ('decay', 'signal_turnover') if k in m} for h, m in metrics.items()}) + '\n```\n'
        if any('path_metrics' in m.get('triggered', {}) for m in metrics.values()):
            report += '\n\n## 事件路径、恢复与达标耗时\n\n以未来收盘定义目标 +2%、止损 -2%，统计多头方向，不模拟盘中成交。完整事件窗口为固定样本；未达标不计为零耗时。\n\n```json\n' + encode({h: m['triggered']['path_metrics'] for h, m in metrics.items() if 'path_metrics' in m.get('triggered', {})}) + '\n```\n'
        if record.get('inference') and record['status'] == 'completed':
            report += inference_report(record['inference'])
        return report

    @staticmethod
    def _base_report(record: dict) -> str:
        if record.get('kind')=='stability' and record.get('summary',{}).get('method') in ('subsample_equivalence','cross_market_equivalence'):
            summary=record['summary'];lines=['# '+record['manifest']['config']['research_question'],'',
                '固定参数、不重叠证券子样本、配对日期。只有校正后的完整日期块置信区间位于预设容许范围内才支持等效；未拒绝差异不是等效证明。',
                '', '| 比较 | 容许差异 ± | 区间下限 | 区间上限 | 有效日期 | 结论 |','|---|---:|---:|---:|---:|---|']
            for row in summary['comparisons']:
                value=row['equivalence'];interval=value['interval'];conclusion='支持等效' if value['equivalent'] is True else ('未能确认等效' if value['equivalent'] is False else '不可检验：'+str(value['reason']))
                lines.append(f"| {row['name']} | {value['margin']} | {interval['ci_low']} | {interval['ci_high']} | {value['paired_valid_dates']} | {conclusion} |")
            lines += ['', '这是日期块 Bootstrap 近似推断；按原计划比较数校正，不可用项保留名额。原始股票样本与容许范围保存在 manifest.plan；归档不证明用户事先未看数据。',
                '', '[等效性检验的区间原则](https://pmc.ncbi.nlm.nih.gov/articles/PMC5502906/)', '', '## 完整统计记录', '', '```json',encode(summary),'```']
            return '\n'.join(lines)+'\n'
        if record.get('kind') in ('residual_alpha','return_increment','stability','return_family','trial_registry','campaign'):
            return '# '+record['manifest']['config']['research_question']+'\n\n```json\n'+encode(record['summary'])+'\n```\n'
        if record.get('kind')=='theory_study' and record['status']=='completed':
            lines=['# 理论研究全流程','','组件、完整组合、消融、固定样本外、滚动和预设参数敏感性。没有自动择优。','']
            lines += [f"- {c['name']}: {c['run_id']}" for c in record['children']]
            return '\n'.join(lines)+ '\n\n## 参数敏感性（描述性）\n\n```json\n'+encode(record['stability'])+'\n```\n'
        if record.get('kind')=='execution' and record['status']=='completed':
            lines=['# 独立成交回测','', '研究信号在可用后下一根开盘参与模拟；本报告与 gross 预测统计分开。','',
                '## 净值与费用','', '```json',encode(record['execution']),'```','',
                '## 成交模型配置','', '```json',encode(record['manifest']['execution']),'```','',
                '## 组合与目标风控配置','','```json',encode(record['manifest'].get('portfolio',{})),'```','',
                '| 股票 | 决策时间 | 成交时间 | 方向 | 数量 | 价格 | 佣金 | 卖出税 |',
                '|---|---|---|---|---:|---:|---:|---:|']
            for f in record['fills']:
                lines.append(f"| {f['symbol']} | {f['decision_at']} | {f['filled_at']} | {f['side']} | {f['quantity']} | {f['price']:.6f} | {f['commission']:.4f} | {f['tax']:.4f} |")
            if record.get('backend_comparison'):
                lines+=['','## vn.py 与自研引擎核对','','```json',encode(record['backend_comparison']),'```','']
            if record.get('execution_audit'):
                audit=record['execution_audit']
                lines+=['','## 实际换手与目标偏差','','完整逐根持仓偏差和未成交重试链保存在 experiment.json.execution_audit。换手使用实际买卖成交金额，不含费用，除以上一交易日收盘净值；首日使用初始资金。','',
                    '| 日期 | 买入金额 | 卖出金额 | 双边实际换手 |','|---|---:|---:|---:|']
                for r in audit['daily_turnover']:
                    ratio=f"{r['gross_turnover']:.6f}" if r['gross_turnover'] is not None else 'unavailable'
                    lines.append(f"| {r['date']} | {r['buy_notional']:.2f} | {r['sell_notional']:.2f} | {ratio} |")
            lines+=['','## 模型边界','']+[f'- {v}' for v in record['limitations']]
            lines+=['','净值序列保存于 observations.parquet；完整成交和未成交原因在 experiment.json。期末持仓未自动平仓。','']
            return '\n'.join(lines)
        if record.get("kind") == "correlation_walkforward" and record["status"] == "completed":
            return LocalExperimentStore._correlation_walkforward_report(record)
        if record.get("kind") == "correlation_holdout" and record["status"] == "completed":
            return LocalExperimentStore._correlation_holdout_report(record)
        if record.get("kind") == "correlation" and record["status"] == "completed":
            return LocalExperimentStore._correlation_report(record)
        if record.get("kind") == "sweep" and record["status"] == "completed":
            return LocalExperimentStore._sweep_report(record)
        if record.get("kind") == "walkforward" and record["status"] == "completed":
            return LocalExperimentStore._walkforward_report(record)
        if record.get("kind") == "holdout" and record["status"] == "completed":
            return LocalExperimentStore._holdout_report(record)
        if record.get("kind") == "ablation" and record["status"] == "completed":
            return LocalExperimentStore._ablation_report(record)
        lines = ["# 因子研究实验", "", f"状态：{record['status']}", "", f"实验：`{record['experiment_id']}`", ""]
        if record["status"] == "failed":
            lines += ["失败原因：", "", "```text", record["error"], "```", ""]
        else:
            origin = record['manifest']['config'].get('theory_origin')
            if origin is not None:
                lines += ['## 研究模板来源', '', f"{origin['name']}：`{origin['template_id']}@{origin['version']}`", '', origin['scope'], '',
                    '| 模板输入 | 概念定义 | 底层因子 | 版本 |', '|---|---|---|---|']
                for alias, spec in origin['parameters']['inputs'].items():
                    lines.append(f"| {alias} | {origin['concepts'][alias]} | {spec['factor_id']} | {spec['version']} |")
                lines += ['', '这里记录原模板来源；消融子实验会删除部分输入，实际执行规则以下方组合参数为准。模板不自动生成交易方向或订单。', '']
            if "processor" in record["manifest"]:
                processor = record['manifest']['processor']
                lines += ["## 截面预处理与流水线", "", "```json", encode(processor), "```", ""]
                if processor.get('fit_period') is not None:
                    lines += ['历史位置/尺度参数仅在指定训练段拟合，验证/测试沿用冻结参数，拟合前输出为空。中性化仅拟合当前 eligible 截面，用当时可用的行业及市值控制变量；不使用未来收益。', '']
                else:
                    lines += ['仅在同一时点、Regime 过滤前的 eligible 股票池内处理，不拟合历史参数。cs_rank = (平均秩 - 0.5) / 有效标的数；cs_zscore 使用总体标准差。', '']
                lines += ['统计使用处理后 value，原值保存在 raw_value。中性化后的非线性处理可能重新引入行业/市值暴露；需要最终残差时将中性化放在末尾。', '']
                if record.get('processor_audit'):
                    audit = record['processor_audit']
                    summary = {'cross_section_steps':len(audit), 'computed':sum(r['status']=='computed' for r in audit),
                        'missing_industry_rows':sum(r['missing_industry_rows'] for r in audit),
                        'missing_size_rows':sum(r['missing_size_rows'] for r in audit),
                        'output_rows':sum(r['output_rows'] for r in audit)}
                    lines += ['### 中性化覆盖审计', '', '```json', encode(summary), '```', '',
                        '详细逐时点审计保存在 experiment.json 的 processor_audit；上述行数按处理步骤累计，是拟合时间屏蔽前的步骤输出，并非独立有效研究样本数。', '']
            if "combination_inputs" in record["manifest"]:
                lines += ["## 因子组合", "", "| 输入 | 因子 | 版本 | 参数 |", "|---|---|---|---|"]
                for item in record["manifest"]["combination_inputs"]:
                    lines.append(f"| {item['alias']} | {item['definition']['factor_id']} | {item['definition']['version']} | {json.dumps(item['parameters'], ensure_ascii=False, sort_keys=True)} |")
                params = record["manifest"]["parameters"]
                lines += ["", "组合规则：", "", "```json", encode({key: value for key, value in params.items() if key != "inputs"}), "```", "",
                    "任一输入缺失则组合为 null；评分直接使用原始因子值，不自动标准化或优化权重。", ""]
            lines += ["以下为未扣成本的预测统计，不是策略成交回测。", "", "| 持有期（bar） | 样本数 | 平均未来收益 | IC | Rank IC |", "|---|---:|---:|---:|---:|"]
            for horizon, metrics in record["metrics"].items():
                def show(value):
                    return "N/A" if value is None else f"{value:.6f}"
                lines.append(f"| {horizon} | {metrics['observations']} | {show(metrics['mean_forward_return'])} | {show(metrics['ic'])} | {show(metrics['rank_ic'])} |")
            lines += ["", "| 持有期（bar） | ICIR | Rank ICIR | 平均 MFE | 平均 MAE | 顶组减底组 | 配对时点数 |", "|---|---:|---:|---:|---:|---:|---:|"]
            for horizon, metrics in record["metrics"].items():
                cells = [show(metrics.get(key)) for key in ("icir", "rank_icir", "mean_mfe", "mean_mae", "long_short_spread")]
                lines.append(f"| {horizon} | " + " | ".join(cells) + f" | {metrics.get('long_short_dates', 0)} |")
            lines += ["", "ICIR 使用逐时点相关系数的样本标准差，不年化；样本不足或标准差为零时为 N/A。",
                "MFE/MAE 以当前收盘为参考，统计后续完整窗口的多头有利/不利幅度（包含零基线）；不包含信号当根高低价。",
                "顶组减底组仅使用两组同时存在的时点，不代表可执行多空组合。"]
            if any("triggered" in m for m in record["metrics"].values()):
                lines += ["", "## 仅触发样本（value=1）", "", "| 持有期 | 触发数 | 完整未来窗口数 | 平均未来收益 | 上涨比例 | 平均 MFE | 平均 MAE |", "|---|---:|---:|---:|---:|---:|---:|"]
                for horizon, metrics in record["metrics"].items():
                    trigger = metrics["triggered"]
                    cells = [show(trigger[key]) for key in ("mean_forward_return", "positive_return_rate", "mean_mfe", "mean_mae")]
                    lines.append(f"| {horizon} | {trigger['event_count']} | {trigger['labelled_count']} | " + " | ".join(cells) + " |")
                lines += ["", "触发时间按因子真实可用时刻统计；高点确认不代表做空信号，收益仍使用多头方向标签。"]
            if "regime_summary" in record:
                summary = record["regime_summary"]
                selection = record["manifest"]["config"]["regime_filter"]
                lines += ["", "## 市场状态", "", f"过滤前 eligible bar 数：{summary['eligible_before']}；过滤后：{summary['eligible_after']}。",
                    "", "条件：" + (", ".join(f"{key}={value}" for key, value in selection.items() if value is not None) if selection else "仅记录状态，不过滤"), "",
                    "方向和结构使用有符号方向效率；波动率与此前完整窗口均值比较。预热不足为 Unknown，流动性尚未分类。"]
                if "baseline_metrics" in record:
                    lines += ["", "| 持有期 | 原样本数 | 条件样本数 | 原平均未来收益 | 条件平均未来收益 | 原 IC | 条件 IC |",
                        "|---|---:|---:|---:|---:|---:|---:|"]
                    for horizon, metrics in record["metrics"].items():
                        baseline = record["baseline_metrics"][horizon]
                        lines.append(f"| {horizon} | {baseline['observations']} | {metrics['observations']} | {show(baseline['mean_forward_return'])} | {show(metrics['mean_forward_return'])} | {show(baseline['ic'])} | {show(metrics['ic'])} |")
                    lines += ["", "这里只比较不同样本条件下的预测统计，不构成因果增量 Alpha 检验；收益标签仍在完整行情上计算，过滤不改变持有期。"]
            if "context_summary" in record:
                summary = record["context_summary"]
                lines += ["", "## 日线背景筛选", "", "```json", encode(record["manifest"]["config"]["context"]), "```", "",
                    f"背景筛选前 {summary['eligible_before']} 行，其中日线因子可用 {summary['context_ready']} 行；筛选后 {summary['eligible_after']} 行。",
                    "基准已应用股票池、预处理及 Regime 条件；下表只增加日线背景条件。缺失背景不满足条件，不填零。",
                    "若同时使用 Regime，上方市场状态表的最终条件样本包含日线背景筛选。", "",
                    "| 持有期 | 背景前样本数 | 背景后样本数 | 背景前平均收益 | 背景后平均收益 | 背景前 IC | 背景后 IC |",
                    "|---|---:|---:|---:|---:|---:|---:|"]
                for horizon, metrics in record["metrics"].items():
                    before = record["context_baseline_metrics"][horizon]
                    lines.append(f"| {horizon} | {before['observations']} | {metrics['observations']} | {show(before['mean_forward_return'])} | {show(metrics['mean_forward_return'])} | {show(before['ic'])} | {show(metrics['ic'])} |")
                lines += ["", "日线按 available_at 向后匹配，可在收盘可用时刻相等时使用；日线来源时间保存在明细。",
                    "日线从显式 context.start 预热，滚动实验也保留此日线预热起点；只读取本段结束前的日线前缀。",
                    "标签仍基于完整低周期行情，不因过滤而跳过 bar。背景可跨日沿用，暂无过期规则。"]
            if 'sequence_audit' in record:
                audit = record['sequence_audit']
                lines += ['', '## 序列审计', '', f"审计截止：{audit['as_of']}。完整事件和状态变化保存在 experiment.json 的 sequence_audit 字段。",
                    '日志覆盖加载历史（含预热、筛选前记录）；完成记录的 completion_selected 标示是否进入最终统计样本。组合内序列完成不一定触发整个组合，且不要求未来收益标签完整。', '',
                    '| 输入 | 序列因子 | 启动记录 | 完成 | 失效 | 超时 | 截止时等待中 | 进入统计的完成 |', '|---|---|---:|---:|---:|---:|---:|---:|']
                for sequence in audit['sequences']:
                    counts = sequence['status_record_counts']
                    lines.append(f"| {sequence['alias']} | {sequence['factor']['factor_id']} | {counts.get('active',0)} | {counts.get('completed',0)} | {counts.get('invalidated',0)} | {counts.get('timeout',0)} | {sequence['pending_at_end']} | {sequence['selected_completions']} |")
                if not audit['sequences']:
                    lines += ['', '本次实际配置不包含受支持的序列输入，审计列表为空。']
            if any("bootstrap" in m for m in record["metrics"].values()):
                lines += ["", "## 日期分块 Bootstrap", "", "先按日期汇总，再对日期等权估计。它不同于上方逐条样本均值，区间不是 p 值。",
                    "", "| 持有期 | 日均指标 | 有效日期 | 点估计 | 区间下界 | 区间上界 | 有效重采样 | 状态/原因 |",
                    "|---|---|---:|---:|---:|---:|---:|---|"]
                for horizon, metrics in record["metrics"].items():
                    for name, estimate in metrics["bootstrap"].items():
                        lines.append(f"| {horizon} | {name} | {estimate['valid_days']} | {show(estimate['estimate'])} | {show(estimate['ci_low'])} | {show(estimate['ci_high'])} | {estimate['resamples_used']} | {estimate['reason'] or estimate['status']} |")
                lines += ["", "配置：", "", "```json", encode(record["manifest"]["config"]["bootstrap"]), "```", "",
                    "按出现于当前统计样本的日期顺序抽取循环连续块；缺失指标保留为空，不作为零收益。默认块长未经市场/持有期校准，不保证消除全部序列相关。",
                    "置信区间采用经验百分位；未校正多重比较，也不用于自动认定 Alpha 有效。"]
            lines += ["", "研究限制：", ""] + [f"- {item}" for item in record["limitations"]]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _correlation_report(record: dict) -> str:
        config = record['manifest']['config']
        aliases = sorted(record['coverage'])
        lookup = {(p['left'],p['right']):p for p in record['pairs']}
        def show(value):
            return 'N/A' if value is None else f'{value:.6f}'
        lines = ['# 因子相关性与冗余分组', '', f"实验：`{record['experiment_id']}`", '',
            '每个时点独立计算股票横截面相关，再对有效时点等权平均；分钟线按时点等权，不按日期等权。',
            f"每对因子至少 {config['min_symbols']} 个共同有效标的、{config['min_periods']} 个有效时点才报告均值。常数截面不计入有效时点。", '',
            '使用每对因子自身的共同非空样本，不填充缺失。不同配对可能使用不同样本，均值矩阵不保证半正定，不可直接作为投资组合协方差矩阵。']
        for method in ('pearson','spearman'):
            lines += ['', f'## {method} 平均截面相关', '', '| 因子 | ' + ' | '.join(aliases) + ' |', '|---|' + '---:|'*len(aliases)]
            for alias in aliases:
                cells = [show(lookup[tuple(sorted((alias, other)))][method]) for other in aliases]
                lines.append('| ' + alias + ' | ' + ' | '.join(cells) + ' |')
        if any('mutual_information' in p for p in record['pairs']):
            lines += ['', '## 非线性依赖与布尔触发重合', '', '互信息：逐时点至多五分位离散（低基数值直接分类）、至少20个共同标的，随后等权平均；有小样本上偏，不作显著性或独立性证明。Jaccard 仅计相同证券与时间的布尔触发，共同缺失不填零。IC相关采用一根收盘到收盘收益标签及配对共同截面；属于研究标签，不能用作当时交易信号。', '', '| 因子 A | 因子 B | 互信息（nats） | 归一化互信息 | 触发 Jaccard | 1根 IC 相关 |', '|---|---|---:|---:|---:|---:|']
            for p in record['pairs']:
                info=p.get('mutual_information',{});overlap=p.get('signal_overlap',{})
                lines.append(f"| {p['left']} | {p['right']} | {show(info.get('estimate'))} | {show(info.get('normalized'))} | {show(overlap.get('jaccard'))} | {show(p.get('ic_correlation',{}).get('estimate'))} |")
        if record.get('sequence_overlap'):
            lines += ['', '## 完整事件链去重', '', '比较同名序列输入的入选完成链；保留完整事件顺序、版本、内容和可用时间，不以相同终点替代相同序列。不自动删除因子，不证明规则等效。', '', '| A | B | A 独立链 | B 独立链 | 重合链 | 完整链 Jaccard |', '|---|---|---:|---:|---:|---:|']
            for p in record['sequence_overlap']['pairs']:
                lines.append('| '+p['left']+' | '+p['right']+' | '+' | '.join(show(p.get(k)) for k in ('left_unique_chains','right_unique_chains','intersection','jaccard'))+' |')
        lines += ['', '## 配对样本与有效时点', '', '| 因子 A | 因子 B | 共同非空行 | 共同非空时点 | 达标标的数的时点 | Pearson 有效时点 | Spearman 有效时点 |', '|---|---|---:|---:|---:|---:|---:|']
        for p in record['pairs']:
            lines.append(f"| {p['left']} | {p['right']} | {p['common_rows']} | {p['common_periods']} | {p['sufficient_symbol_periods']} | {p['pearson_periods']} | {p['spearman_periods']} |")
        lines += ['', '## 冗余分组', '', f"使用绝对平均 Spearman 相关，阈值 {config['cluster_threshold']}。完全链接逐次合并，组内每一对均须达标；负相关可归入同组，相关符号见矩阵。", '',
            '缺失或样本不足的配对不参与合并。并列时按别名字典序决定，因此相同输入可复现；这是阈值分组，不自动删除因子或证明信息完全重复。', '']
        for index, group in enumerate(record['groups'], 1):
            lines.append(f"- 组 {index}：{', '.join(group)}")
        lines += ['', '## 输入与覆盖', '', '| 别名 | 因子 | 版本 | 有效行 | 股票池行 |', '|---|---|---|---:|---:|']
        for item in record['manifest']['inputs']:
            coverage = record['coverage'][item['alias']]
            lines.append(f"| {item['alias']} | {item['definition']['factor_id']} | {item['definition']['version']} | {coverage['valid_rows']} | {coverage['eligible_rows']} |")
        lines += ['', '输入参数：', '', '```json', encode(config['inputs']), '```', '',
            '原始因子面板保存于 observations.parquet。扩展IC相关使用明确的一根研究收益标签；不评估可成交收益，也未做显著性、多重检验或样本外稳定性检验。',
            '支持注册叶子因子、股票池、预处理、Regime 和日线背景筛选；未自动选择代表因子。源行情复权与历史股票池限制仍适用。']
        if 'selection_summary' in record:
            lines += ['', '## 条件与样本覆盖', '', '```json', encode(record['selection_summary']), '```', '',
                '执行顺序为股票池 → 截面预处理 → Regime → 日线背景。条件缺失不满足筛选；预处理在条件筛选前计算。', '',
                '```json', encode({k:config.get(k) for k in ('processor','regime','regime_filter','context')}), '```', '',
                '启用预处理时面板另存 raw_factor_<alias>；状态和日线背景来源时间也保存在面板中。']
        if any('bootstrap' in p for p in record['pairs']):
            lines += ['', '## 日期分块相关置信区间', '',
                '先在同日平均有效截面相关，再按日期等权估计并重采样。这与上方按时点等权的矩阵口径不同，尤其分钟线可能出现不同点估计；分组仍使用原矩阵。', '',
                '```json', encode({'bootstrap':config['bootstrap'],'random_seed':config['random_seed']}), '```', '',
                '| 因子 A | 因子 B | 方法 | 有效日期 | 日期等权点估计 | 下界 | 上界 | 有效重采样 | 状态/原因 |',
                '|---|---|---|---:|---:|---:|---:|---:|---|']
            for pair in record['pairs']:
                for method, interval in pair['bootstrap'].items():
                    lines.append(f"| {pair['left']} | {pair['right']} | {method} | {interval['valid_days']} | {show(interval['estimate'])} | {show(interval['ci_low'])} | {show(interval['ci_high'])} | {interval['resamples_used']} | {interval['reason'] or interval['status']} |")
            lines += ['', '使用当前筛选面板出现的日期网格，缺失日指标不填零；至少满足有效时点门槛及两倍块长的有效日期，不自动缩短块。',
                '区间为循环日期块重采样的经验百分位，默认块长未经校准；未校正多重比较，不是 p 值或跨阶段相关差异区间，也不衡量分组置信度。']
        return '\n'.join(lines) + '\n'

    @staticmethod
    def _correlation_walkforward_report(record: dict) -> str:
        def show(value):
            return 'N/A' if value is None else f'{value:.6f}'
        schedule = record['manifest']['schedule']
        lines = ['# 因子关系滚动评估', '', f"实验：`{record['experiment_id']}`", '',
            f"训练/验证/测试长度（自然日）：{schedule['train_days']} / {schedule['valid_days']} / {schedule['test_days']}；共 {len(record['folds'])} 轮。",
            '每轮前移一个测试窗口，测试日期不重叠。因子、参数、筛选条件与阈值固定，不拟合或择优。',
            '低周期因子每轮从训练起点预热；日线背景沿用显式 context.start，只读取本阶段结束前的前缀。', '',
            '## 测试阶段汇总', '', '| 因子 A | 因子 B | 有效/总轮次 | 等轮次平均 Spearman | 最小 | 最大 | 正/负/零轮次 | 同组/可判断轮次 |',
            '|---|---|---|---:|---:|---:|---|---|']
        for s in record['summary']:
            lines.append(f"| {s['left']} | {s['right']} | {s['valid_folds']}/{s['total_folds']} | {show(s['mean_test_spearman'])} | {show(s['min_test_spearman'])} | {show(s['max_test_spearman'])} | {s['positive_folds']}/{s['negative_folds']}/{s['zero_folds']} | {s['same_group_folds']}/{s['known_group_folds']} |")
        lines += ['', '缺失轮次不填零；平均值对有效测试轮次等权，不是合并所有时点重算的相关。同组比例只以可判断轮次为分母。', '',
            '## 各轮测试相关', '', '| 轮次 | 测试起止 | 因子 A | 因子 B | Spearman | 相对本轮训练 Δ | 有效时点 | 同组 |', '|---|---|---|---|---:|---:|---:|---|']
        for fold in record['folds']:
            test = next(p for p in fold['periods'] if p['name']=='test')
            for c in fold['comparisons']:
                p = c['periods']['test']
                grouped = 'N/A' if p['same_group'] is None else ('是' if p['same_group'] else '否')
                lines.append(f"| {fold['fold']} | {test['start']} 至 {test['end']} | {c['left']} | {c['right']} | {show(p['spearman'])} | {show(p['spearman_delta_from_train'])} | {p['spearman_periods']} | {grouped} |")
        lines += ['', '## 完整分段报告', '']
        for fold in record['folds']:
            lines.append(f"- [第 {fold['fold']} 轮](<{Path(fold['artifact_path']) / 'report.md'}>)")
        tail = record['manifest']['unused_tail']
        lines += ['', f"未覆盖尾部：{tail['start']} 至 {tail['end']}。" if tail else '没有未覆盖尾部。',
            '这是描述性滚动对比；各阶段可选日期等权相关区间见子报告，未计算跨轮汇总或相关差异区间、未做多重比较校正。没有自动删除因子，训练/验证窗口之间可重叠，不应将各轮视为独立统计样本。']
        return '\n'.join(lines) + '\n'

    @staticmethod
    def _correlation_holdout_report(record: dict) -> str:
        def show(value):
            if value is None:
                return 'N/A'
            if isinstance(value, bool):
                return '是' if value else '否'
            return f'{value:.6f}'
        lines = ['# 因子关系时序分段对比', '', f"实验：`{record['experiment_id']}`", '',
            '各阶段固定使用相同因子、参数、筛选条件和分组阈值；仅读取截至本阶段结束的行情前缀，此前历史用于预热。',
            '每阶段独立计算相关与分组，不训练模型或选择代表因子。差值是描述性变化，不是稳定性显著检验。', '',
            '| 因子 A | 因子 B | 阶段 | Pearson | Spearman | 相对训练段 ΔSpearman | 有效 Spearman 时点 | 同组 |',
            '|---|---|---|---:|---:|---:|---:|---|']
        for row in record['comparisons']:
            for name, pair in row['periods'].items():
                lines.append(f"| {row['left']} | {row['right']} | {name} | {show(pair['pearson'])} | {show(pair['spearman'])} | {show(pair['spearman_delta_from_train'])} | {pair['spearman_periods']} | {show(pair['same_group'])} |")
        lines += ['', '## 分段报告', '']
        for period in record['periods']:
            lines.append(f"- [{period['name']}](<{Path(period['artifact_path']) / 'report.md'}>)：{period['start']} 至 {period['end']}。")
        lines += ['', '样本不足时相关、差值或同组状态显示 N/A，不将未知当作相关为零或已分离。不同阶段股票数量与有效时点可能不同。',
            '各阶段可选日期等权相关区间见子报告；未计算跨阶段差异区间或多重比较校正。分段对比不证明测试集从未被查看或 Alpha 有效。滚动对比可另用 correlate --walk-forward。']
        return '\n'.join(lines) + '\n'

    @staticmethod
    def _sweep_report(record: dict) -> str:
        lines = ["# 参数扫描", "", f"实验：`{record['experiment_id']}`", "",
            f"共 {len(record['children'])} 个参数配置，按参数网格顺序列出，不按表现自动择优。", "",
            "各参数预热长度和有效样本数可能不同，未强制共同样本。重复查看多个测试结果不能视为未触碰的独立测试集；可选 IC 检验族校正见文末，不覆盖收益择优或跨研究探索。", "",
            "| 配置 | 阶段 | 持有期 | 样本数 | 平均未来收益 | IC | Rank IC |", "|---|---|---|---:|---:|---:|---:|"]
        def show(value):
            return "N/A" if value is None else f"{value:.6f}"
        for index, child in enumerate(record["children"], 1):
            for evaluation in child["evaluations"]:
                for horizon, m in evaluation["metrics"].items():
                    lines.append(f"| {index} | {evaluation['phase']} | {horizon} | {m['observations']} | {show(m['mean_forward_return'])} | {show(m['ic'])} | {show(m['rank_ic'])} |")
        if any("triggered" in m for c in record["children"] for e in c["evaluations"] for m in e["metrics"].values()):
            lines += ["", "## 仅触发样本", "", "| 配置 | 阶段 | 持有期 | 触发数 | 完整未来窗口数 | 平均未来收益 |", "|---|---|---|---:|---:|---:|"]
            for index, child in enumerate(record["children"], 1):
                for evaluation in child["evaluations"]:
                    for horizon, m in evaluation["metrics"].items():
                        t = m["triggered"]
                        lines.append(f"| {index} | {evaluation['phase']} | {horizon} | {t['event_count']} | {t['labelled_count']} | {show(t['mean_forward_return'])} |")
        lines += ["", "## 配置与完整报告", ""]
        for index, child in enumerate(record["children"], 1):
            lines += [f"### 配置 {index}", "", "```json", encode(child["parameters"]), "```", "",
                f"[完整报告](<{Path(child['artifact_path']) / 'report.md'}>)", ""]
        lines += ["所有配置复用同一源快照；失败时停止并保留已完成子实验。这里只扫描主因子参数，不扫描背景条件、预处理或股票池。",
            "各子实验保留数据快照、参数、背景条件及统计明细；未自动训练、选择参数或模拟交易成本。"]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _ablation_report(record: dict) -> str:
        lines = ["# 组合逐输入消融", "", f"实验：`{record['experiment_id']}`", "",
            f"状态过滤前共同 eligible bar 数：{record['manifest']['common_eligible_before_regime']}。", "",
            "共同样本由完整组合的非缺失输出与原股票池确定；各子实验继续使用相同状态过滤和未来收益口径。",
            "下表为分别计算后相减的描述性差值，本身不是显著性检验或因果贡献证明。可选配对差异检验另见文末。评分权重不重新归一化。", "",
            "| 移除输入 | 持有期 | 指标 | 完整组合 | 移除后 | 差值 |", "|---|---|---|---:|---:|---:|"]
        def show(value):
            return "N/A" if value is None else f"{value:.6f}"
        for comparison in record["comparisons"]:
            for horizon, metrics in comparison["metrics"].items():
                for name, values in metrics.items():
                    lines.append(f"| {comparison['removed']} | {horizon} | {name} | {show(values['full'])} | {show(values['without'])} | {show(values['delta_full_minus_without'])} |")
        lines += ["", "布尔组合的整体平均未来收益仅反映共同样本；请同时查看 triggered 指标。触发样本不同是删除条件的直接结果，样本数随之变化。",
            "", "## 子实验", ""]
        for child in record["children"]:
            label = "完整组合" if child["removed"] is None else "移除 " + child["removed"]
            path = Path(child["artifact_path"]) / "report.md"
            lines.append(f"- [{label}](<{path}>)：`{child['experiment_id']}`")
        lines += ["", "## 删减后参数", "", "```json", encode(record["manifest"]["variants"]), "```", "",
            "未做费用模拟、样本外验证或自动择优；可选配对 IC 差异检验需要显式启用 incremental_test，结果见文末。各子实验 JSON 保留输入版本、参数与数据快照。"]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _holdout_report(record: dict) -> str:
        lines = ["# 按时间分段评估", "", f"实验：`{record['experiment_id']}`", "",
            "固定因子、参数与状态规则，分别报告 train / valid / test；没有自动训练、调参或择优。",
            "每段使用此前历史预热，但计算输入截到该段末尾，未来标签不跨段。", "",
            "| 分段 | 开始 | 结束 | 持有期 | 样本数 | 平均未来收益 | IC | Rank IC |",
            "|---|---|---|---|---:|---:|---:|---:|"]
        def show(value):
            return "N/A" if value is None else f"{value:.6f}"
        for period in record["periods"]:
            for horizon, metrics in period["metrics"].items():
                lines.append(f"| {period['name']} | {period['start']} | {period['end']} | {horizon} | {metrics['observations']} | {show(metrics['mean_forward_return'])} | {show(metrics['ic'])} | {show(metrics['rank_ic'])} |")
        if any("triggered" in m for p in record["periods"] for m in p["metrics"].values()):
            lines += ["", "## 仅触发样本", "", "| 分段 | 持有期 | 触发数 | 完整未来窗口数 | 平均未来收益 |", "|---|---|---:|---:|---:|"]
            for period in record["periods"]:
                for horizon, metrics in period["metrics"].items():
                    m = metrics["triggered"]
                    lines.append(f"| {period['name']} | {horizon} | {m['event_count']} | {m['labelled_count']} | {show(m['mean_forward_return'])} |")
        lines += ["", "## 分段明细", ""]
        for period in record["periods"]:
            lines.append(f"- [{period['name']}](<{Path(period['artifact_path']) / 'report.md'}>)：`{period['experiment_id']}`")
        lines += ["", "空样本或持有期超过段内剩余长度时为 0 / N/A；不得据此声称样本外有效。",
            "是否在查看测试期之前冻结了研究假设需由研究流程保证，本功能不证明测试集从未被查看。",
            "本报告为单次分段，未拟合模型；可选 IC 检验见文末，不检验跨阶段差值；交易成本、股票池与复权限制见子实验。"]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _walkforward_report(record: dict) -> str:
        schedule = record["manifest"]["schedule"]
        lines = ["# 固定参数滚动评估", "", f"实验：`{record['experiment_id']}`", "",
            f"窗口（自然日）：训练 {schedule['train_days']} / 验证 {schedule['valid_days']} / 测试 {schedule['test_days']}。共 {len(record['folds'])} 轮。",
            "每次前移一个测试窗口；测试区间互不重叠。所有轮次使用同一因子和参数，没有逐轮拟合或择优。",
            "每轮低周期因子从训练起点重新预热；若使用日线背景，则日线沿用显式 context.start，仅读取至本段结束。各段末尾不足持有期的标签为 null。", "",
            "| 轮次 | 测试开始 | 测试结束 | 持有期 | 样本数 | 平均未来收益 | IC | Rank IC |",
            "|---|---|---|---|---:|---:|---:|---:|"]
        def show(value):
            return "N/A" if value is None else f"{value:.6f}"
        for fold in record["folds"]:
            test = next(p for p in fold["periods"] if p["name"] == "test")
            for horizon, metrics in test["metrics"].items():
                lines.append(f"| {fold['fold']} | {test['start']} | {test['end']} | {horizon} | {metrics['observations']} | {show(metrics['mean_forward_return'])} | {show(metrics['ic'])} | {show(metrics['rank_ic'])} |")
        lines += ["", "## 各轮完整分段报告", ""]
        for fold in record["folds"]:
            lines.append(f"- [第 {fold['fold']} 轮](<{Path(fold['artifact_path']) / 'report.md'}>)：{fold['start']} 至 {fold['end']}。")
        tail = record["manifest"]["unused_tail"]
        lines += ["", f"未覆盖的末尾区间：{tail['start']} 至 {tail['end']}（不足完整测试窗口）。" if tail else "没有未覆盖的末尾区间。",
            "", "布尔因子的触发统计见各轮报告。没有把重叠持有期收益拼成策略净值，也未进行成本模拟或收益差异检验；可选 IC 检验族校正见文末。",
            "固定参数滚动评估不证明测试集从未被查看；空样本不得解释为样本外有效。"]
        return "\n".join(lines) + "\n"


def load_record(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))

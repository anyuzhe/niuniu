"""Readable, lazily expanded research records with optional raw diagnostics."""
import json
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QTreeWidget,QTreeWidgetItem,QCheckBox,QPlainTextEdit
from quantlab.storage.codec import encode
from .research_config import NAMES
from .action_editor import SCHEMAS

LABELS={**NAMES,'definition':'因子定义','defaults':'默认参数','parameters':'参数设置','factor_id':'因子编号','template_id':'研究模板','name_cn':'名称','name':'名称','version':'版本','description':'说明','formula':'计算公式','category':'分类','factor_type':'输出类型','required_fields':'所需行情字段','timeframes':'支持周期','causal':'因果约束','lookahead_risk':'未来信息风险','available_at_rule':'确认与可用时间规则','tags':'标签','source_theory':'理论来源','code_hash':'代码指纹','scope':'适用范围','concepts':'理论概念','inputs':'输入因子','weights':'评分权重','rule':'组合条件','all':'全部满足','any':'任一满足','not':'条件取反','input':'输入因子','op':'比较方式','value':'数值','steps':'事件步骤','invalidators':'失效事件','step_timeframes':'逐步骤周期','timeout_seconds':'独立超时（秒）','optional':'可选步骤','event':'事件','structures':'结构','events':'事件','zones':'价格区域','zone_states':'区域状态','fills':'成交','overlay_rules':'图层规则','datetime':'行情时间','available_at':'信息可用时间','created_at':'创建时间','run_id':'实验编号','experiment_id':'实验身份','status':'状态','kind':'类型','config':'研究设置','data':'行情请求','symbols':'证券','start':'开始日期','end':'结束日期','timeframe':'K 线周期','adjustment':'复权口径','universe':'股票资格','regime':'市场状态','regime_filter':'状态筛选','bootstrap':'置信区间设置','permutation':'显著性检验设置','processor':'预处理','context':'高周期背景','execution':'成交与账户','portfolio':'组合约束','execution_backend':'成交引擎','snapshot':'数据快照','data_snapshot':'行情快照','qualification':'数据资格要求','files':'文件记录','path':'位置','sha256':'内容校验值','bytes':'文件大小（字节）','snapshot_id':'快照编号','provider':'数据来源','mode':'口径','horizons':'持有期（根）','quantiles':'分位组数','research_question':'研究问题','replay':'保存回放','sequence_audit':'序列审计','manifest':'配置与依赖','metrics':'统计指标','observations':'有效观测数','ic':'信息系数 IC','rank_ic':'秩信息系数','mean_return':'平均未来收益','count':'数量','details':'详细记录','result':'结果','error':'错误说明','errors':'错误说明','jobs':'研究任务','job_id':'任务编号','trials':'登记试验','trial_id':'计划项编号','plan':'研究计划','source':'资料来源','sources':'来源记录','direction':'方向','price':'价格','quantity':'数量','cash_delta':'现金变动','position_delta':'持仓变动','pending_share_delta':'待上市股份变动','receivable_delta':'应收变动','payable_delta':'应付变动','source_run_id':'来源实验','threshold':'阈值','reason':'原因','matched':'核对一致','summary':'摘要','rows':'记录','checks':'核对项目','dependencies':'依赖环境','python':'Python 版本','warnings':'注意事项','failed':'未通过','passed':'通过','sequences':'序列记录','state':'状态','at':'时点','selected_sources':'选定来源','identity':'身份与配置','source_root':'原始数据目录','restored_root':'恢复目录','children':'子实验','comparisons':'比较结果','p_value':'原始显著性概率','adjusted_p':'校正后显著性概率'}
def collect_labels(schema):
    for key,s in schema.items():
        LABELS.setdefault(key,s['title'])
        if 'schema' in s:collect_labels(s['schema'])
for schema in SCHEMAS.values():collect_labels(schema)
LABELS.update({'backend':'成交引擎','corporate_action_mode':'公司行动资料口径','corporate_actions':'现金分红与送转','factor':'因子','factor_code_hash':'因子代码校验值','factor_version':'因子版本','file':'文件','frame':'行情表','frozen_inputs':'冻结输入','hash':'内容校验值','id':'编号','incremental_test':'增量检验','industry_events':'历史行业记录','market_rules':'历史费用与交易规则','mask_hash':'资格筛选校验值','metadata':'附加说明','price_mode':'回测价格模式','random_seed':'随机种子','request':'请求范围','rights_issues':'配股认购','rights_trading':'可转让配股权','runtime':'运行环境','signal_data_snapshot':'信号行情快照','source_experiment_id':'来源实验身份','stock_splits':'拆并股','targets_hash':'目标持仓校验值','theory_origin':'理论来源','weighting':'权重方式'})
VALUES={'completed':'已完成','running':'运行中','queued':'等待运行','failed':'失败','cancelled':'已取消','boolean':'条件事件','scalar':'数值因子','theory':'理论模板','qfq':'前复权','raw':'不复权','research':'研究价格','account':'精细账户','strict':'严格历史可用时间','retrospective':'回顾性资料','gt':'大于','ge':'大于等于','lt':'小于','le':'小于等于','eq':'等于','ne':'不等于','explicit':'指定股票','listing':'历史上市日期','pit':'历史可用资格'}
VALUES.update({'open':'独立开盘成交引擎','vnpy_rules':'vn.py 规则引擎','equal':'等权','score':'评分权重'})

LABELS.update({'proposal_id':'提案编号','request_id':'幂等请求编号','proposal_digest':'完整提案校验值',
    'job_id':'原队列任务编号','approved_at':'人工批准时间','spec':'原始研究配置','spec_digest':'配置校验值',
    'resolved':'原引擎解析结果','estimate':'规模预估','budget':'本次预算','binding':'工作空间与代码绑定',
    'data_policy':'行情快照政策','calendar_days':'自然日跨度','leaf_studies':'叶子研究数',
    'bar_evaluations_upper_estimate':'保守 K 线评价量','resample_date_draws_upper_estimate':'保守重采样工作量',
    'max_symbols':'证券数量上限','max_calendar_days':'自然日跨度上限','max_leaf_studies':'叶子研究上限',
    'max_bar_evaluations':'K 线评价量上限','max_resamples':'重采样次数上限',
    'max_resample_date_draws':'重采样工作量上限','max_pending_proposals':'待处理提案上限',
    'max_active_jobs':'新提案提交时活动任务上限','cooperative_seconds':'每次执行合作式时限（秒）',
    'output':'研究产物目录','data_root':'只读行情目录','device':'存储设备标识','inode':'目录身份标识','approval_freeze':'审批输入冻结','freeze_id':'冻结编号','manifest_hash':'冻结清单校验值'})
VALUES.update({'pending':'待人工批准','approved':'已批准，待入队确认','submitted':'已交付原任务队列',
    'rejected':'已拒绝','execution_time_snapshot_not_approval_time_freeze':'历史口径：批准时不冻结行情字节','approval_time_actual_byte_freeze_on_host_approval':'人工批准时冻结实际研究输入字节并从冻结包执行'})


class BusinessDetails(QWidget):
    def __init__(self,value,parent=None):
        super().__init__(parent);box=QVBoxLayout(self);box.setContentsMargins(0,0,0,0)
        self.tree=QTreeWidget();self.tree.setHeaderLabels(['项目','内容']);self.tree.setColumnWidth(0,220);self.tree.setAccessibleName('业务明细');box.addWidget(self.tree,1)
        self.expert=QCheckBox('显示高级原始记录');box.addWidget(self.expert)
        self.raw=QPlainTextEdit();self.raw.setReadOnly(True);self.raw.hide();box.addWidget(self.raw,1)
        self.expert.toggled.connect(self.raw.setVisible);self.tree.itemExpanded.connect(self.expand)
        self.setPlainText(encode(value))
    def toPlainText(self):return self.raw.toPlainText()
    def setPlainText(self,text):
        self.raw.setPlainText(text);self.tree.clear()
        try:value=json.loads(text)
        except (ValueError,TypeError):value={'result':text}
        if not isinstance(value,(dict,list)):value={'result':value}
        self.populate(self.tree.invisibleRootItem(),value)
    def populate(self,parent,value):
        if isinstance(value,list) and len(value)>100:
            entries=[(f'第 {i+1}–{min(i+100,len(value))} 条',value[i:i+100]) for i in range(0,len(value),100)]
        else:entries=value.items() if isinstance(value,dict) else [(f'第 {i+1} 条',v) for i,v in enumerate(value)]
        for key,item in entries:
            title=LABELS.get(key,str(key));nested=isinstance(item,(dict,list))
            text=f'{len(item)} 项，展开查看' if nested else '未提供' if item is None else '是' if item is True else '否' if item is False else VALUES.get(item,item) if isinstance(item,str) else str(item)
            node=QTreeWidgetItem([title,str(text)]);parent.addChild(node)
            if nested and item:node._pending=item;node.addChild(QTreeWidgetItem(['载入…']))
    def expand(self,node):
        if hasattr(node,'_pending'):
            value=node._pending;del node._pending;node.takeChildren();self.populate(node,value)


LABELS.update({'watch_id':'跟踪编号','snapshot_id':'快照编号','snapshot_count':'快照数量',
    'source_integrity':'当前来源校验','watermarks':'进度水位','data_at':'行情水位',
    'factor_at':'因子水位','labels':'成熟标签水位','baseline_differences':'相对基准变化',
    'historical_revision':'历史输入修订','refresh_requests':'刷新提案','active':'已启用',
    'latest':'最新快照','history':'历史快照','preview':'窗口统计','pending_observations':'未成熟样本',
    'mature_observations':'成熟样本','valid_ic_sessions':'有效 IC 日期数','as_of':'评价截止',
    'automatic_tracking':'自动调度','claim_verified':'结论已认证','tracking_algorithm':'统计代码指纹'})
VALUES.update({'verified':'来源校验一致','source_changed':'来源已变化','unavailable':'不可用',
    'advanced':'水位推进','no_new_data':'没有新数据','historical_revision':'历史输入修订',
    'insufficient_mature_dates':'成熟样本日期不足','descriptive':'仅描述性比较'})

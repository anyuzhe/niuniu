"""Business controls over the existing research contracts; preserves unedited fields."""
from copy import deepcopy
from dataclasses import asdict
import json
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QTabWidget,QWidget,QScrollArea,
    QCheckBox,QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit,QDialogButtonBox)
from quantlab.regime.config import RegimeConfig
from quantlab.statistics.bootstrap import BootstrapConfig
from quantlab.statistics.permutation import PermutationConfig
from quantlab.execution.backtest import ExecutionConfig
from quantlab.execution.portfolio import PortfolioConfig
from .widgets import label,button

PARAMETER_NAMES=dict(zip(
    'lookback left right min_separation context follow_bars max_bars max_age_bars max_hold max_follow_strokes max_gap_seconds trend_lookback trend_threshold atr_multiple body_fraction box_pct reversal ar_atr breakout_body breakout_volume climax_body climax_multiple climax_spread climax_volume contraction_ratio divergence_ratio max_efficiency max_width min_bars_b preliminary_volume retest_fraction retest_volume_ratio search_bars test_fraction test_volume trailing_atr start end timezone'.split(),
    ['回看长度（根）','左侧确认长度（根）','右侧确认长度（根）','最小间隔（根）','背景回看长度（根）','后续观察长度（根）','最大持续长度（根）','最大存续长度（根）','最长持仓长度（根）','最大跟踪笔数','步骤间超时（秒）','趋势回看长度（根）','趋势阈值','真实波幅倍数','实体占比','点数图格宽比例','反转格数','自动反弹波幅倍数','突破实体占比','突破成交量倍数','高潮实体占比','高潮倍数','高潮价差倍数','高潮成交量倍数','收缩比例','背驰比例','最大方向效率','最大区间宽度比例','B 阶段最少根数','初步支撑成交量倍数','回测容差比例','回测成交量比例','搜索长度（根）','测试容差比例','测试成交量比例','跟踪止损波幅倍数','开始时间','结束时间','时区']))
NAMES={**PARAMETER_NAMES,'baseline_window':'波动基准长度（根）','direction_threshold':'方向判定阈值','range_threshold':'震荡判定阈值','volatility_low':'低波动界限','volatility_high':'高波动界限',
    'resamples':'重采样次数','block_days':'日期分块长度','confidence':'置信水平','alpha':'显著性水平','initial_cash':'初始资金（元）','top_n':'最多入选股票数','threshold':'入选分数下限','exposure':'目标总仓位比例','lot_size':'每手股数','t_plus_one':'启用 T+1 卖出限制','commission_bps':'佣金（万分之一）','minimum_commission':'每笔最低佣金（元）','sell_tax_bps':'卖出税费（万分之一）','slippage_bps':'滑点（万分之一）','transfer_bps':'过户费（万分之一）','fee_decimals':'费用小数位数','statutory_fees':'按成交日计法定印花税与过户费','limit_pct':'固定涨跌幅假设（比例）','max_actual_position':'实际单股仓位上限','max_actual_exposure':'实际总仓位上限','allow_st':'允许买入 ST 股票','max_actual_sector':'实际行业仓位上限','max_volume_participation':'最大成交量参与比例','max_position':'目标单股仓位上限','max_exposure':'目标总仓位上限','max_turnover':'单次目标换手上限','volatility_lookback':'波动回看长度（根）','sector_limit':'目标行业仓位上限','min_listed_days':'上市至少自然日数'}


NAMES.update({'middle_timeframe':'中间结构周期','higher_timeframe':'最高结构周期','same_direction':'要求逐层同向'})


def control_for(key,value):
    if key in ('middle_timeframe','higher_timeframe'):
        control=QComboBox()
        for title,period in [('5 分钟','5m'),('15 分钟','15m'),('30 分钟','30m'),('60 分钟','60m'),('日线','1d')]:control.addItem(title,period)
        control.setCurrentIndex(control.findData(value));getter=control.currentData
    elif isinstance(value,bool):
        control=QCheckBox('启用');control.setChecked(value);getter=control.isChecked
    elif isinstance(value,int):
        control=QSpinBox();control.setRange(-2147483647,2147483647);control.setValue(value);getter=control.value
    elif isinstance(value,float):
        control=QDoubleSpinBox();control.setRange(-1e15,1e15);control.setDecimals(10);control.setValue(value);getter=control.value
    else:
        control=QLineEdit(str(value));getter=control.text
    control.setAccessibleName(NAMES.get(key,key))
    displayed=getter()
    return control,lambda:value if getter()==displayed else getter()


class ParameterDialog(QDialog):
    def __init__(self,parent,definition,value):
        super().__init__(parent);self.setWindowTitle('因子参数');self.resize(700,620);self.result_value=None
        self.original=deepcopy(value);self.getters={};self.controls={}
        box=QVBoxLayout(self);d=definition.get('definition',definition)
        box.addWidget(label(d.get('name_cn','因子参数'),'heroTitle'));box.addWidget(label(d.get('description',''),'muted',True))
        page=QWidget();form=QFormLayout(page);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);box.addWidget(scroll,1)
        defaults=definition.get('defaults',{})
        for key,v in {**defaults,**value}.items():
            if isinstance(v,(dict,list)) or v is None:continue
            control,getter=control_for(key,v);self.controls[key]=control;self.getters[key]=getter;form.addRow(NAMES.get(key,key),control)
        if 'steps' in defaults:
            from quantlab.app import default_registry
            from .sequence_builder import NAMES as EVENT_NAMES
            self.sequence_sources=default_registry().get(d['factor_id'],d['version']).SOURCES
            self.original={**deepcopy(defaults),**self.original}
            form.addRow(button('编辑事件步骤与嵌套组',self.edit_sequence))
            invalidators=[]
            for source in self.sequence_sources:
                control=QCheckBox('取消序列：'+EVENT_NAMES.get(source,source));control.setChecked(source in self.original.get('invalidators',[]));form.addRow(control);invalidators.append((source,control))
            self.getters['invalidators']=lambda:[source for source,control in invalidators if control.isChecked()]
            self.sequence_period_form=QFormLayout();form.addRow(self.sequence_period_form)
            self.sequence_period_controls=[];self.refresh_sequence_periods()
        elif any(isinstance(v,(dict,list)) for v in {**defaults,**value}.values()):
            box.addWidget(label('组合输入、条件和事件步骤沿用已有编排器；此处保留其内容，仅修改数值参数。','note',True))
        if not self.controls:form.addRow(label('此因子没有独立数值参数。'))
        self.status=label('参数含义及取值范围由所选因子的规则校验。','muted',True);box.addWidget(self.status)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.finish);buttons.rejected.connect(self.reject);box.addWidget(buttons)
        for control in self.findChildren(QComboBox):control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.factor_id=d.get('factor_id');self.version=d.get('version','1.0.0')

    def edit_sequence(self):
        from .sequence_editor import SequenceEditor
        from .sequence_builder import NAMES as EVENT_NAMES
        dialog=SequenceEditor(self,self.original['steps'],self.sequence_sources,EVENT_NAMES)
        if dialog.exec():
            if dialog.result_steps==self.original['steps'] and self.sequence_period_controls:
                self.original['step_timeframes']=[c.currentData() for c in self.sequence_period_controls]
            else:self.original.pop('step_timeframes',None)
            self.original['steps']=dialog.result_steps;self.refresh_sequence_periods()
            self.status.setText('步骤已更新，请核对失效事件和逐步骤周期后保存。')

    def refresh_sequence_periods(self):
        from quantlab.sequence.specification import normalize_steps
        from .sequence_builder import NAMES as EVENT_NAMES
        while self.sequence_period_form.rowCount():self.sequence_period_form.removeRow(0)
        self.sequence_period_controls=[]
        if self.sequence_sources[0].startswith('CHAN.'):return
        steps,_=normalize_steps(self.original['steps'],self.sequence_sources)
        supplied=self.original.get('step_timeframes',[])
        for i,source in enumerate(steps):
            control=QComboBox()
            for title,period in [('沿用研究周期',''),('1 分钟','1m'),('5 分钟','5m'),('15 分钟','15m'),('30 分钟','30m'),('60 分钟','60m'),('日线','1d')]:control.addItem(title,period)
            control.setCurrentIndex(control.findData(supplied[i]) if i<len(supplied) else 0);control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            title=f'步骤 {i+1} 周期：'+EVENT_NAMES.get(source,source);control.setAccessibleName(title);self.sequence_period_form.addRow(title,control);self.sequence_period_controls.append(control)

    def finish(self):
        from quantlab.app import default_registry
        try:
            value={**self.original,**{k:g() for k,g in self.getters.items()}}
            if getattr(self,'sequence_period_controls',None):
                periods=[c.currentData() for c in self.sequence_period_controls]
                if any(periods) and not all(periods):raise ValueError('请为每个步骤指定周期，或全部沿用研究周期。')
                if all(periods):value['step_timeframes']=periods
                else:value.pop('step_timeframes',None)
            value=default_registry().get(self.factor_id,self.version).parameters(value)
        except (ValueError,TypeError,KeyError) as error:self.status.setText('参数未通过：'+str(error));return
        self.result_value=value;self.accept()


class ResearchConfigDialog(QDialog):
    def __init__(self,parent,value,mode):
        super().__init__(parent);self.setWindowTitle('研究与回测设置');self.resize(800,740)
        self.original=deepcopy(value);self.result_value=None;self.sections={};self.controls={};self.mode=mode
        box=QVBoxLayout(self);self.tabs=QTabWidget();box.addWidget(self.tabs,1)
        self.section('universe','股票资格',{'min_listed_days':0},optional=False)
        self.universe_mode=self.choice('universe','资格口径',[('指定股票','explicit'),('按上市日期筛选（回顾性）','listing'),('按历史可用资格筛选','pit')],value.get('universe',{}).get('mode','explicit'))
        self.reference_manifest=QLineEdit(value.get('universe',{}).get('reference_manifest') or '');self.reference_manifest.setReadOnly(True);self.reference_manifest.setAccessibleName('上市资料来源')
        self.sections['universe'][2].addRow('上市资料来源',self.reference_manifest)
        self.sections['universe'][2].addRow(button('选择 Baostock 归档中的上市资料',self.select_reference))
        self.sections['universe'][2].addRow(button('使用行情目录默认上市资料',self.reference_manifest.clear))
        self.sections['universe'][2].addRow(label('历史资格需要数据中心提供对应记录；缺失资格不会被假定为合格。','note',True))
        self.universe_mode.currentIndexChanged.connect(lambda:self.controls[('universe','min_listed_days')].setEnabled(self.universe_mode.currentData()=='listing'))
        self.controls[('universe','min_listed_days')].setEnabled(self.universe_mode.currentData()=='listing')
        self.section('regime','市场状态',asdict(RegimeConfig()))
        self.regime_filters={}
        for key,title,choices in [('direction','市场方向',[('上涨','Bull'),('下跌','Bear'),('中性','Neutral')]),('structure','结构状态',[('趋势','Trend'),('震荡','Range'),('过渡','Transition')]),('volatility','波动状态',[('低','Low'),('中','Medium'),('高','High')]),('liquidity','流动性',[('低','Low'),('中','Medium'),('高','High')]),('breadth','市场广度',[('扩张','Expansion'),('收缩','Contraction'),('均衡','Balanced')])]:
            self.regime_filters[key]=self.choice('regime',title,[('不限',None)]+choices,value.get('regime_filter',{}).get(key))
        self.section('bootstrap','置信区间',asdict(BootstrapConfig()))
        self.section('permutation','显著性检验',asdict(PermutationConfig()))
        if mode=='execution':
            excluded={'industry_events','corporate_actions','stock_splits','rights_issues','rights_trading','price_mode','corporate_action_mode'}
            self.section('execution','成交与成本',{k:v for k,v in asdict(ExecutionConfig()).items() if k not in excluded},optional=False)
            self.backend=self.choice('execution','成交引擎',[('平台开盘成交引擎','open'),('vn.py 开盘成交引擎','vnpy_open'),('vn.py 历史规则引擎','vnpy_rules')],value.get('execution_backend','open'))
            self.section('portfolio','组合约束',{k:v for k,v in asdict(PortfolioConfig()).items() if k not in {'industry_events','weighting'}},optional=False)
            self.weighting=self.choice('portfolio','资金分配',[('等权','equal'),('按分数','score'),('波动率倒数','inverse_volatility')],value.get('portfolio',{}).get('weighting','equal'))
            for key in ('execution','portfolio'):
                self.sections[key][2].addRow(button('配置'+('实际持仓' if key=='execution' else '目标组合')+'历史行业资料',lambda k=key:self.edit_industry(k)))
        box.addWidget(button('设置因子预处理与历史中性化资料',self.edit_processor))
        box.addWidget(button('设置高周期背景条件',self.edit_context))
        self.status=label('只修改本页支持的设置；导入配置中的其他研究内容完整保留。比例 0.05 表示 5%，费用 1 表示万分之一。','muted',True);box.addWidget(self.status)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.finish);buttons.rejected.connect(self.reject);box.addWidget(buttons)
        for control in self.findChildren(QComboBox):control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def edit_industry(self,key):
        from .action_editor import RecordsDialog
        from quantlab.data.industry import IndustryHistory
        dialog=RecordsDialog(self,'industry_events',self.original.get(key,{}).get('industry_events'),'历史行业归属',IndustryHistory)
        if dialog.exec():self.original.setdefault(key,{})['industry_events']=dialog.result_value or None

    def edit_context(self):
        from .context_editor import ContextDialog
        from PyQt6.QtCore import QDate,Qt
        parent=self.parent();start=parent.start.date() if hasattr(parent,'start') else QDate.currentDate().addYears(-1)
        dialog=ContextDialog(self,self.original.get('context'),start)
        if dialog.exec():
            if dialog.result_value is None:self.original.pop('context',None)
            else:self.original['context']=dialog.result_value
        self.raise_();self.activateWindow()

    def select_reference(self):
        from PyQt6.QtWidgets import QFileDialog
        from quantlab.data.reference_archive import reference_coverage
        path,_=QFileDialog.getOpenFileName(self,'选择 Baostock 资料 manifest.json','','JSON (*.json)')
        if not path:return
        try:coverage=reference_coverage(path)
        except (ValueError,OSError,KeyError,TypeError) as error:self.status.setText('资料不可用：'+str(error));return
        self.reference_manifest.setText(coverage['manifest']);self.universe_mode.setCurrentIndex(self.universe_mode.findData('listing'))
        self.status.setText('已选择归档上市资料。此口径为回顾性；不会将抓取时间改写成历史发布时间。')

    def edit_processor(self):
        from .processor_editor import ProcessorDialog
        from PyQt6.QtCore import QDate,Qt
        parent=self.parent()
        start=parent.start.date() if hasattr(parent,'start') else QDate.currentDate().addYears(-1)
        end=parent.train_end.date() if hasattr(parent,'train_end') else QDate.currentDate()
        dialog=ProcessorDialog(self,self.original.get('processor'),start,end)
        if dialog.exec():
            if dialog.result_value is None:self.original.pop('processor',None)
            else:self.original['processor']=dialog.result_value
        self.raise_();self.activateWindow()

    def section(self,key,title,defaults,optional=True):
        page=QWidget();box=QVBoxLayout(page);enabled=QCheckBox('启用'+title);enabled.setChecked(key in self.original or (key=='regime' and 'regime_filter' in self.original) or not optional);enabled.setVisible(optional);box.addWidget(enabled)
        body=QWidget();form=QFormLayout(body);box.addWidget(body);box.addStretch();body.setEnabled(enabled.isChecked());enabled.toggled.connect(body.setEnabled)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);self.tabs.addTab(scroll,title)
        getters={};current=self.original.get(key,{})
        for name,default in defaults.items():
            val=current.get(name,default)
            if val is not None and name in {'initial_cash','threshold','exposure','commission_bps','minimum_commission','sell_tax_bps','slippage_bps','transfer_bps','max_actual_position','max_actual_exposure'}:val=float(val)
            if default is None:
                active=QCheckBox('设置限制');active.setChecked(val is not None)
                control,getter=control_for(name,val if val is not None else (2 if name=='fee_decimals' else .1));control.setEnabled(active.isChecked());active.toggled.connect(control.setEnabled)
                from .widgets import row
                field=row(active,control);getters[name]=lambda a=active,g=getter:g() if a.isChecked() else None
            else:control,getter=control_for(name,val);field=control;getters[name]=getter
            self.controls[(key,name)]=control;form.addRow(NAMES.get(name,name),field)
        self.sections[key]=(enabled,getters,form)

    def choice(self,key,title,choices,current):
        control=QComboBox()
        for name,value in choices:control.addItem(name,value)
        index=control.findData(current)
        if index<0:raise ValueError(title+'包含无法识别的选项')
        control.setCurrentIndex(index);control.setAccessibleName(title);self.sections[key][2].addRow(title,control);return control

    def collect(self):
        value=deepcopy(self.original)
        for key,(enabled,getters,_) in self.sections.items():
            if enabled.isChecked():value[key]={**value.get(key,{}),**{k:g() for k,g in getters.items()}}
            else:value.pop(key,None)
        value['universe']['mode']=self.universe_mode.currentData()
        if value['universe']['mode']!='listing':value['universe']['min_listed_days']=0
        if value['universe']['mode']=='listing' and self.reference_manifest.text():value['universe']['reference_manifest']=self.reference_manifest.text()
        else:value['universe'].pop('reference_manifest',None)
        if 'regime' in value:
            filters={k:c.currentData() for k,c in self.regime_filters.items() if c.currentData() is not None}
            if filters:value['regime_filter']=filters
            else:value.pop('regime_filter',None)
        else:value.pop('regime_filter',None)
        if self.mode=='execution':
            value['execution_backend']=self.backend.currentData();value['portfolio']['weighting']=self.weighting.currentData()
        return value

    def finish(self):
        from quantlab.data.universe import UniverseConfig
        try:
            value=self.collect();UniverseConfig(**value['universe'])
            for key,klass in [('regime',RegimeConfig),('bootstrap',BootstrapConfig),('permutation',PermutationConfig),('execution',ExecutionConfig),('portfolio',PortfolioConfig)]:
                if key in value:klass(**value[key])
        except (ValueError,TypeError,KeyError) as error:self.status.setText('设置未通过：'+str(error));return
        self.result_value=value;self.accept()

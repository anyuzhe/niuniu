"""Native research configuration dialog; delegates validation/execution to existing core."""
import json
import re
from pathlib import Path
from uuid import uuid4
from PyQt6.QtCore import QDate,Qt
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QLineEdit,QComboBox,QDateEdit,
    QSpinBox,QCheckBox,QPlainTextEdit,QScrollArea,QWidget,QFileDialog,QGroupBox)
from quantlab.workbench.jobs import prepare,JobQueue
from .widgets import label,button,row,raw
from .app import MODES


class ExperimentDialog(QDialog):
    def __init__(self,window,definition=None,mode='single'):
        super().__init__(window);self.window=window;self.job_id=None;self.last_spec=None;self.setWindowTitle('新建研究实验');self.resize(1020,860)
        box=QVBoxLayout(self);box.addWidget(label('新建研究实验','heroTitle'));box.addWidget(label('配置 → 校验 → 本地执行 → 实验归档','muted'))
        scroll=QScrollArea();scroll.setWidgetResizable(True);form_widget=QWidget();form=QFormLayout(form_widget);form.setSpacing(12);scroll.setWidget(form_widget);box.addWidget(scroll,1)
        latest=window.last_records[0] if window.last_records else {}
        self.question=QLineEdit('牛牛桌面因子研究');form.addRow('研究问题',self.question)
        self.symbols=QLineEdit(' '.join(latest.get('symbols',[])));self.symbols.setPlaceholderText('sh.600000 sz.000001');form.addRow('证券代码（空格或逗号分隔）',self.symbols)
        self.start=QDateEdit();self.end=QDateEdit()
        for control,value,fallback in [(self.start,latest.get('start'),QDate.currentDate().addMonths(-1)),(self.end,latest.get('end'),QDate.currentDate())]:
            date=QDate.fromString(value or '', 'yyyy-MM-dd');control.setDate(date if date.isValid() else fallback);control.setDisplayFormat('yyyy-MM-dd');control.setCalendarPopup(True)
        form.addRow('开始日期',self.start);form.addRow('结束日期',self.end)
        self.timeframe=QComboBox();self.timeframe.addItem('日线','1d');self.timeframe.addItem('5 分钟','5m')
        for minutes in (1,15,30,60):self.timeframe.addItem(f'{minutes} 分钟',f'{minutes}m')
        form.addRow('K 线周期',self.timeframe)
        self.adjustment=QComboBox();self.adjustment.addItem('不复权 raw','raw');self.adjustment.addItem('前复权 qfq','qfq');self.adjustment.setCurrentIndex(self.adjustment.findData('qfq'));form.addRow('复权口径',self.adjustment)
        self.target=QComboBox();self.definitions=window.factors+window.theories
        for v in self.definitions:
            d=v.get('definition',v);self.target.addItem(d.get('name_cn',d.get('name',''))+' · '+d.get('factor_id',d.get('template_id','')))
        form.addRow('因子 / 固定研究模板',self.target)
        self.mode=QComboBox()
        for key,title in MODES:self.mode.addItem(title,key)
        self.mode.setCurrentIndex(self.mode.findData(mode));form.addRow('研究方式',self.mode)
        self.price_mode=QComboBox();self.price_mode.addItem('研究价格（默认，与所选复权口径一致）','research');self.price_mode.addItem('精细账户（不复权成交＋公司行动）','account')
        form.addRow('回测价格模式',self.price_mode)
        self.horizons=QLineEdit('1 5 20');form.addRow('未来持有期（K 线根数）',self.horizons)
        self.quantiles=QSpinBox();self.quantiles.setRange(2,100);self.quantiles.setValue(5);form.addRow('分位组数',self.quantiles)
        self.parameters=QPlainTextEdit();self.parameters.setMaximumHeight(115)
        self.parameter_button=button('设置因子参数',self.edit_parameters);form.addRow('因子参数',self.parameter_button)
        self.train_end=QDateEdit(self.start.date().addDays(10));self.valid_end=QDateEdit(self.start.date().addDays(20))
        for c in (self.train_end,self.valid_end):c.setCalendarPopup(True);c.setDisplayFormat('yyyy-MM-dd')
        self.split=row(self.train_end,self.valid_end);form.addRow('训练 / 验证结束日期',self.split)
        self.lengths=[]
        for value in [30,10,10]:
            c=QSpinBox();c.setRange(1,10000);c.setValue(value);self.lengths.append(c)
        self.expanding=QCheckBox('扩展训练窗口（保持历史起点）');self.schedule=row(*self.lengths,self.expanding);form.addRow('滚动训练 / 验证 / 测试自然日',self.schedule)
        self.grid=QLineEdit('{"lookback":[5,10,20]}')
        self.grid_button=button('设置扫描参数与候选值',self.edit_grid);form.addRow('参数扫描',self.grid_button)
        self.replay=QCheckBox('保存 K 线回放');self.replay.setChecked(True);self.audit=QCheckBox('保存序列审计');form.addRow('审计产物',row(self.replay,self.audit))
        self.advanced=QPlainTextEdit('{}');self.advanced.setMaximumHeight(130)
        form.addRow('研究与回测设置',button('设置股票资格、市场状态、统计与交易规则',self.edit_research))
        self.theory_button=button('配置理论拆解、样本外与参数敏感性计划',self.edit_theory);form.addRow('理论全流程',self.theory_button)
        from .corporate_actions import configure_actions
        self.action_config=button('配置公司行动与费用',lambda:configure_actions(self));form.addRow(self.action_config)
        self.expert=QGroupBox('高级配置（查看或编辑原始 JSON）');self.expert.setCheckable(True);self.expert.setChecked(False)
        expert_layout=QVBoxLayout(self.expert);self.expert_body=QWidget();expert_form=QFormLayout(self.expert_body)
        expert_form.addRow('因子参数',self.parameters);expert_form.addRow('扫描网格',self.grid);expert_form.addRow('扩展设置',self.advanced)
        from .config_editor import edit_config
        expert_form.addRow(button('高级字段树编辑',lambda:edit_config(self,self.advanced,'高级研究配置')))
        expert_layout.addWidget(self.expert_body);self.expert_body.hide();self.expert.toggled.connect(self.expert_body.setVisible);form.addRow(self.expert)
        form.addRow(label('行情只读。研究标签与成交收益分开；规则、成本与历史资格来源以保存的配置为准。','note',True))
        self.status=label('尚未校验','muted',True);box.addWidget(self.status)
        self.preview=QPlainTextEdit();self.preview.setReadOnly(True);self.preview.setMaximumHeight(140);self.preview.hide();box.addWidget(self.preview)
        self.validate_button=button('校验并预览配置',self.validate);self.submit_button=button('提交实验',self.submit,True)
        box.addWidget(row(button('导入实验 JSON',self.import_spec),self.validate_button,self.submit_button,button('关闭',self.close)))
        def update():
            current=self.mode.currentData();self.split.setEnabled(current=='holdout');self.schedule.setEnabled(current=='walkforward');self.grid.setEnabled(current=='sweep');self.grid_button.setEnabled(current=='sweep')
            self.action_config.setEnabled(current=='execution');self.theory_button.setEnabled(current=='theory_study')
            self.price_mode.setEnabled(current=='execution')
            self.action_config.setText('配置公司行动与费用' if self.price_mode.currentData()=='account' else '配置历史费用规则')
            self.parameters.setEnabled('definition' in self.definitions[self.target.currentIndex()]);self.parameter_button.setEnabled('definition' in self.definitions[self.target.currentIndex()])
        def select():
            chosen=self.definitions[self.target.currentIndex()];self.parameters.setPlainText(json.dumps(chosen.get('defaults',{}),ensure_ascii=False,indent=2));update()
        self.target.currentIndexChanged.connect(select);self.mode.currentIndexChanged.connect(update)
        self.price_mode.currentIndexChanged.connect(update)
        if definition in self.definitions:self.target.setCurrentIndex(self.definitions.index(definition))
        if mode=='correlation':
            index=next(i for i,v in enumerate(self.definitions) if v.get('definition',{}).get('factor_id')=='COMB.SCORE')
            self.target.setCurrentIndex(index)
        select()
        for control in (self.question,self.symbols,self.horizons,self.grid,self.parameters,self.advanced):
            control.textChanged.connect(self.invalidate_preview)
        for control in (self.start,self.end,self.train_end,self.valid_end):
            control.dateChanged.connect(self.invalidate_preview)
        for control in (self.timeframe,self.adjustment,self.target,self.mode,self.price_mode):
            control.currentIndexChanged.connect(self.invalidate_preview)
        for control in (self.quantiles,*self.lengths):
            control.valueChanged.connect(self.invalidate_preview)
        for control in (self.replay,self.audit,self.expanding):
            control.toggled.connect(self.invalidate_preview)
        if not window.data_root:self.submit_button.setEnabled(False);self.status.setText('未指定数据目录，可校验配置；启动时使用 --data-root 启用执行。')
        for control in self.findChildren(QComboBox):control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def edit_theory(self):
        from .theory_editor import TheoryDialog
        from quantlab.app import default_registry
        from quantlab.theory.templates import resolve_template
        try:
            definition=self.definitions[self.target.currentIndex()];registry=default_registry()
            if 'definition' in definition:
                if not definition['definition']['factor_id'].startswith('COMB.'):raise ValueError('请选择条件或评分组合，再配置理论全流程。')
                params=registry.get(definition['definition']['factor_id'],definition['definition']['version']).parameters(json.loads(self.parameters.toPlainText()))
            else:params,_=resolve_template(definition['template_id'],registry,definition['version'])
            advanced=json.loads(self.advanced.toPlainText())
            dialog=TheoryDialog(self,params,advanced.get('theory_study'),self.start.date(),self.end.date())
            if dialog.exec():advanced['theory_study']=dialog.result_value;self.advanced.setPlainText(json.dumps(advanced,ensure_ascii=False,indent=2))
        except (ValueError,TypeError,KeyError) as error:self.status.setText('理论计划无法打开：'+str(error))
        finally:self.raise_();self.activateWindow()

    def edit_parameters(self):
        from .research_config import ParameterDialog
        try:
            value=json.loads(self.parameters.toPlainText())
            if not isinstance(value,dict):raise ValueError('因子参数必须为对象')
            definition=self.definitions[self.target.currentIndex()]
            if definition.get('definition',{}).get('factor_id','').startswith('COMB.'):
                from .combination_editor import CombinationDialog
                dialog=CombinationDialog(self,definition['definition']['factor_id'],value)
            else:dialog=ParameterDialog(self,definition,value)
            if dialog.exec():self.parameters.setPlainText(json.dumps(dialog.result_value,ensure_ascii=False,indent=2))
        except (ValueError,TypeError) as error:self.status.setText('参数无法打开：'+str(error))
        finally:self.raise_();self.activateWindow()

    def edit_research(self):
        from .research_config import ResearchConfigDialog
        try:
            value=json.loads(self.advanced.toPlainText())
            if not isinstance(value,dict):raise ValueError('扩展设置必须为对象')
            dialog=ResearchConfigDialog(self,value,self.mode.currentData())
            if dialog.exec():self.advanced.setPlainText(json.dumps(dialog.result_value,ensure_ascii=False,indent=2))
        except (ValueError,TypeError) as error:self.status.setText('设置无法打开：'+str(error))
        finally:self.raise_();self.activateWindow()

    def edit_grid(self):
        from .grid_editor import GridDialog
        try:
            dialog=GridDialog(self,self.definitions[self.target.currentIndex()],json.loads(self.grid.text()))
            if dialog.exec():self.grid.setText(json.dumps(dialog.result_value,ensure_ascii=False))
        except (ValueError,TypeError) as error:self.status.setText('扫描设置无法打开：'+str(error))
        finally:self.raise_();self.activateWindow()

    def invalidate_preview(self):
        self.preview.clear();self.preview.hide()
        self.status.setText('配置已修改，请重新校验。'+(' 未指定行情数据目录，暂不能执行。' if not self.window.data_root else ''))

    def import_spec(self):
        path,_=QFileDialog.getOpenFileName(self,'导入实验配置','','JSON (*.json)')
        if not path:return
        try:self.apply_spec(json.loads(Path(path).read_text(encoding='utf-8')))
        except Exception as exc:self.status.setText('导入失败：'+str(exc))

    def apply_spec(self,spec):
        prepared=prepare(spec)
        wanted=spec.get('theory',spec.get('factor','BASE.MOMENTUM'))
        version=spec.get('theory_version',spec.get('version','1.0.0'))
        index=next((i for i,v in enumerate(self.definitions) if v.get('definition',v).get('factor_id',v.get('template_id'))==wanted and v.get('definition',v).get('version')==version),None)
        if index is None:raise ValueError('客户端未注册此因子或模板')
        if not self.quantiles.minimum()<=prepared.config.quantiles<=self.quantiles.maximum():raise ValueError('分位组数超出客户端表单范围')
        if prepared.schedule and any(not c.minimum()<=spec['schedule'][k]<=c.maximum() for c,k in zip(self.lengths,('train_days','valid_days','test_days'))):raise ValueError('滚动天数超出客户端表单范围')
        self.target.setCurrentIndex(index);self.mode.setCurrentIndex(self.mode.findData(prepared.mode))
        self.question.setText(prepared.config.research_question);self.symbols.setText(' '.join(spec['symbols']))
        self.start.setDate(QDate.fromString(spec['start'],'yyyy-MM-dd'));self.end.setDate(QDate.fromString(spec['end'],'yyyy-MM-dd'))
        self.timeframe.setCurrentIndex(self.timeframe.findData(spec.get('timeframe','1d')))
        self.adjustment.setCurrentIndex(self.adjustment.findData(prepared.adjustment))
        self.price_mode.setCurrentIndex(self.price_mode.findData(prepared.execution.price_mode if prepared.execution else 'research'))
        self.horizons.setText(' '.join(map(str,spec.get('horizons',[1,5,20]))));self.quantiles.setValue(spec.get('quantiles',5))
        self.parameters.setPlainText(json.dumps(spec.get('parameters',{}),ensure_ascii=False,indent=2))
        self.replay.setChecked(spec.get('replay',False));self.audit.setChecked(spec.get('sequence_audit',False))
        if prepared.split:
            self.train_end.setDate(QDate.fromString(spec['split']['train_end'],'yyyy-MM-dd'));self.valid_end.setDate(QDate.fromString(spec['split']['valid_end'],'yyyy-MM-dd'))
        if prepared.schedule:
            self.expanding.setChecked(prepared.schedule.expanding)
            for control,key in zip(self.lengths,('train_days','valid_days','test_days')):control.setValue(spec['schedule'][key])
        if prepared.grid:self.grid.setText(json.dumps(spec['grid'],ensure_ascii=False))
        fields={'question','symbols','start','end','timeframe','adjustment','mode','factor','version','parameters','theory','theory_version','horizons','quantiles','replay','sequence_audit','split','schedule','grid'}
        if prepared.mode=='correlation':fields-= {'split','schedule'}
        self.advanced.setPlainText(json.dumps({k:v for k,v in spec.items() if k not in fields},ensure_ascii=False,indent=2))
        self.invalidate_preview();self.status.setText('配置已导入，请核对股票、日期和成本后校验提交。')

    def collect(self):
        advanced=json.loads(self.advanced.toPlainText())
        if not isinstance(advanced,dict):raise ValueError('扩展配置必须是 JSON 对象')
        protected={'question','symbols','start','end','timeframe','adjustment','mode','factor','version','parameters','theory','theory_version','horizons','quantiles','replay','sequence_audit'}
        if protected.intersection(advanced):raise ValueError('扩展 JSON 不得覆盖表单字段：'+', '.join(sorted(protected.intersection(advanced))))
        spec={**advanced,'question':self.question.text().strip(),'symbols':[v for v in re.split(r'[\s,，]+',self.symbols.text().strip()) if v],
            'start':self.start.date().toString('yyyy-MM-dd'),'end':self.end.date().toString('yyyy-MM-dd'),
            'timeframe':self.timeframe.currentData(),'adjustment':self.adjustment.currentData(),'mode':self.mode.currentData(),
            'horizons':[int(v) for v in re.split(r'[\s,，]+',self.horizons.text().strip()) if v],
            'quantiles':self.quantiles.value(),'replay':self.replay.isChecked(),'sequence_audit':self.audit.isChecked()}
        if not spec['question']:raise ValueError('请填写研究问题')
        if spec['mode']=='execution':spec['execution']={**spec.get('execution',{}),'price_mode':self.price_mode.currentData()}
        chosen=self.definitions[self.target.currentIndex()]
        if 'definition' in chosen:spec.update(factor=chosen['definition']['factor_id'],version=chosen['definition']['version'],parameters=json.loads(self.parameters.toPlainText()))
        else:spec.update(theory=chosen['template_id'],theory_version=chosen['version'])
        if spec['mode']=='holdout':spec['split']={'train_end':self.train_end.date().toString('yyyy-MM-dd'),'valid_end':self.valid_end.date().toString('yyyy-MM-dd')}
        if spec['mode']=='walkforward':spec['schedule']={**dict(zip(('train_days','valid_days','test_days'),[c.value() for c in self.lengths])),'expanding':self.expanding.isChecked()}
        if spec['mode']=='sweep':spec['grid']=json.loads(self.grid.text())
        return spec

    def validate(self):
        try:
            spec=self.collect();result=prepare(spec)
            universe_name={'explicit':'指定股票','listing':'按上市日期筛选（回顾性）','pit':'历史可用资格'}.get(result.universe.mode,result.universe.mode)
            summary=[self.question.text(),f'证券：{len(result.config.data.symbols)} 只　期间：{spec["start"]} 至 {spec["end"]}',f'方式：{self.mode.currentText()}　周期：{self.timeframe.currentText()}　价格：{self.adjustment.currentText()}',f'因子：{self.target.currentText()}',f'持有期：{self.horizons.text()}　分位组：{self.quantiles.value()}',f'股票资格：{universe_name}　保存回放：{"是" if result.config.replay else "否"}']
            if result.execution:summary.append(f'初始资金：{result.execution.initial_cash:,.2f} 元　最多入选：{result.execution.top_n} 只　佣金：{result.execution.commission_bps} 万分之一　滑点：{result.execution.slippage_bps} 万分之一')
            self.preview.setPlainText('\n'.join(summary));self.preview.show();self.status.setText('配置校验通过。尚未读取行情或执行实验。');return True
        except Exception as exc:
            self.preview.clear();self.preview.hide();self.status.setText('配置错误：'+str(exc));return False

    def submit(self):
        if not self.validate():return
        spec=self.collect()
        if not self.window.data_root:self.status.setText('请指定行情数据目录。');return
        if spec!=self.last_spec:self.job_id=str(uuid4());self.last_spec=spec
        self.submit_button.setEnabled(False);self.status.setText('正在提交…')
        job_id=self.job_id
        def execute():
            self.window.get_research_queue()
            return self.window.queue.submit(job_id,spec)
        def done(data,error):
            self.submit_button.setEnabled(True)
            if error:self.status.setText('提交失败：'+error);return
            self.status.setText('任务已提交：'+data['job_id']+'；可在“运行任务”查看结果。')
        self.window.async_call(execute,done,guarded=False)

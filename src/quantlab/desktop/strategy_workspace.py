"""Host-only strategy editor and descriptive comparisons; no approval or execution."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from pathlib import Path
import re
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QGroupBox, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QScrollArea, QTabWidget, QVBoxLayout, QWidget)
from quantlab.agent.planning import parse_spec
from quantlab.agent.strategy_package_cli import _read_package
from quantlab.app import default_registry
from quantlab.storage.codec import encode
from quantlab.theory.templates import templates
from quantlab.trading.strategy_package import FORMAT, LIFECYCLE, compile_strategy
from .business_view import BusinessDetails
from .widgets import button, label, row

EXECUTION_FIELDS = (
    ('initial_cash', '初始资金', float), ('top_n', '最多入选数量', int),
    ('threshold', '信号阈值（严格大于）', float), ('exposure', '目标敞口（0–1）', float),
    ('lot_size', '每手股数', int), ('commission_bps', '佣金（万分之一）', float),
    ('minimum_commission', '最低佣金', float), ('sell_tax_bps', '卖出税费（万分之一）', float),
    ('transfer_bps', '过户费（万分之一）', float), ('slippage_bps', '滑点（万分之一）', float))
PORTFOLIO_FIELDS = (
    ('max_position', '单股目标上限（0–1）', float),
    ('max_exposure', '组合目标上限（0–1）', float),
    ('max_turnover', '目标换手上限（空值为不限制）', float))

class StrategyWorkspaceDialog(QDialog):
    """Edit a private draft and return it to the existing human proposal gate."""
    def __init__(self, parent, host, package=None):
        super().__init__(parent)
        self.host = host; self.output = Path(host.output)
        self.result_package = self.result_compiled_hash = self.compiled = self.baseline = None
        self._loading = False; self.busy = False
        self._archive_generation = 0; self._archive_page = None
        self.revision_origin = None
        self._base = {'format': FORMAT, 'strategy_key': '', 'name': '', 'version': '',
            'lifecycle': dict(LIFECYCLE), 'spec': {'mode': 'execution', 'replay': True,
            'qualification': 'research_only', 'execution': {}, 'portfolio': {}}}
        self.setWindowTitle('策略配置 · 版本与结果对照'); self.resize(1120, 880)
        box = QVBoxLayout(self); box.addWidget(label('策略工作台', 'heroTitle'))
        box.addWidget(label('编辑、比较、预览均不执行。v1仅研究口径，按完结K线重算目标；'
            '不支持独立止损止盈、固定持有或期末强平。', 'note', True))
        self.tabs = QTabWidget(); box.addWidget(self.tabs, 1)
        self._make_editor(); self._make_versions(); self._make_results()
        self.status = label('请导入已有策略包，或明确填写必填配置；不自动选择证券、日期和资金。', 'muted', True)
        box.addWidget(self.status)
        self.import_button = button('导入策略包', self.import_dialog)
        self.preview_button = button('校验并预览', self.validate_preview)
        self.export_button = button('另存策略包（不覆盖）', self.export_dialog)
        self.use_button = button('填入待审批草稿（不执行）', self.finish, True); self.use_button.setEnabled(False)
        box.addWidget(row(self.import_button, self.preview_button, self.export_button, self.use_button, button('关闭', self.reject)))
        if package is not None: self.apply_package(package)

    @staticmethod
    def _combo(items):
        control = QComboBox()
        for title, value in items: control.addItem(title, value)
        return control

    def _make_editor(self):
        page = QWidget(); layout = QVBoxLayout(page)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        body = QWidget(); form = QFormLayout(body); scroll.setWidget(body); layout.addWidget(scroll, 1)
        self.identity = {}; self.scope = {}
        for fields, target in [([('strategy_key','策略固定标识'),('name','策略名称'),('version','策略版本标签')], self.identity),
            ([('question','研究问题'),('symbols','证券代码（空格分隔）'),('start','开始日期 YYYY-MM-DD'),('end','结束日期 YYYY-MM-DD')], self.scope)]:
            for key, title in fields:
                field = QLineEdit(); target[key] = field; form.addRow(title, field); field.textChanged.connect(self.invalidate)
        self.timeframe = self._combo([(v, v) for v in ('1d','1m','5m','15m','30m','60m')])
        self.adjustment = self._combo([('前复权 qfq','qfq'),('不复权 raw','raw')])
        form.addRow('K线周期', self.timeframe); form.addRow('信号价格', self.adjustment)
        self.signal = QComboBox(); self.signal.addItem('请选择精确因子或模板', None)
        for entry in default_registry().describe():
            definition = entry['definition'] if isinstance(entry, dict) else entry.definition
            definition = asdict(definition) if is_dataclass(definition) else definition
            fid, version = definition['factor_id'], definition['version']
            self.signal.addItem(definition['name_cn']+' · '+fid+'@'+version, ('factor',fid,version))
        for entry in templates():
            self.signal.addItem(entry['name']+' · '+entry['template_id']+'@'+entry['version'],
                ('theory',entry['template_id'],entry['version']))
        form.addRow('精确因子 / 组合模板', self.signal)
        self.parameters = QPlainTextEdit('{}'); self.parameters.setMaximumHeight(100)
        form.addRow('因子参数（模板规则不可覆盖）', self.parameters)
        self.parameters.textChanged.connect(self.invalidate); self.signal.currentIndexChanged.connect(self._signal_changed)
        self.execution = {}; self.portfolio = {}
        for fields, target, title in [(EXECUTION_FIELDS,self.execution,'资金、选股和费用'),(PORTFOLIO_FIELDS,self.portfolio,'目标组合约束')]:
            group = QGroupBox(title); inner = QFormLayout(group)
            for key, caption, _ in fields:
                field = QLineEdit(); target[key] = field; inner.addRow(caption,field); field.textChanged.connect(self.invalidate)
            form.addRow(group)
        self.weighting = self._combo([('等权','equal'),('评分权重','score'),('波动率倒数','inverse_volatility')])
        self.price_mode = self._combo([('研究价格','research'),('精细账户 raw 成交','account')])
        self.t_plus_one = QCheckBox('遵循 T+1'); self.t_plus_one.setChecked(True)
        self.statutory_fees = QCheckBox('按原引擎逐日法定费用规则提高税费下限')
        form.addRow('权重方式',self.weighting); form.addRow('成交价格模式',self.price_mode)
        form.addRow(self.t_plus_one); form.addRow(self.statutory_fees)
        form.addRow(button('编辑完整配置树（保留高级字段）', self.edit_tree))
        form.addRow(label('已导入的高级设置原样保留。数值输入是配置，不是推荐；目标限制不保证实际持仓永远满足。','muted',True))
        for c in (self.timeframe,self.adjustment,self.weighting,self.price_mode): c.currentIndexChanged.connect(self.invalidate)
        for c in (self.t_plus_one,self.statutory_fees): c.toggled.connect(self.invalidate)
        self.revision_note = label('当前草稿未从历史归档载入。', 'muted', True)
        layout.addWidget(self.revision_note)
        self.preview = BusinessDetails({}); layout.addWidget(self.preview)
        self.tabs.addTab(page,'配置编辑')

    def _make_versions(self):
        page = QWidget(); layout = QVBoxLayout(page)
        layout.addWidget(label('以载入的原版本或指定策略包为基线，比较当前草稿。同名同版本内容不同会警告，不自动改版本。','note',True))
        self.baseline_label = label('尚无对照基线','muted',True); layout.addWidget(self.baseline_label)
        self.origin_details = BusinessDetails({}); layout.addWidget(self.origin_details)
        layout.addWidget(row(button('选择对照策略包',self.import_baseline),button('比较当前草稿',self.compare_versions)))
        self.version_details = BusinessDetails({}); layout.addWidget(self.version_details,1); self.tabs.addTab(page,'版本差异')

    def _make_results(self):
        page = QWidget(); layout = QVBoxLayout(page)
        layout.addWidget(label('查找本工作空间策略归档并选到左右两侧，也可手填UUID。目录仅核验元信息；详情与比较会重新核验完整归档，不判定赢家。','note',True))
        self.archive_query = QLineEdit(); self.archive_query.setPlaceholderText('按策略名称、版本、标识或研究问题查找')
        self.archive_search_button = button('查找 / 刷新归档', lambda: self.load_archives(0))
        self.archive_next_button = button('下一页候选', self.next_archive_page); self.archive_next_button.setEnabled(False)
        layout.addWidget(row(self.archive_query, self.archive_search_button, self.archive_next_button))
        self.archive_list = QListWidget(); self.archive_list.setMaximumHeight(160)
        self.archive_list.setAccessibleName('策略归档目录（元信息）'); layout.addWidget(self.archive_list)
        self.archive_note = label('尚未读取归档。查找不读取数据根，不创建研究或自动挑选收益最高的结果。','muted',True)
        layout.addWidget(self.archive_note)
        self.archive_left_button = button('选到左侧', lambda: self.choose_archive('left'))
        self.archive_right_button = button('选到右侧', lambda: self.choose_archive('right'))
        self.archive_inspect_button = button('核验选中归档', self.inspect_archive)
        layout.addWidget(row(self.archive_left_button,self.archive_right_button,self.archive_inspect_button))
        self.archive_edit_button = button('载入为可编辑副本（不执行）', self.edit_archived_strategy)
        layout.addWidget(self.archive_edit_button)
        self.archive_query.textChanged.connect(self.invalidate_archive_listing)
        self.archive_query.returnPressed.connect(lambda: self.load_archives(0))
        self.archive_list.currentItemChanged.connect(self.archive_selection_changed)
        self.archive_selection_changed()
        form = QFormLayout(); self.left_run = QLineEdit(); self.right_run = QLineEdit()
        form.addRow('左侧实验 run_id',self.left_run); form.addRow('右侧实验 run_id',self.right_run); layout.addLayout(form)
        layout.addWidget(button('读取并核对结果',self.compare_results))
        self.result_details = BusinessDetails({}); layout.addWidget(self.result_details,1)
        self.left_run.textChanged.connect(self._clear_results); self.right_run.textChanged.connect(self._clear_results)
        self.tabs.addTab(page,'结果对照')

    def done(self, result):
        # Closing a dialog does not necessarily delete it before a worker returns.
        # Invalidate pending reads so a cancelled draft cannot be replaced later.
        self._archive_generation += 1
        super().done(result)

    def invalidate_archive_listing(self, *_):
        self._archive_generation += 1; self._archive_page = None
        self.archive_list.clear(); self.archive_next_button.setEnabled(False)
        self.archive_note.setText('查询已修改，请重新查找；旧列表不再用于选择。')
        self.archive_selection_changed()

    def archive_selection_changed(self, *_):
        item = self.archive_list.currentItem()
        record = item.data(Qt.ItemDataRole.UserRole) if item else None
        enabled = not self.busy and bool(record) and record.get('status') == 'completed'
        for control in (self.archive_left_button,self.archive_right_button,self.archive_inspect_button,self.archive_edit_button):
            control.setEnabled(enabled)

    def _archive_read(self, work, done):
        if self.busy: return
        generation = self._archive_generation; self.busy = True; self.tabs.setEnabled(False)
        for control in (self.import_button,self.preview_button,self.export_button,self.use_button): control.setEnabled(False)
        self.archive_selection_changed()
        def finished(value, error):
            if sip.isdeleted(self): return
            self.busy = False; self.tabs.setEnabled(True)
            for control in (self.import_button,self.preview_button,self.export_button): control.setEnabled(True)
            self.use_button.setEnabled(self.compiled is not None)
            if generation != self._archive_generation:
                self.status.setText('查询已变化，忽略旧查询返回值，请重新查找。')
            elif error:
                self.result_details.setPlainText('{}'); self.status.setText('归档读取失败：'+str(error))
                self.archive_note.setText('读取未完成，不将失败解释为空目录。')
            else: done(value)
            self.archive_selection_changed()
        try: self.host.async_call(work,finished,guarded=False)
        except Exception as error: finished(None,str(error))

    def load_archives(self, offset=0):
        if self.busy: return
        from quantlab.trading.strategy_run_catalog import list_strategy_runs
        query = self.archive_query.text()
        self.archive_list.clear(); self._archive_page = None; self.archive_next_button.setEnabled(False)
        self.archive_note.setText('正在读取有界归档目录…')
        def loaded(value):
            self._archive_page = value
            for record in value['runs']:
                state = '已完成（未深验）' if record['status']=='completed' else record['status']+'（不可选作结果）'
                item = QListWidgetItem(record['name']+' @ '+record['version']+' · '+state+' · '+record['run_id'])
                item.setData(Qt.ItemDataRole.UserRole,record); self.archive_list.addItem(item)
            self.archive_next_button.setEnabled(bool(value.get('has_more')) and value.get('next_offset') is not None)
            message = f"本页发现 {len(value['runs'])} 条；仅元信息核验。"
            if value.get('has_more'): message += ' 仍有候选，请使用下一页；当前不是完整匹配总数。'
            if value.get('incomplete'):
                message += ' 目录不完整：' + str(len(value.get('errors',[]))) + ' 项错误。'
                message += ' ' + '; '.join(str(e.get('run_id',''))+': '+str(e.get('message',e.get('reason',e.get('error','读取失败')))) for e in value.get('errors',[])[:3])
            self.archive_note.setText(message); self.status.setText('本页目录读取完成；失败归档保留，核验及对照不会自动执行研究。')
        self._archive_read(lambda:list_strategy_runs(self.output,query=query,offset=offset,limit=20),loaded)

    def next_archive_page(self):
        if self._archive_page and self._archive_page.get('has_more'):
            offset = self._archive_page.get('next_offset')
            if offset is not None: self.load_archives(offset)

    def choose_archive(self, side):
        if self.busy: return
        item = self.archive_list.currentItem(); record = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not record or record.get('status')!='completed': return
        target = self.left_run if side=='left' else self.right_run
        target.setText(record['run_id'])
        self.status.setText('已选择实验编号，尚未核验完整归档；点击读取并核对结果。')

    def inspect_archive(self):
        if self.busy: return
        item = self.archive_list.currentItem(); record = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not record or record.get('status')!='completed': return
        from quantlab.trading.strategy_run_catalog import get_strategy_run
        self.result_details.setPlainText('{}')
        def loaded(value):
            self.result_details.setPlainText(encode(value))
            self.status.setText('归档内部一致性已核验；这是历史证据，不代表Alpha、重新运行或批准。')
        self._archive_read(lambda:get_strategy_run(self.output,record['run_id']),loaded)

    def edit_archived_strategy(self):
        if self.busy: return
        item = self.archive_list.currentItem()
        record = deepcopy(item.data(Qt.ItemDataRole.UserRole)) if item else None
        if not record or record.get('status') != 'completed': return
        answer = QMessageBox.question(self, '载入历史策略副本',
            '核验所选归档后，将替换当前工作台中尚未保存的草稿。\n'
            '原归档、结果和批准均不修改，也不会自动执行。是否继续？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes: return
        from quantlab.trading.strategy_run_catalog import prepare_strategy_revision
        def loaded(value):
            try:
                self.apply_package(value['compiled']['package'],
                    expected_compiled_hash=value['compiled']['compiled_spec_hash'])
                self.revision_origin = deepcopy(value)
                self.origin_details.setPlainText(encode({'historical_source': value['source'],
                    'historical_package': value['historical_package'],
                    'current_compiled_spec_hash_on_load': value['compiled']['compiled_spec_hash'],
                    'current_matches_history_on_load': value['current_matches_history'],
                    'warnings': value['warnings']}))
                identity = value['source']['package_identity']
                self.revision_note.setText('来自历史实验 ' + value['source']['run_id'] + ' · '
                    + identity['strategy_key'] + ' @ ' + identity['version']
                    + '；仅本次编辑保留来源说明，新草稿不继承历史批准。'
                    + (' 当前编译指纹不同，请明确新版本。' if not value['current_matches_history'] else ' 请重新预览。'))
                self.tabs.setCurrentIndex(0)
                self.status.setText('历史配置副本已载入，未保存、未批准、未执行；历史证据见版本差异页。')
            except (ValueError,TypeError,KeyError,OSError) as error:
                self.status.setText('历史副本未载入，原草稿保留：' + str(error))
        self._archive_read(lambda: prepare_strategy_revision(self.output, record['run_id'],
            expected_package_hash=record['package_hash']), loaded)

    def _check_revision_identity(self, compiled):
        if self.revision_origin is None: return
        source = self.revision_origin['source']['package_identity']
        current = compiled['package']
        if (current['strategy_key'] == source['strategy_key'] and current['version'] == source['version']
                and compiled['compiled_spec_hash'] != source['compiled_spec_hash']):
            raise ValueError('历史策略的配置或信号实现已变化；请填写新的策略版本，或明确使用新的策略标识。')

    def invalidate(self, *_):
        if self._loading: return
        self.compiled = None
        if hasattr(self,'use_button'): self.use_button.setEnabled(False)
        for name in ('preview','version_details'):
            if hasattr(self,name): getattr(self,name).setPlainText('{}')
        if hasattr(self,'status'): self.status.setText('草稿已修改，请重新预览。旧批准及已运行结果不会被修改。')

    def _signal_changed(self, *_):
        selected = self.signal.currentData()
        self.parameters.setEnabled(selected is not None and selected[0]=='factor')
        if not self._loading:
            try:
                params = default_registry().get(selected[1],selected[2]).parameters({}) if selected and selected[0]=='factor' else {}
                self.parameters.setPlainText(encode(params))
            except (ValueError,TypeError,KeyError):
                self.parameters.setPlainText('{}')  # Parameterized combinations require user-supplied inputs.
        self.invalidate()

    def apply_package(self, package, *, baseline=True, expected_compiled_hash=None):
        compiled = compile_strategy(package)
        if expected_compiled_hash is not None and compiled['compiled_spec_hash'] != expected_compiled_hash:
            raise ValueError('信号源码或配置在载入期间变化，请重新核验；原草稿保留。')
        normalized = compiled['package']; spec = normalized['spec']
        selected = ('theory',spec['theory'],spec['theory_version']) if 'theory' in spec else ('factor',spec['factor'],spec['version'])
        # QVariant does not reliably compare Python tuple objects by value.
        index = next((i for i in range(self.signal.count())
                      if tuple(self.signal.itemData(i) or ()) == selected), -1)
        if index<0: raise ValueError('当前界面未找到精确信号版本，原草稿保留。')
        selections = [(c, c.findData(v)) for c,v in [(self.timeframe,spec['timeframe']),
            (self.adjustment,spec['adjustment']),(self.weighting,spec['portfolio']['weighting']),
            (self.price_mode,spec['execution']['price_mode'])]]
        if any(i < 0 for _,i in selections):
            raise ValueError('当前界面不支持该配置选项，原草稿保留。')
        self._loading = True
        try:
            self._base = deepcopy(normalized)
            for k,c in self.identity.items(): c.setText(normalized[k])
            for k,c in self.scope.items(): c.setText(' '.join(spec[k]) if k=='symbols' else spec[k])
            for c,i in selections: c.setCurrentIndex(i)
            self.signal.setCurrentIndex(index); self.parameters.setEnabled(selected[0]=='factor')
            self.parameters.setPlainText(encode(spec.get('parameters',{})))
            for fields,controls,values in [(EXECUTION_FIELDS,self.execution,spec['execution']),(PORTFOLIO_FIELDS,self.portfolio,spec['portfolio'])]:
                for k,_,_ in fields: controls[k].setText('' if values[k] is None else str(values[k]))
            self.t_plus_one.setChecked(spec['execution']['t_plus_one']); self.statutory_fees.setChecked(spec['execution']['statutory_fees'])
            if baseline:
                self.baseline = deepcopy(normalized)
                self.revision_origin = None
                self.revision_note.setText('当前草稿未从历史归档载入。')
                self.origin_details.setPlainText('{}')
                self.baseline_label.setText(normalized['name']+' @ '+normalized['version']+' · '+compiled['package_hash'])
        finally: self._loading = False
        self.invalidate(); self.status.setText('已载入可编辑副本；原文件、历史提案和结果均未修改。')

    def collect_package(self):
        value = deepcopy(self._base); spec = value['spec']
        for k,c in self.identity.items(): value[k] = c.text()
        for k,c in self.scope.items(): spec[k] = [v for v in re.split(r'[\s,，]+',c.text().strip()) if v] if k=='symbols' else c.text().strip()
        selected = self.signal.currentData()
        if not selected: raise ValueError('请先选择精确因子或模板。')
        for k in ('factor','version','parameters','theory','theory_version'): spec.pop(k,None)
        if selected[0]=='factor': spec.update(factor=selected[1],version=selected[2],parameters=parse_spec(self.parameters.toPlainText()))
        else: spec.update(theory=selected[1],theory_version=selected[2])
        spec.update(timeframe=self.timeframe.currentData(),adjustment=self.adjustment.currentData())
        for fields,controls,values in [(EXECUTION_FIELDS,self.execution,spec['execution']),(PORTFOLIO_FIELDS,self.portfolio,spec['portfolio'])]:
            for k,title,cast in fields:
                text = controls[k].text().strip()
                if k=='max_turnover' and not text: values[k] = None; continue
                if not text: raise ValueError('请明确填写：'+title)
                if k in values and text==str(values[k]): continue  # Preserve exact int/float identity on no-op edits.
                try: values[k] = cast(text)
                except ValueError as exc: raise ValueError(title+' 的数值格式无效') from exc
        spec['execution'].update(t_plus_one=self.t_plus_one.isChecked(),statutory_fees=self.statutory_fees.isChecked(),price_mode=self.price_mode.currentData())
        spec['portfolio']['weighting'] = self.weighting.currentData()
        return value

    def validate_preview(self):
        try:
            self.compiled = compile_strategy(self.collect_package())
            self._check_revision_identity(self.compiled)
            self.preview.setPlainText(encode(self.compiled))
            self.use_button.setEnabled(True); self.status.setText('配置校验通过，未检查正式数据或创建任务。编译指纹：'+self.compiled['compiled_spec_hash']); return True
        except (ValueError,TypeError,KeyError,OSError) as error:
            self.compiled = None; self.use_button.setEnabled(False); self.preview.setPlainText('{}')
            self.status.setText('校验未通过：'+str(error)); return False

    def finish(self):
        if self.busy: return
        try:
            current = compile_strategy(self.collect_package())
            self._check_revision_identity(current)
            if self.compiled is None or current['compiled_spec_hash']!=self.compiled['compiled_spec_hash']:
                raise ValueError('配置或信号源码已变化，请先重新预览。')
            self.result_package = deepcopy(current['package']); self.result_compiled_hash = current['compiled_spec_hash']; self.accept()
        except (ValueError,TypeError,KeyError,OSError) as error:
            self.invalidate(); self.status.setText('未填入：'+str(error))

    def import_dialog(self):
        if self.busy: return
        path,_ = QFileDialog.getOpenFileName(self,'导入策略包','','JSON (*.json)')
        if path:
            try: self.apply_package(_read_package(Path(path)))
            except (ValueError,TypeError,KeyError,OSError) as error: self.status.setText('导入失败，原草稿保留：'+str(error))

    def save_package(self,path):
        compiled = compile_strategy(self.collect_package())
        self._check_revision_identity(compiled)
        if self.compiled is None or compiled['compiled_spec_hash']!=self.compiled['compiled_spec_hash']:
            raise ValueError('请先预览当前配置，再另存。')
        with Path(path).open('x',encoding='utf-8') as stream: stream.write(encode(compiled['package'])+'\n')
        return compiled['package_hash']

    def export_dialog(self):
        if self.busy: return
        path,_ = QFileDialog.getSaveFileName(self,'另存策略包（不覆盖已有文件）','','JSON (*.json)')
        if path:
            try: self.status.setText('已另存，未创建提案或任务：'+self.save_package(path))
            except (ValueError,TypeError,KeyError,OSError) as error: self.status.setText('未另存：'+str(error))

    def edit_tree(self):
        from .config_editor import ConfigEditor
        try:
            editor = ConfigEditor(self,self.collect_package(),'完整策略配置树')
            if editor.exec(): self.apply_package(editor.result_value,baseline=False)
        except (ValueError,TypeError,KeyError,OSError) as error: self.status.setText('配置树未应用：'+str(error))

    def import_baseline(self):
        path,_ = QFileDialog.getOpenFileName(self,'选择对照策略包','','JSON (*.json)')
        if path:
            try:
                compiled = compile_strategy(_read_package(Path(path))); self.baseline = compiled['package']
                self.baseline_label.setText(self.baseline['name']+' @ '+self.baseline['version']+' · '+compiled['package_hash'])
                self.version_details.setPlainText('{}')
            except (ValueError,TypeError,KeyError,OSError) as error: self.status.setText('对照基线未改变：'+str(error))

    def compare_versions(self):
        try:
            if self.baseline is None: raise ValueError('请先载入或选择对照基线。')
            from quantlab.trading.strategy_comparison import compare_strategy_packages
            result = compare_strategy_packages(self.baseline,self.collect_package())
            self.version_details.setPlainText(encode(result)); self.status.setText('版本差异已核对；不代表新版本更好，不自动修改版本。')
        except (ValueError,TypeError,KeyError,OSError) as error:
            self.version_details.setPlainText('{}'); self.status.setText('版本未比较：'+str(error))

    def _clear_results(self,*_): self.result_details.setPlainText('{}')

    def compare_results(self):
        if self.busy: return
        from quantlab.trading.strategy_comparison import compare_strategy_runs
        left,right = self.left_run.text().strip(),self.right_run.text().strip()
        self.result_details.setPlainText('{}'); self.busy = True
        self.tabs.setEnabled(False)
        for c in (self.import_button,self.preview_button,self.export_button,self.use_button): c.setEnabled(False)
        self.status.setText('正在只读核对两个归档的身份、输入和结果…')
        def finished(value,error):
            if sip.isdeleted(self): return
            self.busy = False; self.tabs.setEnabled(True)
            for c in (self.import_button,self.preview_button,self.export_button): c.setEnabled(True)
            self.use_button.setEnabled(self.compiled is not None)
            if error:
                self.result_details.setPlainText('{}'); self.status.setText('结果核对失败：'+str(error)); return
            self.result_details.setPlainText(encode(value))
            self.status.setText('口径一致，仅描述性对照，不代表Alpha。' if value.get('comparable') else '结果不可直接比较，请查看阻塞原因，不据此判断优劣。')
        try: self.host.async_call(lambda:compare_strategy_runs(self.output,left,right),finished,guarded=False)
        except Exception as error: finished(None,str(error))

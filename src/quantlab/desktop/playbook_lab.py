"""Native host-managed Expert Playbook Lab browser and strict JSON importer."""
import json
from uuid import uuid4

from PyQt6.QtWidgets import QComboBox,QDialog,QDialogButtonBox,QPlainTextEdit,QTabWidget,QVBoxLayout,QWidget

from quantlab.storage.codec import encode
from quantlab.trading.playbook_store import PlaybookError,PlaybookStore
from .business_view import BusinessDetails
from .widgets import button,kpis,label,row,table


KINDS=[
    ('StrategySource','strategy_source'),('PlaybookSourceLink','source_link'),('ExpertSource（兼容）','source'),
    ('PlaybookDefinition','definition'),('PlaybookCase','case'),
    ('CandidateSet','candidate'),('SelectionDecision','selection'),('PlaybookValidation','validation'),
]

TEMPLATES={
    'strategy_source':{'source_key':'my-trading-note','source_kind':'USER_EXPERIENCE','title':'','locator':'local:note',
        'published_at':None,'available_at':None,'content_hash':'','archive_ref':'','completeness':'PENDING',
        'notes':'StrategySource只是来源；需要链接到Playbook并继续验证。','evidence_ids':[]},
    'source_link':{'definition_id':'<UUID>','strategy_source_id':'<UUID>','relation':'SUPPORT',
        'notes':'来源与Playbook的证据关系；不会自动改变规则状态。','evidence_ids':[]},
    'source':{'expert_key':'qimofenshu','title':'','source_type':'PUBLIC_POST','locator':'',
        'published_at':None,'available_at':None,'content_hash':'','archive_ref':'',
        'completeness':'PENDING','notes':'先登记来源；未核验前不得冻结规则。'},
    'definition':{'playbook_key':'qimofenshu','name':'期末50分试点','version':'draft-1','state':'DRAFT',
        'source_ids':[],'market_context':{},'eligibility':{},'selection':{},'veto':{},'entry':{},
        'confirm':{},'invalidation':{},'hold':{},'add':{},'reduce':{},'exit':{},'notes':'等待原始来源。'},
}
TEMPLATES.update({
    'case':{'definition_id':'<UUID>','trading_day':'2026-01-01','frame':'R1',
        'as_of':'2026-01-01T09:35:00+08:00','source_ids':['<UUID>'],'market_snapshot_ids':[],
        'summary':'','notes':''},
    'candidate':{'case_id':'<UUID>','definition_id':'<UUID>','trading_day':'2026-01-01','frame':'R1',
        'as_of':'2026-01-01T09:35:00+08:00','completeness':'UNKNOWN','pit_status':'UNKNOWN',
        'universe_source':'','generation_method':'','candidates':[],'evidence_ids':[]},
    'selection':{'candidate_set_id':'<UUID>','kind':'OBSERVED_EXPERT','selected_symbols':[],
        'ranked_symbols':[],'reasons':{},'evidence_ids':[],'as_of':'2026-01-01T09:35:00+08:00','notes':''},
    'validation':{'definition_id':'<UUID>','method':'RECONSTRUCTION','pairs':[
        {'case_id':'<UUID>','target_selection_id':'<UUID>','model_selection_id':'<UUID>'}],
        'execution_evidence_ids':[],'execution_summary':{},'notes':''},
})


class PlaybookRecordDialog(QDialog):
    def __init__(self, window, store, reload_callback):
        super().__init__(window);self.store=store;self.reload_callback=reload_callback
        self.setWindowTitle('Trading Knowledge / Playbook Lab · 严格对象导入');self.resize(900,720)
        box=QVBoxLayout(self);self.kind=QComboBox()
        for title,key in KINDS:self.kind.addItem(title,key)
        box.addWidget(row(label('对象类型'),self.kind))
        self.editor=QPlainTextEdit();box.addWidget(self.editor,1)
        self.status=label('宿主人工写入；模型只有只读 Playbook 工具。','note',True);box.addWidget(self.status)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self.save);controls.rejected.connect(self.reject);box.addWidget(controls)
        self.kind.currentIndexChanged.connect(self.load_template);self.load_template()

    def load_template(self):
        self.editor.setPlainText(encode(TEMPLATES[self.kind.currentData()]))

    def save(self):
        try:
            value=json.loads(self.editor.toPlainText());request=str(uuid4());kind=self.kind.currentData()
            methods={'strategy_source':self.store.create_strategy_source,'source_link':self.store.create_source_link,
                'source':self.store.create_source,'definition':self.store.create_definition,
                'case':self.store.create_case,'candidate':self.store.create_candidate_set,
                'selection':self.store.create_selection,'validation':self.store.create_validation}
            saved=methods[kind](request,value)
        except (json.JSONDecodeError,PlaybookError,ValueError,OSError) as error:
            self.status.setText(str(error));return
        self.status.setText('已保存：'+next((str(saved.get(k)) for k in
            ('strategy_source_id','link_id','source_id','definition_id','case_id','candidate_set_id','selection_id','validation_id') if saved.get(k)),'完成'))
        self.reload_callback();self.accept()


class PlaybookLabDialog(QDialog):
    def __init__(self, window):
        super().__init__(window);self.window=window;self.store=PlaybookStore(window.output)
        self.setWindowTitle('Trading Knowledge / Playbook Lab · 多来源交易知识研究');self.resize(1380,860)
        self.box=QVBoxLayout(self);self.summary=QWidget();self.box.addWidget(self.summary)
        self.tabs=QTabWidget();self.box.addWidget(self.tabs,1)
        self.summary_box=QVBoxLayout(self.summary);self.summary_box.setContentsMargins(0,0,0,0)
        self.summary_box.addWidget(row(button('＋ 导入严格对象',self.open_import,True),
            button('刷新',self.reload),label('StrategySource → Playbook → CandidateSet → Validation → Daily Decision','muted')))
        self.reload()

    def open_import(self):
        self.window.show_dialog(PlaybookRecordDialog(self.window,self.store,self.reload))

    def _replace_kpis(self, values):
        while self.summary_box.count()>1:
            item=self.summary_box.takeAt(1)
            if item.widget():item.widget().deleteLater()
        self.summary_box.addWidget(kpis(values))

    def page(self):
        page=QWidget();layout=QVBoxLayout(page);return page,layout

    def detail(self, value, title):
        dialog=QDialog(self);dialog.setWindowTitle(title);dialog.resize(980,760)
        layout=QVBoxLayout(dialog);layout.addWidget(BusinessDetails(value),1)
        self.window.show_dialog(dialog)

    def reload(self):
        overview=self.store.overview();self.tabs.clear()
        self._replace_kpis([('策略来源',overview['strategy_sources'],'含旧Expert投影'),('来源关系',overview['source_links'],'多对多'),
            ('玩法版本',overview['definitions'],'Definition'),
            ('冻结规则',overview['frozen_definitions'],'FROZEN'),('历史案例',overview['cases'],'PlaybookCase'),
            ('完整候选集',overview['full_candidate_sets'],'FULL'),('正式审计',overview['audit_complete_validations'],'AUDIT_COMPLETE')])
        self.render_sources();self.render_definitions();self.render_cases();self.render_validations();self.render_architecture()

    def render_sources(self):
        rows=self.store.list_strategy_sources(limit=500)['records'];page,layout=self.page()
        layout.addWidget(label('StrategySource 是来源，不是规则。旧 ExpertSource 会兼容投影为 TRADER；VERIFIED 也不代表 Playbook 有效。','note',True))
        control=table(['来源Key','类别','标题','完整性','可用时间','兼容来源'],[
            [r['source_key'],r['source_kind'],r['title'],r['completeness'],r.get('available_at') or '—',
                'ExpertSource' if r.get('legacy_expert_source_id') else 'StrategySource'] for r in rows],
            lambda i:self.detail(rows[i],'StrategySource'))
        layout.addWidget(control,1);self.tabs.addTab(page,'交易知识来源')

    def render_definitions(self):
        rows=self.store.list_definitions(limit=500)['records'];page,layout=self.page()
        bundles=[self.store.definition_source_bundle(r['definition_id']) for r in rows]
        layout.addWidget(label('规则变化必须新建 version。P8.6 新 StrategySource 关系是补充证据；正式 FROZEN/HOLDOUT 仍沿用旧 VERIFIED source_ids 合同。','note',True))
        control=table(['玩法','Key','版本','状态','正式旧来源','策略来源关系','Definition Hash'],[
            [r['name'],r['playbook_key'],r['version'],r['state'],len(r['source_ids']),len(bundles[i]['strategy_source_links']),r['definition_hash'][:16]]
            for i,r in enumerate(rows)],lambda i:self.detail(bundles[i],'PlaybookDefinition + StrategySources'))
        layout.addWidget(control,1);self.tabs.addTab(page,'Playbook定义')

    def render_cases(self):
        rows=self.store.list_cases(limit=500)['records'];bundles=[self.store.case_bundle(r['case_id']) for r in rows]
        page,layout=self.page();layout.addWidget(label('候选全集优先：不能只保存高手买入的赢家。双击查看完整 Case Bundle。','note',True))
        data=[]
        for bundle in bundles:
            case=bundle['case'];candidate=bundle['candidate_set'];selections=bundle['selections']
            data.append([case['trading_day'],case['frame'],case['playbook_key'],case['playbook_version'],
                candidate['candidate_count'] if candidate else 0,candidate['completeness'] if candidate else '未冻结',
                candidate['pit_status'] if candidate else '—',
                sum(1 for s in selections if s['kind']=='OBSERVED_EXPERT'),sum(1 for s in selections if s['kind']=='SYSTEM_PREDICTION')])
        control=table(['交易日','Frame','玩法','版本','候选数','完整性','PIT','专家选择','系统预测'],data,
            lambda i:self.detail(bundles[i],'PlaybookCase Bundle'))
        layout.addWidget(control,1);self.tabs.addTab(page,'案例 / 候选全集')

    def render_validations(self):
        rows=self.store.list_validations(limit=500)['records'];page,layout=self.page()
        layout.addWidget(label('AUDIT_COMPLETE 仍不是 Alpha 认证；它只表示选择验证与 A 股执行审计合同齐全。','note',True))
        data=[]
        for r in rows:
            metrics=r['metrics'];audit=r['audit']
            data.append([r['playbook_key'],r['playbook_version'],r['method'],r['status'],metrics['cases'],
                metrics['micro_precision'],metrics['micro_recall'],metrics['exact_match_rate'],
                '是' if audit['execution']['ready'] else '否','否' if not r['alpha_verified'] else '是'])
        control=table(['玩法','版本','方法','状态','案例数','Precision','Recall','Exact','执行审计','Alpha已证实'],data,
            lambda i:self.detail(rows[i],'PlaybookValidation'))
        layout.addWidget(control,1);self.tabs.addTab(page,'历史验证')

    def render_architecture(self):
        page,layout=self.page()
        layout.addWidget(label('多来源交易知识架构','panelTitle'))
        layout.addWidget(label(
            'StrategySource 支持 TRADER / USER_EXPERIENCE / PUBLIC_METHOD / HISTORICAL_CASE / '
            'STATISTICAL_DISCOVERY / SYSTEM_REVIEW。来源只是证据入口，PlaybookDefinition 才是规则。\n\n'
            '一个来源可以支持多个 Playbook，一个 Playbook 也可以绑定多个 ORIGIN / SUPPORT / CONTRADICT / '
            'EXAMPLE / COUNTEREXAMPLE 关系。旧 ExpertSource 原样保留，并统一投影为 TRADER。\n\n'
            'P8.6 不改变正式验证门槛：新的 StrategySource 关系不会自动让 DRAFT 变 FROZEN，也不会绕过 VERIFIED '
            'ExpertSource、FULL CandidateSet、STRICT_PIT 或 SYSTEM_PREDICTION。','note',True))
        layout.addWidget(label('期末50分只是首个历史 TRADER 来源试点；系统长期积累的是可版本化 Playbook。','muted',True))
        layout.addStretch();self.tabs.addTab(page,'来源 / Playbook关系')

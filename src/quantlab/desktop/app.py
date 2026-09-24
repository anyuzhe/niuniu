"""Niuniu native PyQt6 application backed by the existing research core."""
import json
import re
import sys
from collections import Counter
from threading import RLock
from pathlib import Path
from uuid import uuid4

from PyQt6.QtCore import Qt, QObject, QRunnable, QThreadPool, pyqtSignal, QTimer, QDate
from PyQt6.QtGui import QPixmap, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QFrame, QScrollArea, QLineEdit, QStackedWidget, QPushButton, QSplitter,
    QTabWidget, QTextBrowser, QComboBox, QDateEdit, QSpinBox, QCheckBox, QPlainTextEdit,
    QDialog, QFormLayout, QDialogButtonBox, QAbstractItemView, QHeaderView)

from quantlab.app import default_registry
from quantlab.storage.codec import encode
from quantlab.theory.templates import templates
from quantlab.workbench.server import ArtifactCatalog
from quantlab.workbench.jobs import JobQueue, prepare
from .widgets import ASSETS, STYLE, Card, Chart, Flow, label, button, row, hero, kpis, table, raw, fmt, execution_table
from .boss_key import BossKey
from .business_view import BusinessDetails

LEGACY_NAV = ['研究工作台','数据中心','因子库','市场状态','结构与事件','序列构建器',
       '理论实验室','实验中心','组合与模型','策略回测','结果对比','系统设置']
# (key, title, icon, pro). Everyday workbenches first; research/governance/dev tools only in 专业模式.
PAGES = [
    ('market','今日市场','⌂',False),('themes','主线方向','▦',False),('sectors','盘中板块','◧',False),
    ('candidates','今日候选','★',False),
    ('stock','个股报告','◎',False),('mine','我的股票','◉',False),('review','复盘验证','↺',False),
    ('kol','大V复盘','✎',False),('assistant','AI 助手','✦',False),
    ('desk','交易台','▣',True),('theme_matrix','主题矩阵','▥',True),('dossiers','股票决策档案','◍',True),
    ('intent','持仓计划','◈',True),('decision_review','决策复盘','↻',True),('ai_team','AI 团队','✧',True),
    ('lab','研究实验室','▤',True),('dev','开发工作台','⌘',True),('system','系统中心','⚙',True),
]
NAV = [title for _,title,_,_ in PAGES]
ICONS = [icon for _,_,icon,_ in PAGES]
PAGE_KEYS = [key for key,_,_,_ in PAGES]
KINDS = {'campaign':'固定研究包','alpha_factory':'Alpha Factory','factor':'因子实验','execution':'独立成交回测','ablation':'消融研究',
    'holdout':'样本外验证','walkforward':'滚动验证','sweep':'参数扫描','theory_study':'理论全流程','trial_registry':'跨实验登记检验族','return_family':'固定净收益检验族','return_increment':'净收益增量比较','stability':'参数与子样本比较','residual_alpha':'残差研究','correlation':'因子相关与去重','correlation_holdout':'样本外相关性','correlation_walkforward':'滚动相关性'}
MODES = [('single','单因子 / 条件 / 组合'),('holdout','固定样本外'),('walkforward','滚动验证'),
    ('ablation','逐输入消融'),('sweep','参数扫描'),('execution','独立成交回测'),('theory_study','理论全流程'),('correlation','因子相关性与冗余')]


class Signals(QObject):
    finished = pyqtSignal(int, object, str)


class Task(QRunnable):
    def __init__(self, key, function, signals):
        super().__init__(); self.key=key; self.function=function; self.signals=signals
    def run(self):
        try: result=self.function(); error=''
        except Exception as exc: result=None; error=f'{type(exc).__name__}: {exc}'
        self.signals.finished.emit(self.key,result,error)


class MainWindow(QMainWindow):
    def __init__(self, output, data_root=None):
        super().__init__()
        self.setWindowTitle('牛牛 AI · 个人 A 股交易研究助手'); self.setWindowIcon(QIcon(str(ASSETS/'niuniu_logo_icon.png')))
        self.resize(1600,980);self.setMinimumSize(1180,760)
        self.output=Path(output).resolve();self.output.mkdir(parents=True,exist_ok=True)
        self.catalog=ArtifactCatalog(self.output);self.data_root=Path(data_root).resolve() if data_root else None
        self.factors=json.loads(encode(default_registry().describe()));self.theories=templates()
        self.queue_lock=RLock()
        self.queue=None;self.callbacks={};self.next_task=0;self.epoch=0;self.current=0;self.root_current=0;self.legacy_current=None;self.closing=False
        self.pool=QThreadPool(self);self.pool.setMaxThreadCount(2)
        self.signals=Signals(self);self.signals.finished.connect(self.finished)
        self.dialogs=[];self.last_records=[]
        self.setStyleSheet(STYLE)
        shell=QWidget();self.setCentralWidget(shell);outer=QHBoxLayout(shell);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        side=QFrame();side.setObjectName('sidebar');side.setFixedWidth(252);sidebox=QVBoxLayout(side);sidebox.setContentsMargins(10,18,10,20);sidebox.setSpacing(7)
        logo=label();logo.setPixmap(QPixmap(str(ASSETS/'niuniu_logo_icon.png')).scaled(58,58,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        brand=QWidget();brand.setObjectName('transparent');bl=QVBoxLayout(brand);bl.setContentsMargins(0,0,0,0);bl.addWidget(label('牛牛 AI','brand'));bl.addWidget(label('个人 A 股交易研究助手','muted'))
        sidebox.addWidget(row(logo,brand));sidebox.addSpacing(22);self.nav=[]
        from .ui_settings import load_ui_settings
        self.pro_mode=load_ui_settings(self.output)['pro_mode']
        self.pro_heading=label('专业模式','muted');self.pro_heading.setContentsMargins(8,10,0,2)
        for index,title in enumerate(NAV):
            if index==next(i for i,p in enumerate(PAGES) if p[3]):sidebox.addWidget(self.pro_heading)
            b=button(f'{ICONS[index]}   {title}',lambda:None);b.setObjectName('nav');b.setCheckable(True);b.setAutoExclusive(True);b.setMinimumHeight(40 if PAGES[index][3] else 49);sidebox.addWidget(b);self.nav.append(b)
            # AX changes checked state without emitting clicked. Defer page
            # destruction until the native accessibility action has returned.
            b.toggled.connect(lambda checked,i=index:QTimer.singleShot(0,lambda:self.navigate_root(i) if self.nav[i].isChecked() else None) if checked else None)
        sidebox.addStretch()
        self.pro_toggle=QCheckBox('专业模式（研究、治理与开发工具）');self.pro_toggle.setAccessibleName('专业模式')
        self.pro_toggle.setChecked(self.pro_mode);self.pro_toggle.toggled.connect(self.set_pro_mode);sidebox.addWidget(self.pro_toggle)
        sidebox.addWidget(label('用数据发现规律\n用逻辑创造价值\n让交易更科学','muted'))
        motto=label('D I S C I P L I N E   C R E A T E S   A L P H A','gold');motto.setStyleSheet('font-size:9px;');sidebox.addWidget(motto)
        outer.addWidget(side)
        workspace=QWidget();wb=QVBoxLayout(workspace);wb.setContentsMargins(0,0,0,0);wb.setSpacing(0);outer.addWidget(workspace,1)
        top=QFrame();top.setObjectName('topbar');tb=QVBoxLayout(top);tb.setContentsMargins(24,10,24,10);tb.setSpacing(8)
        self.search=QLineEdit();self.search.setPlaceholderText('⌕  搜索股票 · 主线 · 因子 · 实验 · 研究记录…');self.search.setAccessibleName('全局搜索');self.search.setMinimumWidth(320);self.search.setMaximumWidth(640);self.search.returnPressed.connect(self.global_search)
        self.boss_key=BossKey(self)
        self.boss_button=button('老板键 F12',self.boss_key.hide)
        self.boss_button.setToolTip(self.boss_key.help_text)
        self.boss_button.setAccessibleDescription(self.boss_key.help_text)
        search_row=row(self.search,button('搜索',self.global_search),button('问 AI',self.research_chat,True),self.boss_button)
        search_row.layout().setStretch(0,1);tb.addWidget(search_row)
        self.pro_actions=row(button('研究议程',self.research_agenda),button('AI 研究接口',self.agent_catalog),button('研究记忆',self.research_memory),button('运行任务',self.show_jobs),button('新建实验',self.new_experiment),button('＋ Decision',self.new_decision,True))
        self.pro_actions.layout().insertStretch(3,1);tb.addWidget(self.pro_actions);wb.addWidget(top)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);wb.addWidget(self.scroll,1)
        self.status=label('牛牛 AI · 研究结论不构成投资建议','muted');self.status.setContentsMargins(24,8,24,8);wb.addWidget(self.status)
        QShortcut(QKeySequence.StandardKey.Find,self,activated=self.search.setFocus)
        self.shutdown_timer=QTimer(self);self.shutdown_timer.setInterval(250);self.shutdown_timer.timeout.connect(self.close)
        self.apply_pro_mode()
        self.navigate_root(0)

    def apply_pro_mode(self):
        self.pro_heading.setVisible(self.pro_mode);self.pro_actions.setVisible(self.pro_mode)
        for button_,(_,_,_,pro) in zip(self.nav,PAGES):button_.setVisible(self.pro_mode or not pro)

    def set_pro_mode(self,enabled):
        from .ui_settings import save_ui_settings
        self.pro_mode=bool(enabled)
        try:save_ui_settings(self.output,pro_mode=self.pro_mode)
        except (OSError,ValueError) as exc:self.status.setText('界面设置未保存：'+str(exc))
        self.apply_pro_mode()
        if not self.pro_mode and PAGES[self.root_current][3]:self.navigate_root(0)

    def navigate_page(self,key):
        index=PAGE_KEYS.index(key)
        if PAGES[index][3] and not self.pro_mode:self.pro_toggle.setChecked(True)
        self.navigate_root(index)

    def research_agenda(self):
        from .research_agenda import ResearchAgendaDialog
        self.show_dialog(ResearchAgendaDialog(self))

    def research_memory(self, memory_id=None):
        from .research_memory import ResearchMemoryDialog
        selected=memory_id if isinstance(memory_id,str) else None
        self.show_dialog(ResearchMemoryDialog(self,selected_id=selected))

    def playbook_lab(self):
        from .playbook_lab import PlaybookLabDialog
        self.show_dialog(PlaybookLabDialog(self))

    def research_skill_library(self,skill_key=None,package_snapshot=None):
        from .research_skill_library import ResearchSkillLibraryDialog
        selected_key=skill_key if isinstance(skill_key,str) else None
        selected_snapshot=package_snapshot if isinstance(package_snapshot,str) else None
        self.show_dialog(ResearchSkillLibraryDialog(self,selected_key,selected_snapshot))

    def research_campaign(self):
        if self.data_root is None:self.status.setText("请先指定行情目录");return
        from .research_campaign import CampaignDialog
        self.show_dialog(CampaignDialog(self))

    def tracking_preview(self):
        from .tracking_preview import TrackingPreviewDialog
        self.show_dialog(TrackingPreviewDialog(self))

    def factor_watches(self, selected_id=None):
        from .factor_watches import FactorWatchDialog
        self.show_dialog(FactorWatchDialog(self,selected_id))

    def agent_catalog(self):
        from .agent_catalog import AgentCatalogDialog
        self.show_dialog(AgentCatalogDialog(self))

    def new_decision(self, source=None):
        from .decision_ledger import DecisionEditor
        dialog=DecisionEditor(self,source)
        dialog.accepted.connect(lambda:self.navigate_root(self.root_current) if PAGE_KEYS[self.root_current] in ('review','desk','theme_matrix','dossiers','intent','decision_review') else None)
        self.show_dialog(dialog)

    def open_decision(self, decision):
        from quantlab.trading.decision_store import DecisionStore
        full=DecisionStore(self.output).get(decision['decision_id'])
        dialog=QDialog(self);dialog.setWindowTitle(full['symbol']+' · '+full['trading_day']+' · '+full['frame']);dialog.resize(900,720)
        layout=QVBoxLayout(dialog);layout.addWidget(BusinessDetails(full),1)
        if full.get('superseded_by'):
            layout.addWidget(label('该 Decision 已有后续修订；历史版本保持只读。','note',True))
        else:
            layout.addWidget(button('基于此 Decision 新建修订',lambda:(dialog.close(),self.new_decision(full)),True))
        self.show_dialog(dialog)

    def open_stock_dossier(self, symbol):
        from .stock_dossier import StockDossierDialog
        self.show_dialog(StockDossierDialog(self,symbol))

    def open_stock_decisions(self, symbol):
        from quantlab.trading.decision_store import DecisionStore
        records=DecisionStore(self.output).timeline(symbol,include_superseded=True)['records']
        dialog=QDialog(self);dialog.setWindowTitle(symbol+' · Decision 时间线');dialog.resize(1100,720);layout=QVBoxLayout(dialog)
        layout.addWidget(label('原判与修订全部保留；双击打开具体 Decision。','note',True))
        layout.addWidget(table(['交易日','Frame','动作','主题','提交时间','判断'],[[d['trading_day'],d['frame'],d['action'],d.get('theme',''),d['submitted_at'].replace('T',' ')[:19],d.get('ai_thesis','')[:100]] for d in records],lambda i:self.open_decision(records[i])),1)
        self.show_dialog(dialog)

    def get_research_queue(self):
        """One shared queue for manual forms, fixed plans and approved proposals."""
        with self.queue_lock:
            if self.closing: raise ValueError('工作台正在关闭，不再创建新任务')
            if self.data_root is None: raise ValueError('请先配置行情数据目录')
            if self.queue is None: self.queue=JobQueue(self.output,self.data_root)
            return self.queue

    def async_call(self, function, callback, guarded=True):
        key=self.next_task;self.next_task+=1
        self.callbacks[key]=(self.epoch if guarded else None,callback)
        self.pool.start(Task(key,function,self.signals))

    def finished(self,key,result,error):
        epoch,callback=self.callbacks.pop(key)
        if epoch is None or epoch==self.epoch:
            try:
                if error:self.status.setText('读取失败：'+error)
                callback(result,error)
            except Exception as exc:self.status.setText(f'界面读取失败：{exc}')

    def page(self,title,subtitle):
        self.epoch+=1
        old=self.scroll.takeWidget()
        if old:old.deleteLater()
        content=QWidget();box=QVBoxLayout(content);box.setContentsMargins(24,12,24,24);box.setSpacing(12)
        box.addWidget(hero(title,subtitle));self.scroll.setWidget(content);self.body=box
        return box

    def as_of_day(self):
        return QDate.currentDate().toString('yyyy-MM-dd')

    def navigate_root(self,index):
        if self.closing:return
        if not 0<=index<len(NAV):raise IndexError(index)
        self.root_current=index
        for i,b in enumerate(self.nav):
            b.blockSignals(True);b.setChecked(i==index);b.blockSignals(False)
        from . import home_pages, trading_pages
        handlers={'market':home_pages.market_page,'themes':home_pages.themes_page,'sectors':home_pages.sectors_page,'candidates':home_pages.candidates_page,
            'stock':home_pages.stock_page,'mine':home_pages.mine_page,'review':home_pages.review_page,'kol':home_pages.kol_page,'assistant':home_pages.assistant_page,
            'desk':trading_pages.today_page,'theme_matrix':trading_pages.theme_page,'dossiers':trading_pages.stock_page,
            'intent':trading_pages.position_page,'decision_review':trading_pages.review_page,'ai_team':trading_pages.ai_team_page,
            'lab':trading_pages.research_lab_page,'dev':trading_pages.dev_studio_page,'system':trading_pages.system_center_page}
        handlers[PAGE_KEYS[index]](self)

    def navigate(self,index):
        """Compatibility route for the original 12 research pages."""
        if self.closing:return
        if not 0<=index<len(LEGACY_NAV):raise IndexError(index)
        self.current=index;self.legacy_current=index
        handlers=[self.home,self.data_page,lambda:self.registry_page('factor'),self.regime_page,
            self.objects_page,self.sequence_page,self.theory_page,
            self.experiments,self.portfolio,self.backtests,self.comparison,self.settings]
        handlers[index]()

    def home(self):
        box=self.page(LEGACY_NAV[0],'统一研究入口 · 从理论拆解、因子注册、事件序列到科学实验与增量 Alpha。')
        d=[f['definition'] for f in self.factors]
        stats=kpis([('注册因子',len(d),'当前注册版本'),('研究模板',len(self.theories),'固定研究模板'),
            ('已完成实验','…','当前产物目录'),('布尔类因子',sum(f['factor_type']=='boolean' for f in d),'事件 / 状态等定义'),
            ('序列定义',sum(f['category']=='sequence' for f in d),'明确规则序列'),('失败记录','…','保留研究证据')]);box.addWidget(stats)
        architecture=Card('统一研究架构总览',lambda:self.navigate(7));architecture.setMinimumWidth(545)
        architecture.add(Flow([('Data Layer','行情快照\nParquet / DuckDB'),('Factor Registry','统一注册\n规则与版本'),('Event / Zone / Structure','确认结构\n时间可用性'),('Sequence Engine','Transition\nTimeout / Invalidation'),('Experiment Engine','Single / OOS\nAblation'),('Alpha / Portfolio','Signal\nRisk / Portfolio')]),1)
        mapping=Card('Theory Mapping',lambda:self.navigate(6));counts=Counter(t for f in d for t in f['source_theory'])
        mapping.add(table(['Theory','注册对象'],[[t,n] for t,n in counts.most_common()]),1);mapping.add(label('注册映射数量，不代表理论完成率。','muted',True))
        guard=Card('Causal Guard',lambda:self.navigate(1))
        for title,sub in [('available_at','时间可用性对齐'),('Point-in-Time Universe','以每次实验来源为准'),('Multi-Timeframe','保留时序口径'),('Future Leak Check','查看实验审计证据'),('Walk Forward','查看归档验证结果')]:guard.add(label(f'◉  {title}\n     {sub}','muted',True))
        guard.body.addStretch();middle=row(architecture,mapping,guard);middle.layout().setStretch(0,43);middle.layout().setStretch(1,28);middle.layout().setStretch(2,28);middle.setMinimumHeight(328);middle.setMaximumHeight(340);box.addWidget(middle,3)
        recent=Card('最近实验',lambda:self.navigate(7));recent.add(label('正在读取已保存实验…','muted'))
        principles=Card('研究核心原则')
        for text in ['Research First 先研究，后策略','Unified Factors 统一底层对象','Causal Correctness 严格时间因果','Reproducible Experiments 可复现','Incremental Alpha 验证增量']:
            principles.add(label('✓  '+text,'muted'))
        principles.add(label('复杂理论拆成统一对象，再通过同一套实验体系公平验证。','note',True));principles.body.addStretch()
        bottom=row(recent,principles);bottom.layout().setStretch(0,2);bottom.layout().setStretch(1,1);bottom.setMinimumHeight(275);bottom.setMaximumHeight(285);box.addWidget(bottom,2);box.addStretch()
        def loaded(data,error):
            if error:recent.body.itemAt(1).widget().setText(error);return
            self.last_records=data['runs'];items=stats.findChildren(type(label()),'stat');items[2].setText(str(data['counts']['completed']));items[5].setText(str(data['counts']['failed']))
            recent.body.takeAt(1).widget().deleteLater()
            recent.add(table(['实验名称','类型','周期','状态'],[[r['question'],KINDS.get(r['kind'],r['kind']),r['timeframe'],r['status']] for r in data['runs']],lambda i:self.open_run(data['runs'][i]['run_id'])),1)
            recent.add(label('双击实验查看完整归档。','muted'))
        self.async_call(lambda:self.catalog.list(limit=6),loaded)

    def registry_page(self,kind,query=''):
        title={'factor':LEGACY_NAV[2],'sequence':LEGACY_NAV[5],'theory':LEGACY_NAV[6]}[kind]
        values=self.theories if kind=='theory' else [v for v in self.factors if kind!='sequence' or v['definition']['category']=='sequence']
        box=self.page(title,'统一注册对象、规则版本与因果口径 · 选择一行查看定义与研究参数。')
        if kind=='factor':
            definitions=[v['definition'] for v in values]
            box.addWidget(kpis([('注册因子',len(definitions),'当前注册版本'),('标量因子',sum(d['factor_type']=='scalar' for d in definitions),'数值输出'),('布尔因子',sum(d['factor_type']=='boolean' for d in definitions),'事件 / 状态等输出'),('结构类',sum(d['category']=='structure' for d in definitions),'注册分类'),('序列类',sum(d['category']=='sequence' for d in definitions),'明确规则'),('理论模板',len(self.theories),'固定组合')]))
        if kind=='sequence':box.addWidget(label('可通过序列构建器编辑步骤、嵌套组、超时和失效条件，并提交研究。','note',True))
        search=QLineEdit(query);search.setPlaceholderText('检索名称、ID、理论或规则');box.addWidget(search)
        split=QSplitter();listing=Card('注册目录');inspector=Card('定义 / 参数 / 因果语义')
        description=label('','muted',True);inspector.add(description);info=BusinessDetails({});inspector.add(info,1)
        selected={'value':None}
        inspector.add(button('使用该定义新建实验',lambda:self.new_experiment(selected['value']),True))
        inspector.add(button('查看关联实验',lambda:self.experiments(query=(selected['value'] or {}).get('definition',selected['value'] or {}).get('factor_id',(selected['value'] or {}).get('template_id','')))))
        if kind=='theory':inspector.add(label('Theory Alpha、Ablation、OOS 与滚动结果均以实际归档为准。','muted',True))
        split.addWidget(listing);split.addWidget(inspector);split.setSizes([950,430]);box.addWidget(split,1)
        def render():
            for i in reversed(range(listing.body.count()-1)):
                item=listing.body.takeAt(i+1)
                if item.widget():item.widget().deleteLater()
            matched=[v for v in values if search.text().casefold() in encode(v).casefold()]
            defs=[v.get('definition',v) for v in matched]
            t=table(['名称','ID / 版本','对象类型','时间可用性'],[[d.get('name_cn',d.get('name')),d.get('factor_id',d.get('template_id'))+' @'+d['version'],d.get('factor_type','theory'),d.get('available_at_rule','按输入因子对齐')] for d in defs])
            def choose(index=None):
                i=t.currentRow() if index is None else index
                selected['value']=matched[i] if i>=0 else None
                d=(selected['value'] or {}).get('definition',selected['value'] or {})
                description.setText(d.get('name_cn',d.get('name',''))+'\n'+d.get('description',d.get('scope','')))
                info.setPlainText(json.dumps(selected['value'] or {},ensure_ascii=False,indent=2))
            t.itemSelectionChanged.connect(choose);listing.add(t,1)
            # Populate the inspector without a selection accessibility event
            # before the newly created table has been laid out on macOS.
            if matched:choose(0)
            else:selected['value']=None;description.setText('');info.setPlainText('没有匹配项。')
        search.textChanged.connect(render);render()

    def run_list(self,box,kind='',query='',on_select=None,multi=False):
        toolbar=row();search=QLineEdit(query);search.setPlaceholderText('搜索实验问题 / 因子 / ID');toolbar.layout().addWidget(search,1)
        state=QComboBox();state.addItem('全部状态','');state.addItem('已完成','completed');state.addItem('失败','failed');toolbar.layout().addWidget(state)
        card=Card('实验记录 · 双击打开');box.addWidget(toolbar);box.addWidget(card,1)
        pagination=row();previous=button('上一页',lambda:load(-30));next_b=button('下一页',lambda:load(30));count=label('读取中…','muted');pagination.layout().addWidget(previous);pagination.layout().addWidget(count);pagination.layout().addWidget(next_b);pagination.layout().addStretch();box.addWidget(pagination)
        holder={'offset':0,'epoch':0,'table':None,'rows':[]};page_epoch=self.epoch
        def loaded(data,error,request):
            if holder['epoch']!=request:return
            previous.setEnabled(holder['offset']>0);next_b.setEnabled(False)
            for i in reversed(range(1,card.body.count())):
                item=card.body.takeAt(i)
                if item.widget():item.widget().deleteLater()
            if error:card.add(label(error,'note',True));return
            holder['rows']=data['runs'];self.last_records=data['runs']
            t=table(['研究问题','因子','类型','周期 / 数据范围','状态'],[[r['question'],r['factor_id'],KINDS.get(r['kind'],r['kind']),f"{r['timeframe']} · {r['start']} → {r['end']}",r['status']] for r in data['runs']],lambda i:self.open_run(data['runs'][i]['run_id']))
            holder['table']=t
            if multi:t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            if on_select:t.itemSelectionChanged.connect(lambda:on_select(data['runs'][t.currentRow()]) if t.currentRow()>=0 else None)
            card.add(t,1);count.setText(f"{holder['offset']+1 if data['total'] else 0}–{min(holder['offset']+30,data['total'])} / {data['total']}")
            next_b.setEnabled(holder['offset']+30<data['total'])
            if not data['runs']:card.add(label('没有匹配的实验记录。','muted'))
        def load(delta=0,reset=False):
            if self.epoch!=page_epoch:return
            holder['offset']=0 if reset else max(0,holder['offset']+delta);holder['epoch']+=1;request=holder['epoch']
            previous.setEnabled(False);next_b.setEnabled(False);count.setText('正在读取实验产物…')
            q=search.text();status=state.currentData();offset=holder['offset']
            self.async_call(lambda:self.catalog.list(query=q,status=status,kind=kind,offset=offset,limit=30),lambda d,e:loaded(d,e,request))
        toolbar.layout().addWidget(button('检索 / 刷新',lambda:load(reset=True)));search.returnPressed.connect(lambda:load(reset=True));state.currentIndexChanged.connect(lambda:load(reset=True));load()
        return holder

    def theory_page(self,index=0):
        selected=self.theories[index]
        box=self.page(LEGACY_NAV[6],'Theory Pack → 组件对象 → 组合规则 → Ablation / OOS / Incremental Alpha')
        chooser=QComboBox()
        for value in self.theories:chooser.addItem(value['name'])
        chooser.setCurrentIndex(index);chooser.currentIndexChanged.connect(self.theory_page)
        box.addWidget(row(chooser,button('新建该理论研究',lambda:self.new_experiment(selected),True)))
        graph=Card('理论组件 · 并列输入 / 组合确认')
        components=row()
        for alias,spec in selected['parameters']['inputs'].items():
            card=Card(alias);card.add(label(spec['factor_id'],'gold',True));card.add(label(selected.get('concepts',{}).get(alias,''),'muted',True));card.add(label('版本 '+spec['version'],'muted'));components.layout().addWidget(card)
        graph.add(components);graph.add(label(selected['scope'],'note',True))
        mapping=Card('组合规则');mapping.add(BusinessDetails(selected['parameters']['rule']),1)
        panels=row(graph,mapping);panels.layout().setStretch(0,2);panels.layout().setStretch(1,1);box.addWidget(panels)
        box.addWidget(label('下方只列出该模板的实际归档。组件 Alpha、消融和增量结论在各实验报告中保留原始口径。','muted',True))
        self.run_list(box,query=selected['template_id'])

    def sequence_page(self):
        from .sequence_builder import SequenceBuilder
        box=self.page(LEGACY_NAV[5],'事件库 → 状态流 → 超时 / 失效 → 完成确认 · 原生拖放编辑')
        box.addWidget(SequenceBuilder(self),1)
        box.addWidget(button('浏览全部已注册序列规则',lambda:self.registry_page('sequence')))

    def experiments(self,query=''):
        box=self.page(LEGACY_NAV[7],'Single / Conditional / Combination / Sequence / Ablation / OOS / Walk Forward')
        box.addWidget(row(button('＋ 新建实验',self.new_experiment,True),button('运行任务',self.show_jobs)))
        self.run_list(box,query=query)

    def data_page(self):
        box=self.page(LEGACY_NAV[1],'数据快照 · 时间可用性 · Universe 版本 · 复现证据')
        from .reference_tools import ReferenceDialog
        box.addWidget(button('获取 Baostock 历史行业 / 股本 / 交易状态',lambda:self.show_dialog(ReferenceDialog(self))))
        sources=Card('数据接入与来源口径');sources.add(Flow([('MQC 行情','日线 / 5 分钟\n只读数据源'),('Parquet','按证券与周期读取'),('DuckDB','查询与研究分析'),('Corporate Action','以实验归档事件为准'),('Universe / PIT','以已保存资格来源为准')]))
        box.addWidget(sources)
        box.addWidget(label('以下为实验归档范围，不代表全量数据质量通过认证。双击记录查看行情快照和股票池版本。','note',True))
        self.run_list(box)

    def regime_page(self):
        box=self.page(LEGACY_NAV[3],'Direction / Structure / Volatility / Liquidity · Alpha(Factor | Regime)')
        box.addWidget(kpis([('Direction','Bull / Bear','方向维度'),('Structure','Trend / Range','结构维度'),('Volatility','Low / High','波动维度'),('Liquidity','依归档','不推断缺失状态')]))
        view=Card('条件研究结果');message=label('选择实验后读取已保存的市场状态统计。','muted');view.add(message);box.addWidget(view)
        def choose(r):
            from quantlab.workbench.research_views import regime_view
            request=r['run_id'];self.regime_selected=request
            def done(data,error):
                if self.regime_selected!=request:return
                while view.body.count()>2:view.body.takeAt(2).widget().deleteLater()
                message.setText(error or data['message'])
                if not error and data['rows']:
                    from PyQt6.QtGui import QColor
                    horizons=list(dict.fromkeys(a['horizon'] for a in data['rows']))
                    groups=list(dict.fromkeys((a['dimension'],a['state']) for a in data['rows']))
                    lookup={(a['dimension'],a['state'],a['horizon']):a['mean_return'] for a in data['rows']}
                    heat=table(['维度 / 状态',*horizons],[[f'{dimension} / {state}',*[lookup.get((dimension,state,h)) for h in horizons]] for dimension,state in groups])
                    for i,(dimension,state) in enumerate(groups):
                        for j,h in enumerate(horizons,1):
                            value=lookup.get((dimension,state,h))
                            if value is not None:
                                cell=label(fmt(value));cell.setStyleSheet('background-color:'+('#174635' if value>=0 else '#54272d')+';color:#edf4fb;padding:6px;')
                                heat.setCellWidget(i,j,cell)
                    view.add(label('条件平均未来收益 · 行为状态，列为持有期；数值与颜色同时保留。','muted',True));view.add(heat)
                    view.add(table(['维度','状态','持有期','样本数','平均收益','合并 IC'],[[a[k] for k in ('dimension','state','horizon','observations','mean_return','pooled_ic')] for a in data['rows']]))
            self.async_call(lambda:regime_view(self.catalog,request),done)
        self.run_list(box,kind='factor',on_select=choose)

    def objects_page(self):
        box=self.page(LEGACY_NAV[4],'Swing / Fractal / FVG / Order Block · occurred_at / available_at / confirmed_at')
        chart=Card('K 线 / 结构 / 事件回放');chart.add(Chart());chart.add(label('选择已保存实验，查看时间截断后的 K 线与结构事件证据。','muted',True));box.addWidget(chart,1)
        def choose(r):
            self.object_selected=r['run_id'];request=r['run_id']
            def done(data,error):
                if self.object_selected!=request:return
                while chart.body.count()>1:
                    old=chart.body.takeAt(1).widget()
                    # A hidden replay may still have an outstanding read callback.
                    old.hide();self.dialogs.append(old)
                if error:chart.add(label(error,'note',True))
                elif 'bars.parquet' in data['files']:chart.add(self.replay_widget(request,data['record']),1)
                else:chart.add(label('本实验未保存 K 线快照；新实验勾选“保存 K 线回放”后可在此查看。','muted',True))
            self.async_call(lambda:self.catalog.detail(request),done)
        self.run_list(box,kind='factor',on_select=choose)

    def backtests(self):
        box=self.page(LEGACY_NAV[9],'Execution Backtester · order / fill / position / commission / slippage / risk')
        box.addWidget(row(button('＋ 新建独立成交回测',lambda:self.new_experiment(mode='execution'),True),label('净值与成交取自归档；双击实验打开研究报告。','muted')))
        curve=Card('策略净值');plot=Chart();curve.add(plot,1)
        summary=Card('收益 / 成本 / 风险');summary.add(label('选择回测记录，查看原始汇总。','muted'))
        panels=row(curve,summary);panels.layout().setStretch(0,2);panels.layout().setStretch(1,1);box.addWidget(panels)
        def choose(r):
            self.backtest_selected=r['run_id'];request=r['run_id']
            def read():
                import polars as pl
                record=self.catalog.record(request)
                values=[]
                try:
                    frame=pl.scan_parquet(self.catalog.file(request,'observations.parquet'))
                    if 'equity' in frame.collect_schema().names():
                        series=frame.select('equity').collect()['equity'];values=series.gather_every(max(1,len(series)//1200)).drop_nulls().to_list()
                except FileNotFoundError:pass
                return record,values
            def done(data,error):
                if self.backtest_selected!=request:return
                while summary.body.count()>1:summary.body.takeAt(1).widget().deleteLater()
                plot.values=[] if error else data[1];plot.update()
                if error:summary.add(label(error,'note',True));return
                summary.add(execution_table(data[0].get('execution',{})),1)
            self.async_call(read,done)
        self.run_list(box,kind='execution',on_select=choose)

    def portfolio(self):
        box=self.page(LEGACY_NAV[8],'Factor → Combination → Alpha Signal → Portfolio → Risk')
        flow=Card('组合与风险流程');flow.add(Flow([('Factor','注册对象'),('Combination','条件 / 加权评分'),('Alpha Signal','可用时间对齐'),('Portfolio','目标权重与约束'),('Risk','模拟成交与账务')]))
        box.addWidget(flow);box.addWidget(label('机器学习与实盘未启用。这里展示现有组合定义和模拟账户归档。','note',True))
        box.addWidget(row(button('条件与评分定义',lambda:self.registry_page('factor','COMB.')),button('查看独立成交回测',lambda:self.navigate(9))))
        def paper_tools():
            from .paper_tools import PaperToolsDialog
            self.show_dialog(PaperToolsDialog(self))
        box.addWidget(button('模拟账户交付 / 持续运行 / 恢复核对',paper_tools,True))
        accounts=Card('模拟账户 / 资金 / 持仓');box.addWidget(accounts,1)
        def read():
            result=[]
            root=self.output/'paper'
            if root.is_symlink():return result
            for path in sorted(root.glob('*.json')):
                if not path.is_symlink():result.append((path.stem,json.loads(path.read_text())))
            return result
        def done(data,error):
            if error:accounts.add(label(error,'note',True));return
            if not data:accounts.add(label('当前目录没有模拟账户归档。','muted'));return
            tabs=QTabWidget()
            for name,state in data:tabs.addTab(raw(state),name)
            accounts.add(tabs,1)
        self.async_call(read,done)

    def comparison(self):
        box=self.page(LEGACY_NAV[10],'IC · Rank IC · OOS · Walk Forward · Ablation · Incremental Alpha')
        box.addWidget(label('按 Command / Ctrl 或 Shift 选择同页 2–4 个实验。保留各自数据范围和评价口径，不直接将不同样本排名。','note',True))
        action=button('比较选中实验',lambda:compare(),True);box.addWidget(row(action,button('相关性研究',lambda:self.new_experiment(mode='correlation')),button('残差与检验族',self.research_tools)))
        holder=self.run_list(box,multi=True)
        def compare():
            t=holder['table'];indices=sorted({i.row() for i in t.selectedIndexes()}) if t else []
            if not 2<=len(indices)<=4:self.status.setText('请选择 2–4 个实验。');return
            ids=[holder['rows'][i]['run_id'] for i in indices]
            def done(records,error):
                if error:return
                dialog=QDialog(self);dialog.setWindowTitle('结果对比');dialog.resize(1250,750);layout=QVBoxLayout(dialog)
                layout.addWidget(label('不同数据范围和口径分别保留；以下是原始归档结果。','note',True))
                tabs=QTabWidget()
                for r in records:tabs.addTab(self.record_widget(r),r['run_id'][:8])
                layout.addWidget(tabs);self.show_dialog(dialog)
            self.async_call(lambda:[self.catalog.record(i) for i in ids],done)

    def research_chat(self):
        from PyQt6 import sip
        from .research_chat import ResearchChatDialog
        try:
            dialog=getattr(self,'_research_chat_dialog',None)
            if dialog is not None and not sip.isdeleted(dialog) and dialog.output==self.output and dialog.data_root==self.data_root:
                dialog.show();dialog.raise_();dialog.activateWindow();return
            dialog=ResearchChatDialog(self);self._research_chat_dialog=dialog;self.show_dialog(dialog)
        except Exception as error:self.status.setText('研究助手未打开：'+str(error))

    def ask_ai(self,prompt):
        """Open the assistant with page context pre-filled; the user reviews and sends."""
        self.research_chat()
        dialog=getattr(self,'_research_chat_dialog',None)
        if dialog is not None and hasattr(dialog,'prefill') and not dialog.prefill(prompt):
            self.status.setText('助手正在回答上一个问题，稍后再试。')

    def open_stock_report(self,code):
        self.pending_stock=code;self.navigate_page('stock')

    def research_tools(self):
        from .research_tools import ResearchToolsDialog
        self.show_dialog(ResearchToolsDialog(self))

    def settings(self):
        from PyQt6.QtWidgets import QFileDialog
        def restore():
            bundle,_=QFileDialog.getOpenFileName(self,'选择实验复现包',str(self.output),'实验包 (*.zip)')
            if not bundle:return
            parent=QFileDialog.getExistingDirectory(self,'选择恢复目录的上级文件夹',str(self.output))
            if not parent:return
            from quantlab.storage.bundle import restore_bundle
            destination=Path(parent)/('restored-'+str(uuid4())[:8])
            self.status.setText('正在校验并恢复实验包…')
            def done(result,error):
                self.status.setText(error or '已恢复并校验：'+result['artifact_root']+'；可在路径设置中切换。')
            self.async_call(lambda:restore_bundle(bundle,destination),done,guarded=False)
        box=self.page(LEGACY_NAV[11],'当前桌面工作空间 · 数据存储 · 研究执行 · 适配器状态')
        paths=Card('路径与存储');paths.add(table(['项目','当前配置'],[['行情只读目录',str(self.data_root or '未配置')],['研究产物目录',str(self.output)],['界面','PyQt6 原生 QWidget / QPainter'],['数据格式','Parquet / DuckDB']]));box.addWidget(paths)
        engine=Card('研究引擎与边界');engine.add(table(['能力','状态'],[['因子注册',len(self.factors)],['固定理论模板',len(self.theories)],['vn.py','独立回测通过 execution_backend 选择；安装不等于逐笔已验证'],['机器学习 / 实盘','未启用']]));box.addWidget(engine)
        box.addWidget(button('修改当前工作空间路径',self.edit_paths,True))
        box.addWidget(button('恢复并校验实验复现包',restore))
        def offline_environment():
            parent=QFileDialog.getExistingDirectory(self,'选择离线环境包的保存位置',str(self.output))
            if not parent:return
            from quantlab.storage.offline_environment import export_offline_environment
            destination=Path(parent)/('offline-environment-'+str(uuid4())[:8])
            self.status.setText('正在下载固定版本 Python 和依赖；首次导出需要联网…')
            self.async_call(lambda:export_offline_environment(destination),lambda result,error:self.status.setText(error or '离线环境已导出：'+result['path']),guarded=False)
        box.addWidget(button('导出当前离线运行环境',offline_environment))

        box.addWidget(label('路径修改仅作用于本次桌面会话；不会移动产物或修改行情文件。','note',True));box.addStretch()

    def edit_paths(self):
        from PyQt6.QtWidgets import QFileDialog
        dialog=QDialog(self);dialog.setWindowTitle('工作空间路径');dialog.resize(760,250);form=QVBoxLayout(dialog)
        output=QLineEdit(str(self.output));data=QLineEdit(str(self.data_root or ''));notice=label('应用后重新加载所选目录；启动参数不变。','muted',True)
        def browse(control):
            path=QFileDialog.getExistingDirectory(dialog,'选择目录',control.text())
            if path:control.setText(path)
        form.addWidget(label('研究产物目录'));form.addWidget(row(output,button('选择目录',lambda:browse(output))))
        form.addWidget(label('只读行情目录（留空关闭执行）'));form.addWidget(row(data,button('选择目录',lambda:browse(data))));form.addWidget(notice)
        def apply():
            if self.callbacks or (self.queue and any(j['status'] in ('queued','running') for j in self.queue.list())):
                notice.setText('请等待当前读取或实验完成后再切换目录。');return
            try:
                catalog=ArtifactCatalog(output.text());data_root=Path(data.text()).resolve() if data.text().strip() else None
                if data_root is not None and not data_root.is_dir():raise ValueError('行情目录不存在')
                if self.queue:self.queue.close();self.queue=None
                self.catalog=catalog;self.output=catalog.root;self.data_root=data_root;self.last_records=[]
                # Old forms retain their original workspace; close them before switching.
                for child in self.dialogs:
                    if isinstance(child,QDialog):child.close()
                self.settings();dialog.accept()
            except (OSError,ValueError) as exc:notice.setText(str(exc))
        form.addWidget(row(button('应用路径',apply,True),button('取消',dialog.reject)));self.show_dialog(dialog)

    def global_search(self):
        query=self.search.text().strip();box=self.page('全局搜索',f'关键词：{query or "全部"} · 股票 / Decision / 因子 / 理论 / 实验')
        from quantlab.trading.decision_store import DecisionStore
        decisions=DecisionStore(self.output).list(query=query,limit=50)['records']
        dcard=Card(f'Decision / 股票 · {len(decisions)}')
        dcard.add(table(['证券','交易日','Frame','动作','主题','判断'],[[d['symbol'],d['trading_day'],d['frame'],d['action'],d.get('theme',''),d.get('ai_thesis','')[:80]] for d in decisions],lambda i:self.open_decision(decisions[i])))
        box.addWidget(dcard)
        matches=[v for v in self.factors+self.theories if query.casefold() in encode(v).casefold()]
        card=Card(f'注册定义 · {len(matches)}')
        card.add(table(['名称','ID','类型'],[[v.get('definition',v).get('name_cn',v.get('name','')),v.get('definition',v).get('factor_id',v.get('template_id','')),v.get('definition',{}).get('factor_type','theory')] for v in matches],lambda i:self.new_experiment(matches[i])))
        box.addWidget(card);self.run_list(box,query=query)

    def record_widget(self,record):
        tabs=QTabWidget();overview=QWidget();box=QVBoxLayout(overview)
        execution=record.get('execution')
        if execution:
            execution_view=execution_table(execution);execution_view.setMinimumHeight(220)
            box.addWidget(execution_view,1)
        metrics=[]
        def visit(value,path='当前实验'):
            if not isinstance(value,dict):return
            for h,m in sorted((value.get('metrics') or {}).items(),key=lambda item:int(item[0])):
                metrics.append([path,h,*[m.get(k) for k in ('observations','factor_coverage','mean_forward_return','ic','rank_ic','icir','long_short_spread')]])
            for key in ('periods','folds','children','evaluations'):
                children=value.get(key,[])
                for k,v in (children.items() if isinstance(children,dict) else enumerate(children)):
                    visit(v,path+' / '+str(v.get('name',v.get('phase',k))) if isinstance(v,dict) else path)
        visit(record)
        if metrics:box.addWidget(table(['阶段','持有期','样本数','覆盖率','平均未来收益','IC','Rank IC','ICIR','多空差'],metrics))
        if record.get('kind')=='residual_alpha' and record.get('summary'):
            summary=record['summary'];test=summary.get('test',{})
            box.addWidget(table(['残差研究指标','数值'],[
                ['训练截止',summary.get('train_end')],['持有期',summary.get('horizon')],
                ['训练样本数',summary.get('model',{}).get('train_rows')],['样本外观测数',summary.get('test_rows')],
                ['原始 IC',summary.get('test_raw_ic')],['残差 IC',summary.get('test_residual_ic')],
                ['原始 p 值（未做跨研究校正）',test.get('p_value')],['检验状态',test.get('reason') or test.get('status')]]))
            box.addWidget(label('仅在训练期拟合控制投影；残差 IC 不等于成交收益或因果贡献。','note',True))
        elif record.get('kind')=='correlation':
            box.addWidget(table(['因子 A','因子 B','Pearson','Spearman','归一化互信息','触发重合度','1根IC相关'],[
                [*[p.get(k) for k in ('left','right','pearson','spearman')],p.get('mutual_information',{}).get('normalized'),p.get('signal_overlap',{}).get('jaccard'),p.get('ic_correlation',{}).get('estimate')] for p in record.get('pairs',[])]))
            box.addWidget(label('互信息采用每时点五分位离散估计，存在小样本偏差；触发重合度只比较布尔因子共同有效样本。两者不是独立性或显著性证明。','note',True))
            box.addWidget(label('完全链接分组：'+'；'.join(' / '.join(g) for g in record.get('groups',[])),'muted',True))
        elif record.get('kind')=='return_increment':
            summary=record.get('summary',{});test=summary.get('permutation',{})
            box.addWidget(table(['净收益比较指标','数值'],[
                ['评价起点',summary.get('evaluation_start')],['配对交易日',summary.get('days')],
                ['日均净收益差',summary.get('mean_daily_difference')],['原始 p 值',test.get('p_value')],
                ['检验状态',test.get('reason') or test.get('status')]]),1)
            box.addWidget(label('候选减基准；这是相同约束下的回顾性净收益差。跨比较校正请查看固定检验族报告。','note',True))
        elif record.get('kind')=='campaign':
            summary=record.get('summary',{});family=summary.get('family') or {}
            box.addWidget(label('固定研究包：'+summary.get('workflow_status','unknown')+'；原计划检验 '+str(summary.get('planned_tests',0))+' 项。失败和跳过项保留，不按显著性追加节点。','note',True))
            box.addWidget(table(['节点','状态','原因','实验编号'],[[n.get('node_id'),n.get('status'),n.get('reason',n.get('error','')),n.get('run_id','')] for n in summary.get('nodes',[])]))
            box.addWidget(table(['节点','持有期','指标','状态','原始p','Holm p'],[[t.get(k) for k in ('trial_id','horizon','metric','status','p_value','p_holm')] for t in family.get('tests',[])]))
        elif record.get('kind')=='trial_registry':
            summary=record.get('summary',{})
            box.addWidget(label(f"原计划 {summary.get('planned_tests',0)} 项；可用 p 值 {summary.get('available_tests',0)} 项。失败、部分失败及未运行项保留；原登记时间不代表新预注册。",'note',True))
            box.addWidget(table(['试验','路径','持有期','指标','状态','原始 p 值','Holm p 值'],[[r.get(k) for k in ('trial_id','path','horizon','metric','status','p_value','p_holm')] for r in summary.get('tests',[])]),1)
        elif record.get('kind')=='return_family':
            summary=record.get('summary',{})
            box.addWidget(label(f"原计划 {summary.get('planned_tests',0)} 项；有可用 p 值 {summary.get('available_tests',0)} 项。失败项保留在 Holm 校正范围内。",'note',True))
            box.addWidget(table(['比较','状态','原始 p 值','Holm p 值','拒绝零假设'],[[r.get(k) for k in ('id','status','p_value','p_holm','reject')] for r in summary.get('tests',[])]),1)
        elif record.get('kind')=='stability':
            box.addWidget(table(['比较项','持有期','日期数','日均 Rank IC 差','原始 p 值','Holm p 值','拒绝均值相等'],[
                [r.get('name'),r.get('horizon'),r.get('dates'),r.get('estimate'),r.get('test',{}).get('p_value'),r.get('p_holm'),r.get('reject_equal_mean')]
                for r in record.get('summary',{}).get('comparisons',[])]),1)
            if record.get('summary',{}).get('method') in ('subsample_equivalence','cross_market_equivalence'):
                box.addWidget(table(['子样本比较','容许差异 ±','区间下限','区间上限','有效配对日','等效结论'],[
                    [r['name'],r['equivalence']['margin'],r['equivalence']['interval']['ci_low'],r['equivalence']['interval']['ci_high'],r['equivalence']['paired_valid_dates'],
                        '支持等效' if r['equivalence']['equivalent'] is True else ('未能确认等效' if r['equivalence']['equivalent'] is False else '样本或重采样不足')]
                    for r in record['summary']['comparisons']]),1)
                box.addWidget(label('不重叠证券组、固定参数、相同日期的 Rank IC 差。等效性使用日期块近似区间和计划内 Bonferroni 校正；范围需事先设定，归档不证明事前登记。','note',True))
            else:box.addWidget(label('共同证券与日期样本；未拒绝均值相等不等于证明参数稳定或等效。','note',True))
        elif not execution and not metrics:box.addWidget(label('此记录没有通用指标，请查看完整记录与研究报告。','muted'))
        if record.get('_display_summary'):
            box.addWidget(label('当前为轻量概览；配置或列表超过 200 项时截断预览，完整数据以原始归档为准。完整审计和回放可按需载入。','note',True))
        if record.get('limitations'):
            limits=QScrollArea();limits.setWidgetResizable(True);limits.setMaximumHeight(150)
            limits.setWidget(label('\n'.join(record['limitations']),'muted',True));box.addWidget(limits)
        tabs.addTab(overview,'研究概览')
        from .research_summary import research_statistics
        if metrics or record.get('inference') or record.get('regime_summary'):tabs.addTab(research_statistics(record),'统计与市场状态')
        if record.get('sequence_overlap'):
            overlap=record['sequence_overlap'];page=QWidget();layout=QVBoxLayout(page)
            layout.addWidget(label('完整事件链逐项保留事件顺序、版本、内容与可用时间；同一完成时刻不代表同一链。此处标记已观察链的重复，不自动删除因子，也不证明规则等效。','note',True))
            layout.addWidget(table(['序列 A','序列 B','A 独立链数','B 独立链数','相同链数','完整链 Jaccard'],[[p.get(k) for k in ('left','right','left_unique_chains','right_unique_chains','intersection','jaccard')] for p in overlap.get('pairs',[])]))
            tabs.addTab(page,'完整序列去重')
        from .audit_view import AuditView
        tabs.addTab(BusinessDetails(record['manifest']),'配置 / 数据快照')
        if record.get('_display_summary'):
            audit_holder=QWidget();audit_box=QVBoxLayout(audit_holder)
            audit_status=label('完整审计按需读取；大型记录可能需要等待。','muted',True);audit_box.addWidget(audit_status)
            def read_audit():
                audit_button.setEnabled(False)
                def done(full,error):
                    audit_button.setEnabled(True)
                    if error:audit_status.setText(error);return
                    audit_box.addWidget(AuditView(full.get('sequence_audit',{})));audit_button.hide()
                self.async_call(lambda:self.catalog.record(record['run_id']),done,guarded=False)
            audit_button=button('载入完整序列审计',read_audit);audit_box.addWidget(audit_button);tabs.addTab(audit_holder,'序列审计')
        else:tabs.addTab(AuditView(record.get('sequence_audit',{})),'序列审计')
        source_path=self.catalog.file(record['run_id'],'experiment.json')
        if source_path.stat().st_size>200000:
            preview=QWidget();preview_box=QVBoxLayout(preview)
            path=self.catalog.file(record['run_id'],'experiment.json')
            preview_box.addWidget(label(f'完整原始记录：{path}\n大样本记录按需读取，界面仅预览前 200,000 个字符；完整数据保存在上述文件。','muted',True))
            text=QPlainTextEdit();text.setReadOnly(True)
            def load_preview():
                def read():
                    with path.open(encoding='utf-8') as stream:return stream.read(200000)
                self.async_call(read,lambda data,error:text.setPlainText(error or data),guarded=False)
            preview_box.addWidget(button('读取原始记录预览',load_preview));preview_box.addWidget(text,1);tabs.addTab(preview,'完整记录')
        else:tabs.addTab(BusinessDetails(record),'完整记录')
        if execution and any(execution.get(key) for key in ('corporate_action_ledger','split_ledger','rights_ledger','rights_trading_ledger','dividend_tax_ledger')):
            from .corporate_actions import action_ledger
            def load_actions(done):
                from quantlab.storage.experiments import load_record_fields
                self.async_call(lambda:load_record_fields(self.catalog.file(record['run_id'],'experiment.json'),{'execution'}).get('execution',{}),done,guarded=False)
            tabs.addTab(action_ledger(execution,bool(record.get('_display_summary')),load_actions),'公司行动与费用')
        if execution:
            from .trade_ledger import TradeLedger
            def load_trades(done):
                from quantlab.storage.experiments import load_record_fields
                self.async_call(lambda:load_record_fields(self.catalog.file(record['run_id'],'experiment.json'),{'fills','rejections','backend_comparison'}),done,guarded=False)
            tabs.addTab(TradeLedger(record,load_trades),'成交账本与拒单')
            if record.get('backend_comparison'):
                tabs.addTab(BusinessDetails(record['backend_comparison']),'vn.py 核对详情')
        return tabs

    def open_run(self,run_id):
        from .result_view import open_result_view
        return open_result_view(self,run_id)

    def show_dialog(self,dialog):
        # Keep widgets alive for outstanding background reads; release with the main window.
        self.dialogs.append(dialog);dialog.show()

    # Observation-table updates affect only visible rows, never archived data.
    def observations_widget(self,run_id):
        w=QWidget();box=QVBoxLayout(w);symbol=QLineEdit();symbol.setPlaceholderText('证券代码，例如 sh.600000');status=label('','muted');holder={'offset':0,'epoch':0,'table':None}
        def clear_rows(*_):
            holder['epoch']+=1
            if holder['table'] is not None:holder['table'].setRowCount(0)
            prev.setEnabled(False);nxt.setEnabled(False)
            status.setText('筛选已变化，请重新检索；旧结果已清除。')
        def load(delta=0,reset=False):
            holder['offset']=0 if reset else max(0,holder['offset']+delta);holder['epoch']+=1;request=holder['epoch'];offset=holder['offset'];stock=symbol.text().strip()
            clear_rows();request=holder['epoch']
            prev.setEnabled(False);nxt.setEnabled(False);status.setText('读取中…')
            def done(data,error):
                if request!=holder['epoch']:return
                if error:status.setText(error);return
                if holder['table']:box.removeWidget(holder['table']);holder['table'].deleteLater()
                t=table(data['columns'],[[r[k] for k in data['columns']] for r in data['rows']]);holder['table']=t;box.addWidget(t,1)
                status.setText(f"{offset} / {data['total']}（每页 30 行）");prev.setEnabled(offset>0);nxt.setEnabled(offset+30<data['total'])
            self.async_call(lambda:self.catalog.observations(run_id,offset,30,stock),done,False)
        prev=button('上一页',lambda:load(-30));nxt=button('下一页',lambda:load(30));box.addWidget(row(symbol,button('检索',lambda:load(reset=True)),prev,nxt,status))
        symbol.textChanged.connect(clear_rows);load();return w

    def replay_widget(self,run_id,record):
        from .replay import ReplayWidget
        if record.get('_display_summary'):
            holder=QWidget();box=QVBoxLayout(holder);notice=label('按需载入完整 K 线与审计；概览不会预先解析全部数据。','muted',True);box.addWidget(notice)
            def load():
                control.setEnabled(False)
                def done(full,error):
                    control.setEnabled(True)
                    if error:notice.setText(error);return
                    box.addWidget(ReplayWidget(self,run_id,full),1);control.hide();notice.hide()
                self.async_call(lambda:self.catalog.record(run_id),done,guarded=False)
            control=button('载入 K 线回放',load);box.addWidget(control);return holder
        return ReplayWidget(self,run_id,record)

    def show_jobs(self):
        box=self.page('运行任务','本地研究队列 · 状态来自任务归档');box.addWidget(button('刷新任务',self.show_jobs));card=Card('任务列表');box.addWidget(card,1)
        def read():
            if self.queue:return self.queue.list()
            return [json.loads(p.read_text()) for p in sorted((self.output/'_jobs').glob('*.json')) if not p.is_symlink()]
        def resume(identifier):
            try:
                if self.data_root is None:raise ValueError('请先配置行情数据目录')
                self.get_research_queue()
                self.queue.resume(identifier)
                self.status.setText('任务已恢复：复用校验通过的缓存和缠论状态断点，其余步骤重新计算。')
                self.show_jobs()
            except (ValueError,OSError) as error:self.status.setText(str(error))
        def done(data,error):
            if error:card.add(label(error,'note'));return
            card.add(table(['研究问题','状态','当前阶段','任务 ID','错误'],[[j['spec'].get('question',''),j['status'],(j.get('progress') or {}).get('stage','')+(' '+str(j['progress']['completed'])+'/'+str(j['progress']['total']) if (j.get('progress') or {}).get('total') else ''),j['job_id'],j.get('error','')] for j in data],lambda i:self.open_run(data[i]['run_id']) if data[i].get('run_id') else self.status.setText(data[i].get('error') or '任务尚未完成。')),1)
            if self.queue:
                for job in data:
                    if job['status'] in ('queued','running'):
                        cancel=button(('取消已请求 ' if job.get('cancel_requested') else '取消任务 ')+job['job_id'][:8],lambda identifier=job['job_id']:(self.queue.cancel(identifier),self.show_jobs()))
                        cancel.setEnabled(not job.get('cancel_requested'));card.add(cancel)
            for job in data:
                if job['status'] in ('interrupted','cancelled','failed') or (self.queue is None and job['status'] in ('queued','running')):
                    card.add(button('恢复任务 '+job['job_id'][:8],lambda identifier=job['job_id']:resume(identifier)))
        self.async_call(read,done)

    def new_experiment(self,definition=None,mode='single'):
        from .experiment import ExperimentDialog
        dialog=ExperimentDialog(self,definition,mode);self.show_dialog(dialog)

    def closeEvent(self,event):
        running=self.queue and any(j['status'] in ('queued','running') for j in self.queue.list())
        if self.callbacks or running:
            self.closing=True;self.centralWidget().setEnabled(False);self.status.setText('正在等待当前读取 / 实验完成后关闭，以保留完整产物。');self.shutdown_timer.start();event.ignore();return
        self.shutdown_timer.stop()
        if self.queue:self.queue.close()
        self.pool.waitForDone();event.accept()


def launch(output=Path('artifacts'),data_root=None):
    app=QApplication.instance() or QApplication(sys.argv[:1]);app.setApplicationName('牛牛平台');app.setStyle('Fusion')
    from .data_workbench import DataConnectedWorkbench
    window=DataConnectedWorkbench(output,data_root);window.show();return app.exec()

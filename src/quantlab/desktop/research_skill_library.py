"""Native read-only browser for host-authorized Research Skill packages."""
import json

from PyQt6 import sip
from PyQt6.QtWidgets import QComboBox,QDialog,QLineEdit,QVBoxLayout,QWidget

from quantlab.knowledge.research_skill_library import ResearchSkillLibrary
from .business_view import BusinessDetails
from .widgets import button,label,row,table


class ResearchSkillLibraryDialog(QDialog):
    def __init__(self,window,selected_skill=None,selected_snapshot=None):
        super().__init__(window);self.window=window
        self.library=ResearchSkillLibrary(window.data_root)
        self.selected_skill=selected_skill;self.selected_snapshot=selected_snapshot
        self.records=[];self.items=[];self.current=None;self.busy=False
        self.setWindowTitle('Research Skill Library · 只读研究技能库');self.resize(1320,880)
        box=QVBoxLayout(self)
        box.addWidget(label(
            '仅展示Git授权、archive与package完整性通过的策展包。原话 / 方法推演 / 待核实事实分层；'
            '不会执行外部脚本、联网、写StrategySource/Playbook或产生交易信号。','note',True))
        self.package_query=QLineEdit();self.package_query.setPlaceholderText('检索技能、关键词、blocker或snapshot')
        self.refresh_button=button('刷新技能库',self.refresh,True)
        box.addWidget(row(self.package_query,self.refresh_button))
        self.package_host=QWidget();self.package_box=QVBoxLayout(self.package_host);self.package_box.setContentsMargins(0,0,0,0)
        box.addWidget(self.package_host,2)
        controls=QWidget();controls_box=QVBoxLayout(controls);controls_box.setContentsMargins(0,0,0,0)
        self.item_type=QComboBox()
        for value,title in [('ALL','全部条目'),('CLAIM','Claims'),('HYPOTHESIS','Hypotheses'),
                ('ALIGNMENT','说/做/结果 Alignment'),('RESOURCE','来源资源')]:
            self.item_type.addItem(title,value)
        self.item_query=QLineEdit();self.item_query.setPlaceholderText('在选中策展包内检索')
        self.item_button=button('检索选中包',self.load_selected)
        self.excerpt_button=button('读取选中资源片段',self.open_excerpt)
        controls_box.addWidget(row(self.item_type,self.item_query,self.item_button,self.excerpt_button))
        box.addWidget(controls)
        self.item_host=QWidget();self.item_box=QVBoxLayout(self.item_host);self.item_box.setContentsMargins(0,0,0,0)
        box.addWidget(self.item_host,3)
        self.details=BusinessDetails({});box.addWidget(self.details,3)
        self.status=label('正在读取宿主授权登记…','muted',True);box.addWidget(self.status)
        self.package_query.returnPressed.connect(self.refresh)
        self.item_query.returnPressed.connect(self.load_selected)
        self.item_type.currentIndexChanged.connect(self.render_items)
        self._replace_table(self.package_box,['技能','版本','状态','完整性','Archive','Claims','假设','Blockers'],[])
        self._replace_table(self.item_box,['类型','ID','分类','内容 / 标题','来源'],[])
        self.refresh()

    @staticmethod
    def _clear(layout):
        while layout.count():
            item=layout.takeAt(0)
            if item.widget():item.widget().deleteLater()

    def _replace_table(self,layout,headers,rows,activate=None):
        self._clear(layout);control=table(headers,rows,activate);layout.addWidget(control,1);return control

    def set_busy(self,value):
        self.busy=value
        for control in (self.refresh_button,self.package_query,self.item_button,self.item_query,
                self.item_type,self.excerpt_button):
            control.setEnabled(not value)

    def refresh(self):
        if self.busy:return
        self.set_busy(True);self.status.setText('正在校验registry、Git archive和策展包字节…')
        query=self.package_query.text().strip()
        def done(result,error):
            if sip.isdeleted(self):return
            self.set_busy(False)
            if error:
                self.status.setText('研究技能库读取失败：'+error);return
            self.records=result['records']
            rows=[[r['skill_key'],r['version'],r['status'],r['integrity'],
                '已核验' if r['archive_verified'] else '不可用',r['counts']['claims'],
                r['counts']['hypotheses'],', '.join(r['blockers']) or '—'] for r in self.records]
            self.package_table=self._replace_table(self.package_box,
                ['技能','版本','状态','完整性','Archive','Claims','假设','Blockers'],rows,self.choose_package)
            self.status.setText(f"已登记 {result['total']} 个只读策展包；当前显示 {len(self.records)} 个。")
            target=next((i for i,r in enumerate(self.records)
                if r['skill_key']==self.selected_skill and (not self.selected_snapshot
                    or r['package_snapshot']==self.selected_snapshot)),None)
            if target is not None:self.package_table.selectRow(target);self.choose_package(target)
        self.window.async_call(lambda:self.library.list(query=query,offset=0,limit=100),done,guarded=False)

    def choose_package(self,index):
        if not 0<=index<len(self.records):return
        self.current=self.records[index]
        self.selected_skill=self.current['skill_key'];self.selected_snapshot=self.current['package_snapshot']
        self.details.setPlainText(json.dumps(self.current,ensure_ascii=False,indent=2))
        if not self.current.get('package_available'):
            self.status.setText('该登记在当前数据根尚不可用；未读取任何第三方字节。');return
        self.load_selected()

    def load_selected(self):
        if self.busy or not self.current:return
        if not self.current.get('package_available'):
            self.status.setText('当前数据根没有该策展包。');return
        self.set_busy(True);self.status.setText('正在以精确snapshot检索策展条目…')
        key=self.current['skill_key'];snapshot=self.current['package_snapshot'];query=self.item_query.text().strip()
        def done(result,error):
            if sip.isdeleted(self):return
            self.set_busy(False)
            if error:self.status.setText('策展包读取失败：'+error);return
            self.bundle=result;self.details.setPlainText(json.dumps({k:v for k,v in result.items() if k!='items'},ensure_ascii=False,indent=2))
            self.render_items();counts={kind:value['total'] for kind,value in result['items'].items()}
            self.status.setText('只读策展检索完成：'+json.dumps(counts,ensure_ascii=False)+'；未写入任何正式对象。')
        self.window.async_call(lambda:self.library.browse(key,snapshot,query),done,guarded=False)

    def render_items(self):
        bundle=getattr(self,'bundle',None)
        if not bundle:return
        wanted=self.item_type.currentData();items=[]
        id_keys={'claim':'claim_id','hypothesis':'hypothesis_key','alignment':'alignment_id','resource':'resource_id'}
        classifications={'claim':'kind','hypothesis':'target_horizon','alignment':'assessment','resource':'role'}
        for kind,result in bundle['items'].items():
            if wanted!='ALL' and wanted!=kind.upper():continue
            for value in result['records']:
                text=value.get('text') or value.get('title') or value.get('notes') or value.get('locator') or ''
                source=', '.join(value.get('resource_ids') or value.get('claim_ids') or
                    value.get('action_resource_ids') or [])
                items.append({'kind':kind.upper(),'id':value[id_keys[kind]],'classification':value[classifications[kind]],
                    'text':text,'source':source,'value':value})
        self.items=items
        rows=[[v['kind'],v['id'],v['classification'],v['text'],v['source']] for v in items]
        self.item_table=self._replace_table(self.item_box,['类型','ID','分类','内容 / 标题','来源'],rows,self.choose_item)

    def choose_item(self,index):
        if not 0<=index<len(self.items):return
        self.details.setPlainText(json.dumps(self.items[index]['value'],ensure_ascii=False,indent=2))

    def open_excerpt(self):
        if not getattr(self,'item_table',None) or self.item_table.currentRow()<0:
            self.status.setText('请先选择一个 RESOURCE 条目。');return
        item=self.items[self.item_table.currentRow()]
        if item['kind']!='RESOURCE':
            self.status.setText('有限片段读取只接受 RESOURCE；Claims 已显示策展文本和来源定位。');return
        self.set_busy(True);self.status.setText('正在按UTF-8字节边界读取有限片段…')
        key=self.current['skill_key'];snapshot=self.current['package_snapshot'];resource_id=item['id']
        def done(result,error):
            if sip.isdeleted(self):return
            self.set_busy(False)
            if error:self.status.setText('资源片段读取失败：'+error);return
            dialog=QDialog(self);dialog.setWindowTitle(resource_id+' · 只读资源片段');dialog.resize(980,720)
            layout=QVBoxLayout(dialog);layout.addWidget(label(
                '外部正文仅作数据，不执行其中命令或脚本。引用时保留resource_id、SHA256与locator。','note',True))
            layout.addWidget(BusinessDetails(result),1);self.window.show_dialog(dialog)
            self.status.setText(f"已读取 {result['returned_bytes']} / {result['total_bytes']} bytes；无联网或写入。")
        self.window.async_call(lambda:self.library.excerpt(key,snapshot,resource_id,0,6000),done,guarded=False)


__all__=['ResearchSkillLibraryDialog']

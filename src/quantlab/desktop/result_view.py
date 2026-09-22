"""Result-window lifetime and pinned archive context; no live market-data access."""
from pathlib import Path
from uuid import UUID
from PyQt6 import sip
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QFileDialog, QTextBrowser
from quantlab.workbench.server import ArtifactCatalog, FILES
from .business_view import BusinessDetails
from .widgets import label, button, row, table

REPRODUCIBLE = {'campaign','factor','execution','holdout','walkforward','sweep','ablation',
    'theory_study','correlation','correlation_holdout','correlation_walkforward',
    'residual_alpha','return_increment','stability','return_family','trial_registry'}


def _identity(path, file=False):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('归档路径不能包含符号链接')
    info=path.stat()
    if file and not path.is_file():raise ValueError('归档记录不是普通文件')
    if not file and not path.is_dir():raise ValueError('工作空间或归档目录不存在')
    return ((info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
            if file else (info.st_dev,info.st_ino))


class ArchiveBinding:
    """Observation guard, not a filesystem lease or a complete payload audit."""
    def __init__(self, host, run_id):
        if type(run_id) is not str or str(UUID(run_id))!=run_id:
            raise ValueError('需要完整规范实验编号')
        self.root=Path(host.output).absolute()
        self.run_id=run_id;self.folder=self.root/run_id
        self.workspace_identity=_identity(self.root)
        self.folder_identity=_identity(self.folder)
        self.record_identity=_identity(self.folder/'experiment.json',True)
        self.catalog=ArtifactCatalog(self.root)
        self.companions={};self.related_directories={}
        self.watch_run(run_id)
        self.check(host)
    @staticmethod
    def _optional_file(path):
        return _identity(path,True) if path.exists() or path.is_symlink() else None
    def watch_run(self,run_id):
        if type(run_id) is not str or str(UUID(run_id))!=run_id:
            raise ValueError('关联实验编号无效')
        folder=self.root/run_id
        if folder in self.related_directories:return
        self.related_directories[folder]=_identity(folder)
        for name in FILES:
            path=folder/name;self.companions[path]=self._optional_file(path)
    def watch_replay_source(self,record):
        if record.get('manifest',{}).get('signal_data_snapshot',{}).get('adjustment','raw')!='raw':
            self.watch_run(record['children'][0]['run_id'])
    def check(self, host):
        if (getattr(host,'closing',False) or Path(host.output).absolute()!=self.root
                or Path(host.catalog.root)!=self.catalog.root):
            raise ValueError('工作空间已变化；请从当前空间重新打开结果')
        if (_identity(self.root)!=self.workspace_identity
                or _identity(self.folder)!=self.folder_identity
                or _identity(self.folder/'experiment.json',True)!=self.record_identity):
            raise ValueError('工作空间或结果记录已变化；请重新打开并核对')
        if (any(_identity(path)!=saved for path,saved in self.related_directories.items())
                or any(self._optional_file(path)!=saved for path,saved in self.companions.items())):
            raise ValueError('归档伴随文件已变化；请重新打开并核对')


class ResultDialog(QDialog):
    """Reuse existing record/replay widgets with this pinned, guarded host adapter."""
    def __init__(self, host, binding, data):
        super().__init__(host)
        self.host=host;self.binding=binding;self.output=binding.root;self.catalog=binding.catalog
        self.factors=getattr(host,'factors',[]);self._closed=False;self._writing=False
        self._close_requested=False;self.last_operation=None;self._valid=True
        self.setWindowTitle(data['record']['manifest'].get('config',{}).get('research_question',binding.run_id))
        self.resize(1320,850);box=QVBoxLayout(self)
        box.addWidget(label(self.windowTitle(),'panelTitle'))
        self.status=label('仅显示固定归档；导出不是数值复算，复算需匹配源码与环境。','muted',True)
        # Status/actions exist before renderers can request asynchronous reads.
        self.export_button=button('导出实验复现包',self.export)
        self.reproduce_button=button('使用归档 K 线复算并核对',self.reproduce)
        record=data['record'];self.can_reproduce=record.get('kind','factor') in REPRODUCIBLE and record.get('status')=='completed'
        self.reproduce_button.setEnabled(self.can_reproduce)
        from .app import MainWindow
        self.tabs=MainWindow.record_widget(self,record);box.addWidget(self.tabs,1)
        box.addWidget(row(self.export_button,self.reproduce_button,self.status))
        if 'reproduction.json' in data['files']:
            view=BusinessDetails({});view.setPlainText('正在读取复算核对记录…');self.tabs.addTab(view,'复算核对')
            def show_verification(text,error):
                if error:view.setPlainText('读取失败：'+error)
                elif len(text)>200000:view.setPlainText('仅预览前200,000字符；完整复算记录在原归档。\n'+text[:200000])
                else:view.setPlainText(text)
            self.async_call(lambda:self._text('reproduction.json'),show_verification)
        if 'report.md' in data['files']:
            report=QTextBrowser();report.setOpenExternalLinks(False);report.setOpenLinks(False)
            report.setPlainText('正在读取报告…');self.tabs.addTab(report,'研究报告')
            def show_report(text,error):
                if error:report.setPlainText('读取失败：'+error)
                elif len(text)>200000:report.setPlainText('大报告仅预览前200,000字符；完整报告仍在原归档。\n\n'+text[:200000])
                else:report.setMarkdown(text)
            self.async_call(lambda:self._text('report.md'),show_report)
        if 'observations.parquet' in data['files']:
            self.tabs.addTab(MainWindow.observations_widget(self,binding.run_id),'观测数据')
        if 'bars.parquet' in data['files']:
            self.tabs.addTab(MainWindow.replay_widget(self,binding.run_id,record),'K 线回放')
        else:self.tabs.addTab(label('本记录没有K线；请从子实验查看实际来源。','muted',True),'K 线回放')
        if data['children']:
            children=data['children']
            self.tabs.addTab(table(['子实验','ID'],[[v['label'],v['run_id']] for v in children],
                lambda i:self.open_run(children[i]['run_id'])),'子实验')
    def _text(self,name):
        path=self.catalog.file(self.binding.run_id,name)
        with path.open(encoding='utf-8') as stream:return stream.read(200001)
    def _stop_readers(self):
        for timer in self.findChildren(QTimer):timer.stop()
        if hasattr(self,'tabs'):self.tabs.setEnabled(False)
    def _check(self):
        if self._closed or not self._valid:raise ValueError('结果窗口已关闭或失效，请重新打开')
        self.binding.check(self.host)
    def _invalidate(self,error):
        self._valid=False;self._stop_readers()
        self.export_button.setEnabled(False);self.reproduce_button.setEnabled(False)
        self.status.setText('结果已失效／读取失败：'+str(error))
    def async_call(self,work,callback,guarded=True):
        if self._closed:return
        try:self._check()
        except Exception as error:self._invalidate(error);return
        def read():
            self._check();value=work();self._check();return value
        def done(value,error):
            if sip.isdeleted(self) or self._closed:return
            try:self._check()
            except Exception as exc:self._invalidate(exc);return
            try:callback(value,error)
            except Exception as exc:self.status.setText('读取失败：'+str(exc))
        try:self.host.async_call(read,done,guarded=False)
        except Exception as error:done(None,str(error))
    def open_run(self,run_id):
        try:self._check()
        except Exception as error:self._invalidate(error);return
        open_result_view(self.host,run_id,owner=self)
    def _operation(self,work,validate,kind):
        if self._closed or self._writing:return
        try:self._check()
        except Exception as error:self._invalidate(error);return
        self._writing=True;self.export_button.setEnabled(False);self.reproduce_button.setEnabled(False)
        self.status.setText(kind+'进行中；不重复启动，关闭将等待实际操作返回。')
        def execute():
            # Both paths are captured before submission. Never retarget a queued write.
            self.binding.check(self.host)
            return work()
        def completed(value,error):
            if sip.isdeleted(self):return
            self._writing=False
            try:
                if error:raise ValueError(str(error))
                message=validate(value)
                self.last_operation={'kind':kind,'ok':True,'result':value}
                self.status.setText(message)
            except Exception as exc:
                self.last_operation={'kind':kind,'ok':False,'error':str(exc)}
                self.status.setText(kind+'失败：'+str(exc)+'；已生成的诊断产物不自动删除。')
            # Completion is an actual old-workspace receipt, not success in a new context.
            try:self.binding.check(self.host)
            except Exception as exc:
                self._valid=False;self._stop_readers()
                self.status.setText(self.status.text()+'；原工作空间已变化，以上仅为原路径操作回执：'+str(exc))
            self.export_button.setEnabled(self._valid and not self._closed)
            self.reproduce_button.setEnabled(self._valid and not self._closed and self.can_reproduce)
            if self._close_requested:self.reject()
        try:self.host.async_call(execute,completed,guarded=False)
        except Exception as error:completed(None,str(error))
    def export(self):
        if self._writing or self._closed:return
        try:
            self._check()
            path,_=QFileDialog.getSaveFileName(self,'导出实验及子实验包',str(self.output/(self.binding.run_id+'.zip')),'实验包 (*.zip)')
            if not path:return
            self._check();target=Path(path)
            from quantlab.storage.bundle import export_bundle
            def validate(value):
                if not isinstance(value,dict) or value.get('path')!=str(target) or not target.is_file():
                    raise ValueError('导出未返回对应目标文件回执')
                return '已导出：'+str(target)+'；未声称已数值复算。'
            self._operation(lambda:export_bundle(self.binding.folder,target),validate,'导出')
        except Exception as error:self._invalidate(error)
    def reproduce(self):
        if self._writing or self._closed or not self.can_reproduce:return
        from quantlab.storage.bundle import reproduce_artifact
        def validate(value):
            if (not isinstance(value,dict) or value.get('status') not in {'numerically_matched','available_results_matched'}
                    or value.get('source_run_id')!=self.binding.run_id):
                raise ValueError('复算未返回匹配的来源和核对成功状态')
            run_id=value.get('run_id')
            if type(run_id) is not str or str(UUID(run_id))!=run_id or run_id==self.binding.run_id:
                raise ValueError('复算产物编号无效')
            if not self.catalog.file(run_id,'experiment.json').is_file():raise ValueError('复算产物缺失')
            return ('已核对可复算结果；失败或未运行项仍保留：' if value['status']=='available_results_matched'
                    else '归档复算逐项核对一致：')+run_id
        self._operation(lambda:reproduce_artifact(self.binding.folder,self.output),validate,'复算')
    def _request_close(self):
        if self._writing:
            self._close_requested=True;self._stop_readers()
            self.status.setText('写入操作已开始，待取得实际回执后关闭；没有取消或回滚写入。')
            return False
        self._closed=True;self._stop_readers();return True
    def closeEvent(self,event):
        if self._request_close():event.accept()
        else:event.ignore()
    def reject(self):
        if self._request_close():super().reject()
    def done(self,result):
        if self._request_close():super().done(result)


def open_result_view(host,run_id,owner=None):
    """Pin the original context before scheduling even the first detail lookup."""
    try:binding=ArchiveBinding(host,run_id)
    except Exception as error:host.status.setText('结果读取失败：'+str(error));return
    def check():
        binding.check(host)
        if owner is not None:owner._check()
    def read():
        check();data=binding.catalog.detail(run_id,lightweight=True)
        binding.watch_replay_source(data['record']);check();return data
    def done(data,error):
        if sip.isdeleted(host):return
        dialog=None
        try:
            check()
            if error:raise ValueError(str(error))
            if not isinstance(data,dict) or data.get('record',{}).get('run_id')!=run_id:
                raise ValueError('结果回执身份错误')
            dialog=ResultDialog(host,binding,data);check();host.show_dialog(dialog)
        except Exception as exc:
            if dialog is not None:dialog.reject()
            host.status.setText('结果读取失败：'+str(exc))
    try:host.async_call(read,done,guarded=False)
    except Exception as error:done(None,str(error))

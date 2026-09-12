"""Optional data-connected host; reuses the original workbench and research core."""
from pathlib import Path
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication,QDialog
from quantlab.desktop.app import MainWindow
from quantlab.desktop.research_chat import ResearchChatDialog
from quantlab.agent.market_data_tools import MarketDataResearchAPI
from quantlab.data.baostock_ingest import load_import
from quantlab.data.baostock_dataset import dataset_manifest,check_dataset_file,read_dataset_bytes


class DataResearchChatDialog(ResearchChatDialog):
    def __init__(self,window):
        super().__init__(window)
        self.runtime.api=MarketDataResearchAPI(window.output,window.data_root)
    def receive(self,kind,value):
        super().receive(kind,value)
        if kind=='tool_result':
            for index in range(self.evidence.count()):
                item=self.evidence.item(index);ref=item.data(Qt.ItemDataRole.UserRole)
                if ref.get('kind')=='market_data':item.setText('数据批次 · '+ref['import_id'])
    def open_reference(self):
        item=self.evidence.currentItem()
        if item and item.data(Qt.ItemDataRole.UserRole).get('kind')=='market_data':
            self.window.open_baostock_data();return
        super().open_reference()


class DataConnectedWorkbench(MainWindow):
    def __init__(self,output,data_root=None):
        super().__init__(output,data_root)
        menu=self.menuBar().addMenu('Baostock 数据')
        menu.addAction('固定更新通道（跨批次接入）',self.open_baostock_series)
        menu.addAction('候选因子对照（只读）',self.open_candidate_review)
        menu.addAction('候选增量证据包',self.open_incremental_evidence)
        menu.addAction('受限DSL候选注册',self.open_dsl_candidates)
        menu.addAction('跟踪基准换版（保留旧历史）',self.open_watch_rebase)
        menu.addAction('导入、查看和选择数据集',self.open_baostock_data)
        menu.addAction('日历驱动的跟踪到期检查',self.open_readiness)
        menu.addAction('打开带数据工具的研究助手',self.research_chat)
        from .tracking_controller import TrackingController
        action=menu.addAction('受控自动跟踪与提醒',self.open_tracking_control)
        self.tracking_controller=TrackingController(self,action)
        from .notification_controller import NotificationController
        self.notification_controller=NotificationController(self,menu.addMenu("桌面通知"))
    def open_watch_rebase(self):
        from .watch_rebase import WatchRebaseDialog
        self.show_dialog(WatchRebaseDialog(self))
    def open_baostock_series(self):
        from .baostock_series import BaostockSeriesDialog
        self.show_dialog(BaostockSeriesDialog(self))
    def select_baostock_series(self,identifier):
        from quantlab.data.baostock_series import SeriesService
        from quantlab.agent.tracking_control_store import ControlStore
        service=SeriesService(self.output);service.get(identifier);directory=service.folder(identifier).resolve()
        if self.callbacks or (self.queue and any(j['status'] in ('queued','running') for j in self.queue.list())):
            raise ValueError('请先等待当前读取和研究完成')
        if self.data_root==directory:return
        controls=ControlStore(self.output).list()
        if controls['errors'] or any(s['enabled'] or any(c['status'] in ('reserved','queued','running') for c in s['cycles']) for s in controls['controls']):
            raise ValueError('切换数据源前请撤销旧授权并处理未完成任务')
        if self.queue:self.queue.close();self.queue=None
        from .baostock_series import BaostockSeriesDialog
        for child in self.dialogs:
            if isinstance(child,QDialog) and not isinstance(child,BaostockSeriesDialog):child.close()
        self.data_root=directory;self._research_chat_dialog=None;self.last_records=[]
    def open_candidate_review(self):
        from .candidate_review import CandidateReviewDialog
        self.show_dialog(CandidateReviewDialog(self))
    def open_incremental_evidence(self):
        from .incremental_evidence import IncrementalEvidenceDialog
        self.show_dialog(IncrementalEvidenceDialog(self))
    def open_dsl_candidates(self):
        from .dsl_candidates import DslCandidateDialog
        self.show_dialog(DslCandidateDialog(self))
    def open_tracking_control(self):
        from .tracking_control import TrackingControlDialog
        self.show_dialog(TrackingControlDialog(self))
    def open_baostock_data(self):
        from .baostock_data import BaostockDataDialog
        self.show_dialog(BaostockDataDialog(self))
    def open_readiness(self):
        from .refresh_readiness import RefreshReadinessDialog
        self.show_dialog(RefreshReadinessDialog(self))
    def research_chat(self):
        dialog=getattr(self,'_research_chat_dialog',None)
        if dialog is None or sip.isdeleted(dialog) or dialog.output!=self.output or dialog.data_root!=self.data_root:
            dialog=DataResearchChatDialog(self);self._research_chat_dialog=dialog;self.show_dialog(dialog)
        else:dialog.show();dialog.raise_();dialog.activateWindow()
    def select_baostock_dataset(self,identifier):
        if self.callbacks or (self.queue and any(j['status'] in ('queued','running') for j in self.queue.list())):
            raise ValueError('请先等待当前读取和研究完成，再切换数据集')
        directory,receipt=load_import(self.output,identifier);dataset=directory/'dataset'
        manifest,_=dataset_manifest(dataset)
        if receipt.get('status') not in ('completed','completed_with_errors') or not receipt.get('dataset_ready') or not manifest['ready']:raise ValueError('该批尚未具备可研究的行情')
        for relative in manifest['files']:
            read_dataset_bytes(dataset,relative,manifest)
        if self.queue:self.queue.close();self.queue=None
        from .baostock_data import BaostockDataDialog
        for child in self.dialogs:
            if isinstance(child,QDialog) and not isinstance(child,BaostockDataDialog):child.close()
        self._research_chat_dialog=None;self.data_root=dataset.resolve();self.last_records=[]
        self.status.setText('已人工选择Baostock管理数据集：'+identifier+'；原行情未移动，当前资料为回顾性口径。')


def main():
    import argparse,sys
    parser=argparse.ArgumentParser(description='原牛牛工作台＋独立Baostock数据入口')
    parser.add_argument('--output',default='artifacts');parser.add_argument('--data-root')
    args=parser.parse_args();app=QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName('牛牛 · 数据接入');app.setStyle('Fusion')
    window=DataConnectedWorkbench(args.output,args.data_root);window.show();window.open_baostock_data()
    return app.exec()


if __name__=='__main__':raise SystemExit(main())

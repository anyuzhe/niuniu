"""Opt-in OS notifications; Qt hand-off is never reported as confirmed delivery."""
from datetime import datetime
from pathlib import Path
from PyQt6 import sip
from PyQt6.QtCore import QObject,QTimer,QSettings
from PyQt6.QtWidgets import QApplication,QSystemTrayIcon,QStyle,QDialog,QVBoxLayout
from quantlab.agent.notification_delivery import DeliveryStore,notice_events,notification_text
from quantlab.storage.codec import digest,encode
from .business_view import BusinessDetails
from .widgets import label


class QtTray:
    def __init__(self, owner, open_inbox):
        icon=QApplication.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
        self.tray=QSystemTrayIcon(icon,owner);self.tray.setToolTip('牛牛研究提醒')
        self.tray.messageClicked.connect(open_inbox)
        self.tray.activated.connect(lambda reason:open_inbox() if reason==QSystemTrayIcon.ActivationReason.Trigger else None)
    def supported(self):
        return QSystemTrayIcon.isSystemTrayAvailable() and QSystemTrayIcon.supportsMessages()
    def set_enabled(self, enabled):self.tray.setVisible(enabled)
    def send(self,title,message):
        self.tray.showMessage(title,message,QSystemTrayIcon.MessageIcon.Information,10000)


class NotificationController(QObject):
    def __init__(self,window,menu,*,settings=None,transport=None,clock=None):
        super().__init__(window);self.window=window;self.busy=False;self.workspace=None
        self.settings=settings if settings is not None else QSettings('RockInnov','NiuniuNotifications')
        self.clock=clock or (lambda:datetime.now().astimezone())
        self.transport=transport or QtTray(self,window.open_tracking_control)
        self.enabled_action=menu.addAction('允许桌面通知（当前工作空间）')
        self.enabled_action.setCheckable(True)
        self.quiet_action=menu.addAction('免打扰 22:00–08:00（本机时区）')
        self.quiet_action.setCheckable(True)
        menu.addAction('检查未读并尝试通知',self.check)
        menu.addAction('查看桌面通知投递记录',self.history)
        self.refresh_settings()
        self.enabled_action.toggled.connect(self.save_settings)
        self.quiet_action.toggled.connect(self.save_settings)
        self.timer=QTimer(self);self.timer.setInterval(60000)
        self.timer.timeout.connect(self.check);self.timer.start()
    def refresh_settings(self):
        output=Path(self.window.output).resolve()
        if output==self.workspace:return
        self.workspace=output;self.key='workspaces/'+digest(str(output))+'/'
        for action,key,default in ((self.enabled_action,'enabled',False),(self.quiet_action,'quiet',True)):
            action.blockSignals(True)
            action.setChecked(self.settings.value(self.key+key,default,type=bool))
            action.blockSignals(False)
        self.transport.set_enabled(self.enabled_action.isChecked())
    def save_settings(self,*_):
        if Path(self.window.output).resolve()!=self.workspace:
            self.refresh_settings()
            self.window.status.setText("工作空间已切换，请重新选择该空间的通知设置。")
            return
        self.settings.setValue(self.key+'enabled',self.enabled_action.isChecked())
        self.settings.setValue(self.key+'quiet',self.quiet_action.isChecked());self.settings.sync()
        self.transport.set_enabled(self.enabled_action.isChecked())
        self.window.status.setText('桌面通知设置已保存；不改变研究授权，应用内提醒始终保留。')
    def permitted(self):
        if not self.enabled_action.isChecked() or self.window.closing:return False
        stamp=self.clock()
        return not (self.quiet_action.isChecked() and (stamp.hour>=22 or stamp.hour<8))
    def check(self):
        self.refresh_settings();window=self.window
        if self.busy or window.callbacks or not self.permitted():return
        if not self.transport.supported():
            window.status.setText('系统通知能力不可用；未读提醒保留在应用内，没有尝试投递。');return
        self.busy=True;output=self.workspace;store=DeliveryStore(output)
        def read():
            source=notice_events(output)
            return store.reserve(source['events']),source['errors']
        def done(value,error):
            if sip.isdeleted(self):return
            self.busy=False
            if error:window.status.setText('通知记录读取失败：'+error);return
            events,errors=value
            self.refresh_settings()
            if output!=self.workspace or not self.permitted() or not self.transport.supported():
                store.finish(events,'suppressed');return
            if errors:window.status.setText('部分提醒来源不可读取，请检查应用内记录。')
            if not events:return
            try:self.transport.send(*notification_text(events))
            except Exception:
                store.finish(events,'dispatch_failed')
                window.status.setText('通知接口调用失败；记录已保留，不会自动重试，应用内未读不变。');return
            store.finish(events,'handed_to_qt')
            window.status.setText('通知已交给系统接口；不代表横幅已显示或用户已读。')
        window.async_call(read,done,guarded=False)
    def history(self):
        output=Path(self.window.output).resolve()
        dialog=QDialog(self.window);dialog.setWindowTitle('桌面通知投递记录');dialog.resize(900,650)
        box=QVBoxLayout(dialog)
        box.addWidget(label('reserved：已占用投递号；handed_to_qt：已交给接口；dispatch_failed：接口异常；suppressed：显示前关闭或切换。都不证明用户已收到。','note',True))
        box.addWidget(label('投递号先持久化以防重启重复。崩溃后的未确认投递不自动重试；原始提醒仍在应用内，可继续查看。','muted',True))
        details=BusinessDetails({});box.addWidget(details,1);self.window.show_dialog(dialog)
        def done(value,error):
            if not sip.isdeleted(details):details.setPlainText(error or encode(value))
        self.window.async_call(lambda:DeliveryStore(output).history(),done,guarded=False)

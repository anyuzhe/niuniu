"""Desktop-lifetime timer; each pass reconciles durable state, not timer counts."""
from PyQt6 import sip
from PyQt6.QtCore import QObject,QTimer
from quantlab.agent.tracking_scheduler import TrackingScheduler
from quantlab.agent.tracking_control_store import ControlStore


class TrackingController(QObject):
    def __init__(self,window,action):
        super().__init__(window);self.window=window;self.action=action;self.busy=False
        self.timer=QTimer(self);self.timer.setInterval(60000)
        self.timer.timeout.connect(self.check);self.timer.start()
    def check(self):
        window=self.window
        if self.busy or window.closing or window.callbacks or window.data_root is None:return
        self.busy=True;output=window.output;data_root=window.data_root
        def queue():
            if window.closing or window.output!=output or window.data_root!=data_root:
                raise ValueError('工作台正在关闭或已切换目录')
            return window.get_research_queue()
        def run():
            result=TrackingScheduler(output,data_root,queue).tick()
            states=ControlStore(output).list()['controls']
            return result,sum(n['unread'] for s in states for n in s['notices'].values())
        def done(value,error):
            if sip.isdeleted(self):return
            self.busy=False
            if window.output!=output or window.data_root!=data_root:return
            if error:
                self.action.setText('受控自动跟踪：检查异常')
                window.status.setText('跟踪检查未完成：'+error)
            else:
                result,unread=value
                self.action.setText('受控自动跟踪与提醒（'+str(unread)+'条未读）')
                if result['errors']:window.status.setText('存在不可读取的跟踪授权，请打开提醒面板核对。')
        window.async_call(run,done,guarded=False)

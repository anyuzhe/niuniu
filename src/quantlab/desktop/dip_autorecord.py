"""牛牛开着时，每隔一阵检查一次数据有没有新的一天，有就自动记前向信号（逻辑在 quantlab.dipbuy.autorecord）。

只在后台线程里读面板和算信号，只写 <output>/_home 下的纸面台账，不下单。窗口关了就不再检查。
"""
import threading

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from quantlab.dipbuy import autorecord

CHECK_INTERVAL_MS = 30 * 60 * 1000       # 每 30 分钟看一眼（只 stat 文件，数据没变几乎不花时间）
FIRST_DELAY_MS = 20 * 1000               # 启动后 20 秒第一次检查，避免和窗口启动抢资源


class DipAutoRecorder(QObject):
    finished = pyqtSignal(object)        # 一次检查的结果：None（没做）/ {checked_at, data_date, results} / {'error': 文本}

    def __init__(self, window, interval_ms=CHECK_INTERVAL_MS):
        super().__init__(window)
        self.window = window
        self.running = False
        self.last = None
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.check)
        self.finished.connect(self._done)

    def start(self, first_delay_ms=FIRST_DELAY_MS):
        self.timer.start()
        QTimer.singleShot(first_delay_ms, self.check)

    def check(self, force=False):
        """开始一次后台检查；上一次还没完或窗口在关闭就不开始。返回是否真的开始了。"""
        if self.running or getattr(self.window, 'closing', False):
            return False
        self.running = True
        threading.Thread(target=self._work, args=(bool(force),), daemon=True).start()
        return True

    def _work(self, force):
        try:
            result = autorecord.run_if_new(self.window.output, getattr(self.window, 'data_catalog_path', None), force=force)
        except Exception as exc:
            result = {'error': f'{type(exc).__name__}: {exc}'}
        self.finished.emit(result)

    def _done(self, result):
        self.running = False
        self.last = result

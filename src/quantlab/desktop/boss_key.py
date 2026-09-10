"""Hide the native application without closing windows or stopping research."""
import ctypes
import sys

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QApplication, QWidget


def hide_macos_application():
    # Use AppKit's application-wide hide: it preserves modal dialogs, keeps
    # future windows hidden too, and lets the Dock restore the original state.
    # Typed Objective-C calls avoid truncating object pointers on 64-bit Macs.
    objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
    get_application = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(address)
    hide = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(address)
    application = get_application(objc.objc_getClass(b'NSApplication'),
                                  objc.sel_registerName(b'sharedApplication'))
    hide(application, objc.sel_registerName(b'hide:'), None)


class BossKey(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        QApplication.instance().installEventFilter(self)

    @property
    def help_text(self):
        if sys.platform == 'darwin':
            return 'F12 隐藏整个应用，点击 Dock 中的牛牛图标恢复；后台任务继续运行。功能键为系统控制时请按 Fn + F12。'
        return 'F12 最小化研究窗口，从任务栏恢复；后台任务继续运行。'

    def hide(self):
        if sys.platform == 'darwin' and QApplication.platformName() == 'cocoa':
            hide_macos_application()
        else:
            # Keep a taskbar recovery path on other window systems.
            for widget in QApplication.topLevelWidgets():
                if widget.isVisible() and self.owns(widget):
                    widget.showMinimized()

    def owns(self, widget):
        # QWidget.isAncestorOf stops at child window boundaries (QDialog).
        while widget is not None:
            if widget is self.window:
                return True
            widget = widget.parent()
        return False

    def eventFilter(self, watched, event):
        if (event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress)
                and event.key() == Qt.Key.Key_F12
                and event.modifiers() == Qt.KeyboardModifier.NoModifier
                and isinstance(watched, QWidget)
                and self.owns(watched)):
            event.accept()
            if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                self.hide()
            return True
        return super().eventFilter(watched, event)

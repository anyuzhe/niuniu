"""Host-bounded desktop flow for finite archived daily research packages.

The dialog performs no work at construction time.  Capture discovery is bound to the
host output workspace, while package creation/inspection reuse the F9 backend exactly.
Only the host's explicit selection method may change the active research data root.
"""
from __future__ import annotations

from pathlib import Path
import re
import weakref

from PyQt6 import sip
from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from quantlab.agent.archived_data_tools import ArchivedMarketDataAPI
from quantlab.agent.catalog import ReadOnlyResearchAPI
from quantlab.data.archived_daily_dataset import (
    export_archived_daily_dataset,
    inspect_archived_daily_dataset,
    preview_archived_daily_dataset,
)
from quantlab.storage.codec import encode
from .business_view import BusinessDetails
from .widgets import button, label, row


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ArchivedDailyDatasetDialog(QDialog):
    """Review, create, verify, and explicitly activate one finite F9 package."""

    _result_ready = pyqtSignal(int, object, object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.output = Path(window.output)
        self._opening_output = self._path_key(window.output)
        self._opening_root = self._path_key(getattr(window, "data_root", None))
        # Generic source discovery is deliberately bound only to the original host output.
        self.archive_api = ArchivedMarketDataAPI(
            ReadOnlyResearchAPI(window.output), window.output, source_workspace=window.output
        )
        self.busy = False
        self.busy_operation = None
        self.closing = False
        self.closed = False
        self._next_token = 1
        self._pending = {}
        self.preview_hash = None
        self.preview_value = None
        self._preview_request = None
        self._preview_target = None
        self.inspected_dataset_id = None
        self.inspected_path = None
        self.inspected_value = None

        self.setWindowTitle("归档日线研究输入 · 有界生成与核验")
        self.resize(1080, 860)
        box = QVBoxLayout(self)
        box.addWidget(label("归档日线研究输入", "heroTitle"))
        box.addWidget(label(
            "固定边界：仅 raw / 1d / research_only；每包 1–10 只沪深证券，最多 371 个自然日。"
            "回溯供应商观察不是 Strict PIT；本页不下载、不采集、不授权、不建任务、不执行研究或交易。",
            "note", True,
        ))

        form = QFormLayout()
        self.capture_id = QLineEdit()
        self.capture_id.setPlaceholderText("手工填写发现结果中的完整 capture_id")
        self.symbols = QLineEdit()
        self.symbols.setPlaceholderText("1–10 个归档代码，例如 sh.600000 sz.000001")
        self.start = QLineEdit()
        self.start.setPlaceholderText("YYYY-MM-DD")
        self.end = QLineEdit()
        self.end.setPlaceholderText("YYYY-MM-DD")
        self.destination = QLineEdit()
        self.destination.setPlaceholderText("必须是尚不存在的全新目录")
        form.addRow("capture_id", self.capture_id)
        form.addRow("证券", self.symbols)
        form.addRow("开始日期", self.start)
        form.addRow("结束日期", self.end)
        form.addRow("全新包目录", row(self.destination, button("选择路径", self.choose_destination)))
        box.addLayout(form)

        self.confirm = QCheckBox("我已核对完整 capture、证券、日期、预检指纹和全新目标目录，确认生成新包。")
        box.addWidget(self.confirm)
        self.discover_button = button("手动发现 capture（仅读元信息）", self.discover)
        self.preview_button = button("预检范围与源字节", self.preview)
        self.export_button = button("确认后生成全新目录", self.export, True)
        box.addWidget(row(self.discover_button, self.preview_button, self.export_button))

        existing = QFormLayout()
        self.package_path = QLineEdit()
        self.package_path.setPlaceholderText("选择一个已存在的 archived-daily-dataset 包目录")
        existing.addRow("已有包目录", row(self.package_path, button("选择已有目录", self.choose_package)))
        box.addLayout(existing)
        self.inspect_button = button("深验已有包", self.inspect_package)
        self.use_button = button("人工选择为研究输入", self.use_package, True)
        box.addWidget(row(self.inspect_button, self.use_button, button("关闭", self.reject)))

        self.summary = label(
            "初始为空：请先手动发现或填写范围。发现只展示 capture 元信息/errors，不会自动选择证券或日期。",
            "muted", True,
        )
        box.addWidget(self.summary)
        self.details = BusinessDetails({})
        box.addWidget(self.details, 1)
        self.status = label(
            "尚未读取、预检、导出或选择任何数据。生成成功也不会自动切换当前数据根。",
            "muted", True,
        )
        box.addWidget(self.status)

        for control in (self.capture_id, self.symbols, self.start, self.end, self.destination):
            control.textChanged.connect(self.invalidate_preview)
        self.package_path.textChanged.connect(self.invalidate_inspection)
        self.confirm.toggled.connect(self._refresh_actions)
        self._result_ready.connect(self._deliver_result)
        self._refresh_actions()

    @staticmethod
    def _path_key(value):
        if value is None:
            return None
        return str(Path(value).expanduser().absolute())

    def _current_context(self):
        return (
            self._path_key(getattr(self.window, "output", None)),
            self._path_key(getattr(self.window, "data_root", None)),
        )

    def _opening_context_matches(self):
        return self._current_context() == (self._opening_output, self._opening_root)

    def _selection_callback_context_matches(self, selected_path):
        output, root = self._current_context()
        return output == self._opening_output and root in {self._opening_root, self._path_key(selected_path)}

    def _request(self):
        return (
            self.capture_id.text().strip(),
            self.symbols.text().strip(),
            self.start.text().strip(),
            self.end.text().strip(),
        )

    def _all_inputs(self):
        request = self._request()
        destination = self.destination.text().strip()
        if not all(request):
            raise ValueError("请完整填写 capture_id、证券、开始和结束日期。")
        if not destination:
            raise ValueError("请明确填写一个全新的目标目录。")
        return (*request, destination)

    def _refresh_actions(self, *_):
        if not hasattr(self, "export_button"):
            return
        available = not self.busy and not self.closed and not self.closing
        self.discover_button.setEnabled(available)
        self.preview_button.setEnabled(available)
        self.inspect_button.setEnabled(available)
        self.export_button.setEnabled(
            available and self.preview_hash is not None and self.confirm.isChecked()
        )
        self.use_button.setEnabled(
            available and self.inspected_dataset_id is not None and self.inspected_path is not None
        )

    def set_busy(self, busy, operation=None):
        """Set the dialog's own guard before asking the host to schedule work."""
        self.busy = bool(busy)
        self.busy_operation = operation if busy else None
        for control in (
            self.capture_id,
            self.symbols,
            self.start,
            self.end,
            self.destination,
            self.package_path,
            self.confirm,
        ):
            control.setEnabled(not busy and not self.closed and not self.closing)
        self._refresh_actions()

    def invalidate_preview(self, *_):
        self.preview_hash = None
        self.preview_value = None
        self._preview_request = None
        self._preview_target = None
        if self.confirm.isChecked():
            self.confirm.setChecked(False)
        self._refresh_actions()
        if not self.busy and hasattr(self, "status"):
            self.status.setText("范围或目标已变化；旧预检与确认均已失效，请重新预检。")

    def invalidate_inspection(self, *_):
        self.inspected_dataset_id = None
        self.inspected_path = None
        self.inspected_value = None
        self._refresh_actions()
        if not self.busy and hasattr(self, "status"):
            self.status.setText("已有包路径已变化；旧核验不能用于选择，请重新深验。")

    def choose_destination(self):
        if self.busy or self.closed or self.closing:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "选择尚不存在的归档包目录", "", "目录名 (*)"
        )
        if path:
            self.destination.setText(path)

    def choose_package(self):
        if self.busy or self.closed or self.closing:
            return
        path = QFileDialog.getExistingDirectory(self, "选择已有归档日线包目录")
        if path:
            self.package_path.setText(path)

    def _start_async(self, operation, function, success, *, is_current=None, context_check=None):
        if self.busy or self.closed or self.closing:
            return False
        if not self._opening_context_matches():
            self.status.setText("工作台 output 或 data_root 已变化；请关闭旧窗口后从当前上下文重新打开。")
            return False
        token = self._next_token
        self._next_token += 1
        self._pending[token] = {
            "operation": operation,
            "success": success,
            "is_current": is_current,
            "context_check": context_check or self._opening_context_matches,
        }
        self.set_busy(True, operation)
        dialog_ref = weakref.ref(self)

        def callback(result, error):
            dialog = dialog_ref()
            if dialog is None or sip.isdeleted(dialog) or dialog.closed:
                return
            dialog._result_ready.emit(token, result, error)

        try:
            self.window.async_call(function, callback, guarded=False)
        except Exception as error:
            callback(None, type(error).__name__ + ": " + str(error))
        return True

    def _deliver_result(self, token, result, error):
        if sip.isdeleted(self) or self.closed:
            return
        pending = self._pending.pop(token, None)
        if pending is None:
            return
        self.set_busy(False)
        context_ok = False
        try:
            context_ok = bool(pending["context_check"]())
        except Exception:
            context_ok = False
        if not context_ok:
            self.status.setText("工作台上下文已变化；忽略旧回调，不修改当前选择或数据根。")
        elif pending["is_current"] is not None and not pending["is_current"]():
            self.status.setText("输入或路径已变化；忽略旧回调，请按当前内容重新核验。")
        elif error:
            self.status.setText(self._failure_prefix(pending["operation"]) + str(error))
        else:
            try:
                pending["success"](result)
            except Exception as exc:
                # A malformed/non-JSON callback is a visible failure, never an empty success.
                self.status.setText(
                    self._failure_prefix(pending["operation"])
                    + type(exc).__name__ + ": " + str(exc)
                )
        if self.closing:
            QTimer.singleShot(50, self.close)

    @staticmethod
    def _failure_prefix(operation):
        return {
            "discover": "capture 发现失败：",
            "preview": "预检失败，旧成功状态保持失效：",
            "export": "导出实际失败：",
            "inspect": "已有包深验失败：",
            "select": "研究输入未切换：",
        }.get(operation, "操作失败：")

    def discover(self):
        if self.busy or self.closed or self.closing:
            return
        self.summary.setText("正在只读发现 capture 元信息；不会自动填充范围。")

        def loaded(result):
            if not isinstance(result, dict) or result.get("ok") is not True:
                message = ((result or {}).get("error") or {}).get("message", "归档接口返回无效结果")
                raise ValueError(message)
            data = result.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("captures"), list):
                raise ValueError("capture 元信息响应缺少 captures")
            captures = data["captures"]
            errors = data.get("errors") or []
            self.details.setPlainText(encode(result))
            self.summary.setText(
                f"发现 {len(captures)} 个有界候选；其中 {len(errors)} 个含显式错误。"
                "当前仅为 plan_metadata_only，不代表历史完整性，且未自动选择任何范围。"
            )
            self.status.setText("capture 元信息读取完成；请人工填写完整 capture_id、证券和日期。")

        self._start_async(
            "discover",
            lambda: self.archive_api.call("list_archived_daily_sources", {}),
            loaded,
        )

    def preview(self):
        if self.busy or self.closed or self.closing:
            return
        request = self._request()
        target = self.destination.text().strip()
        self.preview_hash = None
        self.preview_value = None
        self._preview_request = None
        self._preview_target = None
        self.confirm.setChecked(False)
        self.details.setPlainText("{}")
        self._refresh_actions()
        if not all(request):
            self.status.setText("预检前请完整填写 capture_id、证券、开始和结束日期。")
            return
        self.summary.setText("正在核验固定 capture 的原始/typed/calendar 语义；预检本身不写入。")

        def loaded(result):
            if not isinstance(result, dict):
                raise ValueError("预检响应必须是对象")
            preview_hash = result.get("preview_hash")
            if not isinstance(preview_hash, str) or not _HEX64.fullmatch(preview_hash):
                raise ValueError("预检没有返回完整 preview_hash")
            encoded = encode(result)
            self.details.setPlainText(encoded)
            self.preview_hash = preview_hash
            self.preview_value = result
            self._preview_request = request
            self._preview_target = target
            self.summary.setText(
                f"预检通过：{len(result.get('symbols', []))} 只证券，"
                f"{result.get('actual_sessions', '未知')} 个交易日，{result.get('rows', '未知')} 行；"
                f"raw / 1d / {result.get('qualification', 'research_only')}。"
            )
            self.status.setText("预检成功；请核对完整指纹和全新目标目录后显式勾选确认。")
            self._refresh_actions()

        self._start_async(
            "preview",
            lambda: preview_archived_daily_dataset(self.output, *request),
            loaded,
            is_current=lambda: self._request() == request
            and self.destination.text().strip() == target,
        )

    def export(self):
        if self.busy or self.closed or self.closing:
            return
        try:
            capture_id, symbols, start, end, destination = self._all_inputs()
            request = (capture_id, symbols, start, end)
            if not self.confirm.isChecked():
                raise ValueError("生成前必须显式勾选确认。")
            if (self.preview_hash is None or self._preview_request != request
                    or self._preview_target != destination):
                raise ValueError("当前完整输入和目标没有有效预检，请重新预检。")
            preview_hash = self.preview_hash
            if not _HEX64.fullmatch(preview_hash):
                raise ValueError("缺少完整 preview_hash，请重新预检。")
        except (ValueError, TypeError) as error:
            self.status.setText("未导出：" + str(error))
            return
        self.status.setText("导出已开始；后端将重新读取源并核对完整 preview_hash。关闭请求会延后到实际完成。")

        def loaded(result):
            if not isinstance(result, dict) or result.get("preview_hash") != preview_hash:
                raise ValueError("导出结果未绑定本次完整 preview_hash")
            self.details.setPlainText(encode(result))
            self.summary.setText(
                "新包已生成并保持未激活：dataset_id=" + str(result.get("dataset_id"))
                + "；请在“已有包目录”中人工选择并深验后再使用。"
            )
            self.status.setText("导出实际完成；没有自动选择数据根、创建授权或研究任务。")

        self._start_async(
            "export",
            lambda: export_archived_daily_dataset(
                self.output,
                capture_id,
                symbols,
                start,
                end,
                destination,
                expected_preview_hash=preview_hash,
                confirmed=True,
            ),
            loaded,
            is_current=lambda: self._request() == request
            and self.destination.text().strip() == destination,
        )

    def inspect_package(self):
        if self.busy or self.closed or self.closing:
            return
        path = self.package_path.text().strip()
        self.inspected_dataset_id = None
        self.inspected_path = None
        self.inspected_value = None
        self.details.setPlainText("{}")
        self._refresh_actions()
        if not path:
            self.status.setText("请先明确选择已有包目录。")
            return
        self.summary.setText("正在深验 manifest、全部源字节、typed 数据和 normalized bars；不会回读原工作空间。")

        def loaded(result):
            if not isinstance(result, dict):
                raise ValueError("深验响应必须是对象")
            dataset_id = result.get("dataset_id")
            actual_path = result.get("path")
            if not isinstance(dataset_id, str) or not _HEX64.fullmatch(dataset_id):
                raise ValueError("深验没有返回完整 dataset_id")
            if self._path_key(actual_path) != self._path_key(path):
                raise ValueError("深验返回路径与人工选择路径不一致")
            encoded = encode(result)
            self.details.setPlainText(encoded)
            self.inspected_dataset_id = dataset_id
            self.inspected_path = str(actual_path)
            self.inspected_value = result
            self.summary.setText(
                f"深验通过：{len(result.get('symbols', []))} 只证券，"
                f"{result.get('start')} 至 {result.get('end')}，raw / 1d / research_only；"
                f"dataset_id={dataset_id}。"
            )
            self.status.setText("已有包当前深验通过；尚未切换数据根。使用时宿主仍须核对同一 dataset_id。")
            self._refresh_actions()

        self._start_async(
            "inspect",
            lambda: inspect_archived_daily_dataset(path),
            loaded,
            is_current=lambda: self.package_path.text().strip() == path,
        )

    def use_package(self):
        if self.busy or self.closed or self.closing:
            return
        current_path = self.package_path.text().strip()
        if (
            self.inspected_dataset_id is None
            or self.inspected_path is None
            or self._path_key(current_path) != self._path_key(self.inspected_path)
        ):
            self.status.setText("当前路径没有可用深验结果，请先重新深验。")
            return
        if not self._opening_context_matches():
            self.status.setText("工作台上下文已变化；旧核验不能用于切换，请重新打开。")
            return
        path = self.inspected_path
        expected_dataset_id = self.inspected_dataset_id
        token = self._next_token
        self._next_token += 1

        def selected(result):
            if not isinstance(result, dict) or result.get("dataset_id") != expected_dataset_id or self._path_key(result.get('path')) != self._path_key(path):
                raise ValueError("宿主没有返回与核验身份一致的选择结果")
            if self._current_context() != (self._opening_output, self._path_key(path)):
                raise ValueError("宿主未实际切换到核验输入，不能显示成功")
            self.details.setPlainText(encode(result))
            self.summary.setText("宿主已完成人工选择并核对 dataset_id=" + expected_dataset_id + "。")
            self.status.setText("研究输入已由宿主显式切换；本页未创建授权、提案或任务。")

        self._pending[token] = {
            "operation": "select",
            "success": selected,
            "is_current": lambda: self._path_key(self.package_path.text().strip()) == self._path_key(path)
            and self.inspected_dataset_id == expected_dataset_id,
            "context_check": lambda: self._selection_callback_context_matches(path),
        }
        # Required ordering: the host sees this dialog busy and may ignore only this keep_dialog.
        self.set_busy(True, "select")
        self.status.setText("正在请求宿主核验同一 dataset_id 并切换研究输入；尚未完成。")
        dialog_ref = weakref.ref(self)

        def on_complete(result, error):
            dialog = dialog_ref()
            if dialog is None or sip.isdeleted(dialog) or dialog.closed:
                return
            dialog._result_ready.emit(token, result, error)

        try:
            self.window.select_archived_daily_dataset(
                path,
                expected_dataset_id,
                on_complete,
                keep_dialog=self,
            )
        except Exception as error:
            on_complete(None, type(error).__name__ + ": " + str(error))

    def _mark_closed(self):
        self.closed = True
        self.set_busy(False)
        self._pending.clear()
        self.preview_hash = None
        self.preview_value = None
        self._preview_request = None
        self._preview_target = None
        self.inspected_dataset_id = None
        self.inspected_path = None
        self.inspected_value = None

    def reject(self):
        if self.busy and self.busy_operation in {"export", "select"}:
            self.closing = True
            if self.busy_operation == "export":
                self.status.setText("导出已经开始，不能虚称取消写入；关闭已延后至实际完成或失败。")
            else:
                self.status.setText("宿主选择已经开始；为避免关闭后改变数据根，关闭已延后至实际完成或失败。")
            return
        self._mark_closed()
        super().reject()

    def closeEvent(self, event):
        if self.busy and self.busy_operation in {"export", "select"}:
            self.closing = True
            if self.busy_operation == "export":
                self.status.setText("导出已经开始，不能虚称取消写入；关闭已延后至实际完成或失败。")
            else:
                self.status.setText("宿主选择已经开始；关闭已延后，完成前不会在窗口关闭后切换数据根。")
            event.ignore()
            return
        self._mark_closed()
        event.accept()


__all__ = ["ArchivedDailyDatasetDialog"]

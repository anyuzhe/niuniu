"""Offscreen desktop tests for the bounded archived-dataset workbench."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from test_retro_daily import FakeSDK, bar
from quantlab.data.retro_daily import RetroDailyStore
from quantlab.desktop.archived_daily_dataset import ArchivedDailyDatasetDialog


HASH_A = "a" * 64
HASH_B = "b" * 64


class FakeHost(QWidget):
    def __init__(self, output, data_root):
        super().__init__()
        self.output = Path(output)
        self.data_root = Path(data_root) if data_root is not None else None
        self.deferred = False
        self.pending = []
        self.async_calls = []
        self.selection_calls = []
        self.selection_error = None
        self.defer_selection = False
        self.pending_selection = []

    def async_call(self, function, callback, guarded=False):
        self.async_calls.append((function, callback, guarded))
        if self.deferred:
            self.pending.append((function, callback))
            return
        self._run(function, callback)

    @staticmethod
    def _run(function, callback):
        try:
            callback(function(), None)
        except Exception as error:
            callback(None, type(error).__name__ + ": " + str(error))

    def finish_next(self, result_marker=None, error=None):
        function, callback = self.pending.pop(0)
        if error is not None:
            callback(None, error)
        elif result_marker is not None:
            callback(result_marker, None)
        else:
            self._run(function, callback)
        QApplication.processEvents()

    def select_archived_daily_dataset(self, path, expected_dataset_id, on_complete, keep_dialog=None):
        self.selection_calls.append({
            "path": path,
            "expected_dataset_id": expected_dataset_id,
            "keep_dialog": keep_dialog,
            "busy_at_start": bool(keep_dialog and keep_dialog.busy),
        })
        if self.selection_error is not None:
            raise self.selection_error
        if self.defer_selection:
            self.pending_selection.append((path, expected_dataset_id, on_complete))
            return
        self.data_root = Path(path)
        on_complete({"path": path, "dataset_id": expected_dataset_id}, None)

    def finish_selection(self, error=None):
        path, expected_dataset_id, callback = self.pending_selection.pop(0)
        if error is None:
            self.data_root = Path(path)
            callback({"path": path, "dataset_id": expected_dataset_id}, None)
        else:
            callback(None, error)
        QApplication.processEvents()


class ArchivedDatasetDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.output = self.root / "output"
        self.data_root = self.root / "current-data"
        self.output.mkdir()
        self.data_root.mkdir()
        self.host = FakeHost(self.output, self.data_root)
        self.dialog = ArchivedDailyDatasetDialog(self.host)
        self.addCleanup(self._cleanup_dialog)

    def _cleanup_dialog(self):
        if not self.dialog.closed and not self.dialog.busy:
            self.dialog.close()
        QApplication.processEvents()

    def fill_request(self, destination=None):
        self.dialog.capture_id.setText("11111111-1111-1111-1111-111111111111")
        self.dialog.symbols.setText("sh.600000 sz.000001")
        self.dialog.start.setText("2026-09-01")
        self.dialog.end.setText("2026-09-10")
        if destination is not None:
            self.dialog.destination.setText(str(destination))

    @staticmethod
    def preview_value(preview_hash=HASH_A):
        return {
            "preview_hash": preview_hash,
            "capture_id": "11111111-1111-1111-1111-111111111111",
            "symbols": ["sh.600000", "sz.000001"],
            "start": "2026-09-01",
            "end": "2026-09-10",
            "rows": 16,
            "actual_sessions": 8,
            "fields": ["symbol", "datetime"],
            "adjustment": "raw",
            "qualification": "research_only",
            "time_policy": {"historical_available_at_verified": False},
            "source_evidence": {"raw_and_typed_bytes_verified": True},
            "limitations": ["synthetic"],
        }

    @staticmethod
    def inspected_value(path, dataset_id=HASH_B):
        value = ArchivedDatasetDesktopTests.preview_value(HASH_A)
        return {"dataset_id": dataset_id, "path": str(Path(path).resolve()), **value}

    def preview_success(self):
        with patch("quantlab.desktop.archived_daily_dataset.preview_archived_daily_dataset",
                   return_value=self.preview_value()):
            self.dialog.preview()
        self.assertEqual(self.dialog.preview_hash, HASH_A)

    def test_initial_state_is_blank_and_performs_no_read_export_or_selection(self):
        self.assertEqual(self.dialog.capture_id.text(), "")
        self.assertEqual(self.dialog.symbols.text(), "")
        self.assertEqual(self.dialog.start.text(), "")
        self.assertEqual(self.dialog.end.text(), "")
        self.assertEqual(self.dialog.destination.text(), "")
        self.assertEqual(self.host.async_calls, [])
        self.assertEqual(self.host.selection_calls, [])
        self.assertFalse(self.dialog.export_button.isEnabled())
        self.assertFalse(self.dialog.use_button.isEnabled())
        visible = self.dialog.findChildren(type(self.dialog.status))
        self.assertIn("raw / 1d / research_only", " ".join(item.text() for item in visible))
        self.assertIn("1–10", " ".join(item.text() for item in visible))
        self.assertIn("371", " ".join(item.text() for item in visible))

    def test_discovery_is_manual_metadata_only_and_does_not_choose_scope(self):
        result = {"ok": True, "data": {
            "captures": [{"capture_id": "cap-good"}, {"capture_id": "cap-bad", "error": "broken"}],
            "errors": [{"capture_id": "cap-bad", "error": "broken"}],
            "verification": "plan_metadata_only", "history_complete": False,
        }, "evidence": [], "warnings": [], "error": None}
        with patch.object(self.dialog.archive_api, "call", return_value=result) as call:
            self.dialog.discover()
        call.assert_called_once_with("list_archived_daily_sources", {})
        self.assertEqual(self.dialog.capture_id.text(), "")
        self.assertEqual(self.dialog.symbols.text(), "")
        self.assertEqual(self.dialog.start.text(), "")
        self.assertIn("2 个有界候选", self.dialog.summary.text())
        self.assertIn("cap-bad", self.dialog.details.toPlainText())
        self.assertFalse(self.dialog.busy)

    def test_v2_toggle_invalidates_preview_and_binds_preview_export_contract(self):
        destination = self.root / "new-package"
        self.fill_request(destination)
        self.preview_success()
        self.dialog.confirm.setChecked(True)
        self.dialog.suspension_v2.setChecked(True)
        self.assertIsNone(self.dialog.preview_hash)
        self.assertFalse(self.dialog.confirm.isChecked())
        value = {**self.preview_value(), "input_contract": "preserve_suspension_state_v2", "suspended_rows": 1,
                 "tradable_rows": 15, "valuation_policy": "synthetic", "research_policy": "synthetic", "execution_policy": "synthetic"}
        with patch("quantlab.desktop.archived_daily_dataset.preview_archived_daily_dataset", return_value=value) as previewing:
            self.dialog.preview()
        self.assertEqual(previewing.call_args.kwargs, {"contract": "preserve_suspension_state_v2"})
        self.dialog.confirm.setChecked(True)
        result = {"dataset_id": HASH_B, "path": str(destination), "preview_hash": HASH_A, "rows": 16,
                  "input_contract": "preserve_suspension_state_v2"}
        with patch("quantlab.desktop.archived_daily_dataset.export_archived_daily_dataset", return_value=result) as exporting:
            self.dialog.export()
        self.assertEqual(exporting.call_args.kwargs,
            {"expected_preview_hash": HASH_A, "confirmed": True, "contract": "preserve_suspension_state_v2"})

    def test_scope_or_destination_change_clears_preview_and_confirmation(self):
        self.fill_request(self.root / "new-package")
        self.preview_success()
        self.dialog.confirm.setChecked(True)
        self.assertTrue(self.dialog.export_button.isEnabled())
        self.dialog.symbols.setText("sh.600000")
        self.assertIsNone(self.dialog.preview_hash)
        self.assertFalse(self.dialog.confirm.isChecked())
        self.preview_success()
        self.dialog.confirm.setChecked(True)
        self.dialog.destination.setText(str(self.root / "another-package"))
        self.assertIsNone(self.dialog.preview_hash)
        self.assertFalse(self.dialog.confirm.isChecked())

    def test_export_without_explicit_confirmation_never_calls_backend(self):
        self.fill_request(self.root / "new-package")
        self.preview_success()
        with patch("quantlab.desktop.archived_daily_dataset.export_archived_daily_dataset") as exporting:
            self.dialog.export()
        exporting.assert_not_called()
        self.assertIn("显式勾选确认", self.dialog.status.text())
        self.assertEqual(self.host.data_root, self.data_root)

    def test_preview_failure_and_malformed_json_clear_old_success(self):
        self.fill_request(self.root / "new-package")
        self.preview_success()
        self.dialog.confirm.setChecked(True)
        with patch("quantlab.desktop.archived_daily_dataset.preview_archived_daily_dataset",
                   side_effect=ValueError("synthetic broken source")):
            self.dialog.preview()
        self.assertIsNone(self.dialog.preview_hash)
        self.assertFalse(self.dialog.confirm.isChecked())
        self.assertIn("旧成功状态保持失效", self.dialog.status.text())
        malformed = {**self.preview_value(), "not_json": {1, 2}}
        with patch("quantlab.desktop.archived_daily_dataset.preview_archived_daily_dataset",
                   return_value=malformed):
            self.dialog.preview()
        self.assertIsNone(self.dialog.preview_hash)
        self.assertIn("预检失败", self.dialog.status.text())

    def test_export_passes_complete_hash_and_target_without_switching_root(self):
        destination = self.root / "new-package"
        self.fill_request(destination)
        self.preview_success()
        self.dialog.confirm.setChecked(True)
        result = {"dataset_id": HASH_B, "path": str(destination), "preview_hash": HASH_A, "rows": 16}
        with patch("quantlab.desktop.archived_daily_dataset.export_archived_daily_dataset",
                   return_value=result) as exporting:
            self.dialog.export()
        args = exporting.call_args.args
        kwargs = exporting.call_args.kwargs
        self.assertEqual(args, (self.output, self.dialog.capture_id.text(), self.dialog.symbols.text(),
                                self.dialog.start.text(), self.dialog.end.text(), str(destination)))
        self.assertEqual(kwargs, {"expected_preview_hash": HASH_A, "confirmed": True})
        self.assertEqual(self.host.data_root, self.data_root)
        self.assertEqual(self.host.selection_calls, [])
        self.assertIn("没有自动选择数据根", self.dialog.status.text())

    def test_existing_package_must_be_inspected_before_host_selection(self):
        package = self.root / "package"
        package.mkdir()
        self.dialog.package_path.setText(str(package))
        self.dialog.use_package()
        self.assertEqual(self.host.selection_calls, [])
        with patch("quantlab.desktop.archived_daily_dataset.inspect_archived_daily_dataset",
                   return_value=self.inspected_value(package)):
            self.dialog.inspect_package()
        self.assertEqual(self.host.data_root, self.data_root)
        self.dialog.use_package()
        self.assertEqual(len(self.host.selection_calls), 1)
        call = self.host.selection_calls[0]
        self.assertEqual(call["path"], str(package.resolve()))
        self.assertEqual(call["expected_dataset_id"], HASH_B)
        self.assertIs(call["keep_dialog"], self.dialog)
        self.assertTrue(call["busy_at_start"])
        self.assertEqual(self.host.data_root, package.resolve())
        self.assertFalse(self.dialog.busy)

    def test_path_change_or_failed_reinspection_invalidates_selection(self):
        first = self.root / "first"
        second = self.root / "second"
        first.mkdir(); second.mkdir()
        self.dialog.package_path.setText(str(first))
        with patch("quantlab.desktop.archived_daily_dataset.inspect_archived_daily_dataset",
                   return_value=self.inspected_value(first)):
            self.dialog.inspect_package()
        self.assertTrue(self.dialog.use_button.isEnabled())
        self.dialog.package_path.setText(str(second))
        self.assertIsNone(self.dialog.inspected_dataset_id)
        self.assertFalse(self.dialog.use_button.isEnabled())
        with patch("quantlab.desktop.archived_daily_dataset.inspect_archived_daily_dataset",
                   side_effect=ValueError("tampered package")):
            self.dialog.inspect_package()
        self.assertFalse(self.dialog.busy)
        self.assertIsNone(self.dialog.inspected_dataset_id)
        self.assertIn("深验失败", self.dialog.status.text())
        self.dialog.use_package()
        self.assertEqual(self.host.selection_calls, [])

    def test_host_selection_start_exception_restores_controls(self):
        package = self.root / "package"
        package.mkdir()
        self.dialog.package_path.setText(str(package))
        with patch("quantlab.desktop.archived_daily_dataset.inspect_archived_daily_dataset",
                   return_value=self.inspected_value(package)):
            self.dialog.inspect_package()
        self.host.selection_error = RuntimeError("host task conflict")
        self.dialog.use_package()
        self.assertFalse(self.dialog.busy)
        self.assertTrue(self.dialog.use_button.isEnabled())
        self.assertIn("host task conflict", self.dialog.status.text())
        self.assertEqual(self.host.data_root, self.data_root)

    def test_reject_invalidates_late_read_callback(self):
        self.fill_request(self.root / "new-package")
        self.host.deferred = True
        with patch("quantlab.desktop.archived_daily_dataset.preview_archived_daily_dataset",
                   return_value=self.preview_value()):
            self.dialog.preview()
            self.assertTrue(self.dialog.busy)
            self.dialog.reject()
            self.assertTrue(self.dialog.closed)
            self.host.finish_next()
            self.assertFalse(self.dialog.busy)
        self.assertIsNone(self.dialog.preview_hash)
        self.assertFalse(self.dialog.confirm.isChecked())

    def test_export_cannot_claim_cancel_and_delays_close_until_actual_result(self):
        destination = self.root / "new-package"
        self.fill_request(destination)
        self.preview_success()
        self.dialog.confirm.setChecked(True)
        self.host.deferred = True
        result = {"dataset_id": HASH_B, "path": str(destination), "preview_hash": HASH_A, "rows": 16}
        with patch("quantlab.desktop.archived_daily_dataset.export_archived_daily_dataset",
                   return_value=result):
            self.dialog.export()
            self.dialog.reject()
            self.assertFalse(self.dialog.closed)
            self.assertTrue(self.dialog.closing)
            self.assertIn("不能虚称取消写入", self.dialog.status.text())
            self.host.finish_next()
        self.assertIn("导出实际完成", self.dialog.status.text())
        QTest.qWait(80)
        QApplication.processEvents()
        self.assertTrue(self.dialog.closed)
        self.assertEqual(self.host.data_root, self.data_root)

    def test_old_context_callback_is_ignored_and_old_inspection_cannot_select(self):
        self.fill_request(self.root / "new-package")
        self.host.deferred = True
        with patch("quantlab.desktop.archived_daily_dataset.preview_archived_daily_dataset",
                   return_value=self.preview_value()):
            self.dialog.preview()
            changed = self.root / "changed-root"
            changed.mkdir()
            self.host.data_root = changed
            self.host.finish_next()
        self.assertIsNone(self.dialog.preview_hash)
        self.assertIn("上下文已变化", self.dialog.status.text())

        package = self.root / "package"
        package.mkdir()
        self.dialog.package_path.setText(str(package))
        self.dialog.inspected_path = str(package)
        self.dialog.inspected_dataset_id = HASH_B
        self.dialog.use_package()
        self.assertEqual(self.host.selection_calls, [])

    def test_real_synthetic_f9_preview_export_and_inspect_flow(self):
        # A separate isolated source is used so this test never touches production data.
        source = self.root / "synthetic-source"
        source.mkdir()
        current = self.root / "synthetic-current"
        current.mkdir()
        days = [date(2026, 9, 7) + timedelta(days=i) for i in range(7)]
        sessions = [day for day in days if day.weekday() < 5]
        calendar = [(day.isoformat(), "1" if day in sessions else "0") for day in days]
        symbols = ["sh.600001", "sz.000002"]
        basic = [(symbol, "synthetic", "2000-01-01", "", "1", "1") for symbol in symbols]
        bars = {
            symbol: [bar(day.isoformat(), symbol, 10 + n * 10 + index,
                         9.8 + n * 10 + index)
                     for index, day in enumerate(sessions)]
            for n, symbol in enumerate(symbols)
        }
        sdk = FakeSDK(basic=basic, calendar=calendar, bars=bars)
        store = RetroDailyStore(
            source,
            today_fn=lambda: date(2026, 9, 22),
            now_fn=lambda: datetime(2026, 9, 22, tzinfo=timezone.utc),
        )
        capture = store.create_plan(days[0].isoformat(), days[-1].isoformat(), sdk=sdk)["capture_id"]
        self.assertEqual(store.fetch(capture, sdk=sdk)["completed"], 2)

        real_host = FakeHost(source, current)
        real_dialog = ArchivedDailyDatasetDialog(real_host)
        self.addCleanup(lambda: real_dialog.close() if not real_dialog.closed and not real_dialog.busy else None)
        destination = self.root / "real-f9-package"
        real_dialog.capture_id.setText(capture)
        real_dialog.symbols.setText(" ".join(symbols))
        real_dialog.start.setText(sessions[0].isoformat())
        real_dialog.end.setText(sessions[-1].isoformat())
        real_dialog.destination.setText(str(destination))
        real_dialog.preview()
        self.assertEqual(len(real_dialog.preview_hash), 64)
        real_dialog.confirm.setChecked(True)
        real_dialog.export()
        self.assertTrue(destination.is_dir())
        self.assertEqual(real_host.data_root, current)
        self.assertEqual(real_host.selection_calls, [])
        real_dialog.package_path.setText(str(destination))
        real_dialog.inspect_package()
        self.assertEqual(len(real_dialog.inspected_dataset_id), 64)
        self.assertEqual(real_dialog.inspected_value["preview_hash"], real_dialog.preview_hash)
        self.assertEqual(real_host.data_root, current)


if __name__ == "__main__":
    unittest.main()

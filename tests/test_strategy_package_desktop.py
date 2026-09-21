"""Offscreen strategy import uses the existing human proposal gate."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication, QWidget
from quantlab.desktop.agent_proposals import ProposalDialog
from quantlab.storage.codec import encode
from test_strategy_package_cli import package_fixture


class _Host(QWidget):
    def __init__(self, root):
        super().__init__(); self.output = root; self.data_root = root
    def async_call(self, function, done, guarded=False):
        try: result, error = function(), ''
        except Exception as exc: result, error = None, str(exc)
        done(result, error)
    def get_research_queue(self):
        raise AssertionError('Import and pending proposal must not create a queue')


class StrategyPackageDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if cls.app.platformName() != 'offscreen':
            raise unittest.SkipTest('offscreen required')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.host = _Host(self.root)
        self.dialog = ProposalDialog(self.host); self.addCleanup(self.close)

    def close(self):
        self.dialog.close(); sip.delete(self.dialog)
        self.host.close(); sip.delete(self.host); QApplication.processEvents()

    def test_import_and_pending_save_never_approve_or_execute(self):
        from quantlab.trading.strategy_package import compile_strategy
        path = self.root / 'package.json'; path.write_text(encode(package_fixture()))
        with patch('quantlab.desktop.agent_proposals.QFileDialog.getOpenFileName', return_value=(str(path), 'JSON')):
            self.dialog.import_strategy_package()
        self.assertEqual(json.loads(self.dialog.draft.toPlainText()), compile_strategy(package_fixture())['spec'])
        self.assertIn('未保存、未批准、未执行', self.dialog.status.text())
        self.assertFalse(self.dialog.approve_button.isEnabled())
        self.assertFalse((self.root / '_jobs').exists())
        self.dialog.create()
        self.assertEqual(self.dialog.selected['status'], 'pending')
        self.assertFalse(self.dialog.confirm.isChecked())
        self.assertFalse(self.dialog.approve_button.isEnabled())
        self.assertFalse(self.dialog.isVisible())
        self.assertFalse((self.root / '_jobs').exists())

    def test_new_import_clears_old_selection_and_invalid_package_preserves_draft(self):
        self.dialog.apply_strategy_package(package_fixture()); self.dialog.create()
        self.assertIsNotNone(self.dialog.selected)
        self.dialog.confirm.setChecked(True)
        self.dialog.apply_strategy_package(package_fixture())
        self.assertIsNone(self.dialog.selected)
        self.assertFalse(self.dialog.confirm.isChecked())
        self.assertFalse(self.dialog.approve_button.isEnabled())
        before = self.dialog.draft.toPlainText()
        invalid = package_fixture(); invalid['lifecycle']['stop_loss'] = 0.1
        with self.assertRaises(ValueError): self.dialog.apply_strategy_package(invalid)
        self.assertEqual(self.dialog.draft.toPlainText(), before)
        self.assertFalse((self.root / '_jobs').exists())


if __name__ == '__main__':
    unittest.main()

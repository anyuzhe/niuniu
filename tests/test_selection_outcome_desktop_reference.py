"""Offscreen review-citation wiring; real temporary records, no model or production data."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import unittest
from unittest.mock import patch
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication, QWidget
import test_selection_outcomes as fixtures
from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.desktop.research_chat import ResearchChatDialog

class _Host(QWidget):
    def __init__(self, output):
        super().__init__()
        self.output, self.data_root = output, None
    def async_call(self, function, callback, guarded=False):
        try:
            value, error = function(), ''
        except Exception as exc:
            value, error = None, f'{type(exc).__name__}: {exc}'
        callback(value, error)

class SelectionOutcomeDesktopReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if cls.app.platformName() != 'offscreen':
            raise unittest.SkipTest('Requires the explicit offscreen Qt platform')
    def setUp(self):
        self.fixture = fixtures.SelectionOutcomeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.capture_days(range(1, 6))
        self.fixture.capture_reference(5)
        self.selection = self.fixture.selection()
        self.fixture.service().build(self.selection['selection_id'], [1])
        self.host = _Host(self.fixture.output)
        with patch('quantlab.desktop.research_chat.ChatRuntime',
                   side_effect=lambda output, data_root, queue_factory, **kwargs: ChatRuntime(
                       output, data_root, queue_factory, local_data_only=True, **kwargs)):
            self.dialog = ResearchChatDialog(self.host)
        self.addCleanup(self._close)
        ref = {'kind': 'playbook_selection', 'selection_id': self.selection['selection_id']}
        self.dialog.receive('tool_result', {'name': 'get_selection_outcome_review',
            'result': {'ok': True, 'evidence': [ref]}})
        self.dialog.evidence.setCurrentRow(0)
        self.path = (self.fixture.output / '_trading' / 'selection_outcomes'
                     / self.selection['selection_id'] / 'D1.json')
    def _close(self):
        self.dialog.close()
        sip.delete(self.dialog)
        self.host.close()
        sip.delete(self.host)
        QApplication.processEvents()
    def test_selection_citation_shows_identity_and_opens_without_rewriting(self):
        self.assertIn(self.selection['selection_id'], self.dialog.evidence.item(0).text())
        before = self.path.read_bytes()
        self.dialog.open_reference()
        self.assertFalse(self.dialog.busy)
        self.assertIn('已在右侧', self.dialog.status.text())
        self.assertIn(self.selection['selection_id'], self.dialog.details.toPlainText())
        self.assertIn('D1', self.dialog.details.toPlainText())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.dialog.isVisible())
    def test_corrupt_review_reports_failure_in_reference_view(self):
        self.path.write_text('broken synthetic receipt', encoding='utf-8')
        self.dialog.open_reference()
        self.assertFalse(self.dialog.busy)
        self.assertIn('复盘引用不完整', self.dialog.status.text())
        self.assertIn('CORRUPT_REVIEW', self.dialog.details.toPlainText())
        self.assertNotIn('已在右侧', self.dialog.status.text())
        self.assertFalse(self.dialog.isVisible())

if __name__ == '__main__':
    unittest.main()

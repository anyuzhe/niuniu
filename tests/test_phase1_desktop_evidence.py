import json
import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt

from quantlab.desktop.factor_evidence import FactorEvidenceDialog
from quantlab.desktop.market_pages import candidates_page
from quantlab.trading.market_overview import save_overview


class _Window(QWidget):
    closing = False
    data_root = None
    data_catalog_path = None
    root_current = 0
    epoch = 1

    def __init__(self, output):
        super().__init__(); self.output = Path(output); self.calls = []; self.dialogs = []
        self.status = type('S', (), {'setText': lambda _s, text: setattr(self, 'status_text', text)})()
        self.container = QWidget(); self.layout = QVBoxLayout(self.container)

    def page(self, title, subtitle):
        self.epoch += 1
        self.container = QWidget(); self.layout = QVBoxLayout(self.container)
        return self.layout

    def async_call(self, work, done, guarded=False):
        self.calls.append((work, done, guarded))

    def research_chat(self, **kwargs):
        self.last_research_chat = kwargs

    def ask_ai(self, prompt):
        self.last_ask_ai = prompt

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def open_run(self, run_id):
        self.opened_run = run_id

    def open_stock_report(self, code):
        self.opened_stock = code


class Phase1DesktopEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.output = self.root / 'artifacts'; self.output.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def _record(self, rid=None):
        rid = rid or str(uuid4()); d = self.output / rid; d.mkdir()
        record = {'run_id': rid, 'experiment_id': 'e', 'kind': 'factor', 'status': 'completed', 'created_at': '2026-09-27T00:00:00Z',
                  'manifest': {'config': {'factor_id': 'BASE.TEST', 'factor_version': '1', 'parameters': {},
                                           'data': {'start': '2026-01-01', 'end': '2026-01-02', 'timeframe': '1d', 'symbols': ['s']}}},
                  'limitations': ['fixture']}
        (d / 'experiment.json').write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        return rid

    def test_factor_evidence_async_failure_clears_old_rows_and_stale_ignored(self):
        self._record(); window = _Window(self.output); dialog = FactorEvidenceDialog(window)
        dialog.factor.setText('BASE.TEST'); dialog.reload(reset=True)
        work, done, _ = window.calls.pop()
        result = work(); done(result, '')
        self.assertEqual(len(dialog.rows), 1)
        dialog.params.setPlainText('[]'); dialog.reload(reset=True)
        self.assertEqual(dialog.rows, [])
        self.assertIn('查询失败', dialog.status.text())
        dialog.params.setPlainText(''); dialog.reload(reset=True)
        old_work, old_done, _ = window.calls.pop()
        dialog.reload(reset=True)
        new_work, new_done, _ = window.calls.pop()
        old_done(old_work(), '')
        self.assertEqual(dialog.rows, [])
        new_done(new_work(), '')
        self.assertEqual(len(dialog.rows), 1)

    def test_candidates_formal_research_button_uses_research_profile_draft(self):
        overview = {'format': 'niuniu-market-overview-v1', 'trading_day': '2026-09-27', 'built_at': '2026-09-27T10:00:00+00:00',
                    'summary': ['摘要'], 'market': {}, 'percentile': {}, 'margin': None, 'caveats': [], 'ladder': [], 'industries': [], 'reasons': [], 'sources': {},
                    'candidates': [{'key': 'k', 'name': '候选', 'description': '规则', 'count': 1,
                                    'validation': {'verdict': 'insufficient', 'text': '旧text', 'samples': 1},
                                    'stocks': [{'code': 'sh.600001', 'name': '甲', 'industry': '测试', 'pct': 0.01, 'ret20': 0.02, 'reason': '入选'}]}]}
        save_overview(self.output, overview)
        window = _Window(self.output); candidates_page(window)
        buttons = [b for b in window.container.findChildren(QPushButton) if b.text() == '进入正式研究']
        self.assertEqual(len(buttons), 1)
        QTest.mouseClick(buttons[0], Qt.MouseButton.LeftButton)
        self.assertEqual(window.last_research_chat['profile'], 'research')
        self.assertIn('只生成草稿', window.last_research_chat['draft'])
        self.assertNotIn('submit', window.last_research_chat['draft'].lower())


if __name__ == '__main__':
    unittest.main()

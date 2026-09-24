"""数据中心 sections over DATA's services (status, preview, jobs), on DATA's test lake."""
import os
import unittest
from pathlib import Path

from test_data_services import Lake

from quantlab.data import day_seals


def catalog(root, ready=True):
    status = 'READY' if ready else 'REVIEW_REQUIRED'
    path = Path(root) / f'catalog-{status}.md'
    rows = ''.join(f'| `{d}` | API | x | `DataServices` | x | x | `{status}` | x |\n'
                   for d in ('data_status_service', 'data_preview_service', 'data_update_jobs'))
    path.write_text('# DATA → CODE 数据清单\n\n## 3. 可供 CODE 使用的数据（READY）\n\n'
                    '| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |\n'
                    '|---|---|---|---|---|---|---|---|\n'
                    '| `limit_up_pool_ths` | FILE | 涨停池 | `/lake` | x | 2026-09-01 至 09-24 | `READY` | 读 |\n' + rows,
                    encoding='utf-8')
    return path


class FakeJobs:
    """Stands in for DataUpdateJobs so the page test never starts a background process."""

    def __init__(self):
        self.runs = []
        self.planned = []

    def list_jobs(self):
        return {'jobs': [{'job_id': 'seal_day', 'name': '封存某一天', 'description': '封存', 'estimated_seconds': 120,
                          'needs_data_disk': True, 'uses_network': False, 'writes': [],
                          'params': [{'name': 'date', 'type': 'date', 'required': True, 'description': '日期'}]}]}

    def plan(self, job_id, params):
        self.planned.append((job_id, params))
        blocked = None if params.get('date') == '2026-09-24' else '这一天已封存，采集只读'
        return {'plan_id': 'p1', 'job_id': job_id, 'params': params, 'expires_at': '2026-09-25T01:00:00+08:00',
                'estimated_seconds': 120, 'warnings': ['公告目录待封存'], 'blocked_reason': blocked,
                'steps': [{'name': '封存', 'action': 'seal', 'datasets': ['*'], 'dates': [params.get('date')],
                           'overwrites': False, 'note': None}]}

    def run(self, plan_id):
        self.runs.append({'run_id': 'r1', 'job_id': 'seal_day', 'state': 'running', 'progress': 0.5, 'step': '封存',
                          'trigger': 'user', 'created_at': '2026-09-25T00:30:00+08:00',
                          'started_at': '2026-09-25T00:30:00+08:00', 'finished_at': None,
                          'params': {'date': '2026-09-24'}, 'result': {'datasets': [], 'seal': None}, 'error': None})
        return {'run_id': 'r1'}

    def list_runs(self, limit=20):
        return {'runs': list(self.runs)}

    def log(self, run_id, offset=0):
        lines = ['开始封存', '写入清单'][offset:]
        return {'lines': lines, 'next_offset': offset + len(lines)}

    def cancel(self, run_id):
        self.runs[0]['state'] = 'cancelled'
        return {'state': 'cancelled'}


@unittest.skipUnless(__import__('importlib').util.find_spec('PyQt6'), 'Install desktop dependency')
class DataCenterServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.lake = Lake()
        self.root = self.lake.root

    def tearDown(self):
        self.lake.tmp.cleanup()

    def wait(self, window):
        from PyQt6.QtTest import QTest
        for _ in range(150):
            QTest.qWait(20)
            if not window.callbacks:
                break

    def window(self, ready=True):
        from quantlab.desktop.app import MainWindow
        window = MainWindow(self.root / 'out', self.root)
        window.data_catalog_path = catalog(self.root, ready)
        window.show()
        return window

    def section(self, window, key):
        from quantlab.desktop.data_center_page import open_section
        open_section(window, key)
        self.wait(window)
        from PyQt6.QtWidgets import QTableWidget
        return window.scroll.widget().findChildren(QTableWidget)

    def test_tabs_disabled_until_ready(self):
        from PyQt6.QtWidgets import QPushButton
        window = self.window(ready=False)
        window.navigate_page('data')
        self.wait(window)
        tabs = {b.text(): b.isEnabled() for b in window.scroll.widget().findChildren(QPushButton)}
        self.assertTrue(tabs['数据目录'])
        self.assertFalse(tabs['更新状态'])
        self.assertFalse(tabs['更新与封存'])
        window.close()

    def test_status_shows_datasets_and_seals(self):
        day_seals.seal(self.root, '2026-09-24', log=lambda *_: None)
        window = self.window()
        grids = self.section(window, 'status')
        datasets, seals = grids[0], grids[1]
        self.assertGreater(datasets.rowCount(), 10)
        self.assertEqual(seals.rowCount(), 1)
        self.assertEqual(seals.item(0, 0).text(), '2026-09-24')
        self.assertEqual(seals.item(0, 6).text(), '未核对')
        window.close()

    def test_preview_reads_a_partition(self):
        from PyQt6.QtWidgets import QComboBox, QPushButton
        window = self.window()
        grids = self.section(window, 'preview')
        chooser = window.scroll.widget().findChildren(QComboBox)[0]
        index = next(i for i in range(chooser.count()) if chooser.itemData(i) == ('file', 'limit_up_pool_ths'))
        chooser.setCurrentIndex(index)
        next(b for b in window.scroll.widget().findChildren(QPushButton) if b.text() == '预览').click()
        self.wait(window)
        self.assertEqual(grids[0].rowCount(), 3)
        self.assertEqual(grids[0].horizontalHeaderItem(0).text(), 'code')
        window.close()

    def test_jobs_plan_confirm_run_log_cancel(self):
        from PyQt6.QtWidgets import QLineEdit, QPlainTextEdit, QPushButton
        window = self.window()
        fake = FakeJobs()
        window._data_services = {('DataUpdateJobs', str(window.data_root)): fake}
        grids = self.section(window, 'jobs')
        plan_grid, runs_grid = grids[0], grids[1]
        buttons = {b.text(): b for b in window.scroll.widget().findChildren(QPushButton)}
        date = window.scroll.widget().findChildren(QLineEdit)[0]
        date.setText('2026-09-23')
        buttons['生成计划'].click()
        self.wait(window)
        self.assertFalse(buttons['确认执行'].isEnabled())  # blocked plans cannot run
        date.setText('2026-09-24')
        buttons['生成计划'].click()
        self.wait(window)
        self.assertEqual(fake.planned[-1], ('seal_day', {'date': '2026-09-24'}))
        self.assertEqual(plan_grid.item(0, 1).text(), '封存')
        self.assertTrue(buttons['确认执行'].isEnabled())
        buttons['确认执行'].click()
        self.wait(window)
        self.assertEqual(runs_grid.rowCount(), 1)
        self.assertEqual(runs_grid.item(0, 3).text(), '运行中')
        self.wait(window)
        log = window.scroll.widget().findChild(QPlainTextEdit)
        self.assertIn('写入清单', log.toPlainText())
        self.assertTrue(buttons['取消这次运行'].isEnabled())
        buttons['取消这次运行'].click()
        self.wait(window)
        self.assertEqual(fake.runs[0]['state'], 'cancelled')
        window.close()


if __name__ == '__main__':
    unittest.main()

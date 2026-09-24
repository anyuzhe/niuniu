"""数据中心: catalog view helpers and the page, over a small catalog in DATA's format."""
import os
import tempfile
import unittest
from pathlib import Path

from quantlab.workbench.data_center import catalog_rows, coverage_end, end_text, filter_rows, service_status

CATALOG = '''# DATA → CODE 数据清单

最近一次 DATA 审查：2026-09-24（开放实时行情）。其余说明。

## 3. 可供 CODE 使用的数据（READY）

| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |
|---|---|---|---|---|---|---|---|
| `bars_daily` | FILE | 日K | `/lake/daily` | 每只一个文件 | 5,222 只，1990-12-19 至 **2026-09-23**，约 1,714 万行 | `READY` | 直接读取 |
| `margin` | FILE | 两融 | `/lake/margin` | 按日 | 2026-09-01 至 09-22，16 个交易日 | `READY` | 直接读取 |
| `holders` | FILE | 股东户数 | `/lake/holders` | 按日 | 2026-09-23 观察，5,564 只 | `READY` | 直接读取 |
| `news` | API | 资讯 | `Provider.news` | 行 | 东财资讯 | `READY` | 调用 |
| `flow` | API | 资金流 | `Provider.flow` | 行 | 最近 120 个交易日 | `REVIEW_REQUIRED` | 暂不使用 |

## 4. 尚不可用、待审查或只供 DATA 内部使用

| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |
|---|---|---|---|---|---|---|---|
| `old_qfq` | FILE | 旧前复权 | `/lake/old` | x | 截止 **2026-09-04** | `DEPRECATED` | 不用 |
| `ticks` | STREAM | 逐笔 | 无 | — | 未规划 | `NOT_READY` | 无 |
'''


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'catalog.md'
        self.path.write_text(CATALOG, encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def test_coverage_dates(self):
        self.assertEqual(coverage_end('1990-12-19 至 **2026-09-23**，约 1,714 万行'), ('2026-09-23', 'until'))
        self.assertEqual(coverage_end('2026-09-01 至 09-22，16 个交易日'), ('2026-09-22', 'until'))
        self.assertEqual(coverage_end('2026-09-23 观察，5,564 只'), ('2026-09-23', 'observed'))
        self.assertEqual(coverage_end('观察日 2026-09-23；在市 A 股'), ('2026-09-23', 'observed'))
        self.assertEqual(coverage_end('截止 **2026-09-04**（落后）'), ('2026-09-04', 'until'))
        self.assertEqual(coverage_end('2026-09-23，262 个分钟点'), ('2026-09-23', 'observed'))
        self.assertEqual(coverage_end('东财资讯'), (None, ''))

    def test_rows_filters_and_services(self):
        data = catalog_rows(self.path)
        self.assertEqual(data['review'], '2026-09-24')
        self.assertEqual(data['counts']['READY'], 4)
        rows = {r['dataset_id']: r for r in data['rows']}
        self.assertEqual(end_text(rows['margin']), '至 2026-09-22')
        self.assertEqual(rows['bars_daily']['address'], '/lake/daily')  # markdown marks removed
        self.assertEqual([r['dataset_id'] for r in filter_rows(data['rows'], status='READY', delivery='API')], ['news'])
        self.assertEqual([r['dataset_id'] for r in filter_rows(data['rows'], text='两融')], ['margin'])
        ordered = [r['status'] for r in filter_rows(data['rows'])]
        self.assertEqual(ordered[0], 'READY')
        self.assertEqual(ordered[-1], 'DEPRECATED')
        self.assertEqual(set(service_status(self.path).values()), {'NOT_LISTED'})


@unittest.skipUnless(__import__('importlib').util.find_spec('PyQt6'), 'Install desktop dependency')
class PageTests(HelperTests):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_page_lists_filters_and_shows_detail(self):
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QLabel, QLineEdit, QTableWidget
        from quantlab.desktop.app import MainWindow
        window = MainWindow(Path(self.temp.name) / 'out')
        window.data_catalog_path = self.path
        window.show()
        window.navigate_page('data')
        QTest.qWait(20)
        grid = window.scroll.widget().findChildren(QTableWidget)[0]
        self.assertEqual(grid.rowCount(), 7)
        self.assertEqual(grid.item(0, 4).text(), '可用')
        window.scroll.widget().findChild(QLineEdit).setText('两融')
        self.assertEqual(grid.rowCount(), 1)
        grid.cellClicked.emit(0, 0)
        texts = [w.text() for w in window.scroll.widget().findChildren(QLabel)]
        self.assertTrue(any('位置 / 接口：/lake/margin' in t for t in texts))
        self.assertTrue(any('数据侧尚未提供接口' in t for t in texts))
        window.close()


if __name__ == '__main__':
    unittest.main()

"""盘中板块: catalog gate, summaries, the assistant tool and the page, over DATA's provider with a fake vendor."""
import os
import tempfile
import unittest
from pathlib import Path

from test_sector_intraday import FakeClient, provider

from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.trading import intraday_sectors as sectors


def catalog(root, status):
    path = Path(root) / f'catalog-{status}.md'
    rows = ''.join(f'| `{d}` | API | x | `SectorIntradayProvider` | x | x | `{status}` | x |\n'
                   for d in ('sector_board_snapshot', 'sector_board_members'))
    path.write_text('# DATA → CODE 数据清单\n\n## 3. 可供 CODE 使用的数据（READY）\n\n'
                    '| 数据 ID | 交付方式 | 数据内容 | 地址 / 路径 | 格式 / 粒度 | 覆盖 / 用途 | DATA 状态 | CODE 使用 |\n'
                    '|---|---|---|---|---|---|---|---|\n' + rows, encoding='utf-8')
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ready, self.review = catalog(self.root, 'READY'), catalog(self.root, 'REVIEW_REQUIRED')
        self.provider = provider()
        sectors.reset_shared_provider()
        sectors.shared_provider(factory=lambda: self.provider)
        self.addCleanup(sectors.reset_shared_provider)

    def tearDown(self):
        self.temp.cleanup()


class SummaryTests(Base):
    def test_gate_and_texts(self):
        self.assertTrue(sectors.is_ready(self.ready))
        self.assertFalse(sectors.is_ready(self.review))
        self.assertIn('REVIEW_REQUIRED', sectors.not_ready_text(self.review))
        self.assertIn('扶摇密钥', sectors.error_text(RuntimeError('fuyao x failed: FUYAO_NOT_CONFIGURED')))

    def test_ranking_members_and_prompt(self):
        snapshot = self.provider.board_snapshot(('concept', 'industry'))
        self.assertEqual([b['name'] for b in sectors.pick_boards(snapshot)], ['新能源汽车', '银行', '储能'])
        self.assertEqual([b['name'] for b in sectors.pick_boards(snapshot, 'concept', 'down')], ['储能', '新能源汽车'])
        self.assertIn('交易中', sectors.freshness(snapshot))
        members = self.provider.board_members('885431.TI')
        states = {r['symbol']: sectors.member_state(r) for r in members['members']}
        self.assertEqual((states['sh.600000'], states['sz.300750'], states['sz.000016'], states['sh.600001']),
                         ('涨停', '炸板', '停牌/未成交', '来源不一致'))
        summary = sectors.members_summary(members)
        self.assertEqual((summary['quoted'], summary['rising']), (2, 2))
        prompt = sectors.sector_prompt(snapshot, snapshot['boards'][0], members)
        self.assertIn('新能源汽车', prompt)
        self.assertIn('涨停 1', prompt)


class ToolTests(Base):
    def test_tool_only_after_ready(self):
        blocked = ChatRuntime(self.root, self.root, data_catalog_path=self.review, tool_profile='everyday')
        self.assertNotIn('get_intraday_sectors', {t['name'] for t in blocked.api.schemas()})
        self.assertEqual(blocked.api.call('get_intraday_sectors', {'board': ''})['error']['code'], 'NOT_READY')
        runtime = ChatRuntime(self.root, self.root, data_catalog_path=self.ready, tool_profile='everyday')
        self.assertIn('get_intraday_sectors', {t['name'] for t in runtime.api.schemas()})
        ranking = runtime.api.call('get_intraday_sectors', {'board': ''})
        self.assertTrue(ranking['ok'], ranking)
        self.assertEqual(ranking['data']['boards']['strongest'][0]['name'], '新能源汽车')
        board = runtime.api.call('get_intraday_sectors', {'board': '新能源'})
        self.assertEqual(board['data']['selected']['counts']['limit_up'], 1)
        missing = runtime.api.call('get_intraday_sectors', {'board': '不存在'})
        self.assertEqual(missing['error']['code'], 'NOT_FOUND')


@unittest.skipUnless(__import__('importlib').util.find_spec('PyQt6'), 'Install desktop dependency')
class PageTests(Base):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, window):
        from PyQt6.QtTest import QTest
        for _ in range(100):
            QTest.qWait(20)
            if not window.callbacks:
                break

    def window(self, catalog_path):
        from quantlab.desktop.app import MainWindow
        window = MainWindow(self.root / 'out')
        window.data_catalog_path = catalog_path
        window.sector_provider = self.provider
        window.show()
        return window

    def test_not_ready_shows_why(self):
        from PyQt6.QtWidgets import QLabel
        window = self.window(self.review)
        window.navigate_page('sectors')
        self.wait(window)
        texts = [w.text() for w in window.scroll.widget().findChildren(QLabel)]
        self.assertTrue(any('尚未开放盘中板块接口' in t for t in texts))
        self.assertFalse(hasattr(window, 'sector_page_state') and window.sector_page_state.get('snapshot'))
        window.close()

    def test_ranking_select_and_refresh(self):
        from PyQt6.QtWidgets import QTableWidget
        window = self.window(self.ready)
        window.navigate_page('sectors')
        self.wait(window)
        boards, members = window.scroll.widget().findChildren(QTableWidget)[:2]
        self.assertEqual(boards.rowCount(), 3)
        self.assertEqual(boards.item(0, 0).text(), '新能源汽车')
        self.assertEqual(boards.item(0, 2).text(), '+1.50%')
        boards.cellClicked.emit(0, 0)
        self.wait(window)
        self.assertEqual(members.rowCount(), 4)
        states = {members.item(i, 1).text(): members.item(i, 5).text() for i in range(4)}
        self.assertEqual(states['sh.600000'], '涨停')
        self.assertEqual(window.sector_page_state['board']['code'], '885431.TI')
        window.close()

    def test_provider_failure_stays_on_the_page(self):
        from PyQt6.QtWidgets import QLabel
        from test_sector_intraday import provider as make
        self.provider = make(FakeClient(fail=10))
        window = self.window(self.ready)
        window.navigate_page('sectors')
        self.wait(window)
        texts = [w.text() for w in window.scroll.widget().findChildren(QLabel)]
        self.assertTrue(any('暂时取不到' in t for t in texts))
        self.assertNotIn('失败', window.status.text())
        window.close()


if __name__ == '__main__':
    unittest.main()

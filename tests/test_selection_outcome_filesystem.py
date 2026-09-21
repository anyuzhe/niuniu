"""Selection outcome publication also works on filesystems without hard links."""
import errno
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
import test_selection_outcomes as fixtures

class SelectionOutcomeFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SelectionOutcomeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.capture_days(range(1, 6))
        self.fixture.capture_reference(5)
        self.selection = self.fixture.selection()

    def test_unsupported_hard_links_do_not_block_atomic_publication_or_idempotency(self):
        sid = self.selection['selection_id']
        with patch('os.link', side_effect=OSError(errno.EOPNOTSUPP, 'fixture: hard links unsupported')):
            first = self.fixture.service().build(sid, [1])
            path = self.fixture.output / '_trading' / 'selection_outcomes' / sid / 'D1.json'
            before = path.read_bytes()
            again = self.fixture.service().build(sid, [1])
        self.assertEqual(first['created'], 1)
        self.assertEqual(again['created'], 0)
        self.assertEqual(before, path.read_bytes())

    def test_concurrent_identical_publication_without_hard_links_creates_once(self):
        barrier = Barrier(2)
        sid = self.selection['selection_id']
        def build():
            service = self.fixture.service()
            barrier.wait(timeout=10)
            return service.build(sid, [1])
        with patch('os.link', side_effect=OSError(errno.EOPNOTSUPP, 'fixture: hard links unsupported')):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: build(), range(2)))
        self.assertEqual(sorted(row['created'] for row in results), [0, 1])
        self.assertEqual(results[0]['records'][0]['review_hash'], results[1]['records'][0]['review_hash'])

if __name__ == '__main__':
    unittest.main()

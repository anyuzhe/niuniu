import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QApplication
from quantlab.desktop.comparison_editor import ComparisonEditor


class TemporalEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def editor(self):
        item={'run_id':str(uuid4()),'status':'completed','question':'fixture','start':'2025-01-01','end':'2025-01-12'}
        window=SimpleNamespace(output=Path('/fixture'),catalog=SimpleNamespace(list=lambda **kw:{'runs':[item]}))
        editor=ComparisonEditor(window,'stability',lambda plan:None)
        self.addCleanup(editor.close)
        editor.comparison_kind.setCurrentIndex(editor.comparison_kind.findData('temporal_subsample_equivalence'))
        for field in (editor.candidate_symbols,editor.baseline_symbols):field.setText('A B C')
        editor.start.setDate(QDate(2025,1,1));editor.end.setDate(QDate(2025,1,5))
        editor.baseline_start.setDate(QDate(2025,1,8));editor.baseline_end.setDate(QDate(2025,1,12))
        return editor

    def test_temporal_fields_same_cohort_and_plan_roundtrip(self):
        editor=self.editor();self.assertTrue(editor.baseline_start.isEnabled())
        editor.add();self.assertEqual(len(editor.entries),1)
        plan=editor.plan();item=plan['comparisons'][0]
        self.assertEqual(plan['comparison_kind'],'temporal_subsample_equivalence')
        self.assertNotIn('start',item)
        self.assertEqual(item['candidate_start'],'2025-01-01')
        self.assertEqual(item['candidate_end'],'2025-01-05')
        self.assertEqual(item['baseline_start'],'2025-01-08')
        self.assertEqual(item['baseline_end'],'2025-01-12')
        self.assertEqual(item['candidate_symbols'],item['baseline_symbols'])
        self.assertFalse(editor.comparison_kind.isEnabled())
        editor.table.setCurrentCell(0,0);editor.remove()
        self.assertTrue(editor.comparison_kind.isEnabled())

    def test_overlapping_period_and_repeated_comparison_rejected(self):
        editor=self.editor();editor.baseline_start.setDate(QDate(2025,1,5));editor.add()
        self.assertEqual(editor.entries,[])
        self.assertIn('不重叠',editor.status.text())
        editor.baseline_start.setDate(QDate(2025,1,8));editor.add();editor.add()
        self.assertEqual(len(editor.entries),1)
        editor.candidate_symbols.setText('A A C');editor.add()
        self.assertEqual(len(editor.entries),1)

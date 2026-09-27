import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from unittest.mock import patch
from uuid import uuid4
import test_research_pickers as helpers
from quantlab.desktop.research_picker import FactorPickerDialog,ArchivePickerDialog
from quantlab.trading import research_evidence


class PickerReviewTests(unittest.TestCase):
    def setUp(self):self.window=helpers.Window();self.dialogs=[]
    def tearDown(self):
        for d in self.dialogs:d.close()
        self.window.close()
    def archive(self):
        d=ArchivePickerDialog(self.window);self.dialogs.append(d);return d
    def page(self,ref,inventory='a',next_offset=None,errors=None):
        return {'matches':[ref],'errors':errors or [],'next_offset':next_offset,'has_more':next_offset is not None,
                'scanned':1,'offset':0,'incomplete':next_offset is not None,'inventory_digest':inventory}
    def load(self,d,ref,**kwargs):
        with patch.object(research_evidence,'find_research_archives',return_value=self.page(ref,**kwargs)):
            d.search(reset=True);self.window.complete()
    def test_actual_pack_name_is_searchable_without_altering_definition_contract(self):
        d=FactorPickerDialog(self.window);self.dialogs.append(d);d.search.setText('BaseQuantPack')
        self.assertGreater(d.versions.count(),0)
        d.versions.setCurrentRow(0);d.use_selected()
        self.assertEqual(set(d.result_definition),{'definition','defaults','code_hash'})
        definition=d.result_definition['definition'];self.assertEqual(d.pack_names[(definition['factor_id'],definition['version'])],'BaseQuantPack')
    def test_query_change_invalidates_pending_search_and_never_auto_fetches(self):
        d=self.archive();ref=helpers.reference(str(uuid4()))
        d.search_button.click();self.assertEqual(len(self.window.pending),1)
        d.query.setText('changed');self.assertEqual(len(self.window.pending),1)
        with patch.object(research_evidence,'find_research_archives',return_value=self.page(ref)):
            self.window.complete()
        self.assertEqual(d.rows,[]);self.assertIsNone(d.results);self.assertFalse(d.use_button.isEnabled())
    def test_query_change_invalidates_pending_verification(self):
        d=self.archive();ref=helpers.reference(str(uuid4()));self.load(d,ref)
        d.results.selectRow(0);d.use_button.click();self.assertEqual(len(self.window.pending),1)
        d.query.setText('different');self.assertIsNone(d.selected_reference)
        with patch.object(research_evidence,'archive_research_reference',return_value=ref):self.window.complete()
        self.assertIsNone(d.result_reference);self.assertNotEqual(d.result(),d.DialogCode.Accepted)
    def test_cross_page_inventory_change_rejects_new_page(self):
        d=self.archive();ref=helpers.reference(str(uuid4()));self.load(d,ref,next_offset=20)
        d.next_button.click();self.assertEqual(len(self.window.pending),1);self.assertFalse(d.next_button.isEnabled())
        with patch.object(research_evidence,'find_research_archives',return_value=self.page(ref,inventory='b')):self.window.complete()
        self.assertEqual(d.rows,[]);self.assertIsNone(d.next_offset);self.assertIn('目录已变化',d.status.text())
        self.load(d,ref,inventory='b');self.assertEqual(len(d.rows),1)
    def test_bad_entries_visible_and_failed_archive_cannot_be_used(self):
        d=self.archive();ref=helpers.reference(str(uuid4()),status='failed')
        self.load(d,ref,errors=[{'run_id':'bad','error':'checksum mismatch'}])
        self.assertIn('checksum mismatch',d.page_evidence.toPlainText())
        d.results.selectRow(0);self.assertFalse(d.use_button.isEnabled());d.use_selected();self.assertEqual(self.window.pending,[])


if __name__=='__main__':unittest.main()

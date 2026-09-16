import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from importlib.util import find_spec
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HAS_QT=find_spec('PyQt6') is not None
if HAS_QT:
    from PyQt6.QtWidgets import QApplication,QWidget
    from quantlab.desktop.research_skill_library import ResearchSkillLibraryDialog


@unittest.skipUnless(HAS_QT,'Install the desktop optional dependency to test native UI')
class ResearchSkillLibraryDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.dialogs=[]
        class Window(QWidget):pass
        self.window=Window();self.window.output=self.root;self.window.data_root=None
        self.window.async_call=lambda work,done,guarded=False:done(work(),'')
        self.window.show_dialog=lambda dialog:self.dialogs.append(dialog)
        self.record={'entry_id':'a'*64,'skill_key':'manager-skill','title':'策展包','version':'v1','status':'DRAFT',
            'authorization':'HOST_APPROVED_READ_ONLY','package_snapshot':'b'*64,'control_snapshot':'c'*64,
            'archive_snapshot':'d'*64,'package_available':True,'integrity':'VERIFIED','archive_verified':True,
            'archive':{'commit':'e'*40,'tree':'f'*40,'observed_at':'2026-09-16T00:00:00+00:00','files':4,'bytes':100},
            'counts':{'claims':1,'hypotheses':1},'readiness':{},'blockers':['publication_time_unverified_resources'],
            'boundaries':{'strict_pit_eligible':False}}
        self.bundle={'format':'niuniu-research-skill-library-v1','skill':self.record,
            'resource_role_counts':{'PRIMARY_STATEMENT':1},'strategy_source_preview':{'completeness':'PARTIAL'},
            'item_types':['CLAIM','HYPOTHESIS','ALIGNMENT','RESOURCE'],'classification_values':{},'scope':'read only',
            'items':{
                'claim':{'records':[{'claim_id':'view','kind':'DIRECT_QUOTE','text':'原话','resource_ids':['statement']}],'total':1},
                'hypothesis':{'records':[{'hypothesis_key':'cycle','title':'候选','status':'DRAFT','target_horizon':'MEDIUM_TERM','claim_ids':['view']}],'total':1},
                'alignment':{'records':[],'total':0},
                'resource':{'records':[{'resource_id':'statement','role':'PRIMARY_STATEMENT','locator':'https://example.invalid','excerpt_allowed':True}],'total':1},
            }}

    def tearDown(self):
        for dialog in self.dialogs:dialog.close()
        if hasattr(self,'dialog'):self.dialog.close()
        self.window.close();self.temp.cleanup()

    def test_dialog_lists_and_searches_without_write_controls(self):
        listing={'records':[self.record],'total':1}
        with patch('quantlab.desktop.research_skill_library.ResearchSkillLibrary.list',return_value=listing), \
             patch('quantlab.desktop.research_skill_library.ResearchSkillLibrary.browse',return_value=self.bundle):
            self.dialog=ResearchSkillLibraryDialog(self.window,'manager-skill','b'*64)
        self.assertEqual(self.dialog.package_table.rowCount(),1)
        self.assertEqual(self.dialog.item_table.rowCount(),3)
        self.assertIn('未写入任何正式对象',self.dialog.status.text())
        labels=[button.text() for button in self.dialog.findChildren(type(self.dialog.refresh_button))]
        self.assertFalse(any(text.startswith(('写入','执行','创建 StrategySource','创建 Playbook')) for text in labels))


if __name__=='__main__':unittest.main()

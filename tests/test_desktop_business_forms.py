"""Business form contract tests; native acceptance is recorded separately."""
import json
import os
import unittest
from importlib.util import find_spec
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
HAS_QT=find_spec('PyQt6') is not None
if HAS_QT:
    from PyQt6.QtWidgets import QApplication
    from quantlab.desktop.action_editor import RecordFields, RecordDialog, RecordsDialog, SCHEMAS
    from quantlab.desktop.business_view import BusinessDetails
from quantlab.storage.codec import encode


@unittest.skipUnless(HAS_QT,'Install the desktop optional dependency to test native UI')
class BusinessFormsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_corporate_nested_roundtrip_and_flat_stock_edit(self):
        from test_stock_distributions import StockDistributionTests
        from test_rights_issues import RightsIssueTests
        from test_stock_splits import StockSplitTests
        fixtures=[('corporate_actions',StockDistributionTests().account()[3].corporate_actions[0]),
                  ('rights_issues',RightsIssueTests().fixture()[3].rights_issues[0]),
                  ('stock_splits',StockSplitTests().fixture()[3].stock_splits[0])]
        for key,value in fixtures:
            with self.subTest(key=key):
                value=json.loads(encode(value));form=RecordFields(SCHEMAS[key],value)
                self.assertEqual(form.collect(),value)
                if key=='corporate_actions':
                    form.controls['cash_per_share'].setText('0.1234567890123')
                    self.assertEqual(form.collect()['cash_per_share'],.1234567890123)
                    form.optional['_stock'].setChecked(False)
                    self.assertNotIn('stock_per_share',form.collect())
                    self.assertNotIn('list_at',form.collect())
                form.close()

    def test_nested_optional_and_mapping_preserve_values(self):
        from quantlab.desktop.action_editor import HOLDING
        value={'basis_per_share':.12345678901234,'available_at':'2024-01-01T07:00:00.123456+00:00','source':'合成表单测试',
               'bands':[{'months':1,'rate':.2},{'months':None,'rate':0.}],
               'lots':[{'acquired_at':'2023-12-01','quantity':100}]}
        form=RecordFields(HOLDING,value);self.assertEqual(form.collect(),value)
        schema={'entitlement_allocations':SCHEMAS['stock_splits']['entitlement_allocations']}
        value={'entitlement_allocations':{'送股一':{'shares':100,'cash':.25,'principal_reduction':0.}}}
        form=RecordFields(schema,value);self.assertEqual(form.collect(),value)
        form.optional['entitlement_allocations'].setChecked(False);self.assertEqual(form.collect(),{})

    def test_invalid_input_and_history_contract_rejected(self):
        from quantlab.processing.neutralization import SizeHistory
        dialog=RecordDialog(None,{'source':SCHEMAS['size_events']['source']},{},'新增资料')
        dialog.finish();self.assertEqual(dialog.result(),0);self.assertIn('不能为空',dialog.status.text())
        values=[{'symbol':'sh.600000','market_cap':-1,'effective_at':'2024-01-01T15:00:00+08:00',
                 'available_at':'2024-01-01T15:00:00+08:00','expires_at':'2024-01-02T15:00:00+08:00','source':'合成表单测试'}]
        dialog=RecordsDialog(None,'size_events',values,'市值资料',SizeHistory)
        dialog.finish();self.assertEqual(dialog.result(),0);self.assertIn('未通过',dialog.status.text())
        values[0]['market_cap']=100000.;dialog.editor.setPlainText(encode(values));dialog.finish()
        self.assertEqual(dialog.result(),1);self.assertEqual(dialog.result_value,values)

    def test_sequence_periods_are_editable_and_validated(self):
        from quantlab.app import default_registry
        from quantlab.desktop.research_config import ParameterDialog
        definition=next(d for d in json.loads(encode(default_registry().describe())) if d['definition']['factor_id']=='SEQ.CUSTOM_ORDERED')
        dialog=ParameterDialog(None,definition,{})
        self.assertEqual(len(dialog.sequence_period_controls),2)
        dialog.sequence_period_controls[0].setCurrentIndex(2);dialog.finish()
        self.assertEqual(dialog.result(),0);self.assertIn('每个步骤',dialog.status.text())
        dialog.sequence_period_controls[1].setCurrentIndex(3);dialog.finish()
        self.assertEqual(dialog.result_value['step_timeframes'],['5m','15m'])
        self.assertEqual(dialog.result_value['steps'],definition['defaults']['steps'])

    def test_business_view_hides_raw_and_expands_large_lists(self):
        data={'config':{'adjustment':'qfq'},'events':[{'value':i} for i in range(251)]}
        view=BusinessDetails(data);self.assertTrue(view.raw.isHidden())
        node=view.tree.topLevelItem(0);self.assertEqual(node.text(0),'研究设置')
        view.expand(node);self.assertEqual(node.child(0).text(1),'前复权')
        node=view.tree.topLevelItem(1);view.expand(node);self.assertEqual(node.childCount(),3)
        view.expand(node.child(2));self.assertEqual(node.child(2).childCount(),51)
        self.assertEqual(json.loads(view.toPlainText()),data)

    def test_table_times_match_beijing_label(self):
        from quantlab.desktop.action_editor import RecordsEditor
        value={'symbol':'sh.600000','sector':'测试','effective_at':'2024-01-01T07:00:00+00:00',
               'available_at':'2024-01-01T07:00:00+00:00','source':'合成测试'}
        view=RecordsEditor(SCHEMAS['industry_events'],[value],'行业')
        self.assertEqual(view.view.item(0,2).text(),'2024-01-01 15:00:00')
        self.assertEqual(view.values(),[value])

    def test_industry_buttons_dispatch_to_correct_section(self):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QPushButton
        from quantlab.desktop.research_config import ResearchConfigDialog
        dialog=ResearchConfigDialog(None,{},'execution')
        with patch.object(dialog,'edit_industry') as edit:
            for title,key in [('实际持仓','execution'),('目标组合','portfolio')]:
                button=next(b for b in dialog.findChildren(QPushButton) if b.text()=='配置'+title+'历史行业资料')
                button.click();edit.assert_called_with(key)
        dialog.close()

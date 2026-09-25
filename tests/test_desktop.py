"""Native UI regression coverage; run with QT_QPA_PLATFORM=offscreen."""
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from uuid import uuid4
from importlib.util import find_spec
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
HAS_QT=find_spec('PyQt6') is not None
if HAS_QT:
    from PyQt6.QtCore import Qt,QDate
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication,QTableWidget,QLineEdit
    from quantlab.desktop.app import MainWindow,NAV
    from quantlab.desktop.experiment import ExperimentDialog


@unittest.skipUnless(HAS_QT,'Install the desktop optional dependency to test native UI')
class DesktopTest(unittest.TestCase):
    def test_multiscale_audit_business_detail_and_period_controls(self):
        from quantlab.desktop.audit_view import AuditView
        from quantlab.desktop.research_config import ParameterDialog
        from quantlab.app import default_registry
        from quantlab.storage.codec import encode
        definition=next(d for d in json.loads(encode(default_registry().describe())) if d['definition']['factor_id']=='CHAN.CLASSIC_MULTISCALE_DIRECTION')
        dialog=ParameterDialog(self.window,definition,{'middle_timeframe':'15m','higher_timeframe':'30m','same_direction':True})
        self.assertEqual(dialog.controls['higher_timeframe'].currentText(),'30 分钟');dialog.finish()
        self.assertEqual(dialog.result_value['higher_timeframe'],'30m')
        event={'symbol':'sh.600000','available_at':'2025-01-03','metadata':{'status':'nested','levels':['5m','15m','30m'],
            'segments':[{'timeframe':'30m','direction':1,'start_at':'2025-01-01','end_at':'2025-01-02','available_at':'2025-01-03'}]}}
        view=AuditView({'sequences':[{'factor':definition['definition'],'events':[event]}]})
        view.current_table.setCurrentCell(0,0)
        self.assertEqual(view.current_table.item(0,1).text(),'已连接')
        self.assertIn('30 分钟',view.detail.toPlainText());self.assertIn('结构在 2025-01-03 可用',view.detail.toPlainText())
        view.close();dialog.close()

    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);cls.app.setStyle('Fusion')

    def setUp(self):
        # Walking every page must not call live market interfaces (盘中板块) or open the real 日内 database from tests.
        from unittest.mock import patch as _patch
        _gate=_patch('quantlab.desktop.sector_pages.is_ready',return_value=False);_gate.start();self.addCleanup(_gate.stop)
        _gate2=_patch('quantlab.desktop.intraday_page.is_data_ready',return_value=False);_gate2.start();self.addCleanup(_gate2.stop)
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        for i in range(2):
            run_id=str(uuid4());folder=root/run_id;folder.mkdir()
            record={'run_id':run_id,'status':'completed','created_at':str(i),'kind':'factor',
                'manifest':{'config':{'research_question':f'原生验收 {i}','factor_id':'BASE.MOMENTUM',
                    'data':{'symbols':['sh.600000'],'start':'2026-08-03','end':'2026-08-20','timeframe':'1d'}}},
                'metrics':{'1':{'observations':20,'ic':0.1}}}
            (folder/'experiment.json').write_text(json.dumps(record))
        self.window=MainWindow(root);self.window.resize(1440,960);self.window.show();self.wait()

    def wait(self):
        # Navigation schedules work on the next event-loop turn. Let it enqueue
        # reads before checking callbacks, rather than returning mid-navigation.
        QTest.qWait(30)
        end=time.monotonic()+10
        while self.window.callbacks and time.monotonic()<end:QTest.qWait(10)
        QTest.qWait(30)
        self.assertFalse(self.window.callbacks,'background reads did not complete')
        self.assertNotIn('失败',self.window.status.text())

    def tearDown(self):
        self.wait();self.window.close();QTest.qWait(10);self.temp.cleanup()

    def test_boss_key_from_modal_input_and_toolbar(self):
        from PyQt6.QtWidgets import QDialog, QVBoxLayout
        dialog=QDialog(self.window);dialog.setModal(True)
        edit=QLineEdit('未提交的实验配置',dialog);QVBoxLayout(dialog).addWidget(edit)
        dialog.show();edit.setFocus();QTest.qWait(10)
        with patch('quantlab.desktop.boss_key.sys.platform','darwin'), \
             patch('quantlab.desktop.boss_key.QApplication.platformName',return_value='cocoa'), \
             patch('quantlab.desktop.boss_key.hide_macos_application') as hide:
            QTest.keyClick(edit,Qt.Key.Key_F12)
            hide.assert_called_once_with()
            QTest.keyClick(edit,Qt.Key.Key_F12,Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(hide.call_count,1)
            dialog.hide()
            QTest.mouseClick(self.window.boss_button,Qt.MouseButton.LeftButton)
            self.assertEqual(hide.call_count,2)
        self.assertEqual(edit.text(),'未提交的实验配置')
        self.assertFalse(self.window.closing)
        dialog.close()

    def test_boss_key_preserves_background_work_and_window(self):
        results=[]
        self.window.async_call(lambda:(time.sleep(.05),'完成')[1],lambda result,error:results.append((result,error)))
        with patch('quantlab.desktop.boss_key.sys.platform','linux'):
            self.window.boss_key.hide()
        self.assertTrue(self.window.isMinimized())
        self.wait()
        self.assertEqual(results,[('完成','')])
        self.assertFalse(self.window.closing)
        self.window.showNormal()
        self.assertTrue(self.window.isVisible())

    def test_navigation_registry_filter_search_and_detail(self):
        self.window.pro_toggle.setChecked(True);self.wait()
        for index in range(len(NAV)):
            QTest.mouseClick(self.window.nav[index],Qt.MouseButton.LeftButton);self.wait()
            self.assertTrue(self.window.nav[index].isChecked())
        self.window.registry_page('factor','BASE.CLOSE_LOCATION')
        t=self.window.scroll.widget().findChild(QTableWidget)
        self.assertEqual(t.rowCount(),1);self.assertIn('BASE.CLOSE_LOCATION',t.item(0,1).text())
        self.window.search.setText('原生验收 1');QTest.keyClick(self.window.search,Qt.Key.Key_Return);self.wait()
        tables=self.window.scroll.widget().findChildren(QTableWidget)
        self.assertEqual(tables[-1].rowCount(),1)
        self.window.open_run(self.window.last_records[0]['run_id']);self.wait()
        self.assertEqual(self.window.dialogs[-1].windowTitle(),'原生验收 1')

    def test_form_validation_and_late_page_reads(self):
        dialog=ExperimentDialog(self.window)
        dialog.symbols.setText('sh.600000 sz.000001');dialog.start.setDate(QDate(2026,8,3));dialog.end.setDate(QDate(2026,8,20))
        self.assertEqual(dialog.adjustment.currentData(),'qfq')
        self.assertTrue(dialog.validate());self.assertIn('校验通过',dialog.status.text())
        dialog.symbols.setText('invalid')
        self.assertIn('重新校验',dialog.status.text());self.assertTrue(dialog.preview.isHidden());self.assertEqual(dialog.preview.toPlainText(),'')
        self.assertFalse(dialog.validate());self.assertIn('配置错误',dialog.status.text())
        self.assertTrue(dialog.preview.isHidden())
        dialog.close()
        self.window.home();self.window.navigate(11);self.wait()
        self.assertEqual(self.window.current,11)
        self.assertIn('PyQt6',self.window.scroll.widget().findChild(QTableWidget).item(2,1).text())

    def test_research_tools_callback_survives_navigation(self):
        import threading
        from quantlab.desktop.research_tools import ResearchToolsDialog
        dialog=ResearchToolsDialog(self.window);release=threading.Event()
        self.assertIn('BASE.MOMENTUM',dialog.candidate.itemText(0))
        dialog.perform(lambda:(release.wait(5),{'status':'done'})[1])
        self.window.navigate(11);release.set();self.wait()
        self.assertTrue(dialog.residual_button.isEnabled())
        self.assertIn('done',dialog.output.toPlainText());dialog.close()

    def test_chart_axis_precision_and_constant_curve(self):
        from quantlab.desktop.widgets import Chart
        for values in ([1000000,1000118.47],[.000001,.000002],[-2,3]):
            lo,hi,ticks=Chart.axis(values)
            self.assertEqual(len(set(ticks)),5)
            self.assertAlmostEqual(float(ticks[0].replace(',','')),hi)
            self.assertAlmostEqual(float(ticks[-1].replace(',','')),lo)
        for value in (1000000,0,-10):
            lo,hi,ticks=Chart.axis([value,value])
            self.assertAlmostEqual((value-lo)/(hi-lo),.5)
            self.assertEqual(float(ticks[2].replace(',','')),value)

    def test_complete_trade_ledger_pagination_and_filter(self):
        from quantlab.desktop.trade_ledger import TradeLedger
        fills=[{'symbol':'A' if i<200 else 'B','side':'buy','quantity':100,'price':10.123456789,'commission':5} for i in range(266)]
        rejects=[{'symbol':'B','side':'buy','requested':200,'filled':100,'reason':'actual_position_or_exposure_cap'}]
        widget=TradeLedger({'fills':fills[:200],'_display_summary':{'counts':{'/fills':266,'/rejections':1}}},lambda done:done({'fills':fills,'rejections':rejects},None))
        self.assertFalse(widget.complete);widget.load();self.assertTrue(widget.complete)
        self.assertEqual(widget.fills.rowCount(),200);widget.turn(1);self.assertEqual(widget.fills.rowCount(),66)
        widget.symbol.setText('B');self.assertEqual(widget.page,0);self.assertEqual(widget.fills.rowCount(),66)
        self.assertEqual(widget.fills.item(0,2).text(),'买入');self.assertEqual(widget.fills.item(0,4).toolTip(),'10.123456789')
        widget.tabs.setCurrentIndex(1);self.assertIn('仓位',widget.rejections.item(0,5).text());widget.close()

    def test_replay_symbol_search_clears_invalid_and_recovers(self):
        import polars as pl
        from test_technical import bars
        from quantlab.desktop.replay import ReplayWidget
        folder=next(Path(self.temp.name).glob('*/experiment.json')).parent
        pl.concat([bars([10.,11.],symbol='sz.002099'),bars([20.,21.],symbol='sz.300118')]).write_parquet(folder/'bars.parquet')
        widget=ReplayWidget(self.window,folder.name,{});self.wait()
        self.assertTrue(widget.symbol.isEditable())
        widget.symbol.setEditText('sz.300118');self.wait()
        self.assertEqual(widget.chart.candles[0]['symbol'],'sz.300118')
        widget.symbol.setEditText('sz.300');self.wait()
        self.assertEqual(widget.chart.candles,[]);self.assertFalse(widget.play.isEnabled())
        self.assertEqual(widget.fills.toPlainText(),'[]')
        widget.symbol.setEditText('sz.002099');self.wait()
        self.assertEqual(widget.symbol.count(),2)
        self.assertEqual(widget.chart.candles[0]['symbol'],'sz.002099');self.assertTrue(widget.play.isEnabled())
        widget.close()

    def test_multiscale_replay_period_switch_keeps_available_cutoff(self):
        from test_chan_multiscale import ChanMultiscaleTests
        from quantlab.desktop.replay import ReplayWidget
        frame=ChanMultiscaleTests().frame();folder=next(Path(self.temp.name).glob('*/experiment.json')).parent
        frame.write_parquet(folder/'bars.parquet')
        record={'manifest':{'config':{'factor_id':'CHAN.CLASSIC_MULTISCALE_DIRECTION','data':{'timeframe':'5m'}},
                            'parameters':{'middle_timeframe':'15m','higher_timeframe':'30m'}}}
        widget=ReplayWidget(self.window,folder.name,record);self.wait();widget.cursor.setValue(50);self.wait()
        self.assertFalse(widget.evidence.isTabVisible(1));self.assertFalse(widget.evidence.isTabVisible(2))
        cutoff=widget.times[widget.cursor.value()]
        widget.period.setCurrentIndex(1);widget.period.setCurrentIndex(2);self.wait()
        self.assertEqual(widget.bars['timeframe'].unique().to_list(),['30m'])
        self.assertEqual(widget.bars.height,frame.height//6)
        self.assertLessEqual(widget.times[widget.cursor.value()],cutoff)
        widget.period.setCurrentIndex(0);self.wait();self.assertTrue(widget.bars.equals(frame));widget.close()

    def test_replay_business_details_page_and_clear(self):
        from quantlab.desktop.replay_details import ReplayDetails
        widget=ReplayDetails({'TEST':'确认事件'})
        events=[{'factor_id':'TEST','available_at':'2025-01-01T15:00:00+08:00','direction':1,'metadata':{'status':'added'}} for _ in range(205)]
        widget.set_data({'events':events});self.assertEqual(widget.table.rowCount(),100)
        self.assertEqual(widget.table.item(0,2).text(),'确认事件');self.assertEqual(widget.table.item(0,5).text(),'新出现')
        widget.move(2);self.assertEqual(widget.table.rowCount(),5)
        self.assertIn('205',widget.status.text());widget.set_data({});self.assertEqual(widget.table.rowCount(),0);widget.close()

    def test_replay_date_and_event_fill_navigation(self):
        from PyQt6.QtCore import QDateTime
        from test_technical import bars
        from quantlab.desktop.replay import ReplayWidget
        frame=bars([10.,11.,12.,13.]).gather([0,1,3])
        folder=next(Path(self.temp.name).glob('*/experiment.json')).parent
        frame.write_parquet(folder/'bars.parquet')
        times=frame['available_at'].to_list()
        event={'symbol':'A','available_at':times[1].isoformat(),'occurred_at':times[0].isoformat(),'event_id':'confirmed-later'}
        fill={'symbol':'A','filled_at':times[2].replace(hour=9,minute=30).isoformat()}
        widget=ReplayWidget(self.window,folder.name,{'replay':{'events':[event]},'fills':[fill]});self.wait()
        self.assertTrue(widget.cursor.isHidden())
        self.assertFalse(widget.navigation['fill',-1].isEnabled())
        QTest.mouseClick(widget.navigation['signal',1],Qt.MouseButton.LeftButton);self.wait()
        self.assertEqual(widget.cursor.value(),1)
        self.assertIn('confirmed-later',widget.objects.toPlainText())
        self.assertEqual(widget.fills.toPlainText(),'[]')
        QTest.mouseClick(widget.navigation['fill',1],Qt.MouseButton.LeftButton);self.wait()
        self.assertEqual(widget.cursor.value(),2);self.assertIn('09:30',widget.fills.toPlainText())
        self.assertFalse(widget.navigation['fill',1].isEnabled())
        widget.date.setDateTime(QDateTime(times[1].replace(day=3)));self.wait()
        self.assertEqual(widget.cursor.value(),1)
        self.assertEqual(widget.date.date().day(),2)
        QTest.mouseClick(widget.navigation['bar',-1],Qt.MouseButton.LeftButton);self.wait()
        self.assertEqual(widget.cursor.value(),0)
        self.assertNotIn('confirmed-later',widget.objects.toPlainText());self.assertEqual(widget.fills.toPlainText(),'[]')
        widget.close()

    def test_execution_format_and_audit_paging(self):
        from quantlab.desktop.widgets import execution_table
        from quantlab.desktop.audit_view import AuditView
        t=execution_table({'initial_cash':1000000,'final_equity':1001118.46941052,'net_return':.00111846941052,'max_drawdown':-.0025913238})
        self.assertEqual(t.item(1,1).text(),'1,001,118.47')
        self.assertEqual(t.item(2,1).text(),'0.1118%')
        self.assertEqual(t.item(3,1).text(),'-0.2591%')
        self.assertIn('1001118.46941052',t.item(1,1).toolTip())
        entries=[{'symbol':f'symbol-{i}','status':'completed','completion_selected':False} for i in range(101)]
        audit=AuditView({'sequences':[{'alias':'sequence','transitions':entries},{'alias':'empty'}]})
        self.assertEqual(audit.current_table.rowCount(),100);self.assertTrue(audit.next.isEnabled())
        audit.move(1);self.assertEqual(audit.page_label.text(),'101–101 / 101')
        audit.current_table.setCurrentCell(0,0);self.assertIn('symbol-100',audit.detail.toPlainText())
        audit.selector.setCurrentIndex(1)
        self.assertEqual(audit.page_label.text(),'0–0 / 0');self.assertFalse(audit.next.isEnabled());self.assertFalse(audit.previous.isEnabled())
        self.assertNotIn('symbol-100',audit.detail.toPlainText())

    def test_comparison_form_builds_plan_and_rejects_duplicates(self):
        from quantlab.desktop.comparison_editor import ComparisonEditor
        widget=ComparisonEditor(self.window,'stability',lambda plan:None)
        widget.add();self.assertEqual(widget.entries,[])
        widget.baseline.setCurrentIndex(1);widget.add();self.assertEqual(len(widget.entries),1)
        widget.add();self.assertEqual(len(widget.entries),1)
        plan=widget.plan();self.assertEqual(plan['comparisons'][0]['name'],'comparison_1')
        self.assertEqual(plan['permutation']['block_days'],5)
        widget.table.selectRow(0);widget.remove();self.assertEqual(widget.entries,[])
        with self.assertRaises(ValueError):widget.plan()
        widget.comparison_kind.setCurrentIndex(widget.comparison_kind.findData('cross_market_equivalence'))
        widget.baseline.setCurrentIndex(widget.candidate.currentIndex())
        widget.candidate_symbols.setText('sh.600000 sh.600001 sh.600002')
        widget.baseline_symbols.setText('sz.000001 sz.000002 sz.000003');widget.margin.setValue(.03)
        widget.add();self.assertEqual(len(widget.entries),1)
        plan=widget.plan();self.assertEqual(plan['comparison_kind'],'cross_market_equivalence')
        self.assertEqual(plan['comparisons'][0]['equivalence_margin'],.03)
        self.assertFalse(widget.comparison_kind.isEnabled())
        widget.close()

    def test_nested_sequence_form_preserves_scopes(self):
        from quantlab.desktop.sequence_editor import SequenceEditor
        from quantlab.sequence.specification import normalize_steps,sequence_scopes
        steps=['A',{'steps':['B',{'event':'C','optional':True}],'timeout_seconds':120,'invalidators':['A']},'D']
        dialog=SequenceEditor(self.window,steps,('A','B','C','D'),{})
        self.assertEqual(dialog.steps(),steps)
        group=dialog.tree.topLevelItem(1);dialog.tree.setCurrentItem(group)
        dialog.timeout.setValue(240);dialog.apply();result=dialog.steps()
        self.assertEqual(result[1]['timeout_seconds'],240)
        self.assertEqual(normalize_steps(result,('A','B','C','D'))[1],(2,))
        self.assertEqual(len(sequence_scopes(result)),1)
        dialog.timeout.setValue(0);self.assertFalse(dialog.apply())
        self.assertEqual(dialog.steps()[1]['timeout_seconds'],240)
        dialog.reject()

    def test_typed_config_form_preserves_values(self):
        from quantlab.desktop.config_editor import ConfigEditor
        value={'n':3,'enabled':False,'controls':['A',None,{'weight':.5}]}
        dialog=ConfigEditor(self.window,value)
        self.assertEqual(dialog.decode(),value)
        dialog.tree.setCurrentItem(dialog.root.child(0));dialog.value.setText('8');self.assertTrue(dialog.apply())
        self.assertEqual(dialog.decode()['n'],8)
        dialog.kind.setCurrentText('小数');dialog.value.setText('nan');self.assertFalse(dialog.apply())
        self.assertEqual(dialog.decode()['n'],8)
        dialog.reject()

    def test_fixed_family_form_freezes_without_running(self):
        from PyQt6.QtCore import QTimer
        from quantlab.desktop.research_tools import ResearchToolsDialog
        from quantlab.experiments.trial_registry import _load_registry
        dialog=ResearchToolsDialog(self.window)
        def fill():
            editor=QApplication.activeModalWidget()
            editor.symbols.setText('sh.600000')
            editor.start.setDate(QDate(2025,1,1));editor.end.setDate(QDate(2025,6,30))
            editor.question.setText('表单计划验证')
            QTest.mouseClick(editor.submit_button,Qt.MouseButton.LeftButton)
            if editor.isVisible():editor.reject()
        QTimer.singleShot(20,fill);dialog.add_trial_form()
        self.assertEqual(len(dialog.draft_trials),1)
        self.assertIn('permutation',dialog.draft_specs[0])
        dialog.freeze_trials();self.wait()
        registry=_load_registry(dialog.registry_path)
        self.assertEqual(registry['plan']['trials'][0]['config']['research_question'],'表单计划验证')
        self.assertEqual(dialog.frozen_specs[1][0][1]['question'],'表单计划验证')
        dialog.draft_specs[0]['question']='后来修改'
        self.assertEqual(dialog.frozen_specs[1][0][1]['question'],'表单计划验证')
        self.assertIsNone(self.window.queue)
        reopened=ResearchToolsDialog(self.window);reopened.select_registry(dialog.registry_path)
        self.assertEqual(reopened.frozen_specs,dialog.frozen_specs);reopened.close()
        dialog.close()

    def test_business_settings_preserve_unknown_sections_and_validate(self):
        from quantlab.desktop.research_config import ResearchConfigDialog,ParameterDialog
        original={'processor':{'steps':[{'method':'cs_rank'}]},'execution':{'top_n':20,'price_mode':'research'},'portfolio':{'max_position':.05},'regime_filter':{'direction':'Bull'}}
        dialog=ResearchConfigDialog(self.window,original,'execution')
        dialog.controls[('execution','commission_bps')].setValue(2.5)
        dialog.controls[('execution','initial_cash')].setValue(2500000.)
        dialog.finish();result=dialog.result_value
        self.assertIsNotNone(result);self.assertEqual(result['processor'],original['processor'])
        self.assertEqual(result['execution']['price_mode'],'research')
        self.assertEqual(result['execution']['commission_bps'],2.5)
        self.assertEqual(result['regime_filter'],{'direction':'Bull'})
        self.assertEqual(result['portfolio']['max_position'],.05)
        self.assertEqual(original['execution'],{'top_n':20,'price_mode':'research'})
        dialog=ResearchConfigDialog(self.window,{},'single')
        dialog.sections['bootstrap'][0].setChecked(True);dialog.controls[('bootstrap','resamples')].setValue(1)
        dialog.finish();self.assertIsNone(dialog.result_value);self.assertIn('未通过',dialog.status.text());dialog.reject()
        definition=next(v for v in self.window.factors if v['definition']['factor_id']=='BASE.MOMENTUM')
        editor=ParameterDialog(self.window,definition,{'lookback':20})
        editor.controls['lookback'].setValue(0);editor.finish();self.assertIsNone(editor.result_value)
        editor.controls['lookback'].setValue(30);editor.finish();self.assertEqual(editor.result_value,{'lookback':30})

    def test_grid_business_editor_and_expert_disclosure(self):
        from quantlab.desktop.grid_editor import GridDialog
        definition=next(v for v in self.window.factors if v['definition']['factor_id']=='BASE.MOMENTUM')
        editor=GridDialog(self.window,definition,{'lookback':[5,10]})
        editor.controls['lookback'].setText('5， 15 30');editor.finish()
        self.assertEqual(editor.result_value,{'lookback':[5,15,30]})
        dialog=ExperimentDialog(self.window,definition)
        self.assertTrue(dialog.expert_body.isHidden());self.assertFalse(dialog.grid_button.isEnabled());self.assertTrue(dialog.parameter_button.isEnabled())
        dialog.mode.setCurrentIndex(dialog.mode.findData('sweep'));self.assertTrue(dialog.grid_button.isEnabled())
        dialog.expert.setChecked(True);self.assertFalse(dialog.expert_body.isHidden());dialog.close()

    def test_combination_business_rules_and_weights(self):
        from quantlab.desktop.combination_editor import CombinationDialog
        from quantlab.app import default_registry
        registry=default_registry()
        for key in ('COMB.CONDITION','COMB.SCORE'):
            expected=registry.get(key,'1.0.0').parameters({})
            dialog=CombinationDialog(self.window,key,expected);dialog.finish()
            self.assertEqual(dialog.result_value,expected)
        dialog=CombinationDialog(self.window,'COMB.SCORE',{})
        alias=dialog.inputs.currentItem().data(Qt.ItemDataRole.UserRole)
        dialog.weight.setValue(.25);dialog.finish();self.assertEqual(dialog.result_value['weights'][alias],.25)
        dialog=CombinationDialog(self.window,'COMB.CONDITION',{})
        root=dialog.tree.topLevelItem(0);dialog.tree.setCurrentItem(root)
        dialog.kind.setCurrentIndex(dialog.kind.findData('any'));self.assertTrue(dialog.apply_rule())
        dialog.finish();self.assertIn('any',dialog.result_value['rule'])
        dialog=CombinationDialog(self.window,'COMB.CONDITION',{})
        dialog.remove_input();dialog.finish();self.assertIsNone(dialog.result_value);self.assertIn('未通过',dialog.status.text());dialog.reject()

    def test_processor_business_order_and_missing_controls(self):
        from quantlab.desktop.processor_editor import ProcessorDialog
        original={'steps':[{'method':'replace_inf'},{'method':'clip','lower':-2.,'upper':2.},{'method':'cs_rank'}],'fit_start':'2025-01-01','fit_end':'2025-06-30'}
        dialog=ProcessorDialog(self.window,original,QDate(2025,1,1),QDate(2025,6,30))
        dialog.finish();self.assertEqual(dialog.result_value,original)
        dialog=ProcessorDialog(self.window,None,QDate(2025,1,1),QDate(2025,6,30))
        dialog.method.setCurrentIndex(dialog.method.findData('neutralization'));dialog.add();dialog.finish()
        self.assertIsNone(dialog.result_value);self.assertIn('未通过',dialog.status.text());dialog.reject()
        dialog=ProcessorDialog(self.window,'cs_rank',QDate(2025,1,1),QDate(2025,6,30));dialog.finish();self.assertEqual(dialog.result_value,'cs_rank')

    def test_context_theory_and_statistics_business_forms(self):
        from quantlab.desktop.context_editor import ContextDialog
        from quantlab.desktop.theory_editor import TheoryDialog
        from quantlab.desktop.research_summary import research_statistics
        from quantlab.app import default_registry
        context={'start':'2025-01-01','factor_id':'BASE.MOMENTUM','version':'1.0.0','parameters':{'lookback':20},'op':'gt','value':0.,'timeframe':'1d'}
        editor=ContextDialog(self.window,context,QDate(2025,1,1));editor.finish();self.assertEqual(editor.result_value,context)
        params=default_registry().get('COMB.CONDITION','1.0.0').parameters({})
        plan={'split':{'train_end':'2025-06-30','valid_end':'2025-09-30'},'schedule':{'train_days':90,'valid_days':30,'test_days':30,'expanding':False},'input':'momentum','grid':{'lookback':[5,10,20]},'audit_components':True}
        editor=TheoryDialog(self.window,params,plan,QDate(2025,1,1),QDate(2025,12,31));editor.finish();self.assertEqual(editor.result_value,plan)
        panel=research_statistics({'metrics':{'1':{'bootstrap':{'daily_mean_ic':{'estimate':.1,'ci_low':-.2,'ci_high':.3,'status':'computed','confidence':.95,'valid_days':100}}}}})
        t=panel.findChild(QTableWidget);self.assertEqual(t.rowCount(),1);self.assertEqual(t.item(0,2).text(),'日均 IC');panel.close()

    def test_import_large_classic_experiment_roundtrip(self):
        from quantlab.workbench.jobs import prepare
        spec={'question':'经典缠论500股','symbols':[f'sh.{600000+i}' for i in range(500)],
            'start':'2016-09-05','end':'2026-09-04','timeframe':'1d','mode':'execution',
            'factor':'CHAN.CLASSIC_POSITION','parameters':{},'regime':{},'sequence_audit':True,'replay':True,
            'execution':{'top_n':20,'minimum_commission':5,'sell_tax_bps':5},'portfolio':{'max_position':.05}}
        dialog=ExperimentDialog(self.window);dialog.apply_spec(spec)
        self.assertEqual(prepare(dialog.collect()).preview(),prepare(spec).preview())
        self.assertIn('已导入',dialog.status.text());self.assertTrue(dialog.preview.isHidden())
        self.assertEqual(dialog.collect()['adjustment'],'qfq')
        dialog.apply_spec({**spec,'adjustment':'raw'})
        self.assertEqual(dialog.collect()['adjustment'],'raw')
        before=dialog.collect()
        with self.assertRaises(ValueError):dialog.apply_spec({**spec,'symbols':['bad']})
        self.assertEqual(before,dialog.collect());dialog.close()

    def test_sequence_drag_order_and_experiment_parameters(self):
        from quantlab.desktop.sequence_builder import SequenceBuilder
        from PyQt6.QtCore import QPointF
        self.window.navigate(5)
        editor=self.window.scroll.widget().findChild(SequenceBuilder)
        # Move a real graphics item across the other node; the canvas order must become execution order.
        node=editor.canvas.nodes[0];start=editor.canvas.mapFromScene(node.pos()+QPointF(70,40));end=editor.canvas.mapFromScene(QPointF(490,110))
        QTest.mousePress(editor.canvas.viewport(),Qt.MouseButton.LeftButton,pos=start)
        QTest.mouseMove(editor.canvas.viewport(),end,30)
        QTest.mouseRelease(editor.canvas.viewport(),Qt.MouseButton.LeftButton,pos=end)
        QTest.qWait(40)
        self.assertEqual(editor.steps,['EVT.BREAKOUT_HIGH','EVT.FAILED_BREAKOUT_LOW'])
        editor.research();dialog=self.window.dialogs[-1]
        self.assertEqual(dialog.collect()['parameters']['steps'],editor.steps)
        self.assertEqual(dialog.collect()['factor'],'SEQ.CUSTOM_ORDERED')
        self.assertTrue(dialog.audit.isChecked())
        editor.save();self.assertEqual(len(list((self.window.output/'_sequence_drafts').glob('*.json'))),1)
        dialog.close()

    def test_chan_family_draft_and_submission(self):
        from unittest.mock import patch
        from quantlab.desktop.sequence_builder import SequenceBuilder
        self.window.navigate(5);editor=self.window.scroll.widget().findChild(SequenceBuilder)
        editor.family.setCurrentIndex(editor.family.findData('SEQ.CHAN_ORDERED'))
        self.assertEqual(editor.library.count(),4)
        editor.structure['right'].setValue(3);params=editor.validate();self.assertNotIn('lookback',params)
        editor.save();path=next((self.window.output/'_sequence_drafts').glob('*.json'))
        editor.family.setCurrentIndex(0)
        with patch('quantlab.desktop.sequence_builder.QFileDialog.getOpenFileName',return_value=(str(path),'JSON')):editor.load()
        self.assertEqual(editor.parameters(),params)
        editor.research();dialog=self.window.dialogs[-1]
        self.assertEqual(dialog.collect()['factor'],'SEQ.CHAN_ORDERED')
        self.assertEqual(dialog.collect()['parameters'],params);dialog.close()

    def test_workspace_path_edit_applies_without_moving_records(self):
        from PyQt6.QtWidgets import QPushButton
        original=self.window.output;target=original/'other';target.mkdir()
        self.window.edit_paths();dialog=self.window.dialogs[-1]
        dialog.findChildren(QLineEdit)[0].setText(str(target))
        apply=next(b for b in dialog.findChildren(QPushButton) if b.text()=='应用路径')
        QTest.mouseClick(apply,Qt.MouseButton.LeftButton);self.wait()
        self.assertEqual(self.window.catalog.root,target)
        self.assertEqual(len(list(original.glob('*/experiment.json'))),2)
        self.assertEqual(self.window.catalog.list()['total'],0)

    def test_company_action_complete_ledger_paging(self):
        from quantlab.desktop.corporate_actions import action_ledger
        from PyQt6.QtWidgets import QPushButton,QPlainTextEdit,QLabel
        events=[{'kind':'dividend_tax_assessment','action_id':str(i),'symbol':'sh.600000','at':f'2026-09-01T09:30:{i%60:02}',
            'tax':1.,'payable_delta':1.,'source':'paging fixture'} for i in range(205)]
        page=action_ledger({'dividend_tax_ledger':events[:200]},True,lambda done:done({'dividend_tax_ledger':events},None))
        page.show();QTest.qWait(10)
        buttons={b.text():b for b in page.findChildren(QPushButton)}
        QTest.mouseClick(buttons['载入完整公司行动账本'],Qt.MouseButton.LeftButton)
        QTest.mouseClick(buttons['下一页'],Qt.MouseButton.LeftButton)
        QTest.mouseClick(buttons['下一页'],Qt.MouseButton.LeftButton);QTest.qWait(10)
        self.assertTrue(any('201–205 / 205' in l.text() for l in page.findChildren(QLabel)))
        self.assertIn('paging fixture',page.findChild(QPlainTextEdit).toPlainText())
        self.assertFalse(buttons['下一页'].isEnabled());page.close()

    def test_research_price_mode_default_and_account_roundtrip(self):
        dialog=ExperimentDialog(self.window,mode='execution')
        self.assertEqual(dialog.price_mode.currentData(),'research')
        self.assertEqual(dialog.adjustment.currentData(),'qfq')
        self.assertEqual(dialog.action_config.text(),'配置历史费用规则')
        dialog.symbols.setText('sh.600000')
        spec=dialog.collect();self.assertEqual(spec['execution']['price_mode'],'research')
        dialog.price_mode.setCurrentIndex(dialog.price_mode.findData('account'))
        self.assertEqual(dialog.action_config.text(),'配置公司行动与费用')
        spec=dialog.collect();self.assertEqual(spec['execution']['price_mode'],'account')
        other=ExperimentDialog(self.window);other.apply_spec(spec)
        self.assertEqual(other.price_mode.currentData(),'account')
        other.close();dialog.close()

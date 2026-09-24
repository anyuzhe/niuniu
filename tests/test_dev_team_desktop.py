"""Offscreen formal workbench wiring; model transport is scripted, never paid."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import unittest
from unittest.mock import patch

from test_dev_team import ToyProject, ScriptedTeamProvider, models
from quantlab.devstudio.planning import DevRequestPlanner
from quantlab.devstudio.runtime import DevAgentRuntime
from quantlab.devstudio.team import DOMAINS, load_team_models


class DevTeamDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from PyQt6.QtWidgets import QMainWindow
        from quantlab.desktop.dev_studio import DevStudioWidget
        self.project = ToyProject()
        ScriptedTeamProvider.calls = []
        ScriptedTeamProvider.proposal = self.project.proposal()
        ScriptedTeamProvider.fail_first_app = False
        class Window(QMainWindow):
            def __init__(self, output):
                super().__init__(); self.output = output; self.dialogs = []
            def show_dialog(self, dialog):
                self.dialogs.append(dialog)
            def async_call(self, function, done, *args):
                try: value, error = function(), ''
                except Exception as exc: value, error = None, type(exc).__name__ + ': ' + str(exc)
                done(value, error)
        self.window = Window(self.project.output)
        with patch('quantlab.desktop.dev_studio.repo_root', return_value=self.project.repo):
            self.widget = DevStudioWidget(self.window)
        self.widget.poll.stop()

    def tearDown(self):
        for dialog in self.window.dialogs:
            if hasattr(dialog, 'busy'): dialog.busy = False
            dialog.close()
        self.widget.close(); self.widget.deleteLater()
        self.window.close(); self.window.deleteLater()
        self.app.processEvents()
        self.project.cleanup()

    def test_request_plan_confirm_runs_formal_pipeline_and_shows_roles(self):
        from quantlab.desktop.dev_team import DevRequestDialog
        with patch('quantlab.desktop.dev_team.DevRequestPlanner', side_effect=lambda service:
                   DevRequestPlanner(service, models(), ScriptedTeamProvider)), \
             patch('quantlab.desktop.dev_studio.DevAgentRuntime', side_effect=lambda service:
                   DevAgentRuntime(service, provider_factory=ScriptedTeamProvider)):
            self.widget.new_request()
            dialog = self.window.dialogs[-1]
            self.assertIsInstance(dialog, DevRequestDialog)
            dialog.request.setPlainText('把四个模块的 VALUE 改为 2')
            self.assertFalse(dialog.confirm_button.isEnabled())
            dialog.generate()
            self.assertTrue(dialog.confirm_button.isEnabled(), dialog.status.text())
            self.assertIn('精确文件与负责人', dialog.preview.toPlainText())
            self.assertEqual(self.project.service.list(), [])
            dialog.confirm()
            self.assertIsNotNone(dialog.created, dialog.status.text())
        self.assertEqual(self.widget.selected()['state'], 'READY_FOR_HUMAN', self.widget.status.text())
        self.assertEqual(self.widget.details.rowCount(), 6)
        self.assertIn('LEAD_CYCLE', self.widget.journal.toPlainText())
        self.assertFalse(self.widget.busy)
        self.assertEqual(self.widget.selected()['merge'], None)

    def test_edited_request_invalidates_previous_plan(self):
        from quantlab.desktop.dev_team import DevRequestDialog
        dialog = DevRequestDialog(self.window, self.project.service)
        self.window.dialogs.append(dialog)
        dialog.request.setPlainText('old')
        dialog.plan = self.project.plan()
        dialog.confirm_button.setEnabled(True)
        dialog.request.setPlainText('new request')
        self.assertIsNone(dialog.plan)
        self.assertFalse(dialog.confirm_button.isEnabled())
        dialog.confirm()
        self.assertEqual(self.project.service.list(), [])

    def test_six_model_profiles_save_independently(self):
        from quantlab.desktop.dev_team import DevTeamModelsDialog
        dialog = DevTeamModelsDialog(self.window, self.project.output)
        self.window.dialogs.append(dialog)
        self.assertEqual(set(dialog.fields), set(DOMAINS))
        dialog.fields['APP']['model'].setText('unit-test-app')
        dialog.fields['APP']['effort'].setCurrentText('low')
        dialog.save()
        saved = load_team_models(self.project.output)
        self.assertEqual(saved['APP']['model'], 'unit-test-app')
        self.assertEqual(saved['APP']['effort'], 'low')
        self.assertNotEqual(saved['LEAD']['model'], 'unit-test-app')

    def test_invalid_profile_shows_error_without_saving(self):
        from quantlab.desktop.dev_team import DevTeamModelsDialog
        dialog = DevTeamModelsDialog(self.window, self.project.output)
        self.window.dialogs.append(dialog)
        dialog.fields['APP']['api_key_env'].setText('not an environment variable')
        dialog.save()
        self.assertIn('未保存', dialog.status.text())
        self.assertFalse((self.project.output / '_devstudio/team-models.json').exists())

    def test_close_busy_planner_requests_stop_without_starting_task(self):
        from quantlab.desktop.dev_team import DevRequestDialog
        dialog = DevRequestDialog(self.window, self.project.service)
        self.window.dialogs.append(dialog)
        dialog.set_busy(True)
        dialog.reject()
        self.assertTrue(dialog.stop.is_set())
        self.assertFalse(dialog.start_requested)
        self.assertEqual(self.project.service.list(), [])
        dialog.set_busy(False)

    def test_legacy_advanced_task_is_preserved(self):
        from quantlab.desktop.dev_studio import DevTaskCreateDialog
        self.widget.new_task()
        dialog = self.window.dialogs[-1]
        self.assertIsInstance(dialog, DevTaskCreateDialog)
        self.assertNotIn('team', dialog.payload())
        self.assertEqual(dialog.parallel.value(), 2)

    def test_deleted_workbench_does_not_auto_start_late_created_task(self):
        from PyQt6 import sip
        self.widget.new_request();dialog=self.window.dialogs[-1]
        dialog.created=self.project.task();dialog.start_requested=True
        sip.delete(self.widget)
        with patch('quantlab.desktop.dev_studio.DevAgentRuntime') as runtime:
            dialog.accepted.emit();runtime.assert_not_called()
        self.assertTrue(dialog.stop.is_set())
        self.assertEqual(self.project.service.get(dialog.created['task_id'])['state'],'DRAFT')
        # Replace only the destroyed test harness widget for normal teardown.
        from quantlab.desktop.dev_studio import DevStudioWidget
        with patch('quantlab.desktop.dev_studio.repo_root',return_value=self.project.repo):
            self.widget=DevStudioWidget(self.window)
        self.widget.poll.stop()

    def test_stale_plan_cannot_create_or_start_task(self):
        from quantlab.desktop.dev_team import DevRequestDialog
        dialog = DevRequestDialog(self.window, self.project.service)
        self.window.dialogs.append(dialog)
        plan = self.project.plan()
        dialog.request.setPlainText(plan['spec']['request'])
        dialog.plan = plan
        (self.project.repo / 'README.md').write_text('new source\n')
        self.project.git('add', 'README.md'); self.project.git('commit', '-m', 'move baseline')
        with patch('quantlab.desktop.dev_studio.DevAgentRuntime') as runtime:
            dialog.confirm()
            runtime.assert_not_called()
        self.assertIsNone(dialog.created)
        self.assertIsNone(dialog.plan)
        self.assertEqual(self.project.service.list(), [])


if __name__ == '__main__':
    unittest.main()

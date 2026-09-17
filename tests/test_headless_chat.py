"""Headless CLI wiring: no GUI, no network and no implicit execution grant."""
import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from quantlab.agent.chat_cli import headless_chat_runtime, main
from quantlab.agent.model_config import ModelConfig


class HeadlessChatTests(unittest.TestCase):
    def test_default_never_exposes_or_creates_queue(self):
        with tempfile.TemporaryDirectory() as tmp, patch('quantlab.agent.chat_cli.ChatRuntime') as runtime, \
                patch('quantlab.workbench.jobs.JobQueue') as queue:
            with headless_chat_runtime(tmp) as value:
                self.assertIs(value, runtime.return_value)
                self.assertIsNone(runtime.call_args.kwargs['queue_factory'])
            queue.assert_not_called()

    def test_opt_in_requires_data_and_is_lazy(self):
        with tempfile.TemporaryDirectory() as tmp, patch('quantlab.agent.chat_cli.ChatRuntime') as runtime, \
                patch('quantlab.workbench.jobs.JobQueue') as queue:
            with self.assertRaises(ValueError):
                with headless_chat_runtime(tmp, allow_granted_research=True):
                    pass
            with headless_chat_runtime(tmp, tmp, allow_granted_research=True):
                self.assertTrue(callable(runtime.call_args.kwargs['queue_factory']))
            queue.assert_not_called()

    def test_one_queue_and_cleanup_after_exception(self):
        with tempfile.TemporaryDirectory() as tmp, patch('quantlab.agent.chat_cli.ChatRuntime') as runtime, \
                patch('quantlab.workbench.jobs.JobQueue') as queue:
            with self.assertRaisesRegex(RuntimeError, 'model failed'):
                with headless_chat_runtime(tmp, tmp, allow_granted_research=True):
                    factory = runtime.call_args.kwargs['queue_factory']
                    self.assertIs(factory(), factory())
                    queue.assert_called_once_with(tmp, tmp)
                    raise RuntimeError('model failed')
            queue.return_value.close.assert_called_once_with()

    def test_cli_opt_in_is_explicit_and_cleanup_runs(self):
        with tempfile.TemporaryDirectory() as tmp, patch('quantlab.agent.chat_cli.ChatRuntime') as runtime, \
                patch('quantlab.agent.chat_cli.load_model_config', return_value=ModelConfig()), \
                patch('quantlab.workbench.jobs.JobQueue') as queue:
            runtime.return_value.store.create.return_value = 'session'
            def send(*args, **kwargs):
                runtime.call_args.kwargs['queue_factory']()
                return {'text': 'fixture result'}
            runtime.return_value.send.side_effect = send
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = main(['--output', tmp, '--data-root', tmp, '--ask', 'fixture',
                             '--allow-granted-research', '--accept-model-service'])
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(stream.getvalue())['ok'])
            queue.return_value.close.assert_called_once_with()

    def test_cli_rejects_opt_in_for_list_or_gui(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            for extra in (['--list-sessions'], ['--gui'], ['--probe']):
                with self.subTest(extra=extra), self.assertRaises(SystemExit):
                    main(['--output', tmp, '--data-root', tmp, '--ask', 'fixture',
                          '--allow-granted-research', *extra])

    def test_real_grant_guard_and_dsl_queue_without_gui(self):
        import test_core
        from quantlab.agent.research_session_grant import preview_grant, authorize_grant, grant_status
        from quantlab.storage.codec import digest
        fixture = test_core.CoreTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        output = fixture.root / 'headless'
        output.mkdir()
        scope = {'symbols': list(fixture.symbols), 'timeframe': '1d', 'start': '2025-01-01',
                 'end': '2025-01-10', 'adjustment': 'qfq', 'qualification': 'research_only',
                 'allowed_modes': ['single'], 'allowed_factors': ['DSL.RESTRICTED@1.0.0']}
        spec = {'question': 'headless DSL fixture', 'symbols': list(fixture.symbols),
                'start': scope['start'], 'end': scope['end'], 'timeframe': '1d', 'adjustment': 'qfq',
                'factor': 'DSL.RESTRICTED', 'parameters': {'ast': {'op': 'pct_change',
                'arg': {'op': 'field', 'name': 'close'}, 'bars': 2}}, 'replay': True, 'horizons': [1]}
        with headless_chat_runtime(output, fixture.root, allow_granted_research=True,
                fuyao_client=SimpleNamespace(available=False), live_quote_service=object()) as runtime:
            no_grant = runtime.api.call('submit_granted_experiment', {'grant_id': str(uuid4()),
                'request_id': str(uuid4()), 'spec_json': json.dumps(spec)})
            self.assertFalse(no_grant['ok'])
            self.assertFalse((output / '_jobs').exists())
            plan = preview_grant(output, fixture.root, scope,
                expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(), max_jobs=1)
            granted = authorize_grant(output, fixture.root, plan, digest(plan), confirmed=True)
            submitted = runtime.api.call('submit_granted_experiment', {'grant_id': granted['grant_id'],
                'request_id': str(uuid4()), 'spec_json': json.dumps(spec)})
            self.assertTrue(submitted['ok'], submitted)
            job_id = submitted['data']['job']['job_id']
            deadline = time.monotonic()+20
            while time.monotonic() < deadline:
                state = runtime.api.call('get_job', {'job_id': job_id})['data']
                if state['status'] not in ('queued', 'running'):
                    break
                time.sleep(.05)
            self.assertEqual(state['status'], 'completed', state)
            self.assertTrue((output / '_approval_input_freezes' / job_id / 'manifest.json').is_file())
            over = runtime.api.call('submit_granted_experiment', {'grant_id': granted['grant_id'],
                'request_id': str(uuid4()), 'spec_json': json.dumps(spec)})
            self.assertFalse(over['ok'])
            self.assertEqual(over['error']['code'], 'GRANT_BUDGET_EXCEEDED')
            self.assertEqual(grant_status(output, fixture.root)['used']['jobs'], 1)
        self.assertFalse((output / '_dsl_candidates' / 'registered').exists())


if __name__ == '__main__':
    unittest.main()

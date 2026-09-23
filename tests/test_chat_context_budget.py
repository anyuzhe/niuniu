"""Context budget: the default must leave room for tool results; too small fails early."""
import tempfile
import unittest
from pathlib import Path

from quantlab.agent.chat_runtime import MIN_TOOL_CONTEXT_CHARS, ChatRuntime
from quantlab.agent.model_config import ModelConfig, ModelError


class CapabilityProvider:
    def __init__(self):
        self.result = None
        self.called = False

    def run(self, system, messages, tools, dispatch, emit, stop):
        self.called = True
        self.result = dispatch('get_capabilities', {}, 'c1')
        return {'text': 'ok', 'model': 'fixture', 'provider': 'fixture', 'tool_calls': 1, 'usage': {}}


class ChatContextBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_default_budget_leaves_room_for_first_tool_result(self):
        runtime = ChatRuntime(self.root, self.root)
        cid = runtime.store.create()
        provider = CapabilityProvider()
        events = []
        runtime.send(cid, '查询能力', ModelConfig(), allow_send=True, provider=provider,
                     emit=lambda kind, value: events.append((kind, value)))
        self.assertTrue(provider.result['ok'], provider.result.get('error'))
        started = [value for kind, value in events if kind == 'turn_started'][0]
        usage = started['context_usage']
        self.assertEqual(usage['budget'], ModelConfig().max_context_chars)
        self.assertGreater(usage['tool_schema_chars'], 0)
        self.assertGreaterEqual(usage['tool_context_limit'] - usage['system_chars'], MIN_TOOL_CONTEXT_CHARS)

    def test_too_small_budget_fails_before_model_call_with_numbers(self):
        runtime = ChatRuntime(self.root, self.root)
        cid = runtime.store.create()
        provider = CapabilityProvider()
        with self.assertRaisesRegex(ModelError, '上下文预算.*提高到至少'):
            runtime.send(cid, '查询能力', ModelConfig(max_context_chars=60000), allow_send=True, provider=provider)
        self.assertFalse(provider.called)
        self.assertEqual(runtime.store.turns(cid), [])


if __name__ == '__main__':
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from quantlab.agent.playbook_tools import PlaybookResearchAPI
from quantlab.trading.paper_lifecycle import PaperLifecycleAnalytics


class PaperLifecycleContractTests(unittest.TestCase):
    def test_empty_lifecycle_read_is_side_effect_free(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);before=sorted(str(p.relative_to(root)) for p in root.rglob('*'))
            value=PaperLifecycleAnalytics(root).build()
            after=sorted(str(p.relative_to(root)) for p in root.rglob('*'))
            self.assertEqual(before,after);self.assertEqual(value['paper_executions'],0)
            self.assertEqual(value['dynamic_account_count'],0);self.assertFalse(value['automatic_real_trade'])

    def test_model_tool_catalog_has_no_paper_execution_or_intent_write(self):
        with tempfile.TemporaryDirectory() as directory:
            api=PlaybookResearchAPI(Path(directory));names={tool['name'] for tool in api.schemas()}
            forbidden={'create_paper_plan','execute_paper_plan','paper_rebalance','apply_paper_fill_intent',
                'transition_strategy_intent','run_daily_orchestrator','execute_dynamic_paper'}
            self.assertFalse(forbidden & names)
            for name in forbidden:self.assertFalse(api.call(name,{})['ok'])


if __name__=='__main__':unittest.main()

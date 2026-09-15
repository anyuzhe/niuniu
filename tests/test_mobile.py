import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from quantlab.agent.market_data_tools import MarketDataResearchAPI
from quantlab.trading.decision_store import DecisionStore
from quantlab.trading.mobile import MobileBriefService
from quantlab.trading.theme_store import ThemeStore


class MobileBriefTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.data=self.root/'data';self.data.mkdir()
        self.symbol='sh.600000';self.store=DecisionStore(self.root)
        self.decision=self.store.create(str(uuid4()),{'symbol':self.symbol,'trading_day':'2026-09-15','frame':'R1','action':'WATCH',
            'role_id':'human','theme':'银行','theme_role':'观察','ai_thesis':'手机同源判断','risk_flags':['demo']})
        ThemeStore(self.root).create(str(uuid4()),{'theme':'银行','trading_day':'2026-09-15','frame':'R1','machine_state':'START',
            'ai_state':'PREHEAT','facts':{'leader_symbol':self.symbol},'facts_source':'fixture','facts_as_of':'2026-09-15T09:35:00+08:00','source':'test'})

    def tearDown(self):self.temp.cleanup()
    def files(self):return sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*') if p.is_file())

    def test_brief_reuses_authoritative_state_without_mobile_storage(self):
        before=self.files();value=MobileBriefService(self.root,self.data).build('2026-09-15',self.symbol);after=self.files()
        self.assertEqual(before,after);self.assertEqual(value['format'],'niuniu-mobile-brief-v1')
        self.assertEqual(value['stock']['current_decision']['decision_id'],self.decision['decision_id'])
        self.assertEqual(value['candidates'][0]['decision_id'],self.decision['decision_id'])
        self.assertTrue(value['policy']['read_only']);self.assertIsNone(value['policy']['mobile_state_store'])
        self.assertIsNone(value['policy']['bot_state_store']);self.assertFalse(value['policy']['automatic_execution'])
        self.assertFalse((self.root/'_mobile').exists());self.assertFalse((self.root/'mobile.sqlite3').exists())

    def test_decisions_and_stock_are_compact_views_of_shared_ledger(self):
        service=MobileBriefService(self.root,self.data);timeline=service.decisions(self.symbol);stock=service.stock(self.symbol)
        self.assertEqual(timeline['records'][0]['decision_id'],self.decision['decision_id'])
        self.assertEqual(stock['current_decision']['decision_id'],self.decision['decision_id'])
        self.assertEqual(stock['counts']['decision_history'],1);self.assertNotIn('payload',stock['current_decision'])

    def test_empty_workspace_is_readable_without_creating_mobile_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);before=list(root.iterdir());value=MobileBriefService(root).build();after=list(root.iterdir())
            self.assertEqual(before,after);self.assertEqual(value['counts']['current_states'],0)
            self.assertEqual(value['system_health']['summary']['automatic_actions'],False)

    def test_mcp_mobile_brief_is_read_only(self):
        before=self.files();result=MarketDataResearchAPI(self.root,self.data).call('get_mobile_brief',{'trading_day':'2026-09-15','symbol':self.symbol});after=self.files()
        self.assertTrue(result['ok']);self.assertEqual(before,after)
        self.assertEqual(result['data']['stock']['current_decision']['decision_id'],self.decision['decision_id'])
        caps=MarketDataResearchAPI(self.root,self.data).call('get_capabilities',{})['data']
        self.assertTrue(caps['mobile_brief_available']);self.assertFalse(caps['mobile_brief_write_model']);self.assertFalse(caps['mobile_has_independent_state'])


if __name__=='__main__':unittest.main()

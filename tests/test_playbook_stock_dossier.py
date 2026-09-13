import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from quantlab.trading.playbook_store import PlaybookStore
from quantlab.trading.stock_dossier import StockDossier


class PlaybookStockDossierTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.store=PlaybookStore(self.root)
    def tearDown(self):self.temp.cleanup()

    def test_dossier_keeps_selected_and_unselected_playbook_history(self):
        source=self.store.create_source(str(uuid4()),{'expert_key':'expert','title':'source','source_type':'PUBLIC_POST',
            'locator':'local:x','available_at':'2024-01-01T09:00:00+08:00','content_hash':'d'*64,
            'archive_ref':'local:x','completeness':'VERIFIED'})
        definition=self.store.create_definition(str(uuid4()),{'playbook_key':'demo','name':'Demo','version':'v1',
            'state':'FROZEN','source_ids':[source['source_id']],'market_context':{},'eligibility':{'x':1},
            'selection':{'x':1},'veto':{},'entry':{},'confirm':{},'invalidation':{},'hold':{},'add':{},'reduce':{},'exit':{},'notes':''})
        case=self.store.create_case(str(uuid4()),{'definition_id':definition['definition_id'],'trading_day':'2024-01-02',
            'frame':'R1','as_of':'2024-01-02T09:35:00+08:00','source_ids':[source['source_id']],'summary':'case','notes':''})
        candidates=self.store.create_candidate_set(str(uuid4()),{'case_id':case['case_id'],'definition_id':definition['definition_id'],
            'trading_day':'2024-01-02','frame':'R1','as_of':'2024-01-02T09:35:00+08:00','completeness':'FULL',
            'pit_status':'STRICT_PIT','universe_source':'snapshot','generation_method':'frozen rule','candidates':[
                {'symbol':'sh.600000','eligibility_reasons':['eligible'],'features':{},'evidence_ids':[]},
                {'symbol':'sz.000001','eligibility_reasons':['eligible'],'features':{},'evidence_ids':[]}],
            'evidence_ids':['snapshot']})
        self.store.create_selection(str(uuid4()),{'candidate_set_id':candidates['candidate_set_id'],'kind':'OBSERVED_EXPERT',
            'selected_symbols':['sh.600000'],'ranked_symbols':[],'reasons':{},'evidence_ids':[],
            'as_of':'2024-01-02T09:36:00+08:00','notes':''})
        selected=StockDossier(self.root).get('sh.600000');unselected=StockDossier(self.root).get('sz.000001')
        self.assertEqual(selected['counts']['playbooks'],1);self.assertEqual(selected['playbooks'][0]['selected_by'],['OBSERVED_EXPERT'])
        self.assertEqual(unselected['counts']['playbooks'],1);self.assertEqual(unselected['playbooks'][0]['unselected_by'],['OBSERVED_EXPERT'])
        self.assertFalse((self.root/'_jobs').exists())


if __name__=='__main__':unittest.main()

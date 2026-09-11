import hashlib
import tempfile
import unittest
from pathlib import Path
from quantlab.agent.chat_store import ChatStore as EarlySQLiteStore
from quantlab.agent.chat_journal import ChatStore
from quantlab.agent.chat_runtime import ChatRuntime
from quantlab.agent.model_config import ModelConfig
from test_agent_chat import FakeProvider


class ChatJournalTests(unittest.TestCase):
    def test_early_sqlite_import_is_idempotent_and_source_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=EarlySQLiteStore(tmp);cid=old.create('early');tid=old.begin(cid,'question',{})
            old.event(tid,'tool_result',{'name':'fixture','result':{'ok':True}})
            old.finish(tid,'completed','answer',{'model':'fixture'})
            before=hashlib.sha256(old.path.read_bytes()).hexdigest()
            migrated=ChatStore(tmp)
            self.assertEqual(migrated.turns(cid)[0]['id'],tid)
            self.assertEqual(migrated.messages(cid,2000)[-1]['content'],'answer')
            self.assertEqual(len(migrated.events(tid)),3)
            self.assertEqual(len(ChatStore(tmp).turns(cid)),1)
            self.assertEqual(hashlib.sha256(old.path.read_bytes()).hexdigest(),before)
    def test_old_plain_conversation_remains_in_model_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=ChatRuntime(tmp);cid=r.store.create()
            r.store.append(cid,'user',{'text':'older question'})
            r.store.append(cid,'assistant',{'text':'older answer','status':'completed'})
            p=FakeProvider()
            r.send(cid,'next question',ModelConfig(),allow_send=True,provider=p)
            self.assertEqual(p.messages[0]['content'],'older question')
            self.assertEqual(p.messages[1]['content'],'older answer')
            self.assertEqual(p.messages[-1]['content'],'next question')

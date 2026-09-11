"""Unified turn view over the existing immutable conversation journal."""
import json
from uuid import UUID,uuid4
from quantlab.agent.conversations import ConversationStore
from quantlab.agent.model_config import ModelError


class ChatStore(ConversationStore):
    def __init__(self,output):
        super().__init__(output);self.locations={}
        self._import_previous_sqlite()
    def conversations(self):return self.list()
    def lease(self,cid):return self.turn_lock(cid)
    def turns(self,cid):
        result={};history=super().events(cid,2000)
        if history['omitted']:raise ModelError('会话事件过长，请新建会话；旧记录仍保留')
        for event in history['events']:
            value=event['payload'];tid=value.get('turn_id')
            if not tid:continue
            self.locations[tid]=cid
            if event['kind']=='user':
                result[tid]={'id':tid,'conversation_id':cid,'user_text':value['text'],
                    'assistant_text':'','status':'running','metadata':{'config':value.get('config',{})},
                    'created_at':event['created_at']}
            elif event['kind']=='assistant' and tid in result:
                result[tid].update(assistant_text=value['text'],status=value['status'],
                    metadata={**result[tid]['metadata'],**value.get('metadata',{})})
        return list(result.values())

    def locate(self,turn_id):
        if not isinstance(turn_id,str) or str(UUID(turn_id))!=turn_id:
            raise ModelError('无效对话轮次')
        if turn_id not in self.locations:
            for item in self.list(500):self.turns(item['id'])
        if turn_id not in self.locations:raise ModelError('对话轮次不存在')
        return self.locations[turn_id]

    def begin(self,conversation_id,text,config):
        for previous in self.turns(conversation_id):
            if previous['status']=='running':
                self.finish(previous['id'],'interrupted','',{'error':'上一进程未完成'})
        turn_id=str(uuid4());self.locations[turn_id]=conversation_id
        self.append(conversation_id,'user',{'text':text,'turn_id':turn_id,'config':config})
        return turn_id

    def event(self,turn_id,kind,payload):
        mapped={'tool_call':'tool_start','connection':'model'}.get(kind,kind)
        if mapped not in ('tool_start','tool_result','model'):mapped='state'
        if mapped=='state':payload={'status':'running',**payload}
        self.append(self.locate(turn_id),mapped,{**payload,'turn_id':turn_id,'event_kind':kind})

    def finish(self,turn_id,status,text,metadata):
        if status not in ('completed','failed','stopped','interrupted'):
            raise ValueError('无效结束状态')
        cid=self.locate(turn_id)
        self.append(cid,'assistant',{'text':text,'status':status,'turn_id':turn_id,
            'model':metadata.get('model',''),'metadata':metadata})
        self.append(cid,'state',{'turn_id':turn_id,'status':'cancelled' if status=='stopped' else status,
            'error':metadata.get('error','')})

    def events(self,identifier,limit=500):
        if not isinstance(identifier,str) or str(UUID(identifier))!=identifier:
            raise ModelError('无效会话或轮次编号')
        if (self.root/identifier/'meta.json').is_file():return super().events(identifier,limit)
        cid=self.locate(identifier)
        return [{'kind':e['payload'].get('event_kind',e['kind']),'payload':e['payload'],'created_at':e['created_at']}
            for e in super().events(cid,2000)['events'] if e['payload'].get('turn_id')==identifier]

    def _import_previous_sqlite(self):
        """Preserve early P1B test conversations; leave their original DB untouched."""
        import sqlite3
        from contextlib import closing
        source=self.root.parent/'chat.sqlite3';marker=self.root/'sqlite-imported.json'
        if not source.is_file() or marker.exists():return
        if source.is_symlink():raise ModelError('旧会话数据库不能是符号链接')
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            conversations=[dict(row) for row in db.execute('SELECT * FROM conversations ORDER BY created_at')]
            turns=[dict(row) for row in db.execute('SELECT * FROM turns ORDER BY created_at')]
            events=[dict(row) for row in db.execute('SELECT * FROM chat_events ORDER BY seq')]
        imported=[]
        for conversation in conversations:
            cid=conversation['id']
            if str(UUID(cid))!=cid:raise ModelError('旧会话编号无效')
            folder=self.root/cid
            if folder.exists():continue
            staging=self.root/('.import-'+cid);staging.mkdir(exist_ok=True)
            meta={k:conversation[k] for k in ('id','title','created_at')}
            if not (staging/'meta.json').exists():self.write(staging/'meta.json',meta)
            records=[]
            for turn in [t for t in turns if t['conversation_id']==cid]:
                tid=turn['id'];metadata=json.loads(turn['metadata'])
                records.append(('user',{'text':turn['user_text'],'turn_id':tid,
                    'config':metadata.get('config',{})},turn['created_at']))
                for event in [e for e in events if e['turn_id']==tid]:
                    kind=event['kind'];mapped={'tool_call':'tool_start','connection':'model'}.get(kind,kind)
                    if mapped not in ('tool_start','tool_result','model'):mapped='state'
                    records.append((mapped,{**json.loads(event['payload']),'turn_id':tid,'event_kind':kind},event['created_at']))
                records.append(('assistant',{'text':turn['assistant_text'],'turn_id':tid,
                    'status':turn['status'],'metadata':metadata,'model':metadata.get('model','')},turn['created_at']))
            for index,(kind,payload,created_at) in enumerate(records):
                path=staging/(str(index).zfill(20)+'-sqlite.json')
                value={'kind':kind,'payload':payload,'created_at':created_at}
                if path.exists():
                    if self.read(path)!=value:raise ModelError('会话迁移记录发生冲突')
                else:self.write(path,value)
            staging.rename(folder);imported.append(cid)
        self.write(marker,{'imported_conversations':imported,'source_preserved':True})

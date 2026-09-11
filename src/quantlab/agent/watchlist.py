"""Manual, approval-backed factor watches; no hidden scheduling or trading."""
from copy import deepcopy
from datetime import datetime, date
from pathlib import Path
from uuid import uuid4
import polars as pl
from quantlab.agent.watch_store import WatchStore, now
from quantlab.agent.tracking_preview import tracking_preview, tracking_fingerprint
from quantlab.storage.artifact_integrity import snapshot_tree
from quantlab.storage.codec import digest
from quantlab.experiments.runner import runtime_fingerprint
from quantlab.storage.experiments import load_record_fields
from quantlab.workbench.server import ArtifactCatalog


def rule_identity(record):
    manifest = record['manifest']; config = deepcopy(manifest['config'])
    for key in ('research_question','replay','sequence_audit'): config.pop(key,None)
    config['data'].pop('end')
    return {'config':config,'factor_code_hash':manifest['factor_code_hash'],
        'factor_definition':manifest['factor'],
        'adjustment':manifest['data_snapshot']['adjustment'],
        'provider':manifest['data_snapshot']['source'],
        'source_runtime':manifest['runtime'],
        'universe':{k:manifest['universe'].get(k) for k in ('id','version')}}


class WatchService:
    def __init__(self, output, data_root=None):
        self.output = Path(output).resolve(); self.data_root = data_root
        self.catalog = ArtifactCatalog(self.output); self.store = WatchStore(self.output)
    def capture(self, run_id, as_of, windows, min_dates):
        tree = snapshot_tree(self.output,run_id)
        record = load_record_fields(self.catalog.file(run_id,'experiment.json'),
            {'run_id','kind','status','manifest'})
        if record['status'] != 'completed' or record.get('kind','factor') != 'factor':
            raise ValueError('A watch requires a completed factor archive')
        if as_of is None:
            stamp = pl.scan_parquet(self.catalog.file(run_id,'bars.parquet')).select(
                pl.col('available_at').max()).collect().item()
            if stamp is None: raise ValueError('No source bars')
            as_of = stamp.isoformat()
        preview = tracking_preview(self.output,run_id,as_of,windows,min_dates)
        if preview['source_fingerprint'] != digest(tree):
            raise ValueError('Source changed while preparing watch evidence')
        return record, preview
    def create(self, name, run_id, *, windows=(20,60,120), min_dates=20, watch_id=None):
        if not isinstance(name,str) or not name.strip() or len(name)>120:
            raise ValueError('Watch name must contain 1–120 characters')
        watch_id = watch_id or str(uuid4())
        record, result = self.capture(run_id,None,windows,min_dates)
        definition = {'version':1,'watch_id':watch_id,'name':name.strip(),
            'base_run_id':run_id,'rule':rule_identity(record),'windows':list(windows),
            'min_dates':min_dates,'base_fingerprint':result['source_fingerprint'],
            'tracking_algorithm':result['tracking_source_hash'],
            'scope':'Fixed rule and start date, human-approved refresh, descriptive gross metrics only'}
        self.store.initialize(watch_id,definition)
        _, existing = self.store.read(watch_id)
        if existing['history']:
            return {'watch_id':watch_id,'snapshot':self.store.snapshot(watch_id,existing['history'][0]),
                'created':False,'new_research_jobs':0}
        return self.observe(watch_id,run_id,result['as_of'])
    def observe(self, watch_id, run_id, as_of=None):
        definition, state = self.store.read(watch_id)
        if not state['active']: raise ValueError('Watch is paused')
        record, result = self.capture(run_id,as_of,definition['windows'],definition['min_dates'])
        if result['tracking_source_hash'] != definition['tracking_algorithm']:
            raise ValueError('Tracking algorithm changed; create a new watch instead of mixing versions')
        if rule_identity(record) != definition['rule']:
            raise ValueError('Factor, parameters, universe, start date or price convention changed; create a new watch')
        latest = state['history'][-1] if state['history'] else None
        previous = self.store.snapshot(watch_id,latest) if latest else None
        change = {'kind':'baseline','historical_revision':False}; alerts = []
        if previous:
            if digest(snapshot_tree(self.output,previous['source_run_id'])) != previous['preview']['source_fingerprint']:
                raise ValueError('Previous monitoring source changed or is unavailable')
            old = previous['preview']
            if datetime.fromisoformat(result['as_of']) < datetime.fromisoformat(old['as_of']):
                raise ValueError('Monitoring cutoff cannot move backwards')
            _, overlap = self.capture(run_id,old['as_of'],definition['windows'],definition['min_dates'])
            revised = any(overlap[k] != old[k] for k in ('input_bar_hash','input_factor_hash'))
            advanced = result['watermarks'] != old['watermarks']
            change = {'kind':'historical_revision' if revised else 'advanced' if advanced else 'no_new_data',
                'historical_revision':revised,'previous_snapshot_id':latest,
                'known_bars_delta':result['bars']-old['bars']}
            if revised: alerts.append({'kind':'historical_input_revision','severity':'review'})
        baseline = self.store.snapshot(watch_id,state['history'][0])['preview'] if state['history'] else result
        differences = {}
        for window, item in result['windows'].items():
            differences[window] = {}
            if item['missing_or_ineligible']:
                alerts.append({'kind':'missing_or_ineligible','window':window,
                    'count':item['missing_or_ineligible'],'severity':'data_notice'})
            for horizon, value in item['horizons'].items():
                old_value = baseline['windows'][window]['horizons'][horizon]
                a = value['metrics']['rank_ic']; b = old_value['metrics']['rank_ic']
                enough = value['status']=='computed' and old_value['status']=='computed'
                differences[window][horizon] = {'rank_ic_difference':a-b if enough and a is not None and b is not None else None,
                    'status':'descriptive' if enough else 'insufficient_mature_dates'}
                if not enough:
                    alerts.append({'kind':'insufficient_mature_dates','window':window,
                        'horizon':horizon,'severity':'sample_notice'})
        key = digest({'watch_id':watch_id,'source':result['source_fingerprint'],
            'as_of':result['as_of'],'algorithm':result['tracking_source_hash']})
        value = {'snapshot_id':key,'watch_id':watch_id,'created_at':now(),
            'previous_snapshot_id':latest,'source_run_id':run_id,'preview':result,
            'change':change,'baseline_differences':differences,'alerts':alerts,
            'limitations':['Persistent manual monitoring, not scheduled execution or investment approval.',
                'Window differences are descriptive, not decay significance or sequential tests.',
                'Missing/ineligible observations are combined; no complete exchange calendar is inferred.']}
        saved, created = self.store.publish(watch_id,value,latest)
        return {'watch_id':watch_id,'snapshot':saved,'created':created,'new_research_jobs':0}
    def get(self, watch_id):
        definition, state = self.store.read(watch_id)
        latest = self.store.snapshot(watch_id,state['history'][-1]) if state['history'] else None
        integrity = 'not_started'
        if latest:
            try:
                current = digest(snapshot_tree(self.output,latest['source_run_id']))
                integrity = 'verified' if current==latest['preview']['source_fingerprint'] else 'source_changed'
            except (OSError,ValueError,KeyError,TypeError): integrity = 'unavailable'
        history = [self.store.snapshot(watch_id,key) for key in state['history'][-20:]]
        return {'definition':definition,'active':state['active'],'latest':latest,
            'source_integrity':integrity,'snapshot_count':len(state['history']),
            'history':[{'snapshot_id':r['snapshot_id'],'source_run_id':r['source_run_id'],
                'as_of':r['preview']['as_of'],'change':r['change']['kind']} for r in history],
            'history_omitted':max(0,len(state['history'])-20),
            'refresh_requests':state['refresh_requests'][-20:],
            'automatic_tracking':False,'claim_verified':False}
    def propose_refresh(self, watch_id, end, request_id):
        from quantlab.agent.proposals import ProposalService
        if self.data_root is None: raise ValueError('A data directory is required for refresh proposals')
        if self.store.read(watch_id)[0]['rule']['source_runtime'] != runtime_fingerprint():
            raise ValueError('Baseline source runtime differs; recompute a baseline with current code and create a new watch')
        if self.store.read(watch_id)[0]['tracking_algorithm'] != tracking_fingerprint():
            raise ValueError('Tracking algorithm changed; create a new watch')
        definition, state = self.store.read(watch_id)
        if not state['active']: raise ValueError('Watch is paused')
        current = self.store.snapshot(watch_id,state['history'][-1]) if state['history'] else None
        run_id = current['source_run_id'] if current else definition['base_run_id']
        if current and digest(snapshot_tree(self.output,run_id)) != current['preview']['source_fingerprint']:
            raise ValueError('Refresh source archive has changed')
        record = load_record_fields(self.catalog.file(run_id,'experiment.json'),{'manifest'})
        cfg = deepcopy(record['manifest']['config'])
        if rule_identity(record) != definition['rule']: raise ValueError('Watch source rule changed')
        if record['manifest']['universe']['id']!='explicit_symbols' or cfg.get('theory_origin'):
            raise ValueError('Automatic proposal construction currently requires explicit symbols and a registered factor; attach other compatible results manually')
        if date.fromisoformat(end) < date.fromisoformat(cfg['data']['end']):
            raise ValueError('Refresh end cannot shorten the saved research interval')
        names = {'research_question':'question','factor_id':'factor',
                 'factor_version':'version','random_seed':'seed'}
        spec = {names.get(k,k):v for k,v in cfg.items()
                if k not in ('data','theory_origin') and v is not None}
        spec.update(cfg['data']); spec.update(end=end,mode='single',replay=True,
            question=definition['name']+' · 人工刷新',
            adjustment=record['manifest']['data_snapshot']['adjustment'])
        proposal = ProposalService(self.output,self.data_root).propose(request_id,spec)
        self.store.add_request(watch_id,{'proposal_id':proposal['proposal_id'],
            'job_id':proposal['job_id'],'end':end})
        return proposal
    def sync_refresh(self, watch_id, proposal_id):
        from quantlab.agent.catalog import ReadOnlyResearchAPI
        from quantlab.agent.proposal_store import ProposalStore
        _, state = self.store.read(watch_id)
        request = next((r for r in state['refresh_requests'] if r['proposal_id']==proposal_id),None)
        if request is None: raise ValueError('Proposal does not belong to this watch')
        proposal = ProposalStore(self.output).get(proposal_id)
        if proposal['status']!='submitted' or proposal['job_id']!=request['job_id']:
            raise ValueError('Refresh proposal has not been submitted')
        result = ReadOnlyResearchAPI(self.output).call('get_job',{'job_id':request['job_id']})
        if not result['ok'] or result['data'].get('status')!='completed':
            raise ValueError('Refresh research is not completed; no monitoring snapshot created')
        return self.observe(watch_id,result['data']['run_id'])

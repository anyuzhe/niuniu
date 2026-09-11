"""Host-approved full-history batch rollover; immutable imports are never edited."""
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID, uuid4
import fcntl
import hashlib
import json
import polars as pl
from quantlab.data.baostock_ingest import load_import
from quantlab.data.baostock_dataset import dataset_manifest, read_table, read_dataset_bytes, responses
from quantlab.data.baostock_provider import BaostockSnapshotProvider
from quantlab.data.base import DataRequest, DataBatch, DataSnapshot
from quantlab.domain import Timeframe
from quantlab.experiments.campaign_state import read_checked, write_checked
from quantlab.storage.codec import digest

MARKER = 'baostock-series.json'


def canonical_id(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Invalid series UUID')
    return value


def delivery(output, import_id):
    directory, receipt = load_import(output, import_id)
    if receipt.get('status') not in ('completed', 'completed_with_errors') or not receipt.get('dataset_ready'):
        raise ValueError('Only completed, usable import batches can enter a series')
    receipt_bytes=(directory/'manifest.json').read_bytes()
    if json.loads(receipt_bytes)!=receipt: raise ValueError('Import receipt changed during audit')
    dataset = directory/'dataset'; manifest, provenance = dataset_manifest(dataset)
    if not manifest['ready'] or not manifest['calendar_ready']:
        raise ValueError('A complete trading calendar and normalized bars are required')
    if manifest['plan'] != receipt['plan'] or manifest['import_id'] != import_id:
        raise ValueError('Import and dataset plans differ')
    if manifest['source_response_hashes'] != [r['sha256'] for r in receipt['responses']]:
        raise ValueError('Dataset source responses differ from the import receipt')
    for _ in responses(directory, receipt): pass
    for relative in manifest['files']: read_dataset_bytes(dataset, relative, manifest)
    plan = manifest['plan']; start = date.fromisoformat(plan['start']); end = date.fromisoformat(plan['end'])
    calendar = read_table(dataset, 'calendar').select('calendar_date', 'is_trading_day').sort('calendar_date')
    expected = [str(start+timedelta(days=i)) for i in range((end-start).days+1)]
    if calendar['calendar_date'].to_list() != expected or any(v not in ('0','1') for v in calendar['is_trading_day']):
        raise ValueError('Calendar has missing or duplicate dates or unknown trading flags')
    sessions = calendar.filter(pl.col('is_trading_day') == '1')['calendar_date'].to_list()
    if not sessions: raise ValueError('No trading sessions in the import')
    request = DataRequest(tuple(plan['symbols']), Timeframe.DAILY, start, end)
    modes = ['raw', 'qfq'] if 'daily_qfq' in plan['datasets'] else ['raw']
    frames = {}
    for mode in modes:
        bars = BaostockSnapshotProvider(dataset, mode).load(request).bars
        if bars.height > 250000: raise ValueError('Series audit exceeds 250000 bars per price mode')
        for symbol in request.symbols:
            actual = bars.filter(pl.col('symbol') == symbol)['datetime'].dt.date().cast(pl.String).to_list()
            if actual != sessions:
                raise ValueError('Unexplained daily gap or non-session bar: '+symbol+'; no suspension or IPO is inferred')
        frames[mode] = bars
    if (directory/'manifest.json').read_bytes()!=receipt_bytes or dataset_manifest(dataset)[1]!=provenance:
        raise ValueError('Source metadata changed during the delivery audit')
    token = {'import_id':import_id, 'dataset_checksum':manifest['checksum'],
        'receipt_sha256':hashlib.sha256(receipt_bytes).hexdigest(),
        'symbols':sorted(plan['symbols']), 'start':plan['start'], 'end':plan['end'], 'modes':modes}
    return token, frames, calendar


def read_series(root):
    root = Path(root).absolute()
    if root.parent.name != 'baostock_series' or root.parent.parent.name != '_market_data':
        raise ValueError('Series must belong to a workspace managed-data directory')
    canonical_id(root.name)
    if any(p.is_symlink() for p in (root, root.parent, root.parent.parent, root/MARKER)):
        raise ValueError('Series paths cannot contain symlinks')
    if (root/MARKER).stat().st_size > 2_000_000: raise ValueError('Series history exceeds budget')
    state = read_checked(root/MARKER)
    if state.get('format') != 'baostock-series-v1' or state.get('series_id') != root.name:
        raise ValueError('Invalid series marker identity')
    history = state['history']
    if not history or len(history) > 500 or state['generation'] != len(history):
        raise ValueError('Invalid series history')
    for i, entry in enumerate(history):
        previous = history[i-1]['publication_id'] if i else None
        if entry['previous'] != previous or entry['publication_id'] != digest({k:v for k,v in entry.items() if k!='publication_id'}):
            raise ValueError('Invalid series publication chain')
    return state

class SeriesService:
    def __init__(self, output):
        self.output = Path(output).resolve()
        if not self.output.is_dir(): raise ValueError('Series workspace is missing')
        self.root = self.output/'_market_data'/'baostock_series'
    def folder(self, series_id):
        folder = self.root/canonical_id(series_id)
        if any(p.is_symlink() for p in (self.root.parent, self.root, folder)):
            raise ValueError('Series directory symlink')
        return folder
    @contextmanager
    def locked(self, series_id):
        folder = self.folder(series_id); folder.mkdir(parents=True, exist_ok=True)
        path = folder/'series.lock'
        if path.is_symlink(): raise ValueError('Series lock symlink')
        with path.open('a+b') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX|fcntl.LOCK_NB)
            try: yield folder
            finally: fcntl.flock(stream, fcntl.LOCK_UN)
    def get(self, series_id): return read_series(self.folder(series_id))
    def list(self):
        if self.root.is_symlink() or self.root.parent.is_symlink(): raise ValueError('Series directory symlink')
        rows = []; errors = []
        for folder in sorted(self.root.iterdir()) if self.root.exists() else []:
            try:
                s = self.get(folder.name); rows.append({'series_id':s['series_id'], 'name':s['name'],
                    'generation':s['generation'], 'current':s['history'][-1]['delivery']})
            except (OSError, ValueError, KeyError, TypeError) as error:
                errors.append({'entry':folder.name, 'error':str(error)[:200]})
        return {'series':rows, 'errors':errors}
    @staticmethod
    def publication(previous, token, audit, plan_digest):
        from datetime import datetime, timezone
        entry = {'previous':previous, 'delivery':token, 'audit':audit,
            'plan_digest':plan_digest, 'accepted_at':datetime.now(timezone.utc).isoformat()}
        return {**entry, 'publication_id':digest(entry)}
    def create(self, name, import_id, *, confirmed=False, series_id=None):
        if confirmed is not True: raise ValueError('Host confirmation is required')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            raise ValueError('Series name must contain 1–120 characters')
        series_id = series_id or str(uuid4()); token, frames, _ = delivery(self.output, import_id)
        with self.locked(series_id) as folder:
            if (folder/MARKER).exists():
                old = self.get(series_id)
                if old['name'] != name.strip() or old['history'][0]['delivery'] != token:
                    raise ValueError('Existing series has a different origin')
                return old
            entry = self.publication(None, token, {'kind':'baseline'}, None)
            state = {'format':'baostock-series-v1', 'series_id':series_id, 'name':name.strip(),
                'generation':1, 'history':[entry], 'network_download':False,
                'policy':'Explicit host-approved full-history batches; no implicit selection, merge, filling, or research approval.'}
            write_checked(folder/MARKER, state)
            return state
    def preview(self, series_id, import_id):
        state = self.get(series_id); prior = state['history'][-1]
        before, old_frames, old_calendar = delivery(self.output, prior['delivery']['import_id'])
        if before != prior['delivery']: raise ValueError('Previously accepted batch has changed')
        incoming, new_frames, calendar = delivery(self.output, import_id)
        if import_id == before['import_id']: raise ValueError('This batch is already current')
        for key in ('symbols', 'start', 'modes'):
            if before[key] != incoming[key]: raise ValueError('Series contract changed: '+key)
        if incoming['end'] < before['end']: raise ValueError('Series cutoff cannot move backwards')
        if not old_calendar.equals(calendar.filter(pl.col('calendar_date') <= before['end'])):
            raise ValueError('Historical trading calendar changed; use a new series')
        comparisons = {}; keys = ['symbol', 'datetime']
        for mode, old in old_frames.items():
            new = new_frames[mode]
            if old.schema != new.schema: raise ValueError('Normalized schema changed')
            if old.join(new.select(keys), on=keys, how='anti').height:
                raise ValueError('Incoming batch removed historical bars')
            common = old.join(new, on=keys, how='inner', suffix='__new', validate='1:1')
            fields = [c for c in old.columns if c not in keys]
            changed = common.filter(~pl.all_horizontal([pl.col(c).eq_missing(pl.col(c+'__new')) for c in fields]))
            added = new.join(old.select(keys), on=keys, how='anti')
            comparisons[mode] = {'previous_rows':old.height, 'incoming_rows':new.height,
                'added_rows':added.height, 'revised_rows':changed.height,
                'revised_examples':changed.select('symbol', pl.col('datetime').cast(pl.String)).head(10).to_dicts()}
        if self.get(series_id) != state: raise ValueError('Series changed during preview')
        return {'format':'baostock-rollover-plan-v1', 'series_id':series_id,
            'previous_publication_id':prior['publication_id'], 'incoming':incoming,
            'comparisons':comparisons, 'revisions_require_confirmation':any(r['revised_rows'] for r in comparisons.values()),
            'limitations':['人工接入完整历史批次，不下载、不批准或启动研究。',
                '缺日不解释为停牌或未上市；需取得实际完整日线后才能接入。',
                '历史复权/估值修订保留旧批次；确认修订不是严格PIT或正确性认证。']}
    def accept(self, plan, expected_digest, *, confirmed=False, accept_revisions=False):
        if confirmed is not True or type(accept_revisions) is not bool:
            raise ValueError('Explicit host confirmation is required')
        if digest(plan) != expected_digest: raise ValueError('Rollover plan digest changed')
        series_id = canonical_id(plan['series_id'])
        with self.locked(series_id) as folder:
            state = self.get(series_id)
            existing = next((p for p in state['history'] if p['plan_digest'] == expected_digest), None)
            if existing is not None:
                return {'series_id':series_id, 'generation':state['generation'], 'created':False, 'publication':existing}
            current = self.preview(series_id, plan['incoming']['import_id'])
            if current != plan: raise ValueError('Stale rollover preview; inspect the current batch again')
            if plan['revisions_require_confirmation'] and not accept_revisions:
                raise ValueError('Historical revisions require a separate confirmation')
            if len(state['history']) >= 500: raise ValueError('Series has reached the 500-publication budget')
            entry = self.publication(plan['previous_publication_id'], plan['incoming'],
                {'comparisons':plan['comparisons'], 'revisions_accepted':accept_revisions}, expected_digest)
            state['history'].append(entry); state['generation'] += 1
            write_checked(folder/MARKER, state)
            return {'series_id':series_id, 'generation':state['generation'], 'created':True, 'publication':entry}

class BaostockSeriesProvider:
    """Resolve once per load; exact publication identity enters frozen research inputs."""
    def __init__(self, root, adjustment='qfq'):
        self.root = Path(root).absolute(); self.adjustment = adjustment
        if adjustment not in ('raw', 'qfq'): raise ValueError('Unknown price adjustment')
    def load(self, request):
        state = read_series(self.root); current = state['history'][-1]; token = current['delivery']
        output = self.root.parents[2]
        directory, receipt = load_import(output, token['import_id'])
        dataset = directory/'dataset'; manifest, _ = dataset_manifest(dataset)
        if receipt.get('status') not in ('completed', 'completed_with_errors') or not receipt.get('dataset_ready'):
            raise ValueError('Accepted batch is no longer usable')
        if manifest['checksum'] != token['dataset_checksum'] or hashlib.sha256((directory/'manifest.json').read_bytes()).hexdigest() != token['receipt_sha256']:
            raise ValueError('Accepted batch metadata changed')
        if self.adjustment not in token['modes']: raise ValueError('Series has no requested price mode')
        if not set(request.symbols) <= set(token['symbols']) or str(request.start) < token['start'] or str(request.end) > token['end']:
            raise ValueError('Requested interval is outside the current accepted batch')
        batch = BaostockSnapshotProvider(dataset, self.adjustment).load(request)
        if read_series(self.root) != state: raise ValueError('Series publication changed during loading')
        evidence = {'series_id':state['series_id'], 'generation':state['generation'],
            'publication_id':current['publication_id'], 'import_id':token['import_id'],
            'series_state_hash':digest(state), 'policy':'Host-approved immutable batch; retrospective, not certified PIT.'}
        identity = digest({'batch':batch.snapshot.snapshot_id, 'series':evidence})
        return DataBatch(batch.bars, DataSnapshot(identity, batch.snapshot.source,
            self.adjustment, (*batch.snapshot.files, evidence)))

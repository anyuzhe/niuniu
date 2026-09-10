"""Content-addressed factor artifacts, with verified bytes and atomic publication.

No fitted processors or universe masks are cached here. Raw inputs and the full
research source fingerprint participate in identity; a revision is a cache miss.
"""
import hashlib
import io
import json
import shutil
import tempfile
from pathlib import Path

import polars as pl

from quantlab.storage.codec import digest, encode


class FactorCache:
    def __init__(self, root, code_hash):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.code_hash=code_hash;self.hits=0;self.misses=0

    def key(self, identity, bars):
        # IPC buffers can differ after Parquet decoding despite equal values.
        # Canonical logical JSON plus schema makes identity independent of buffers.
        return digest({'identity':identity,'code':self.code_hash,'schema':str(bars.schema),
            'input_sha256':hashlib.sha256(bars.write_json().encode()).hexdigest()})

    def get(self, key):
        path=self.root/key
        try:
            if path.is_symlink():raise ValueError('Cache symlink')
            manifest=json.loads((path/'manifest.json').read_text())
            payloads={name:(path/name).read_bytes() for name in ('values.parquet','events.json')}
            if any(hashlib.sha256(payloads[k]).hexdigest()!=manifest[k] for k in payloads):
                raise ValueError('Cache checksum mismatch')
            result=(pl.read_parquet(io.BytesIO(payloads['values.parquet'])),json.loads(payloads['events.json']))
        except (OSError,ValueError,KeyError,TypeError,pl.exceptions.PolarsError):
            self.misses+=1;return None
        self.hits+=1;return result

    def put(self, key, values, events=()):
        staging=Path(tempfile.mkdtemp(prefix='.pending-',dir=self.root))
        try:
            values.write_parquet(staging/'values.parquet')
            (staging/'events.json').write_text(encode(events))
            manifest={name:hashlib.sha256((staging/name).read_bytes()).hexdigest()
                for name in ('values.parquet','events.json')}
            (staging/'manifest.json').write_text(json.dumps(manifest))
            destination=self.root/key
            if destination.exists():
                # A corrupt entry must not permanently disable caching.
                if self.get(key) is None:shutil.rmtree(destination)
                else:return
            try:staging.rename(destination)
            except FileExistsError:pass  # Another identical computation won.
        finally:
            if staging.exists():shutil.rmtree(staging)

    def compute(self, factor, bars, parameters, calculate):
        key=self.key({'factor':factor.definition.factor_id,'version':factor.definition.version,
            'definition':factor.definition,'parameters':parameters},bars)
        cached=self.get(key)
        if cached is not None:return cached[0]
        values=calculate();self.put(key,values);return values

    def compute_classic(self,identity,bars):
        """Resume the pinned recursive engine after an authenticated exact prefix."""
        from quantlab.adapters.chan_classic import ClassicChanState
        from quantlab.adapters.chan_state import load_state
        family='continuation-'+self._prefix_family(identity,bars)
        state=None
        try:
            old=(self.root/family).read_text()
            if len(old)!=64 or any(c not in '0123456789abcdef' for c in old):raise ValueError('Invalid state key')
            folder=self.root/('state-'+old)
            if folder.is_symlink():raise ValueError('State symlink')
            metadata=json.loads((folder/'manifest.json').read_text())
            data=(folder/'input.parquet').read_bytes();payload=(folder/'state.json').read_bytes()
            if metadata!={'input_sha256':hashlib.sha256(data).hexdigest(),'state_sha256':hashlib.sha256(payload).hexdigest()}:raise ValueError('State checksum mismatch')
            prefix=pl.read_parquet(io.BytesIO(data))
            if prefix.height>bars.height or self.key(identity,prefix)!=old or not prefix.equals(bars.head(prefix.height)):raise ValueError('Changed historical prefix')
            candidate=load_state(json.loads(payload))
            if len(candidate.rows)!=prefix.height or len(candidate.matrix)!=prefix.height or candidate.symbol!=bars['symbol'][0] or candidate.timeframe.value!=bars['timeframe'][0]:raise ValueError('State/input mismatch')
            state=candidate
        except (OSError,ValueError,KeyError,TypeError,AttributeError,ImportError,pl.exceptions.PolarsError):pass
        if state is None:state=ClassicChanState(bars['symbol'][0],bars['timeframe'][0])
        self.classic_resumed_bars=getattr(self,'classic_resumed_bars',0)+len(state.rows)
        start=len(state.rows)
        for offset in range(start,bars.height,512):
            stop=min(offset+512,bars.height);state.extend(bars.slice(offset,stop-offset))
            self._save_classic_state(identity,bars.head(stop),state,family)
        return pl.DataFrame(state.matrix),state.events

    def _save_classic_state(self,identity,bars,state,family):
        from quantlab.adapters.chan_state import dump_state
        key=self.key(identity,bars);destination=self.root/('state-'+key)
        staging=Path(tempfile.mkdtemp(prefix='.state-pending-',dir=self.root))
        try:
            bars.write_parquet(staging/'input.parquet')
            (staging/'state.json').write_text(json.dumps(dump_state(state),ensure_ascii=False,separators=(',',':')))
            metadata={name+'_sha256':hashlib.sha256((staging/file).read_bytes()).hexdigest() for name,file in [('input','input.parquet'),('state','state.json')]}
            (staging/'manifest.json').write_text(json.dumps(metadata))
            if destination.exists():
                # All payloads are derived; replace only this identical-prefix state.
                if destination.is_symlink():raise ValueError('State symlink')
                shutil.rmtree(destination)
            staging.rename(destination)
            with tempfile.NamedTemporaryFile(mode='w',dir=self.root,delete=False) as stream:stream.write(key);temporary=Path(stream.name)
            try:temporary.replace(self.root/family)
            finally:temporary.unlink(missing_ok=True)
        finally:
            if staging.exists():shutil.rmtree(staging)

    def get_prefix(self, identity, bars):
        """Only for certified causal algorithms: verify the entire exact prefix.

        An earlier start, revised history or different symbol/timeframe is a miss.
        This does not resume an opaque recursive engine from an arbitrary suffix.
        """
        family=self._prefix_family(identity,bars)
        try:
            key=(self.root/family).read_text()
            if len(key)!=64 or any(c not in '0123456789abcdef' for c in key):return None
            source=pl.read_parquet(self.root/key/'input.parquet')
            if source.height<bars.height or self.key(identity,source)!=key or not source.head(bars.height).equals(bars):return None
            saved=self.get(key)
            if saved is None:return None
            values,events=saved;cut=bars['available_at'].max()
            from datetime import datetime
            return values.head(bars.height),[e for e in events if datetime.fromisoformat(e['available_at'])<=cut]
        except (OSError,ValueError,KeyError,TypeError,pl.exceptions.PolarsError):return None

    def _prefix_family(self,identity,bars):
        return 'prefix-'+digest({'identity':identity,'code':self.code_hash,'symbol':bars['symbol'][0],
            'timeframe':bars['timeframe'][0],'start':bars['datetime'][0]})

    def publish_prefix(self,identity,bars,key):
        family=self._prefix_family(identity,bars)
        destination=self.root/family
        try:
            old=destination.read_text()
            if len(old)==64 and all(c in '0123456789abcdef' for c in old):
                source=pl.read_parquet(self.root/old/'input.parquet')
                if source.height>bars.height and source.head(bars.height).equals(bars) and self.key(identity,source)==old:return
        except (OSError,ValueError,pl.exceptions.PolarsError):pass
        path=self.root/key/'input.parquet'
        # Content is authenticated by recomputing the content-addressed key.
        with tempfile.NamedTemporaryFile(dir=path.parent,suffix='.parquet',delete=False) as f:temporary=Path(f.name)
        try:bars.write_parquet(temporary);temporary.replace(path)
        finally:temporary.unlink(missing_ok=True)
        with tempfile.NamedTemporaryFile(mode='w',dir=self.root,delete=False) as f:f.write(key);temporary=Path(f.name)
        try:temporary.replace(destination)
        finally:temporary.unlink(missing_ok=True)

"""Optional verified dataset provider; the original MQC adapter stays unchanged."""
from datetime import time
from pathlib import Path
import io
import polars as pl
from quantlab.data.base import DataBatch,DataSnapshot
from quantlab.data.mqc import MQCParquetProvider
from quantlab.data.baostock_dataset import dataset_manifest,check_dataset_file,read_dataset_bytes
from quantlab.domain import Timeframe
from quantlab.storage.codec import digest


class BaostockSnapshotProvider:
    def __init__(self,root,adjustment='qfq'):
        self.root=Path(root).resolve();self.adjustment=adjustment
        self.base=MQCParquetProvider(self.root,adjustment)
    def load(self,request):
        if request.timeframe!=Timeframe.DAILY:raise ValueError('本批管理数据集只提供真实日线，不合成分钟数据')
        manifest,provenance=dataset_manifest(self.root)
        if not manifest['ready']:raise ValueError('本批行情未通过标准化验收')
        suffix='lake/bronze/provider=baostock/stock_kline_daily/' if self.adjustment=='raw' else 'lake/silver/qfq_kline_daily/'
        for symbol in request.symbols:
            read_dataset_bytes(self.root,suffix+symbol.replace('.','_')+'.parquet',manifest)
        base=self.base.load(request);parts=[]
        for entry in base.snapshot.files:
            path=Path(entry['path']);payload=read_dataset_bytes(self.root,path.relative_to(self.root).as_posix(),manifest)
            check_dataset_file(self.root,path,payload,manifest)
            if entry['sha256']!=manifest['files'][path.relative_to(self.root).as_posix()]['sha256']:
                raise ValueError('行情在读取期间变化')
            frame=pl.read_parquet(io.BytesIO(payload))
            timestamp=pl.col('date').dt.combine(time(15)).dt.replace_time_zone('Asia/Shanghai')
            frame=frame.filter(pl.col('date').is_between(request.start,request.end))
            parts.append(frame.select(pl.col('code').alias('symbol'),timestamp.alias('datetime'),
                *[pl.col(v).cast(pl.Float64) for v in manifest['features'].values()]))
        features=pl.concat(parts).sort('symbol','datetime')
        bars=base.bars.join(features,on=['symbol','datetime'],how='left',validate='1:1')
        identity={'base':base.snapshot.snapshot_id,'provenance':provenance,
            'feature_policy':'Unlagged provider values; research must explicitly apply an information-time lag.'}
        snapshot=DataSnapshot(digest(identity),'baostock_managed_snapshot',self.adjustment,
            (*base.snapshot.files,provenance))
        return DataBatch(bars,snapshot)

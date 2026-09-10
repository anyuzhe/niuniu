"""Read-only views over immutable research artifacts."""
import polars as pl


def regime_view(catalog,run_id):
    frame=pl.read_parquet(catalog.file(run_id,'observations.parquet'))
    columns=[c for c in frame.columns if c.startswith('regime_') and frame.schema[c]==pl.String]
    if not columns:return {'rows':[],'message':'此实验未保存 Regime。请在新建实验中启用市场状态。'}
    if 'eligible' in frame.columns:frame=frame.filter(pl.col('eligible'))
    labels=[c for c in frame.columns if c.startswith('forward_') and frame.schema[c].is_numeric()]
    rows=[]
    for dimension in columns:
        for label in labels:
            result=frame.group_by(dimension).agg(pl.len().alias('observations'),
                pl.col(label).is_finite().sum().alias('label_count'),
                pl.col(label).filter(pl.col(label).is_finite()).mean().alias('mean_return'),
                pl.corr('value',label).fill_nan(None).alias('pooled_ic'))
            for row in result.sort(dimension).to_dicts():
                rows.append({'dimension':dimension,'state':row.pop(dimension),'horizon':label,**row})
    return {'rows':rows,'message':'保存的入池样本按单一状态维度分组；pooled IC 为组内合并相关性，不是日均截面 IC。Unknown 单独保留；未来收益仅用于事后研究。'}

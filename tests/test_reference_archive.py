import json
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
import polars as pl
from quantlab.storage.codec import digest,encode
from quantlab.data.reference_archive import listing_reference,reference_coverage
from quantlab.data.universe import UniverseConfig,build_universe


class ReferenceArchiveTest(unittest.TestCase):
    def archive(self,root):
        entries=[]
        records=[{'kind':'basic','request':{},'rows':[{'code':'sh.600000','ipoDate':'2020-01-02','outDate':'2020-01-05','type':'1'}]},
            {'kind':'daily_status','request':{},'rows':[{'code':'sh.600000','date':'2020-01-03','tradestatus':'1','isST':'0'}]}]
        for i,record in enumerate(records):
            record.update(symbol='sh.600000',fetched_at='2026-09-10T00:00:00+00:00',historical_available_at=None)
            path=root/f'{i}.json';path.write_text(encode(record));entries.append({'path':path.name,'rows':len(record['rows']),'sha256':digest(record)})
        path=root/'manifest.json';path.write_text(encode({'provider':'baostock','status':'completed','symbols':['sh.600000'],'files':entries}));return path

    def test_archived_listing_source_and_unknown_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=self.archive(root)
            config=UniverseConfig('listing',1,str(path));universe=build_universe(root,('sh.600000',),config)
            times=[datetime(2020,1,i,tzinfo=timezone.utc) for i in (2,3,5)]
            bars=pl.DataFrame({'symbol':['sh.600000']*3,'datetime':times,'available_at':times})
            self.assertEqual(universe.mask(bars)['eligible'].to_list(),[False,True,False])
            item=reference_coverage(path)['symbols'][0];self.assertFalse(item['historical_publication_known']);self.assertEqual(item['industry_unqueried_status_dates'],1)
            self.assertFalse(reference_coverage(path)['daily_capitalization_ready'])
            with self.assertRaisesRegex(ValueError,'PIT'):UniverseConfig('pit',0,str(path))

    def test_tampering_and_missing_symbol_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=self.archive(root)
            with self.assertRaisesRegex(ValueError,'缺少'):listing_reference(path,['sz.000001'])
            raw=json.loads((root/'0.json').read_text());raw['rows'][0]['ipoDate']='1990-01-01';(root/'0.json').write_text(encode(raw))
            with self.assertRaisesRegex(ValueError,'校验'):listing_reference(path,['sh.600000'])

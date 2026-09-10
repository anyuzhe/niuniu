import json
from datetime import datetime,timedelta,date
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo
import unittest
import polars as pl
from polars.testing import assert_frame_equal
from test_technical import bars
from quantlab.data.archive import BarArchive,ArchivedBarProvider
from quantlab.data.base import DataRequest
from quantlab.domain import Timeframe


class ArchiveTests(unittest.TestCase):
    def test_increment_revision_vintage_and_immutable_parent(self):
        market=bars([10.,11.,12.,13.]);now=market['datetime'].max()+timedelta(days=1)
        with TemporaryDirectory() as directory:
            archive=BarArchive(directory)
            first=archive.publish(market.head(2),{'adjustment':'raw','source':'fixture'},observed_at=now)
            old=Path(first['manifest']).parent.joinpath('bars.parquet').read_bytes()
            second=archive.publish(market.tail(3),{'adjustment':'raw','source':'overlap'},first['manifest'],observed_at=now+timedelta(days=1))
            self.assertEqual(second['new_rows'],2);self.assertEqual(second['duplicate_rows'],1)
            repeat=archive.publish(market,{'adjustment':'raw','source':'repeat'},second['manifest'],observed_at=now+timedelta(days=2))
            self.assertEqual(repeat['status'],'unchanged')
            changed=market.with_columns((pl.col('volume')+1).alias('volume'))
            with self.assertRaisesRegex(ValueError,'revisions'):archive.publish(changed,{'adjustment':'raw','source':'correction'},second['manifest'],observed_at=now+timedelta(days=2))
            third=archive.publish(changed,{'adjustment':'raw','source':'correction'},second['manifest'],True,now+timedelta(days=2))
            self.assertEqual(third['revised_rows'],4)
            assert_frame_equal(archive.at(now).all_bars(),market.head(2))
            assert_frame_equal(archive.at(now+timedelta(days=1)).all_bars(),market)
            self.assertEqual(old,Path(first['manifest']).parent.joinpath('bars.parquet').read_bytes())
            with self.assertRaisesRegex(ValueError,'No archived'):archive.at(now-timedelta(seconds=1))

    def test_data_and_manifest_tamper_rejected(self):
        market=bars([10.,11.]);now=market['datetime'].max()+timedelta(days=1)
        with TemporaryDirectory() as directory:
            result=BarArchive(directory).publish(market,{'adjustment':'raw','source':'fixture'},observed_at=now)
            path=Path(result['manifest']);record=json.loads(path.read_text());record['source']={'adjustment':'raw','source':'tampered'};path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'identity'):ArchivedBarProvider(path).all_bars()
            (path.parent/'bars.parquet').write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'checksum'):ArchivedBarProvider(path).all_bars()

    def test_archive_feed_advances_and_rejects_history_revision(self):
        import test_core
        from quantlab.execution.feed import MQCPaperFeed
        from quantlab.execution.backtest import ExecutionConfig
        from quantlab.storage.codec import encode
        fixture=test_core.CoreTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        market=fixture.provider.load(fixture.request).bars
        at=datetime(2025,1,4,16,tzinfo=ZoneInfo('Asia/Shanghai'))
        archive=BarArchive(fixture.root/'archive')
        first=archive.publish(market.filter(pl.col('datetime').dt.day()<=3),{'adjustment':'raw','source':'fixture'},observed_at=at)
        rules=[{'symbol':s,'effective_at':'2025-01-01T00:00:00+08:00','available_at':'2025-01-01T00:00:00+08:00',
            'expires_at':'2025-02-01T00:00:00+08:00','suspended':False,'st':False,'limit_up':None,'limit_down':None,
            'commission_bps':0,'minimum_commission':0,'sell_tax_bps':0,'transfer_bps':0,'source':'synthetic'} for s in fixture.symbols]
        rulefile=fixture.root/'rules.json';rulefile.write_text(encode(rules));account=fixture.root/'account.json'
        feed=MQCPaperFeed(fixture.root,account,fixture.symbols,Timeframe.DAILY,fixture.start,'BASE.MOMENTUM',{'lookback':1},ExecutionConfig(),archive_root=archive.root,adjustment='raw')
        self.assertEqual(feed.poll(rulefile,at)['revision'],1)
        second=archive.publish(market.filter(pl.col('datetime').dt.day()<=6),{'adjustment':'raw','source':'fixture2'},first['manifest'],observed_at=at+timedelta(days=3))
        self.assertEqual(feed.poll(rulefile,at+timedelta(days=3))['revision'],2)
        before=account.read_bytes()
        archive.publish(market.filter(pl.col('datetime').dt.day()<=6).with_columns((pl.col('volume')+1).alias('volume')),
            {'adjustment':'raw','source':'correction'},second['manifest'],True,at+timedelta(days=4))
        with self.assertRaisesRegex(ValueError,'revised'):feed.poll(rulefile,at+timedelta(days=4))
        self.assertEqual(account.read_bytes(),before)

    def test_portable_archive_keeps_research_snapshot_identity(self):
        import shutil
        market=bars([10.,11.,12.],symbol='sh.600000');now=market['datetime'].max()+timedelta(days=1)
        request=DataRequest(('sh.600000',),Timeframe.DAILY,date(2025,1,1),date(2025,1,3))
        with TemporaryDirectory() as directory:
            root=Path(directory);result=BarArchive(root/'original').publish(market,{'adjustment':'raw','source':'fixture'},observed_at=now)
            first=ArchivedBarProvider(result['manifest']).load(request)
            shutil.copytree(Path(result['manifest']).parent,root/'copied')
            copied=ArchivedBarProvider(root/'copied/manifest.json').load(request)
            self.assertEqual(first.snapshot,copied.snapshot)
            assert_frame_equal(first.bars,copied.bars)

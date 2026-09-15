"""Real MQC -> native Qt submission -> Chan score -> independent fills acceptance.
Run: QT_QPA_PLATFORM=offscreen .venv/bin/python examples/verify_chan_e2e.py --output <new-directory>
"""
import argparse
import json
import os
import time
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import polars as pl
from PyQt6.QtCore import QDate,Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication,QTableWidget
from quantlab.desktop.app import MainWindow
from quantlab.desktop.experiment import ExperimentDialog
from quantlab.desktop.sequence_builder import SequenceBuilder
from quantlab.factors.chan_sequence import ChanOrderedSequence
from quantlab.causal import assert_prefix_invariant
from quantlab.sequence.replay import replay_page
from quantlab.execution.portfolio import TargetWeightBuilder,PortfolioConfig
from quantlab.storage.codec import encode


def run(output,data_root):
    output.mkdir(parents=True,exist_ok=False);runs=output/'runs';runs.mkdir()
    symbols=['sh.600000','sh.600036','sz.000001','sz.300750']
    sequence=ChanOrderedSequence().parameters({})
    model={'inputs':{'sequence':{'factor_id':'SEQ.CHAN_ORDERED','parameters':sequence},
        'exit':{'factor_id':'CHAN.INCLUSION_CENTER_EXIT_UP','parameters':{'left':2,'right':2,'min_separation':3}}},
        'weights':{'sequence':1.,'exit':.25}}
    execution={'top_n':2,'threshold':.9,'exposure':.5,'commission_bps':3,'minimum_commission':5,
        'slippage_bps':2,'sell_tax_bps':5,'t_plus_one':True}
    portfolio={'max_position':.25,'max_exposure':.5}
    advanced={'regime':{},'regime_filter':{'direction':'Bull'}}
    plan={'symbols':symbols,'start':'2026-08-03','end':'2026-09-04','timeframe':'5m','model':model,
        'execution':execution,'portfolio':portfolio,'split':{'train_end':'2026-08-14','valid_end':'2026-08-21'},**advanced,'scope':'Fixed rule score; explicit symbol sample; no ML, no live orders; modeled costs'}
    (output/'fixed-plan.json').write_text(encode(plan))
    app=QApplication.instance() or QApplication([]);app.setStyle('Fusion')
    window=MainWindow(runs,data_root);window.resize(1600,1000);window.show()
    def wait(predicate,seconds=300):
        deadline=time.monotonic()+seconds
        while not predicate():
            if time.monotonic()>deadline:raise TimeoutError('Native workflow timed out')
            QTest.qWait(30)
    def idle():wait(lambda:not window.callbacks)
    def submit(dialog,name):
        dialog.question.setText('缠论端对端验收 '+name);dialog.symbols.setText(' '.join(symbols))
        dialog.start.setDate(QDate(2026,8,3));dialog.end.setDate(QDate(2026,9,4));dialog.timeframe.setCurrentIndex(1)
        dialog.audit.setChecked(True);dialog.advanced.setPlainText(json.dumps(advanced));dialog.show()
        assert dialog.validate(),dialog.status.text()
        if name=='strategy':dialog.advanced.setPlainText(json.dumps({**advanced,'execution':execution,'portfolio':portfolio}))
        (output/(name+'-submission.json')).write_text(encode(dialog.collect()))
        QTest.mouseClick(dialog.submit_button,Qt.MouseButton.LeftButton)
        idle();assert window.queue is not None,dialog.status.text()
        def finished():return any(j['job_id']==dialog.job_id and j['status'] in ('completed','failed') for j in window.queue.list())
        wait(finished,600)
        job=next(j for j in window.queue.list() if j['job_id']==dialog.job_id)
        assert job['status']=='completed',job
        path=runs/job['run_id'];record=json.loads((path/'experiment.json').read_text())
        print(name,job['run_id'],flush=True);dialog.close();return path,record
    try:
        idle();window.navigate(5);idle();editor=window.scroll.widget().findChild(SequenceBuilder)
        editor.family.setCurrentIndex(editor.family.findData('SEQ.CHAN_ORDERED'))
        assert editor.validate()==sequence
        editor.save();editor.research();seqpath,seqrecord=submit(window.dialogs[-1],'sequence')
        window.grab().save(str(output/'sequence-editor.png'))
        definition=next(v for v in window.factors if v['definition']['factor_id']=='COMB.SCORE')
        dialog=ExperimentDialog(window,definition,'execution');dialog.parameters.setPlainText(json.dumps(model))
        path,record=submit(dialog,'strategy')
        sourcepath=Path(record['children'][0]['artifact_path']);source=json.loads((sourcepath/'experiment.json').read_text())
        bars=pl.read_parquet(sourcepath/'bars.parquet');obs=pl.read_parquet(sourcepath/'observations.parquet')
        assert seqrecord['manifest']['config']['parameters']==sequence
        assert source['manifest']['config']['parameters']['inputs']['sequence']['parameters']==sequence
        assert source['manifest']['config']['parameters']['weights']==model['weights']
        assert bars.equals(pl.read_parquet(seqpath/'bars.parquet')),'Native runs read different source bars'
        factor=ChanOrderedSequence();values,transitions,events=factor.trace(bars,sequence)
        counts=Counter(t.status for t in transitions);assert counts['completed']>0,counts
        cutoffs=sorted(set(bars['available_at']));checks=[cutoffs[len(cutoffs)*i//4] for i in (1,2,3)]
        assert_prefix_invariant(factor,bars,sequence,checks)
        for cutoff in checks:
            assert factor.trace(bars.filter(pl.col('available_at')<=cutoff),sequence)[2]==[e for e in events if e.available_at<=cutoff]
        completed={(t.symbol,t.available_at) for t in transitions if t.status=='completed'}
        positive=obs.filter(pl.col('value')>.9);assert positive.height>0
        assert all((r['symbol'],r['available_at']) in completed and r['regime_direction']=='Bull' for r in positive.iter_rows(named=True))
        targets=pl.read_parquet(path/'targets.parquet')
        rebuilt,_=TargetWeightBuilder(PortfolioConfig(**portfolio)).build(obs,bars,top_n=2,threshold=.9,exposure=.5)
        assert rebuilt.equals(targets)
        # Research outcome labels must never influence decisions.
        label_columns=[c for c in obs.columns if c.startswith(('forward_','mfe_','mae_'))]
        assert len(label_columns)==9
        scrambled=obs.with_columns([pl.lit(-999.).alias(c) for c in label_columns])
        assert TargetWeightBuilder(PortfolioConfig(**portfolio)).build(scrambled,bars,top_n=2,threshold=.9,exposure=.5)[0].equals(targets)
        fills=record['fills'];assert len(fills)>0
        lots=defaultdict(list);cash=1_000_000.;positions=defaultdict(int)
        indexed={(r['symbol'],r['datetime']):r for r in bars.iter_rows(named=True)}
        for fill in fills:
            symbol=fill['symbol'];decision=datetime.fromisoformat(fill['decision_at']);at=datetime.fromisoformat(fill['filled_at']);end=datetime.fromisoformat(fill['bar_end'])
            assert decision<=at<end
            later=bars.filter((pl.col('symbol')==symbol)&(pl.col('datetime')>pl.lit(decision).dt.convert_time_zone('Asia/Shanghai'))).sort('datetime')
            assert later['datetime'][0]==end,'Fill skipped the next observed bar'
            bar=indexed[symbol,end];buy=fill['side']=='buy';size=fill['quantity'];price=fill['price']
            assert abs(price-bar['open']*(1+(.0002 if buy else -.0002)))<1e-8
            assert size>0 and size%100==0
            assert abs(fill['commission']-max(5,size*price*.0003))<1e-7
            assert abs(fill['tax']-(0 if buy else size*price*.0005))<1e-7
            if buy:lots[symbol].append([at.date(),size]);positions[symbol]+=size
            else:
                remaining=size
                for lot in lots[symbol]:
                    if lot[0]>=at.date():continue
                    use=min(lot[1],remaining);remaining-=use;lot[1]-=use
                assert remaining==0,'T+1 sell exceeded older holdings'
                positions[symbol]-=size
            cash+=(-1 if buy else 1)*size*price-fill['commission']-fill['tax']-fill['transfer_fee']
            assert cash>=-1e-7
        final_marks={r['symbol']:r['close'] for r in bars.sort('datetime').group_by('symbol',maintain_order=True).last().iter_rows(named=True)}
        equity=cash+sum(q*final_marks[s] for s,q in positions.items())
        assert abs(equity-record['execution']['final_equity'])<1e-6
        curve=pl.read_parquet(path/'observations.parquet')
        assert abs(curve['equity'][-1]-equity)<1e-6
        # Independently reconstruct every close, not only the final total.
        cash_check=1_000_000.;position_check=defaultdict(int);fill_index=0;marks={}
        all_bars={key[0]:group for key,group in bars.group_by('datetime')}
        for point in curve.iter_rows(named=True):
            dt=point['datetime']
            while fill_index<len(fills) and datetime.fromisoformat(fills[fill_index]['bar_end'])<=dt:
                f=fills[fill_index];sign=1 if f['side']=='buy' else -1
                position_check[f['symbol']]+=sign*f['quantity']
                cash_check-=sign*f['quantity']*f['price']+f['commission']+f['tax']+f['transfer_fee'];fill_index+=1
            for b in all_bars[dt].iter_rows(named=True):marks[b['symbol']]=b['close']
            position_value=sum(q*marks[s] for s,q in position_check.items())
            assert abs(cash_check-point['cash'])<1e-6
            assert abs(position_value-point['position_value'])<1e-6
            assert abs(cash_check+position_value-point['equity'])<1e-6
        assert all(r['reason']=='t_plus_one' and r['filled']==0 for r in record['rejections'])
        replay_checks=0
        for symbol in symbols:
            n=bars.filter(pl.col('symbol')==symbol).height
            for cursor in (0,n//2,n-1):
                page=replay_page(bars,source,symbol,cursor)
                assert all(e['available_at']<=page['as_of'].isoformat() for e in page['events']);replay_checks+=1
        # The fixed model also goes through chronological train/valid/test evaluation.
        holdout=ExperimentDialog(window,definition,'holdout');holdout.parameters.setPlainText(json.dumps(model))
        holdout.train_end.setDate(QDate(2026,8,14));holdout.valid_end.setDate(QDate(2026,8,21))
        holdout_path,holdout_record=submit(holdout,'holdout')
        assert len(holdout_record['periods'])==3
        for index,name in [(3,'market-state'),(4,'structure-replay'),(8,'rule-model'),(9,'strategy')]:
            window.navigate(index);idle()
            tables=window.scroll.widget().findChildren(QTableWidget)
            for table in tables:
                if table.rowCount():table.selectRow(0)
            idle()
            if index==4:
                from quantlab.desktop.replay import ReplayWidget
                replay=window.scroll.widget().findChild(ReplayWidget);assert replay is not None
                replay.cursor.setValue(replay.cursor.maximum());idle()
                assert any(e['factor_id'].startswith('CHAN.') for e in replay.chart.overlays['events'])
            QTest.qWait(150);window.grab().save(str(output/(name+'.png')))
        window.open_run(record['run_id']);idle();window.dialogs[-1].grab().save(str(output/'execution-detail.png'))
        result={'status':'passed','rows':bars.height,'symbols':symbols,'sequence_counts':dict(counts),
            'event_counts':dict(Counter(e.factor_id for e in events)),'selected_score_rows':positive.height,
            'prefix_checks':3,'replay_checks':replay_checks,'sequence_run':seqrecord['run_id'],
            'holdout_run':holdout_record['run_id'],'ledger_close_checks':curve.height,'rejection_reasons':dict(Counter(r['reason'] for r in record['rejections'])),
            'execution_run':record['run_id'],'source_run':source['run_id'],'execution':record['execution'],
            'checks':['native form submission and archived parameters','same raw source bars','confirmed event prefix invariance',
                'market-state gated sequence scores','targets independent of future return labels','raw next-open fills',
                'lot size, T+1, configured costs, nonnegative cash','independent every-close ledger reconciliation','chronological fixed-model holdout','replay cutoff','native page rendering']}
        (output/'result.json').write_text(encode(result));print(encode(result),flush=True)
    finally:
        if window.queue:window.queue.close()
        idle();window.close();QTest.qWait(100)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--data-root',type=Path,default=Path('/Volumes/Lexar/niuniu-data'))
    args=parser.parse_args();run(args.output,args.data_root)

"""Deterministic AUCTION/R1 scanner over frozen Playbook candidates and MarketSnapshots."""
from __future__ import annotations

from pathlib import Path

from .market_snapshot import MarketSnapshotError,MarketSnapshotStore
from .playbook_store import PlaybookError,PlaybookStore

SCANNER_VERSION='v3-active-execution-v1'


class PlaybookScanError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def _pct(price,previous):
    if price is None or previous is None or previous<=0:return None
    return (price/previous-1.0)*100.0


def _index(snapshot):return {item['symbol']:item for item in snapshot['instruments']}


def _one_price(item):
    values=[item.get(key) for key in ('open','high','low','last')]
    return all(v is not None for v in values) and max(values)-min(values)<1e-9


def _unique(values):
    result=[]
    for value in values:
        if value not in result:result.append(value)
    return result


class DailyPlaybookScanner:
    def __init__(self,output):
        self.output=Path(output).resolve();self.playbooks=PlaybookStore(self.output);self.snapshots=MarketSnapshotStore(self.output)

    def _base(self,candidate_set_id):
        try:candidate=self.playbooks.get_candidate_set(candidate_set_id)
        except PlaybookError as exc:raise PlaybookScanError('CANDIDATE_SET_INVALID',str(exc)) from None
        case=self.playbooks.get_case(candidate['case_id']);definition=self.playbooks.get_definition(candidate['definition_id'])
        return candidate,case,definition

    def _snapshot(self,snapshot_id,day,frame):
        try:value=self.snapshots.get(snapshot_id)
        except MarketSnapshotError as exc:raise PlaybookScanError('MARKET_SNAPSHOT_INVALID',str(exc)) from None
        if value['trading_day']!=day or value['frame']!=frame:
            raise PlaybookScanError('MARKET_SNAPSHOT_MISMATCH',f'MarketSnapshot 必须属于 {day} / {frame}。')
        return value

    @staticmethod
    def _pit(base,*snapshots):
        if base['pit_status']=='STRICT_PIT' and all(s.get('strict_pit_eligible') for s in snapshots):return 'STRICT_PIT'
        if base['pit_status']=='RETROSPECTIVE_REFERENCE':return 'RETROSPECTIVE_REFERENCE'
        return 'UNKNOWN'

    @staticmethod
    def _complete(base,*snapshots):
        return base['completeness']=='FULL' and all(s['completeness']=='FULL' for s in snapshots)

    def _auction_rows(self,base,snapshot):
        items=_index(snapshot);rows=[];missing=[]
        for candidate in base['candidates']:
            symbol=candidate['symbol'];item=items.get(symbol)
            if item is None:
                missing.append(symbol);features={**candidate['features'],'snapshot_missing':True};gap=None
            else:
                gap=_pct(item.get('auction_price'),item.get('previous_close'))
                features={**candidate['features'],'snapshot_missing':False,'name':item.get('name',''),
                    'auction_price':item.get('auction_price'),'previous_close':item.get('previous_close'),
                    'auction_gap_pct':gap,'tradable':item.get('tradable',True),
                    'execution_profile':item.get('execution_profile','UNKNOWN')}
            rows.append({'symbol':symbol,'candidate':candidate,'features':features,'gap':gap})
        rows.sort(key=lambda row:(row['gap'] is not None,row['gap'] if row['gap'] is not None else -1e9,row['symbol']),reverse=True)
        return rows,missing

    def _r1_rows(self,base,auction,r1):
        auction_items=_index(auction);r1_items=_index(r1);rows=[];missing=[]
        for candidate in base['candidates']:
            symbol=candidate['symbol'];a=auction_items.get(symbol);r=r1_items.get(symbol)
            if a is None or r is None:
                missing.append(symbol);features={**candidate['features'],'snapshot_missing':True}
                rows.append({'symbol':symbol,'candidate':candidate,'features':features,'eligible':False,
                    'impulse':None,'r1_pct':None,'auction_gap':None});continue
            auction_gap=_pct(a.get('auction_price'),a.get('previous_close'))
            r1_pct=_pct(r.get('last'),r.get('previous_close'))
            impulse=None if auction_gap is None or r1_pct is None else r1_pct-auction_gap
            profile=r.get('execution_profile','UNKNOWN');one_price=_one_price(r)
            eligible=bool(r.get('tradable',True) and profile=='STANDARD_ACCESS' and not one_price and
                r1_pct is not None and r1_pct>0 and impulse is not None and impulse>0)
            features={**candidate['features'],'snapshot_missing':False,'name':r.get('name',''),
                'auction_gap_pct':auction_gap,'r1_close_pct':r1_pct,'r1_vs_auction_pct':impulse,
                'r1_open':r.get('open'),'r1_high':r.get('high'),'r1_low':r.get('low'),'r1_last':r.get('last'),
                'r1_volume':r.get('volume'),'r1_amount':r.get('amount'),'tradable':r.get('tradable',True),
                'execution_profile':profile,'one_price_first_window':one_price,'scanner_eligible':eligible}
            rows.append({'symbol':symbol,'candidate':candidate,'features':features,'eligible':eligible,
                'impulse':impulse,'r1_pct':r1_pct,'auction_gap':auction_gap})
        def rank_key(row):
            r1=row['r1_pct'] if row['r1_pct'] is not None else -1e9
            if row['eligible']:
                return (2,row['impulse'] if row['impulse'] is not None else -1e9,r1,row['symbol'])
            return (1 if r1>0 else 0,r1,row['impulse'] if row['impulse'] is not None else -1e9,row['symbol'])
        rows.sort(key=rank_key,reverse=True)
        return rows,missing

    def scan(self,candidate_set_id,market_snapshot_id,auction_snapshot_id=''):
        base,case,definition=self._base(candidate_set_id);day=base['trading_day']
        snapshot=self._snapshot(market_snapshot_id,day,self.snapshots.get(market_snapshot_id)['frame'])
        if snapshot['frame']=='AUCTION':
            rows,missing=self._auction_rows(base,snapshot);snapshots=[snapshot]
            selected=[];ranked=[row['symbol'] for row in rows]
            reasons={row['symbol']:[f"竞价涨跌幅={row['gap']:.4f}%" if row['gap'] is not None else '竞价快照缺失',
                'AUCTION阶段仅排序，不直接产生入场选择'] for row in rows}
            summary='AUCTION deterministic scan：只排序，不入场；等待R1主动性与执行访问确认。'
        elif snapshot['frame']=='R1':
            if not auction_snapshot_id:raise PlaybookScanError('AUCTION_SNAPSHOT_REQUIRED','R1 扫描必须引用同日 AUCTION MarketSnapshot。')
            auction=self._snapshot(auction_snapshot_id,day,'AUCTION');rows,missing=self._r1_rows(base,auction,snapshot);snapshots=[auction,snapshot]
            ranked=[row['symbol'] for row in rows];selected=[] if missing or not self._complete(base,*snapshots) else [next((r['symbol'] for r in rows if r['eligible']),None)]
            selected=[s for s in selected if s]
            reasons={}
            for row in rows:
                text=[]
                if row['features'].get('snapshot_missing'):text.append('实时快照缺失，禁止选择')
                else:
                    text.append(f"R1涨跌幅={row['r1_pct']:.4f}%" if row['r1_pct'] is not None else 'R1涨跌幅未知')
                    text.append(f"相对竞价变化={row['impulse']:.4f}%" if row['impulse'] is not None else '相对竞价变化未知')
                    text.append('执行='+row['features']['execution_profile'])
                    if row['features']['one_price_first_window']:text.append('首窗口一字/单一价格，不视为普通账户可达')
                    if row['eligible']:text.append('满足STANDARD_ACCESS + 正收益 + 主动增强子规则')
                reasons[row['symbol']]=text
            summary='R1 deterministic scan：STANDARD_ACCESS + 正收益 + 相对竞价主动增强；缺数据时NO_TRADE。'
        else:
            raise PlaybookScanError('UNSUPPORTED_FRAME','DailyPlaybookScanner 第一版只支持 AUCTION/R1。')

        complete=self._complete(base,*snapshots) and not missing
        completeness='FULL' if complete else 'PARTIAL'
        pit_status=self._pit(base,*snapshots) if complete else 'UNKNOWN'
        evidence=[f"market_snapshot:{s['snapshot_id']}" for s in snapshots]
        candidates=[]
        for row in rows:
            original=row['candidate']
            candidates.append({'symbol':row['symbol'],'eligibility_reasons':original['eligibility_reasons'],
                'features':row['features'],'evidence_ids':_unique([*original.get('evidence_ids',[]),*evidence])})
        notes=f"scanner={SCANNER_VERSION}; scope=active_confirmation_and_execution_access; missing={','.join(missing) or 'none'}"
        payload={'definition_id':definition['definition_id'],'trading_day':day,'frame':snapshot['frame'],
            'as_of':snapshot['as_of'],'source_ids':case['source_ids'],'market_snapshot_ids':[s['snapshot_id'] for s in snapshots],
            'summary':summary,'notes':notes,
            'candidate_set':{'completeness':completeness,'pit_status':pit_status,
                'universe_source':f"base_candidate_set:{base['candidate_set_id']} + frozen MarketSnapshot",
                'generation_method':f"{SCANNER_VERSION}; 不增删基础候选，只补当时快照特征与确定性排序",
                'candidates':candidates,'evidence_ids':evidence},
            'prediction':{'selected_symbols':selected,'ranked_symbols':ranked,'reasons':reasons,
                'evidence_ids':evidence,'notes':('NO_TRADE：快照不完整。' if missing else notes)}}
        return {'scanner_version':SCANNER_VERSION,'base_candidate_set_id':base['candidate_set_id'],
            'frame':snapshot['frame'],'trading_day':day,'complete':complete,'missing_symbols':missing,
            'selected_symbols':selected,'ranked_symbols':ranked,'forward_payload':payload}


__all__=['SCANNER_VERSION','PlaybookScanError','DailyPlaybookScanner']

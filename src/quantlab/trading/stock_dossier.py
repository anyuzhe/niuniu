"""Read-only stock dossier assembled from existing immutable research evidence."""
from __future__ import annotations

from pathlib import Path

from quantlab.agent.watch_store import WatchStore
from quantlab.workbench.server import ArtifactCatalog
from .decision import SYMBOL
from .decision_store import DecisionStore


class StockDossier:
    def __init__(self, output):
        self.output = Path(output).resolve()
        if not self.output.is_dir():
            raise ValueError('Stock Dossier workspace does not exist')
        self.decisions = DecisionStore(self.output)
        self.catalog = ArtifactCatalog(self.output)
        self.watches = WatchStore(self.output)

    @staticmethod
    def validate_symbol(symbol):
        if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol.lower()):
            raise ValueError('symbol 必须是 sh/sz/bj.XXXXXX。')
        return symbol.lower()

    def decision_evidence(self, symbol):
        current = self.decisions.list(symbol=symbol, limit=200)['records']
        history = self.decisions.list(symbol=symbol, include_superseded=True, limit=200)['records']
        return current, history

    def experiment_evidence(self, symbol):
        rows = self.catalog.list(query=symbol, limit=10000)['runs']
        return [row for row in rows if symbol in row.get('symbols', [])]

    def watch_evidence(self, symbol):
        result = []
        directory = self.watches.list()
        for row in directory['watches']:
            try:
                definition, state = self.watches.read(row['watch_id'])
                config = definition['rule']['config']
                if symbol not in config.get('data', {}).get('symbols', []):
                    continue
                latest = self.watches.snapshot(row['watch_id'], state['history'][-1]) if state['history'] else None
                result.append({
                    **row,
                    'symbols': list(config.get('data', {}).get('symbols', [])),
                    'latest_snapshot_id': latest.get('snapshot_id') if latest else None,
                    'latest_source_run_id': latest.get('source_run_id') if latest else None,
                    'latest_change': latest.get('change') if latest else None,
                    'latest_alerts': latest.get('alerts', []) if latest else [],
                })
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return result, directory['unreadable']

    def get(self, symbol):
        symbol = self.validate_symbol(symbol)
        current, history = self.decision_evidence(symbol)
        experiments = self.experiment_evidence(symbol)
        watches, unreadable = self.watch_evidence(symbol)
        latest = self.decisions.latest_current(symbol)
        themes = []
        for item in history:
            value = item.get('theme', '')
            if value and value not in themes:
                themes.append(value)
        return {
            'symbol': symbol,
            'current_decision': latest,
            'decision_current': current,
            'decision_history': history,
            'experiments': experiments,
            'watches': watches,
            'unreadable_watches': unreadable,
            'themes': themes,
            'counts': {
                'decision_current': len(current),
                'decision_history': len(history),
                'experiments': len(experiments),
                'watches': len(watches),
            },
            'policy': '只聚合已有归档；打开 Stock Dossier 不创建研究、不刷新 Watch、不修改 Decision。',
        }

"""Shared collection envelope for vendor data pulls into the bronze lake.

Every collector in this package runs inside the same envelope so that a run is
reproducible, resumable and reviewable without trusting the operator's summary:

  - the destination directory is never silently overwritten; a non-empty target
    is refused unless ``--resume`` is given, and resume only ever *adds* files
  - ``--dry-run`` prints the full plan and exits without a single vendor call
  - every symbol is written atomically (temp file + replace) and then read back
    and verified before it is counted as collected
  - vendor columns are preserved in full; anything the writer had to coerce is
    recorded per symbol rather than silently normalised away
  - the run ends with a receipt that makes "never attempted", "returned empty"
    and "failed" three distinct, countable states

The fetch callable is injected, so collectors are testable without network
access. See ``scripts/collect/README.md`` for the operating contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path


class CollectionRefused(RuntimeError):
    """Raised when the envelope refuses to start. Never caught internally."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def symbol_filename(code: str) -> str:
    """``sh.600000`` -> ``sh_600000.parquet``. Matches the existing lake layout."""
    if '/' in code or '\\' in code or '\x00' in code:
        raise ValueError('Unsafe symbol: %r' % code)
    return code.replace('.', '_') + '.parquet'


def build_parser(description: str, *, default_dest: str, default_throttle: float) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument('--dest', default=default_dest,
                   help='目标 bronze 目录（默认 %(default)s）')
    p.add_argument('--receipt', default=None,
                   help='回执 JSON 路径；默认写入 <dest>/_receipts/<name>-<run_id>.json')
    p.add_argument('--universe', default=None,
                   help='证券清单文件（每行一个代码，如 sh.600000）；缺省用采集器的默认全集')
    p.add_argument('--limit', type=int, default=None,
                   help='只处理前 N 只，用于小规模试采')
    p.add_argument('--throttle', type=float, default=default_throttle,
                   help='每次请求后的等待秒数（默认 %(default)s）')
    p.add_argument('--retries', type=int, default=3, help='单只证券的最大尝试次数（默认 %(default)s）')
    p.add_argument('--resume', action='store_true',
                   help='续采：跳过已存在且回读校验通过的文件；不覆盖、不删除')
    p.add_argument('--dry-run', action='store_true',
                   help='只打印计划，不发起任何供应商请求')
    p.add_argument('--fail-fast', action='store_true',
                   help='任一只证券失败即停止，保留已完成部分')
    return p


def _verify_existing(path: Path, read_parquet) -> tuple[bool, str, tuple]:
    """Readback check for resume. Returns (ok, reason, column signature)."""
    try:
        df = read_parquet(path)
    except Exception as exc:                       # noqa: BLE001 - reason is recorded
        return False, '%s: %s' % (type(exc).__name__, exc), ()
    if getattr(df, 'columns', None) is None:
        return False, 'no columns', ()
    return True, 'rows=%d' % len(df), tuple(str(c) for c in df.columns)


def _signature_audit(dest: Path, read_parquet, sample: int | None = None) -> list[dict]:
    """Group the destination's parquet files by their column signature.

    A directory that holds more than one signature is a silently mixed dataset —
    exactly what happens when a resume tops up files that an older, column-
    truncating collector wrote. Downstream readers then see a schema that depends
    on which symbol they opened, so this is surfaced rather than left to be
    discovered later.
    """
    files = sorted(dest.glob('*.parquet'))
    if sample is not None:
        files = files[:sample]
    groups: dict[tuple, list[str]] = {}
    for f in files:
        ok, _reason, sig = _verify_existing(f, read_parquet)
        if ok:
            groups.setdefault(sig, []).append(f.name)
    return [{'n_columns': len(sig), 'n_files': len(names), 'columns': list(sig),
             'example_files': names[:3]}
            for sig, names in sorted(groups.items(), key=lambda kv: -len(kv[1]))]


class Envelope:
    """Drives one collection run. ``fetch(code)`` returns a pandas DataFrame or None."""

    def __init__(self, args, *, name: str, source: str, required_columns=(), pandas=None):
        if pandas is None:
            import pandas as pandas          # local import keeps --help dependency-free
        self.pd = pandas
        self.args = args
        self.name = name
        self.source = source
        self.required = list(required_columns)
        self.dest = Path(args.dest)
        self.run_id = time.strftime('%Y%m%dT%H%M%S')
        if args.receipt:
            self.receipt_path = Path(args.receipt)
        else:
            self.receipt_path = self.dest / '_receipts' / ('%s-%s.json' % (name, self.run_id))

    # -- gating ---------------------------------------------------------------

    def plan(self, universe: list[str]) -> dict:
        """Decide what would be fetched. Performs no vendor call."""
        if self.args.limit is not None:
            if self.args.limit <= 0:
                raise CollectionRefused('--limit 必须为正整数')
            universe = universe[:self.args.limit]

        existing = sorted(p.name for p in self.dest.glob('*.parquet')) if self.dest.exists() else []
        if existing and not self.args.resume:
            raise CollectionRefused(
                '目标目录已有 %d 个 parquet，拒绝执行：%s\n'
                '本采集器只写新目录。要在已有结果上继续，请显式加 --resume（只增不覆盖）。'
                % (len(existing), self.dest))

        todo, skipped, corrupt = [], [], []
        for code in universe:
            path = self.dest / symbol_filename(code)
            if self.args.resume and path.exists():
                ok, reason, _sig = _verify_existing(path, self.pd.read_parquet)
                (skipped if ok else corrupt).append({'code': code, 'reason': reason})
                if ok:
                    continue
            todo.append(code)
        incumbent = _signature_audit(self.dest, self.pd.read_parquet) if existing else []
        return {'universe': len(universe), 'todo': todo,
                'skipped_verified': skipped, 'existing_unreadable': corrupt,
                'existing_files': len(existing), 'incumbent_signatures': incumbent}

    # -- writing --------------------------------------------------------------

    def _write_verified(self, code: str, df) -> dict:
        """Atomic write + readback. Returns the per-symbol receipt entry."""
        path = self.dest / symbol_filename(code)
        tmp = path.with_suffix('.parquet.tmp')
        coerced: list[str] = []
        frame = df
        try:
            frame.to_parquet(tmp, index=False)
        except Exception:
            # Preserve the record rather than the dtype: coerce only the columns
            # arrow rejected, and say which ones. Never a blanket astype(str).
            frame = df.copy()
            for col in frame.columns:
                try:
                    frame[[col]].to_parquet(tmp, index=False)
                except Exception:              # noqa: BLE001 - column is recorded
                    frame[col] = frame[col].map(lambda v: None if v is None else str(v))
                    coerced.append(str(col))
            frame.to_parquet(tmp, index=False)

        back = self.pd.read_parquet(tmp)
        if len(back) != len(frame):
            tmp.unlink(missing_ok=True)
            raise ValueError('回读行数不符：%d != %d' % (len(back), len(frame)))
        if list(back.columns) != list(frame.columns):
            tmp.unlink(missing_ok=True)
            raise ValueError('回读列不符')
        os.replace(tmp, path)
        return {'code': code, 'rows': int(len(frame)),
                'columns': [str(c) for c in frame.columns],
                'coerced_to_string': coerced,
                'sha256': sha256_file(path)}

    # -- driving --------------------------------------------------------------

    def run(self, universe: list[str], fetch) -> int:
        plan = self.plan(universe)
        todo = plan['todo']

        print('采集器   %s' % self.name)
        print('来源     %s' % self.source)
        print('目标     %s' % self.dest)
        print('全集     %d 只' % plan['universe'])
        print('已存在   %d 个文件（校验通过 %d，不可读 %d）'
              % (plan['existing_files'], len(plan['skipped_verified']), len(plan['existing_unreadable'])))
        print('待采集   %d 只' % len(todo))
        print('节流     %.2fs   重试 %d 次   失败即停=%s'
              % (self.args.throttle, self.args.retries, self.args.fail_fast))
        if plan['existing_unreadable']:
            print('⚠ 以下已存在文件回读失败，将被重新采集并覆盖：')
            for e in plan['existing_unreadable'][:10]:
                print('    %s  %s' % (e['code'], e['reason']))
        for sig in plan['incumbent_signatures']:
            print('已存在列签名  %d 列 × %d 个文件（例 %s）'
                  % (sig['n_columns'], sig['n_files'], ', '.join(sig['example_files'])))
        if len(plan['incumbent_signatures']) > 1:
            print('⚠ 目标目录本来就存在多种列签名，续采只会让混合更严重。')
        if plan['incumbent_signatures'] and todo:
            print('⚠ 续采写出的列宽由供应商当前返回决定，可能与上面的既有签名不一致。'
                  '若既有文件是旧采集器截列写下的，正确做法是**采到新目录重来**，'
                  '而不是在旧目录上续采。运行结束会再核对一次列签名。')

        if self.args.dry_run:
            print('\n--dry-run：未发起任何供应商请求，未写入任何文件。')
            return 0
        if not todo:
            print('\n无待采集项，退出。')
            return 0

        self.dest.mkdir(parents=True, exist_ok=True)
        self.receipt_path.parent.mkdir(parents=True, exist_ok=True)

        receipt = {
            'name': self.name, 'source': self.source, 'run_id': self.run_id,
            'dest': str(self.dest), 'started_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'universe_size': plan['universe'], 'n_todo': len(todo),
            'skipped_verified': [e['code'] for e in plan['skipped_verified']],
            'required_columns': self.required,
            'ok': [], 'empty': [], 'failed': [], 'schema_issue': [],
            'stopped_early': False,
        }
        stopped = False
        for i, code in enumerate(todo, 1):
            df, err = None, None
            for attempt in range(1, self.args.retries + 1):
                try:
                    df = fetch(code)
                    err = None
                    break
                except Exception as exc:                    # noqa: BLE001 - recorded
                    err = '%s: %s' % (type(exc).__name__, exc)
                    if attempt < self.args.retries:
                        time.sleep(self.args.throttle * attempt * 2)
            try:
                if err is not None:
                    # No file is written on failure, so "absent + listed in failed"
                    # is unambiguous against "absent + never attempted".
                    receipt['failed'].append({'code': code, 'error': err})
                    print('  [%d/%d] %s 失败 %s' % (i, len(todo), code, err[:70]))
                    if self.args.fail_fast:
                        receipt['stopped_early'] = True
                        stopped = True
                elif df is None or len(df) == 0:
                    empty = self.pd.DataFrame(columns=list(self.required) or ['code'])
                    entry = self._write_verified(code, empty)
                    entry['note'] = '供应商返回 0 行；写出零行文件以便续采时不再重复请求'
                    receipt['empty'].append(entry)
                else:
                    missing = [c for c in self.required if c not in df.columns]
                    if missing:
                        # Recorded *and* skipped: never write a half-understood schema.
                        receipt['schema_issue'].append(
                            {'code': code, 'missing': missing,
                             'columns': [str(c) for c in df.columns]})
                        print('  [%d/%d] %s 缺列 %s' % (i, len(todo), code, missing))
                    else:
                        receipt['ok'].append(self._write_verified(code, df))
            except Exception as exc:                        # noqa: BLE001 - recorded
                receipt['failed'].append(
                    {'code': code, 'error': 'write/verify: %s: %s' % (type(exc).__name__, exc)})
                print('  [%d/%d] %s 写入或校验失败 %s' % (i, len(todo), code, exc))
                if self.args.fail_fast:
                    receipt['stopped_early'] = True
                    stopped = True
            if stopped:
                break
            if i % 25 == 0:
                print('  进度 %d/%d  ok=%d empty=%d fail=%d schema=%d'
                      % (i, len(todo), len(receipt['ok']), len(receipt['empty']),
                         len(receipt['failed']), len(receipt['schema_issue'])))
            time.sleep(self.args.throttle)

        receipt['finished_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        receipt['summary'] = {k: len(receipt[k]) for k in ('ok', 'empty', 'failed', 'schema_issue')}
        receipt['summary']['skipped_verified'] = len(receipt['skipped_verified'])
        receipt['files_in_dest'] = len(list(self.dest.glob('*.parquet')))
        receipt['column_signatures'] = _signature_audit(self.dest, self.pd.read_parquet)
        receipt['schema_is_uniform'] = len(receipt['column_signatures']) <= 1
        with open(self.receipt_path, 'w', encoding='utf-8') as f:
            json.dump(receipt, f, ensure_ascii=False, indent=1)

        print('\n=== 回执 %s ===' % self.receipt_path)
        print(json.dumps(receipt['summary'], ensure_ascii=False))
        if not receipt['schema_is_uniform']:
            print('⚠ 目标目录存在 %d 种列签名，数据集列宽不统一：'
                  % len(receipt['column_signatures']))
            for sig in receipt['column_signatures']:
                print('    %d 列 × %d 文件（例 %s）'
                      % (sig['n_columns'], sig['n_files'], ', '.join(sig['example_files'])))
        if receipt['failed']:
            print('失败样例:', [e['code'] for e in receipt['failed'][:8]])
        if receipt['schema_issue']:
            print('缺列样例:', [e['code'] for e in receipt['schema_issue'][:8]])
        return 1 if (receipt['failed'] or receipt['stopped_early']) else 0


def read_universe_file(path: str) -> list[str]:
    codes = []
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            codes.append(line)
    if not codes:
        raise CollectionRefused('证券清单为空：%s' % path)
    return codes


def main_guard(fn):
    """Turn a refusal into a clean exit code instead of a traceback."""
    try:
        return fn()
    except CollectionRefused as exc:
        print('拒绝执行：%s' % exc, file=sys.stderr)
        return 2

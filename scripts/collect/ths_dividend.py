"""同花顺分红方案采集（akshare ``stock_fhps_detail_ths``）。

替代 ``artifacts/data-governance-20260922-D1D3/logs/ths-collect.py``。相对旧脚本的整改：

  - 目标目录、证券清单、节流全部走参数，不再硬编码绝对路径
  - ``--resume`` 可续采；旧脚本「目录非空即退出」使得中断后无法接着跑
  - ``--dry-run`` 可先看计划再决定是否发起请求
  - 不再对所有列做 ``astype(str)``：那会把缺失值变成字符串 ``'nan'``、把日期变成
    文本，事后无法区分「供应商没给」和「供应商给了空串」。现在保留原始 dtype，
    只有 parquet 写不下的列才逐列降级为字符串，并在回执里逐列点名
  - ``schema_issue`` 的证券在回执里有名有姓，不再是「既没有文件也不在失败名单」的黑洞

用法（先看计划，不发请求）::

    python scripts/collect/ths_dividend.py --dest <新目录> --dry-run

运行采集需要单独授权；本脚本自身不会在被 import 时产生任何副作用。
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collect import universe as uni
from collect.envelope import Envelope, build_parser, main_guard, read_universe_file

# No default destination: the old v1 directory (whitelisted columns) is superseded
# and the current v2 directory must be named explicitly (remediation P5).
DEFAULT_DEST = None
SOURCE = 'akshare.stock_fhps_detail_ths'
REQUIRED = ['报告期', '实施公告日', '分红方案说明', 'A股股权登记日', 'A股除权除息日', '方案进度']


def make_fetcher():
    """Import akshare lazily so --help / --dry-run work without it installed."""
    import akshare as ak
    import pandas as pd
    import requests

    def fetch(code: str):
        bare = code.split('.')[1]
        try:
            df = ak.stock_fhps_detail_ths(symbol=bare)
        except ValueError as exc:
            if 'No tables found' not in str(exc):
                raise
            url = f'https://basic.10jqka.com.cn/new/{bare}/bonus.html'
            response = requests.get(
                url,
                headers={'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                        'AppleWebKit/537.36 Chrome/89.0.4389.90 Safari/537.36')},
                timeout=30,
            )
            response.encoding = 'gbk'
            title_match = re.search(r'<title[^>]*>(.*?)</title>', response.text,
                                    flags=re.IGNORECASE | re.DOTALL)
            title = re.sub(r'\s+', ' ', title_match.group(1)).strip() if title_match else ''
            table_count = len(re.findall(r'<table', response.text, flags=re.IGNORECASE))
            if response.status_code != 200 or f'({bare})' not in title or table_count != 0:
                raise
            df = pd.DataFrame()
            df.attrs['empty_evidence'] = {
                'url': url, 'http_status': response.status_code,
                'response_bytes': len(response.content), 'title': title,
                'table_count': table_count,
                'response_sha256': hashlib.sha256(response.content).hexdigest(),
                'interpretation': 'correct stock page returned HTTP 200 and zero HTML tables',
            }
        if df is None or len(df) == 0:
            if df is not None and 'empty_evidence' in df.attrs:
                df.attrs.update(df.attrs.pop('empty_evidence'))
            return df
        df = df.copy()
        df['code'] = code          # 供应商只回裸代码，补回带市场前缀的主键
        return df

    return fetch


def main(argv=None) -> int:
    p = build_parser(__doc__.splitlines()[0], default_dest=DEFAULT_DEST, default_throttle=1.5)
    p.add_argument('--universe-preset', default='stocks-listed', choices=sorted(uni.PRESETS),
                   help='默认证券清单预设（默认 %(default)s）')
    args = p.parse_args(argv)

    codes = read_universe_file(args.universe) if args.universe else uni.resolve(args.universe_preset)
    label = args.universe or ('preset:%s（%s）' % (args.universe_preset, uni.describe(args.universe_preset)))
    print('证券清单  %s' % label)
    if not args.universe:
        print('清单已知局限：%s' % uni.known_limitations())

    env = Envelope(args, name='ths-dividend', source=SOURCE, required_columns=REQUIRED)
    fetch = (lambda code: None) if (args.dry_run or not args.apply) else make_fetcher()
    return env.run(codes, fetch)


if __name__ == '__main__':
    raise SystemExit(main_guard(main))

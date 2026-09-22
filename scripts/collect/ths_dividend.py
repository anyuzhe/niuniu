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

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collect import universe as uni
from collect.envelope import Envelope, build_parser, main_guard, read_universe_file

DEFAULT_DEST = '/Volumes/Lexar/niuniu-data/lake/bronze/provider=ths/corporate_actions_dividend'
SOURCE = 'akshare.stock_fhps_detail_ths'
REQUIRED = ['报告期', '实施公告日', '分红方案说明', 'A股股权登记日', 'A股除权除息日', '方案进度']


def make_fetcher():
    """Import akshare lazily so --help / --dry-run work without it installed."""
    import akshare as ak

    def fetch(code: str):
        df = ak.stock_fhps_detail_ths(symbol=code.split('.')[1])
        if df is None or len(df) == 0:
            return df
        df = df.copy()
        df['code'] = code          # 供应商只回裸代码，补回带市场前缀的主键
        return df

    return fetch


def main(argv=None) -> int:
    p = build_parser(__doc__.splitlines()[0], default_dest=DEFAULT_DEST, default_throttle=1.5)
    p.add_argument('--universe-preset', default='stocks', choices=sorted(uni.PRESETS),
                   help='默认证券清单预设（默认 %(default)s）')
    args = p.parse_args(argv)

    codes = read_universe_file(args.universe) if args.universe else uni.resolve(args.universe_preset)
    label = args.universe or ('preset:%s（%s）' % (args.universe_preset, uni.describe(args.universe_preset)))
    print('证券清单  %s' % label)
    if not args.universe:
        print('清单已知局限：%s' % uni.known_limitations())

    env = Envelope(args, name='ths-dividend', source=SOURCE, required_columns=REQUIRED)
    fetch = (lambda code: None) if args.dry_run else make_fetcher()
    return env.run(codes, fetch)


if __name__ == '__main__':
    raise SystemExit(main_guard(main))

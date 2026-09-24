"""巨潮资讯配股方案采集（akshare ``stock_allotment_cninfo``）。

替代 ``artifacts/data-governance-20260922-D1D3/logs/cninfo-collect.py``。相对旧脚本的整改，
其中前两条是这一轮最要紧的：

  - **不再截列。** 旧脚本用一个 15 列的 ``KEEP`` 白名单做投影，把供应商另外约 40 列
    直接丢掉且不记录丢了什么。停牌起始日、缴款日期、大股东认购数量等字段就是这样
    消失的——而它们恰恰是判定那 19 条未决配股事件所需要的证据。现在**原样保留
    供应商返回的全部列**，只额外插入 ``code`` 主键。
  - **不再从分析产物取清单。** 旧脚本的证券清单来自
    ``d4/rights-issue-adjustment-gaps.csv``，那是一份带上游筛选的分析结果，
    导致采集口径比目标总体少 114 只。现在走 ``scripts/collect/universe.py`` 的具名
    预设，默认 ``tdx-rights-listed``（TDX c4>0 与当前在市 A 股的交集，退市股排除），
    也可以 ``--universe`` 给显式清单；默认运行不会采集退市股。
  - 目标目录、回执路径参数化。旧脚本把 cninfo 的回执写进了 ``ths/`` 目录。
  - ``--resume`` / ``--dry-run`` / 原子写入 / 回读校验统一由采集信封提供。
  - 不再用裸 ``assert`` 做行数校验（``python -O`` 下会被整条优化掉）。

用法（先看计划，不发请求）::

    python scripts/collect/cninfo_allotment.py --dest <新目录> --dry-run

运行采集需要单独授权；本脚本自身不会在被 import 时产生任何副作用。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collect import universe as uni
from collect.envelope import Envelope, build_parser, main_guard, read_universe_file

# No default destination: v1 dropped ~40 vendor columns and must never be resumed;
# name the target explicitly (remediation P5).
DEFAULT_DEST = None
SOURCE = 'akshare.stock_allotment_cninfo'
# 只作为「这一列必须在」的存在性门槛，**不是**投影白名单：其余列一律照单全收。
REQUIRED = ['证券代码', '配股价格', '配股比例', '除权基准日', '股权登记日', '实际配股数量']


def make_fetcher():
    """Import akshare lazily so --help / --dry-run work without it installed."""
    import akshare as ak

    def fetch(code: str):
        df = ak.stock_allotment_cninfo(symbol=code.split('.')[1])
        if df is None or len(df) == 0:
            return df
        df = df.copy()
        df.insert(0, 'code', code)   # 全列保留，只在最前面补带市场前缀的主键
        return df

    return fetch


def main(argv=None) -> int:
    p = build_parser(__doc__.splitlines()[0], default_dest=DEFAULT_DEST, default_throttle=1.2)
    p.add_argument('--universe-preset', default='tdx-rights-listed', choices=sorted(uni.PRESETS),
                   help='默认证券清单预设（默认 %(default)s）')
    args = p.parse_args(argv)

    codes = read_universe_file(args.universe) if args.universe else uni.resolve(args.universe_preset)
    label = args.universe or ('preset:%s（%s）' % (args.universe_preset, uni.describe(args.universe_preset)))
    print('证券清单  %s' % label)
    if not args.universe:
        print('清单已知局限：%s' % uni.known_limitations())
    print('列策略    保留供应商全部列（REQUIRED 仅作存在性门槛，不做投影）')

    env = Envelope(args, name='cninfo-allotment', source=SOURCE, required_columns=REQUIRED)
    fetch = (lambda code: None) if (args.dry_run or not args.apply) else make_fetcher()
    return env.run(codes, fetch)


if __name__ == '__main__':
    raise SystemExit(main_guard(main))

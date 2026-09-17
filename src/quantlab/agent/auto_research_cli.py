"""Host CLI for bounded autonomous limit-board research: plan preview/authorize/revoke, status, queue, host proposals, nightly run.

No network, no trading. AI agents cannot use this CLI; they can only read status and propose into an authorized plan's queue.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from quantlab.storage.codec import digest, encode
from quantlab.trading.auto_research import AutoResearch, AutoResearchError


def _load(path, what):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise AutoResearchError('INVALID_REQUEST', f'{what} 文件读取失败：{str(error)[:200]}') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description='打板自主研究循环（research_only）：宿主授权研究计划，AI 只能提案，夜间只在样本内筛选')
    parser.add_argument('--output', required=True)
    parser.add_argument('--call', required=True, choices=('preview', 'authorize', 'revoke', 'status', 'queue', 'propose', 'run'))
    parser.add_argument('--scope-file', default='', help='preview：研究范围 JSON')
    parser.add_argument('--expires-at', default='', help='preview：计划到期时间（带时区 ISO，1 小时至 30 天）')
    parser.add_argument('--studies-per-week', type=int, default=10)
    parser.add_argument('--runs-per-night', type=int, default=3)
    parser.add_argument('--plan-out', default='', help='preview：写出计划文件（不覆盖已有文件）')
    parser.add_argument('--plan-file', default='', help='authorize：preview 写出的计划文件')
    parser.add_argument('--digest', default='', help='authorize：preview 给出的 plan_digest')
    parser.add_argument('--plan-id', default='', help='revoke：研究计划 ID')
    parser.add_argument('--confirm', action='store_true', help='authorize/revoke：宿主已核对并明确确认')
    parser.add_argument('--state', default='', help='queue：按状态筛选')
    parser.add_argument('--proposal-file', default='', help='propose：提案 JSON')
    parser.add_argument('--proposer', default='host:manual')
    parser.add_argument('--night', default='', help='run：夜间批次日期 YYYY-MM-DD，默认今天')
    parser.add_argument('--max-runs', type=int, default=None)
    args = parser.parse_args(argv)
    try:
        auto = AutoResearch(Path(args.output))
        if args.call == 'preview':
            if not (args.scope_file and args.expires_at and args.plan_out):
                raise AutoResearchError('INVALID_REQUEST', 'preview 需要 --scope-file、--expires-at 与 --plan-out。')
            plan = auto.preview_plan(_load(args.scope_file, 'scope'), expires_at=args.expires_at, studies_per_week=args.studies_per_week,
                                     runs_per_night=args.runs_per_night)
            with Path(args.plan_out).open('x', encoding='utf-8') as stream:
                stream.write(encode(plan))
            data = {'plan': plan, 'plan_digest': digest(plan), 'plan_file': str(Path(args.plan_out).resolve()),
                    'next': '核对计划后 30 分钟内运行 --call authorize --plan-file <计划文件> --digest <plan_digest> --confirm'}
        elif args.call == 'authorize':
            data = auto.authorize_plan(_load(args.plan_file, 'plan'), args.digest, confirmed=args.confirm)
        elif args.call == 'revoke':
            data = auto.revoke_plan(args.plan_id, confirmed=args.confirm)
        elif args.call == 'status':
            data = auto.status()
        elif args.call == 'queue':
            data = {'items': auto.items(state=args.state or None)}
        elif args.call == 'propose':
            if not args.proposer.startswith('host:'):
                raise AutoResearchError('INVALID_REQUEST', '命令行只能以 host: 身份提交提案。')
            data = auto.propose(str(uuid4()), _load(args.proposal_file, 'proposal'), proposer=args.proposer)
        else:
            data = auto.run(night=args.night or None, max_runs=args.max_runs)
        result = {'ok': True, 'data': data}
    except (AutoResearchError, ValueError, OSError) as error:
        result = {'ok': False, 'error': {'code': getattr(error, 'code', None) or 'INVALID_REQUEST', 'message': str(error)[:500]}}
    print(encode(result))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())

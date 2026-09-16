"""Host controls and macOS LaunchAgent for after-close public evidence capture."""
from __future__ import annotations

import argparse
import sys

from quantlab.agent.evidence_scheduler import EvidenceScheduler, SchedulerError, install_agent
from quantlab.storage.codec import encode


def main(argv=None):
    parser = argparse.ArgumentParser(description='收盘后公开证据与当日全市场日线自动归档；不盘中抓取、不补历史、不交易')
    parser.add_argument('--output', required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in ('enable', 'pause', 'tick', 'status', 'install-agent'):
        modes.add_argument('--' + mode, action='store_true')
    parser.add_argument('--confirm', action='store_true')
    parser.add_argument('--authorization', default='')
    args = parser.parse_args(argv)
    try:
        scheduler = EvidenceScheduler(args.output)
        if args.enable:
            result = scheduler.enable(confirmed=args.confirm, authorization=args.authorization)
        elif args.pause:
            result = scheduler.pause()
        elif args.tick:
            result = scheduler.tick()
            if not result['actions']:
                return 0
        elif args.install_agent:
            result = install_agent(args.output)
        else:
            result = scheduler.status()
        print(encode(result))
        return 0
    except (SchedulerError, OSError, ValueError) as error:
        print(encode({'status': 'ERROR', 'code': getattr(error, 'code', 'ERROR'), 'error': str(error)[:500]}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Read-only CLI for P11 System Health."""
import argparse
from pathlib import Path

from quantlab.agent.system_health import SystemHealthService
from quantlab.storage.codec import encode


def main(argv=None):
    parser=argparse.ArgumentParser(description='牛牛 P11 System Health；只读聚合服务/任务/数据/PIT/Dev/Paper健康证据，不执行修复动作')
    parser.add_argument('--output',required=True);parser.add_argument('--data-root')
    args=parser.parse_args(argv)
    try:
        data=SystemHealthService(Path(args.output),Path(args.data_root) if args.data_root else None).build()
        print(encode({'ok':True,'data':data}));return 0
    except (OSError,ValueError,KeyError,TypeError) as error:
        print(encode({'ok':False,'error':{'code':'SYSTEM_HEALTH_READ_FAILED','message':str(error)[:500]}}));return 2


if __name__=='__main__':raise SystemExit(main())

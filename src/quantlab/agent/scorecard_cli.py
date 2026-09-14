"""Read-only CLI for task-separated Agent Scorecard evidence."""
import argparse
from pathlib import Path

from quantlab.agent.scorecard import AgentScorecardError,AgentScorecardService
from quantlab.storage.codec import encode


def main(argv=None):
    parser=argparse.ArgumentParser(description='牛牛 Agent Scorecard；按任务类型只读展示，不生成模型总分或自动调权')
    parser.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    try:data=AgentScorecardService(Path(args.output)).build();reply={'ok':True,'data':data}
    except (AgentScorecardError,OSError,ValueError,KeyError,TypeError) as error:
        reply={'ok':False,'error':{'code':'SCORECARD_READ_FAILED','message':str(error)[:500]}}
    print(encode(reply));return 0 if reply.get('ok') else 2


if __name__=='__main__':raise SystemExit(main())

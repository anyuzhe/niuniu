"""JSON entry for research queries, proposals and durable memory; no approval."""
import argparse
import json
from quantlab.agent.memory_tools import ResearchMemoryAPI
from quantlab.agent.model_config import strict_json


def main(argv=None):
    parser=argparse.ArgumentParser(description='牛牛研究记忆与查询工具')
    parser.add_argument('--output',required=True)
    parser.add_argument('--data-root',default=None)
    parser.add_argument('--schemas',action='store_true')
    parser.add_argument('--call',default='get_capabilities')
    parser.add_argument('--arguments',default='{}')
    args=parser.parse_args(argv)
    try:
        api=ResearchMemoryAPI(args.output,args.data_root)
        result={'tools':api.schemas()} if args.schemas else api.call(args.call,strict_json(args.arguments))
    except (OSError,ValueError,RuntimeError,TypeError) as error:
        result={'ok':False,'error':{'code':'INVALID_REQUEST','message':type(error).__name__}}
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    return 2 if result.get('ok') is False else 0


if __name__=='__main__':
    raise SystemExit(main())

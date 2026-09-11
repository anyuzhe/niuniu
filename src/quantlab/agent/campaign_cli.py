"""JSON entry to campaign query/proposal tools; no approval command."""
import argparse
import json
from quantlab.agent.campaign_tools import ResearchCampaignAPI
from quantlab.agent.planning import parse_spec


def main(argv=None):
    parser=argparse.ArgumentParser(description='固定研究包工具：预检、提案、读取，不批准')
    parser.add_argument('--output',required=True)
    parser.add_argument('--data-root')
    parser.add_argument('--schemas',action='store_true')
    parser.add_argument('--call',default='get_capabilities')
    parser.add_argument('--arguments',default='{}')
    args=parser.parse_args(argv)
    try:
        api=ResearchCampaignAPI(args.output,args.data_root)
        result={'tools':api.schemas()} if args.schemas else api.call(args.call,parse_spec(args.arguments))
    except (ValueError,TypeError,OSError) as error:
        result={'ok':False,'error':{'code':'INVALID_REQUEST','message':type(error).__name__}}
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    return 2 if result.get('ok') is False else 0


if __name__=='__main__':raise SystemExit(main())

"""JSON CLI for the first read-only agent tool boundary."""
import argparse
import json
from quantlab.agent.catalog import ReadOnlyResearchAPI


def main(argv=None):
    parser = argparse.ArgumentParser(description='牛牛研究工具接口（只读，不接模型、不提交研究）')
    parser.add_argument('--output', required=True, help='现有研究产物目录')
    parser.add_argument('--data-root', help='指定只读行情工作空间以启用预算预检和提案工具；批准仅由桌面执行')
    parser.add_argument('--schemas', action='store_true', help='输出模型可用的工具合同')
    parser.add_argument('--call', default='get_capabilities')
    parser.add_argument('--arguments', default='{}', help='JSON 对象参数')
    args = parser.parse_args(argv)
    try:
        from quantlab.agent.proposal_tools import ResearchProposalAPI
        api = ResearchProposalAPI(args.output,args.data_root) if args.data_root else ReadOnlyResearchAPI(args.output)
        def reject_constant(value):
            raise ValueError('JSON 不允许非有限常量')
        values = json.loads(args.arguments, parse_constant=reject_constant)
        result = {'tools': api.schemas(), 'access': 'read_and_propose' if args.data_root else 'read_only'} if args.schemas else api.call(args.call, values)
    except (OSError, ValueError, TypeError, RecursionError) as error:
        result = {'ok': False, 'error': {'code': 'INVALID_REQUEST', 'message': type(error).__name__}}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 2 if result.get('ok') is False else 0


if __name__ == '__main__':
    raise SystemExit(main())

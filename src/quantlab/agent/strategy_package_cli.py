"""Host strategy-package preview/export/proposal; never approve or execute a study."""
from __future__ import annotations

import argparse
from pathlib import Path
from uuid import UUID

from quantlab.agent.planning import parse_spec
from quantlab.storage.codec import encode

MAX_PACKAGE_BYTES = 65536


def _read_package(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError('策略包必须是普通 JSON 文件，不能是符号链接。')
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        raise ValueError('策略包不能超过 64 KiB。')
    with path.open('rb') as stream:
        raw = stream.read(MAX_PACKAGE_BYTES + 1)
    if len(raw) > MAX_PACKAGE_BYTES:
        raise ValueError('策略包不能超过 64 KiB。')
    return parse_spec(raw.decode('utf-8'))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='统一策略包：预览、导出和待批准提案；不批准、不执行、不下单。')
    commands = parser.add_subparsers(dest='command', required=True)
    preview = commands.add_parser('preview', help='只校验策略合同和配置；不读取行情，不创建研究。')
    preview.add_argument('--package', type=Path, required=True)
    preview.add_argument('--export-spec', type=Path, help='明确导出完整研究 spec；不覆盖已有文件。')
    propose = commands.add_parser('propose', help='将核对过的精确策略包交给原提案服务；仍需人工批准。')
    propose.add_argument('--package', type=Path, required=True)
    propose.add_argument('--expected-package-hash', required=True, help='preview 返回的完整 package_hash。')
    propose.add_argument('--expected-compiled-spec-hash', required=True, help='preview 的 compiled_spec_hash，同时固定信号源码/模板解析证据。')
    propose.add_argument('--output', type=Path, required=True)
    propose.add_argument('--data-root', type=Path, required=True)
    propose.add_argument('--request-id', required=True, help='调用者保存的规范 UUID；同一请求重试时复用。')
    versions = commands.add_parser('compare-packages', help='只读比较两份策略配置的逐字段差异。')
    versions.add_argument('--left-package', type=Path, required=True)
    versions.add_argument('--right-package', type=Path, required=True)
    results = commands.add_parser('compare-runs', help='只读对照两个本地策略实验；先核对可比口径，不选择赢家。')
    results.add_argument('--output', type=Path, required=True)
    results.add_argument('--left-run', required=True)
    results.add_argument('--right-run', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in ('compare-packages', 'compare-runs'):
            from quantlab.trading.strategy_comparison import compare_strategy_packages, compare_strategy_runs
            result = (compare_strategy_packages(_read_package(args.left_package), _read_package(args.right_package))
                      if args.command == 'compare-packages' else
                      compare_strategy_runs(args.output, args.left_run, args.right_run))
            print(encode({'ok': True, 'data': result}))
            return 3 if args.command == 'compare-runs' and not result['comparable'] else 0
        from quantlab.trading.strategy_package import compile_strategy
        compiled = compile_strategy(_read_package(args.package))
        if args.command == 'preview':
            if args.export_spec is not None:
                with args.export_spec.open('x', encoding='utf-8') as stream:
                    stream.write(encode(compiled['spec']) + '\n')
            result = {**compiled, 'data_checked': False, 'proposal_created': False,
                      'execution_authorized': False}
        else:
            if (args.expected_package_hash != compiled['package_hash'] or
                    args.expected_compiled_spec_hash != compiled['compiled_spec_hash']):
                raise ValueError('策略包或信号源码/模板解析与已预览指纹不一致，请重新核对；未保存提案。')
            if str(UUID(args.request_id)) != args.request_id:
                raise ValueError('request-id 必须是规范 UUID。')
            if not args.output.is_dir() or not args.data_root.is_dir():
                raise ValueError('output 和 data-root 必须是已有工作空间；此命令不创建数据根。')
            from quantlab.agent.proposals import ProposalService
            proposal = ProposalService(args.output, args.data_root).propose(args.request_id, compiled['spec'])
            result = {'package_hash': compiled['package_hash'], 'compiled_spec_hash': compiled['compiled_spec_hash'],
                      'proposal_id': proposal['proposal_id'],
                      'proposal_digest': proposal['proposal_digest'], 'status': proposal['status'],
                      'execution_authorized': False,
                      'next_step': '在同一工作空间的人工提案审批面板核对完整配置并批准；策略包不是授权。'}
        print(encode({'ok': True, 'data': result}))
        return 0
    except (ValueError, TypeError, KeyError, OSError, RecursionError) as error:
        print(encode({'ok': False, 'error': {'code': getattr(error, 'code', 'INVALID_STRATEGY_PACKAGE'),
                                          'message': str(error)[:500]}}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

"""Explicit portable collector test profile; optional full native-app integration.

Windows nodes deploy the collector, not the complete research application.
The single excluded app integration test is always printed and remains in the Mac profile.
"""
import argparse
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]


def flatten(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from flatten(item)
        else:yield item


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include-native-app',action='store_true')
    args=parser.parse_args()
    found=unittest.TestLoader().discover(str(ROOT/'tests'),pattern='test_tdx*.py')
    cases=[];not_in_profile=[]
    for case in flatten(found):
        if not args.include_native_app and case.id().endswith('.test_native_runtime_can_read_database_without_network_or_new_grant'):
            not_in_profile.append(case.id())
        else:cases.append(case)
    print(json.dumps({'profile':'collector+native-app' if args.include_native_app else 'portable-collector',
        'selected_tests':len(cases),'native_application_not_in_profile':not_in_profile}),flush=True)
    if not cases:raise RuntimeError('No tests discovered')
    result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(cases))
    print(json.dumps({'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'skipped':len(result.skipped),'native_application_not_in_profile':not_in_profile,'ok':result.wasSuccessful()}),flush=True)
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())

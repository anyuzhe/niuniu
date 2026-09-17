"""Evidence-backed, bounded checks for imported QM50 specifications; not a strategy engine."""
from pathlib import Path
from datetime import datetime,timezone
from uuid import uuid4,UUID
import json
from quantlab.agent.research_specs import ResearchSpecStore,SUPPORTED_HASHES,save_new,checked,sha
from quantlab.storage.codec import digest

class SpecTestService:
    def __init__(self,output,data_root=None):
        self.output=Path(output).resolve();self.data_root=Path(data_root).resolve() if data_root else None
        self.store=ResearchSpecStore(output); self.root=self.output/'_research_spec_tests'
    def _spec(self,sid):
        manifest,text,spec=self.store.get(sid)
        if manifest['files']!=SUPPORTED_HASHES:raise ValueError('UNSUPPORTED_SPEC_REVISION：此精确文件版本未由适配器实现，不能只凭同名运行')
        return manifest,text,spec
    def audit(self,sid):
        manifest,_,spec=self.store.get(sid)
        inventory={}
        if self.data_root:
            for key,relative in {'daily_raw':'lake/bronze/provider=baostock/stock_kline_daily',
                'minute5_raw':'lake/bronze/provider=baostock/stock_kline_min5',
                'minute1_raw':'lake/bronze/provider=baostock/stock_kline_min1',
                'calendar':'lake/bronze/provider=baostock/trade_calendar',
                'industry_snapshot':'lake/bronze/provider=baostock/industry'}.items():
                folder=self.data_root/relative
                safe=not any(p.is_symlink() for p in (folder,*list(folder.parents)[:3]))
                inventory[key]={'files':sum(1 for p in folder.glob('*.parquet') if not p.name.startswith('._')) if safe else None,
                    'status':'PRESENT_UNQUALIFIED' if safe and folder.is_dir() else 'NOT_FOUND_OR_UNSAFE',
                    'scope':'只检查此标准目录；存在不等于所需历史时点/语义/覆盖通过'}
        rows=[]
        for f in spec['factors']:
            row={'factor_id':f['id'],'key':f['key'],'group':f['group'],'definition_hash':digest(f),
                'required_data':f['required_data'],'earliest_available':f['earliest_available'],
                'score_transform':f['score_transform'],'strict_status':'UNSUPPORTED',
                'reason':'未注册此文档版本的完整精确原始输入适配器；不使用通用因子或旧qimo代理代替',
                'data_qualification':'NOT_VERIFIED','raw_diagnostic_available':False}
            if f['id']=='P07' and manifest['files']==SUPPORTED_HASHES:
                row.update(raw_diagnostic_available=True,strict_status='MISSING_SOURCE',reason='原始成交额公式已实现；历史时点与完整候选池未认证，只许可独立原始字段诊断')
            if f['id']=='P01' and manifest['files']==SUPPORTED_HASHES:
                row.update(component_contract_available=True,dependency_inspection_available=True,reason='P01/基础资格纯组件合同已实现；完整原始证据字段尚未接齐，不能把组件测试当作真实因子可用')
            rows.append(row)
        return {'spec_id':sid,'source_hashes':manifest['files'],'source_pair_consistent':manifest['consistency']['matched'],
            'exact_revision_supported':manifest['files']==SUPPORTED_HASHES,'contract_test_available':manifest['files']==SUPPORTED_HASHES,'factors':rows,'factor_count':len(rows),
            'archived_daily_input_adapter':{'implemented':True,'source_discovery':'list_qm50_archived_sources','test_tool':'run_qm50_archived_inputs','source_qualification':'provider_retrospective_only','full_factor_implementation':False},
            'inventory':inventory,'full_backtest_status':'BLOCKED','core_score_Q':None,'trades':None,'alpha_verified':False,
            'critical_blockers':['全60项尚无完整精确适配器','竞价实际成交及250日条件历史需要核验','历史流通股本、盘前冻结题材/候选全集及逐日有效涨跌停价需要核验',
                '1分钟/逐笔及排队位置不得由5m或日线替代','entry_notional_budget与cost_budget_bps在原规格中均未填写',
                '盘口过期阈值、固定回归窗口细节等需要参数合同，不得自行补充后仍称原版'],
            'excluded_substitutes':['qimo-source-rules-v2','qimo_paper','BASE.MOMENTUM','DSL.RESTRICTED'],
            'warnings':['UNSUPPORTED表示适配器未具备，不等于已证明这台电脑没有所有相关数据。','60项包含背景/执行约束/诊断，不是60个独立Alpha。']}
    def get(self,sid,test_id):
        self.store.get(sid)
        if str(UUID(test_id))!=test_id:raise ValueError('Invalid test ID')
        folder=self.root/test_id
        if self.root.is_symlink() or folder.is_symlink():raise ValueError('Test folder symlink')
        result=checked(folder/'result.json')
        if result['spec_id']!=sid:raise ValueError('Test belongs to another specification')
        if 'observation_sha256' in result and sha((folder/'observations.parquet').read_bytes())!=result['observation_sha256']:
            raise ValueError('Test observations changed')
        if 'coverage_sha256' in result and sha((folder/'coverage.parquet').read_bytes())!=result['coverage_sha256']:
            raise ValueError('Coverage evidence changed')
        return result
    def run(self,sid,args):
        manifest,_,spec=self._spec(sid)
        kind=args['kind']
        if kind not in ('CONTRACT_GUARDS','P07_DIAGNOSTIC','BASE_RULES_GUARDS','BASE_RULES_COVERAGE'):raise ValueError('UNSUPPORTED_FACTOR_OR_TEST：不得以其他因子替换')
        if kind in ('CONTRACT_GUARDS','BASE_RULES_GUARDS') and any(args[k] for k in ('symbols','start','end')):raise ValueError('合成合同测试不接受行情参数')
        if self.root.is_symlink():raise ValueError('Test root symlink')
        test_id=str(uuid4());folder=self.root/test_id;folder.mkdir(parents=True,exist_ok=False)
        from quantlab.experiments.runner import runtime_fingerprint
        result={'test_id':test_id,'spec_id':sid,'kind':kind,'source_hashes':manifest['files'],'requested':args,
            'started_at':datetime.now(timezone.utc).isoformat(),'runtime':runtime_fingerprint(),
            'full_model_backtest':False,'alpha_verified':False,'status':'RUNNING'}
        save_new(folder/'request.json',result)
        try:
            if kind=='CONTRACT_GUARDS':
                from quantlab.trading.qm50_contract import contract_checks
                detail=contract_checks(spec);result.update(status=detail['status'],detail=detail)
            elif kind=='BASE_RULES_GUARDS':
                from quantlab.trading.qm50_base_contract import run_base_guards
                detail=run_base_guards();result.update(status=detail['status'],detail=detail)
            elif kind=='BASE_RULES_COVERAGE':
                from quantlab.agent.qm50_base_coverage import inspect_base_coverage
                import polars as pl
                rows,detail=inspect_base_coverage(self.data_root,args['symbols'],args['start'],args['end'])
                flat=[{**{k:v for k,v in row.items() if k not in ('session_checks','evidence','reason_codes')},
                    'session_checks_json':json.dumps(row['session_checks'],ensure_ascii=False),
                    'evidence_json':json.dumps(row['evidence'],ensure_ascii=False),
                    'reason_codes_json':json.dumps(row['reason_codes'],ensure_ascii=False)} for row in rows]
                pl.DataFrame(flat).write_parquet(folder/'coverage.parquet')
                result.update(status='AUDIT_COMPLETED_INPUTS_BLOCKED',detail=detail,
                    coverage_sha256=sha((folder/'coverage.parquet').read_bytes()))
            else:
                from quantlab.agent.spec_p07_diagnostic import diagnose
                frame,detail=diagnose(self.data_root,args['symbols'],args['start'],args['end'])
                frame.write_parquet(folder/'observations.parquet')
                result.update(status='DIAGNOSTIC_COMPLETED_NOT_STRICT',detail=detail,
                    observation_sha256=sha((folder/'observations.parquet').read_bytes()))
        except Exception as exc:
            result.update(status='FAILED',error=type(exc).__name__+': '+str(exc)[:350])
        result['finished_at']=datetime.now(timezone.utc).isoformat()
        save_new(folder/'result.json',result)
        return result

    def run_archived(self,sid,args,source_workspace):
        manifest,_,_=self._spec(sid)
        if not source_workspace:raise ValueError('Host must bind the archive source workspace')
        from quantlab.agent.qm50_archived_inputs import ArchivedDailyBridge,materialize
        if self.root.is_symlink():raise ValueError('Test root symlink')
        test_id=str(uuid4());folder=self.root/test_id;folder.mkdir(parents=True,exist_ok=False)
        from quantlab.experiments.runner import runtime_fingerprint
        result={'test_id':test_id,'spec_id':sid,'kind':'ARCHIVED_DAILY_INPUTS','source_hashes':manifest['files'],
            'requested':args,'source_workspace':str(Path(source_workspace).resolve()),'runtime':runtime_fingerprint(),
            'started_at':datetime.now(timezone.utc).isoformat(),'full_model_backtest':False,'alpha_verified':False,'status':'RUNNING'}
        save_new(folder/'request.json',result)
        try:
            detail=materialize(ArchivedDailyBridge(source_workspace),args['capture_id'],args['symbols'],args['start'],args['end'],folder)
            result.update(status='MATERIALIZED_RETROSPECTIVE_INPUTS',detail=detail,
                          observation_sha256=sha((folder/'observations.parquet').read_bytes()))
        except Exception as exc:result.update(status='FAILED',error=type(exc).__name__+': '+str(exc)[:350])
        result['finished_at']=datetime.now(timezone.utc).isoformat();save_new(folder/'result.json',result)
        return result
    def replay_archived(self,sid,test_id):
        result=self.get(sid,test_id)
        if result['kind']!='ARCHIVED_DAILY_INPUTS' or result['status']!='MATERIALIZED_RETROSPECTIVE_INPUTS':
            raise ValueError('Only a completed archived-input test can be replayed')
        from quantlab.agent.qm50_archived_inputs import replay
        return {'test_id':test_id,'spec_id':sid,**replay(self.root/test_id,result['detail'])}

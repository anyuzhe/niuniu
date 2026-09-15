"""Host CLI for Research Session Grant preview/authorize/revoke/status."""
import argparse,json
from pathlib import Path
from quantlab.agent.research_session_grant import preview_grant,authorize_grant,revoke_grant,grant_status
from quantlab.storage.codec import encode,digest

def _json_file(path):
    value=json.loads(Path(path).read_text())
    if not isinstance(value,dict):raise ValueError('JSON 文件必须是对象')
    return value

def main(argv=None):
    p=argparse.ArgumentParser(description='Research Session Grant 宿主管理；模型不能创建/撤销授权')
    p.add_argument('action',choices=['preview','authorize','revoke','status']);p.add_argument('--output',required=True);p.add_argument('--data-root')
    p.add_argument('--scope-file');p.add_argument('--plan-file');p.add_argument('--expires-at');p.add_argument('--grant-id');p.add_argument('--confirm',action='store_true')
    p.add_argument('--max-jobs',type=int,default=5);p.add_argument('--max-active-jobs',type=int,default=2);p.add_argument('--max-leaf-studies',type=int,default=32)
    p.add_argument('--max-total-leaf-studies',type=int,default=80);p.add_argument('--max-total-bar-evaluations',type=int,default=20_000_000)
    p.add_argument('--max-total-resample-date-draws',type=int,default=100_000_000);p.add_argument('--cooperative-seconds',type=int,default=300)
    a=p.parse_args(argv)
    try:
        if a.action=='status':data=grant_status(a.output,a.data_root)
        elif a.action=='preview':
            if not a.data_root or not a.scope_file or not a.expires_at:raise ValueError('preview 需要 --data-root/--scope-file/--expires-at')
            data=preview_grant(a.output,a.data_root,_json_file(a.scope_file),expires_at=a.expires_at,max_jobs=a.max_jobs,
                max_active_jobs=a.max_active_jobs,max_leaf_studies=a.max_leaf_studies,max_total_leaf_studies=a.max_total_leaf_studies,
                max_total_bar_evaluations=a.max_total_bar_evaluations,max_total_resample_date_draws=a.max_total_resample_date_draws,
                cooperative_seconds=a.cooperative_seconds)
            data={'plan':data,'plan_digest':digest(data)}
        elif a.action=='authorize':
            if not a.data_root or not a.plan_file:raise ValueError('authorize 需要 --data-root/--plan-file')
            value=_json_file(a.plan_file);plan=value.get('plan',value);expected=value.get('plan_digest',digest(plan))
            data=authorize_grant(a.output,a.data_root,plan,expected,confirmed=a.confirm)
        else:
            if not a.grant_id:raise ValueError('revoke 需要 --grant-id')
            data=revoke_grant(a.output,a.grant_id,confirmed=a.confirm)
        print(encode({'ok':True,'data':data}));return 0
    except (ValueError,KeyError,TypeError,OSError,json.JSONDecodeError) as exc:
        print(encode({'ok':False,'error':{'code':'SESSION_GRANT_FAILED','message':str(exc)[:500]}}));return 2

if __name__=='__main__':raise SystemExit(main())

"""Host controls and macOS scheduler for the experimental paper account."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from quantlab.storage.codec import encode
from quantlab.trading.qimo_paper import QimoPaperRunner

LABEL='com.niuniu.qimo-paper'


def install_agent(output,data_root):
    if sys.platform!='darwin':raise ValueError('自动安装仅支持 macOS；其他平台可定时运行 --tick。')
    output=Path(output).resolve();data_root=Path(data_root).resolve()
    if not (output/'_qimo_paper/control.json').exists():raise ValueError('先启用并保存模拟盘授权。')
    folder=Path.home()/'Library/LaunchAgents';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(LABEL+'.plist');logs=output/'_qimo_paper'
    config={'Label':LABEL,'ProgramArguments':[sys.executable,'-m','quantlab.agent.qimo_paper_cli',
        '--output',str(output),'--data-root',str(data_root),'--tick'],
        'WorkingDirectory':str(Path(__file__).resolve().parents[3]),'StartInterval':30,'RunAtLoad':True,
        'ProcessType':'Background','StandardOutPath':str(logs/'scheduler.log'),
        'StandardErrorPath':str(logs/'scheduler.error.log')}
    if path.exists() and plistlib.loads(path.read_bytes())!=config:
        raise ValueError('同名后台任务已有不同配置，请先检查 '+str(path))
    path.write_bytes(plistlib.dumps(config))
    domain='gui/'+str(os.getuid())
    loaded=subprocess.run(['launchctl','print',domain+'/'+LABEL],capture_output=True,text=True)
    if loaded.returncode!=0:
        result=subprocess.run(['launchctl','bootstrap',domain,str(path)],capture_output=True,text=True)
        if result.returncode:raise ValueError('launchctl bootstrap: '+result.stderr.strip())
    return {'installed':True,'label':LABEL,'plist':str(path),'interval_seconds':30,
        'requires':'Mac 登录、联网、外置盘挂载；休眠期间不运行。'}


def main(argv=None):
    parser=argparse.ArgumentParser(description='期末50分实验代理自动模拟盘；不连接券商')
    parser.add_argument('--output',required=True);parser.add_argument('--data-root',required=True)
    modes=parser.add_mutually_exclusive_group(required=True)
    for mode in ('enable','tick','status','pause','install-agent'):modes.add_argument('--'+mode,action='store_true')
    parser.add_argument('--source-definition-id');parser.add_argument('--confirm',action='store_true')
    args=parser.parse_args(argv)
    try:
        runner=QimoPaperRunner(args.output,args.data_root)
        if args.enable:result=runner.enable(args.source_definition_id,confirmed=args.confirm)
        elif args.pause:result=runner.pause()
        elif args.tick:result=runner.tick()
        elif args.install_agent:result=install_agent(args.output,args.data_root)
        else:result=runner.status()
        print(encode(result));return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(encode({'status':'ERROR','error':str(exc)}),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())

from argparse import ArgumentParser
from pathlib import Path
from .app import launch

parser=ArgumentParser(description='牛牛 PyQt6 原生研究平台')
parser.add_argument('--output',type=Path,default=Path('artifacts'))
parser.add_argument('--data-root',type=Path)
args=parser.parse_args()
raise SystemExit(launch(args.output,args.data_root))

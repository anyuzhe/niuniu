#!/bin/zsh
project_dir="${0:A:h}"
cd "$project_dir" || exit 1
# 本机私有凭证（问财等数据源 key），.env 已被 .gitignore 忽略
if [ -f "$project_dir/.env" ]; then set -a; source "$project_dir/.env"; set +a; fi
# 交易日自动启动盘中记录器（用户 2026-09-25 授权）；非交易日、已收盘或已在运行时什么都不做
"$project_dir/.venv/bin/python" "$project_dir/scripts/collect/autostart.py" >> "$project_dir/artifacts/autostart.log" 2>&1 &
# 值班程序（用户 2026-09-29 授权）：牛牛开着时，每个交易日 09:10 起启动盘中记录器、16:30 起跑收盘后日常更新；牛牛关闭即退出
"$project_dir/.venv/bin/python" "$project_dir/scripts/collect/scheduler.py" --parent-pid $$ >> "$project_dir/artifacts/scheduler.log" 2>&1 &
exec "$project_dir/.venv/bin/python" -m quantlab.cli desktop --output "$project_dir/artifacts" --data-root /Volumes/Lexar/niuniu-data

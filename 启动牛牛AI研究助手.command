#!/bin/zsh
project_dir="${0:A:h}"
cd "$project_dir" || exit 1
# 本机私有凭证（问财等数据源 key），.env 已被 .gitignore 忽略
if [ -f "$project_dir/.env" ]; then set -a; source "$project_dir/.env"; set +a; fi
# 交易日自动启动盘中记录器（用户 2026-09-25 授权）；非交易日、已收盘或已在运行时什么都不做
"$project_dir/.venv/bin/python" "$project_dir/scripts/collect/autostart.py" >> "$project_dir/artifacts/autostart.log" 2>&1 &
exec "$project_dir/.venv/bin/python" -m quantlab.agent.chat_cli --gui --output "$project_dir/artifacts" --data-root /Volumes/Lexar/niuniu-data

#!/bin/zsh
project_dir="${0:A:h}"
cd "$project_dir" || exit 1
# 本机私有凭证（问财等数据源 key），.env 已被 .gitignore 忽略
if [ -f "$project_dir/.env" ]; then set -a; source "$project_dir/.env"; set +a; fi
exec "$project_dir/.venv/bin/python" -m quantlab.agent.chat_cli --gui --output "$project_dir/artifacts" --data-root /Volumes/Lexar/niuniu-data

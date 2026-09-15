#!/bin/zsh
project_dir="${0:A:h}"
cd "$project_dir" || exit 1
exec "$project_dir/.venv/bin/python" -m quantlab.agent.chat_cli --gui --output "$project_dir/artifacts" --data-root /Volumes/Lexar/niuniu-data

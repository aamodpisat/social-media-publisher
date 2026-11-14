#!/usr/bin/env bash
set -eu
TASK_DIR="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
cd "$TASK_DIR"
exec "$TASK_DIR/.venv/bin/python" "$TASK_DIR/mcp_main.py" "$@"

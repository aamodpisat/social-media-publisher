#!/usr/bin/env bash
set -eu
TASK_DIR="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
cd "$TASK_DIR"
python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11 or newer is required"'
if [ ! -x "$TASK_DIR/.venv/bin/python" ]; then
  python3 -m venv "$TASK_DIR/.venv"
fi
DEPENDENCY_HASH="$(sha256sum requirements.lock.txt | cut -d ' ' -f 1)"
CURRENT_HASH=""
if [ -f .venv/dependencies.sha256 ]; then CURRENT_HASH="$(cat .venv/dependencies.sha256)"; fi
if [ "$DEPENDENCY_HASH" != "$CURRENT_HASH" ] || ! .venv/bin/python -c 'import requests, dotenv, filelock, google.cloud.storage, PIL' >/dev/null 2>&1; then
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements.lock.txt
  printf '%s\n' "$DEPENDENCY_HASH" > .venv/dependencies.sha256
fi
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "FFmpeg/FFprobe are missing. Install FFmpeg in the cloud environment setup before publishing." >&2
  exit 1
fi
mkdir -p work data preview
chmod 700 work data preview
printf '%s\n' "Automation dependencies are ready. No media was published."

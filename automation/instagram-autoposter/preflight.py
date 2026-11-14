#!/usr/bin/env python3
"""Local readiness check. Prints setting names and status, never secret values."""
import json
import os
import shutil
from pathlib import Path
import sys

import mcp_main as app


def check():
    app.apply_host_aliases()
    missing = []
    names = (
        "GOOGLE_DRIVE_FOLDER_ID",
        "GOOGLE_DRIVE_POSTS_FOLDER_ID", "GOOGLE_DRIVE_STORIES_FOLDER_ID", "GOOGLE_DRIVE_REELS_FOLDER_ID", "INSTAGRAM_EXPECTED_USERNAME",
        "INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_BUSINESS_ACCOUNT_ID",
        "GCS_BUCKET_NAME", "GCS_SERVICE_ACCOUNT_JSON",
        "BRAND_NAME", "BRAND_NICHE", "BRAND_AUDIENCE", "BRAND_VOICE",
        "BRAND_OFFER", "BRAND_CTA", "BRAND_HASHTAG",
    )
    for name in names:
        ready = bool(os.getenv(name, "").strip())
        print(f"{'READY' if ready else 'MISSING'}: {name}")
        if not ready:
            missing.append(name)
    print("READY: OPENAI_API_KEY" if os.getenv("OPENAI_API_KEY", "").strip() else "OPTIONAL FOR STORIES: OPENAI_API_KEY is missing; feed/Reel captions require it")
    raw = os.getenv("GCS_SERVICE_ACCOUNT_JSON", "").strip()
    key_ready = False
    if raw:
        try:
            info = json.loads(raw) if raw.startswith("{") else json.loads(
                (app.core.ROOT / raw).read_text(encoding="utf-8"))
            key_ready = bool(info.get("private_key") and info.get("client_email") and info.get("project_id"))
        except Exception:
            pass
    print(f"{'READY' if key_ready else 'MISSING'}: readable Storage signing key")
    if not key_ready:
        missing.append("STORAGE_SIGNING_KEY_FILE")
    state_name = os.getenv("STATE_PATH", "data/processed_images.json")
    state_path = Path(state_name)
    if not state_path.is_absolute():
        state_path = app.core.ROOT / state_path
    print("Posting record: " + ("exists; will be validated before use" if state_path.exists() else "not initialized; do not initialize until folder/account are correct"))
    for executable in ("ffmpeg", "ffprobe"):
        ready = bool(shutil.which(executable))
        print(f"{'READY' if ready else 'MISSING'}: {executable}")
        if not ready:
            missing.append(executable)
    print("Drive MCP: requires a real folder fetch/materialization test")
    print("API networking: requires the four service hosts in environment settings")
    print("RESULT: " + ("Configuration incomplete; no post attempted." if missing else "Local settings present; live service checks still required."))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(check())

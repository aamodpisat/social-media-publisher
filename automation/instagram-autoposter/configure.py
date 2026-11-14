#!/usr/bin/env python3
"""Interactive local setup; retains existing secrets and never prints them."""
from getpass import getpass
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

from dotenv import set_key
import mcp_main as app


def ask(label, current="", secret=False):
    if secret:
        return getpass(label + (" [Enter keeps existing]" if current else "") + ": ").strip() or current
    return input(label + (" [Enter keeps existing]" if current else "") + ": ").strip() or current


def main():
    app.apply_host_aliases()
    root = app.core.ROOT
    env = root / ".env"
    values = {}
    folder = ask("Google Drive folder URL or ID", os.getenv("GOOGLE_DRIVE_FOLDER_ID", ""))
    if folder.startswith("https://"):
        parsed = urlparse(folder)
        if parsed.hostname != "drive.google.com":
            raise ValueError("Use a Google Drive folder URL.")
        match = re.search(r"/folders/([A-Za-z0-9_-]+)", parsed.path)
        if not match:
            raise ValueError("The URL must identify a folder.")
        folder = match.group(1)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", folder):
        raise ValueError("A valid folder ID is required.")
    values["GOOGLE_DRIVE_FOLDER_ID"] = folder
    for name, label in (
        ("BRAND_NAME", "Business name"), ("BRAND_NICHE", "Niche or industry"),
        ("BRAND_AUDIENCE", "Target audience and struggles"), ("BRAND_VOICE", "Writing tone"),
        ("BRAND_OFFER", "Actual offer"), ("BRAND_CTA", "One call to action"),
        ("BRAND_HASHTAG", "One branded hashtag, including #"),
        ("GCS_BUCKET_NAME", "Private Storage bucket name"),
    ):
        values[name] = ask(label, os.getenv(name, ""))
        if not values[name]:
            raise ValueError(f"{name} is required. Nothing was saved.")
    if not re.fullmatch(r"#\w+", values["BRAND_HASHTAG"], re.UNICODE):
        raise ValueError("Use one hashtag without spaces.")
    values["GCS_SERVICE_ACCOUNT_JSON"] = ask(
        "Storage key path", os.getenv("GCS_SERVICE_ACCOUNT_JSON", "secrets/google-service-account.json"))
    for name, label in (("OPENAI_API_KEY", "OpenAI API key"),
                        ("INSTAGRAM_ACCESS_TOKEN", "Instagram Page access token"),
                        ("INSTAGRAM_BUSINESS_ACCOUNT_ID", "Numeric Instagram account ID")):
        existing = os.getenv(name, "").strip()
        if existing:
            print(label + ": using the existing environment setting.")
        else:
            values[name] = ask(label, secret=name != "INSTAGRAM_BUSINESS_ACCOUNT_ID")
            if not values[name]:
                raise ValueError(f"{name} is required. Nothing was saved.")
    account = values.get("INSTAGRAM_BUSINESS_ACCOUNT_ID") or os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
    if not account.isdigit():
        raise ValueError("Instagram account ID must be numeric.")
    record_path = Path(os.getenv("STATE_PATH", "data/processed_images.json"))
    if not record_path.is_absolute():
        record_path = root / record_path
    if record_path.exists():
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("binding") != {"folder_id": folder, "instagram_account_id": account}:
            raise ValueError("Existing posting record belongs to a different folder/account. No settings were saved.")
    env.touch(exist_ok=True)
    env.chmod(0o600)
    for name, value in values.items():
        set_key(str(env), name, value)
    print("Settings saved privately to .env. No posting record was reset and no post was attempted.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyboardInterrupt) as exc:
        print(str(exc) if isinstance(exc, ValueError) else "Setup canceled.", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Setup stopped ({type(exc).__name__}). No credential values were printed.", file=sys.stderr)
        sys.exit(1)

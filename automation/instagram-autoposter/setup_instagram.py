#!/usr/bin/env python3
"""Interactive Facebook Login token exchange. Never prints access tokens."""
from getpass import getpass
from pathlib import Path
import re
import sys

from dotenv import load_dotenv, set_key
import os
import requests

ROOT = Path(__file__).resolve().parent


def call(session, url, **kwargs):
    response = session.get(url, timeout=(15, 60), **kwargs)
    if not response.ok:
        raise ValueError(f"Meta rejected the request (HTTP {response.status_code}). Check app roles, selected Pages, token and permissions.")
    return response.json()


def main():
    load_dotenv(ROOT / ".env")
    version = input("Graph API version [v27.0]: ").strip() or "v27.0"
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise ValueError("Use a version such as v27.0.")
    app_id = input("Meta App ID: ").strip()
    app_secret = getpass("Meta App Secret (hidden): ").strip()
    short_token = getpass("Short-lived Facebook USER access token (hidden): ").strip()
    if not app_id.isdigit() or not app_secret or not short_token:
        raise ValueError("App ID, app secret and user token are required.")
    session = requests.Session()
    base = f"https://graph.facebook.com/{version}"
    exchanged = call(session, f"{base}/oauth/access_token", params={
        "grant_type": "fb_exchange_token", "client_id": app_id,
        "client_secret": app_secret, "fb_exchange_token": short_token})
    user_token = exchanged["access_token"]
    pages = []
    after = None
    while True:
        params = {"fields": "id,name,access_token,instagram_business_account{id,username}", "limit": 100}
        if after:
            params["after"] = after
        payload = call(session, f"{base}/me/accounts", params=params,
                       headers={"Authorization": f"Bearer {user_token}"})
        pages.extend(payload.get("data", []))
        paging = payload.get("paging", {})
        if not paging.get("next"):
            break
        after = paging.get("cursors", {}).get("after")
        if not after:
            raise ValueError("Meta pagination was incomplete. Use the Graph API Explorer to find your Page.")
    eligible = [p for p in pages if p.get("instagram_business_account", {}).get("id") and p.get("access_token")]
    if not eligible:
        raise ValueError("No eligible Pages found. Link your Professional Instagram account to a Page, grant Page access and required permissions, then generate a new user token.")
    for index, page in enumerate(eligible, 1):
        account = page["instagram_business_account"]
        print(f"{index}. {page['name']} — Instagram @{account.get('username', 'unknown')} (ID {account['id']})")
    selection = int(input("Enter the number for the account you want to publish to: ")) - 1
    if selection < 0 or selection >= len(eligible):
        raise ValueError("Choose a number from the displayed list.")
    page = eligible[selection]
    env_file = ROOT / ".env"
    env_file.touch(exist_ok=True)
    if os.name == "posix":
        env_file.chmod(0o600)
    set_key(str(env_file), "META_GRAPH_VERSION", version)
    set_key(str(env_file), "INSTAGRAM_ACCESS_TOKEN", page["access_token"])
    set_key(str(env_file), "INSTAGRAM_BUSINESS_ACCOUNT_ID", page["instagram_business_account"]["id"])
    print("Saved the long-lived PAGE access token and Instagram account ID to .env. No post was created.")
    print("Page tokens can still be revoked. Regenerate them if Meta reports an invalid token.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError) as exc:
        # Only our own ValueErrors are displayed; never display raw HTTP responses.
        if isinstance(exc, ValueError) and not isinstance(exc, requests.exceptions.JSONDecodeError):
            print(str(exc) if str(exc).startswith(("Meta rejected", "Use a version", "App ID", "No eligible", "Choose a number", "Meta pagination")) else "Invalid selection or response. Run setup again.", file=sys.stderr)
        else:
            print("Meta returned an unexpected response. Check your token and app setup.", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Setup stopped ({type(exc).__name__}). Check connectivity and run again. Credentials were not printed.", file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""Download or permanently delete one private Google Drive file.

Uses the user's OAuth refresh token. The Storage service account is never used.
Tokens, Authorization headers, and download URLs are not printed.
"""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sys

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

import main as core
import mcp_main

DRIVE_API = "https://www.googleapis.com/drive/v3/files"
SCOPES = ["https://www.googleapis.com/auth/drive"]
IMAGE_LIMIT = 25 * 1024 * 1024
AUDIO_LIMIT = 25 * 1024 * 1024
VIDEO_LIMIT = 250 * 1024 * 1024
METADATA_FIELDS = "id,name,mimeType,parents,md5Checksum,createdTime,trashed,size"


def build_credentials():
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    refresh = os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN", "").strip()
    if not client_id or not client_secret or not refresh:
        raise core.SafeError(
            "Drive login is not configured. Add GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, "
            "and GOOGLE_DRIVE_REFRESH_TOKEN in the cloud environment secrets. Nothing was changed.")
    return Credentials(
        token=None,
        refresh_token=refresh,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )


def authorized_session(credentials=None):
    credentials = credentials or build_credentials()
    try:
        credentials.refresh(Request())
    except Exception:
        raise core.SafeError(
            "Google Drive login was rejected. Renew GOOGLE_DRIVE_REFRESH_TOKEN in the environment secrets. "
            "Nothing was changed.") from None
    if not credentials.token:
        raise core.SafeError("Google Drive login did not return an access token. Nothing was changed.")
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {credentials.token}"
    return session


def _check_response(response, action):
    if response.is_redirect or response.status_code in {301, 302, 303, 307, 308}:
        raise core.SafeError(f"Drive {action} was redirected. Nothing was changed.")
    return response


def fetch_metadata(session, file_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
        raise core.SafeError("Invalid Drive file ID. Nothing was changed.")
    response = _check_response(session.get(
        f"{DRIVE_API}/{file_id}",
        params={"fields": METADATA_FIELDS, "supportsAllDrives": "true"},
        timeout=60,
        allow_redirects=False,
    ), "metadata request")
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise core.SafeError(f"Drive metadata request failed ({response.status_code}). Nothing was changed.")
    try:
        payload = response.json()
    except ValueError:
        raise core.SafeError("Drive metadata was not JSON. Nothing was changed.") from None
    if payload.get("id") != file_id:
        raise core.SafeError("Drive returned a different file ID. Nothing was changed.")
    return payload


def _parents(metadata):
    parents = metadata.get("parents")
    if not isinstance(parents, list) or not parents or any(not isinstance(parent, str) for parent in parents):
        raise core.SafeError("Drive file is missing a parent folder. Nothing was changed.")
    return parents


def _size(metadata):
    try:
        size = int(metadata["size"])
    except (KeyError, TypeError, ValueError):
        raise core.SafeError("Drive file is missing its size. Nothing was changed.") from None
    if size <= 0:
        raise core.SafeError("Drive file size is empty. Nothing was changed.")
    return size


def limit_for(metadata, source_ids, music_folder, *, allow_trashed=False):
    parents = _parents(metadata)
    if metadata.get("trashed") is True and not allow_trashed:
        raise core.SafeError("Drive file is in the trash. Nothing was changed.")
    mime = metadata.get("mimeType")
    name = metadata.get("name")
    if not isinstance(name, str) or not name:
        raise core.SafeError("Drive file is missing its name. Nothing was changed.")
    suffix = Path(name).suffix.lower()
    in_sources = [parent for parent in parents if parent in source_ids]
    in_music = bool(music_folder) and music_folder in parents
    if in_music and in_sources:
        raise core.SafeError("A file cannot be both a music track and a publishing source. Nothing was changed.")
    if in_music:
        if mime != "audio/mpeg" or suffix != ".mp3":
            raise core.SafeError("Music folder files must be MP3. Nothing was changed.")
        return AUDIO_LIMIT, suffix
    if len(in_sources) != 1:
        raise core.SafeError("File must belong to exactly one Posts, Stories, or Reels folder. Nothing was changed.")
    image = mime in {"image/jpeg", "image/png"} and suffix in {".jpg", ".jpeg", ".png"}
    video = mime in {"video/mp4", "video/quicktime"} and suffix in {".mp4", ".mov"}
    if image:
        return IMAGE_LIMIT, suffix
    if video:
        return VIDEO_LIMIT, suffix
    raise core.SafeError("This file type is not a publishing source. Nothing was changed.")


def download_original(session, file_id, dest_dir, source_ids, music_folder):
    metadata = fetch_metadata(session, file_id)
    if metadata is None:
        raise core.SafeError("Drive file was not found. Nothing was saved.")
    limit, suffix = limit_for(metadata, source_ids, music_folder)
    size = _size(metadata)
    if size > limit:
        raise core.SafeError("Drive file exceeds the workflow size limit. Nothing was saved.")
    response = _check_response(session.get(
        f"{DRIVE_API}/{file_id}",
        params={"alt": "media", "supportsAllDrives": "true"},
        timeout=300,
        stream=True,
        allow_redirects=False,
    ), "download")
    if response.status_code != 200:
        raise core.SafeError(f"Drive download failed ({response.status_code}). Nothing was saved.")
    chunks = []
    total = 0
    for chunk in response.iter_content(1024 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > limit:
            raise core.SafeError("Drive download exceeded the workflow size limit. Nothing was saved.")
        chunks.append(chunk)
    raw = b"".join(chunks)
    if len(raw) != size:
        raise core.SafeError("Downloaded byte count differs from Drive's reported size. Nothing was saved.")
    destination = Path(dest_dir)
    if not destination.is_absolute():
        destination = core.ROOT / destination
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"{file_id}{suffix}"
    path.write_bytes(raw)
    os.chmod(path, 0o600)
    manifest = {
        "file_id": file_id,
        "filename": metadata["name"],
        "mime_type": metadata["mimeType"],
        "parent_ids": metadata["parents"],
        "file_size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "local_path": str(path.resolve()),
    }
    checksum = metadata.get("md5Checksum")
    if isinstance(checksum, str) and re.fullmatch(r"[a-fA-F0-9]{32}", checksum):
        manifest["md5_checksum"] = checksum.lower()
    return manifest


def deletion_allowed(metadata, record_status, source_ids, music_folder):
    """Return True when a published source file may be permanently deleted.

    A missing Drive file is not decided here. Callers handle a 404 separately.
    """
    if record_status != "published":
        raise core.SafeError("This file is not a confirmed published source. It was not deleted.")
    if metadata is None:
        return True
    parents = _parents(metadata)
    if music_folder and music_folder in parents:
        raise core.SafeError("Music tracks are reused and are never deleted.")
    if metadata.get("mimeType", "").startswith("audio/"):
        raise core.SafeError("Audio files are never deleted.")
    in_sources = [parent for parent in parents if parent in source_ids]
    if len(in_sources) != 1 or len(parents) != 1:
        raise core.SafeError("Only a direct child of Posts, Stories, or Reels can be deleted. Nothing was deleted.")
    limit_for(metadata, source_ids, music_folder, allow_trashed=True)
    return True


def delete_published_source(session, file_id, record_status, source_ids, music_folder):
    metadata = fetch_metadata(session, file_id)
    if metadata is None:
        if record_status != "published":
            raise core.SafeError("This file is not a confirmed published source. It was not deleted.")
        return "already-absent"
    deletion_allowed(metadata, record_status, source_ids, music_folder)
    response = _check_response(session.delete(
        f"{DRIVE_API}/{file_id}",
        params={"supportsAllDrives": "true"},
        timeout=60,
        allow_redirects=False,
    ), "delete")
    if response.status_code == 404:
        return "already-absent"
    if response.status_code not in {200, 204}:
        raise core.SafeError(f"Drive delete failed ({response.status_code}). The Instagram post was not changed.")
    return "deleted"


def _source_ids(cfg):
    return set(cfg.sources)


def _record_status(cfg, file_id):
    state = core.load_state(cfg)
    record = state["records"].get(file_id)
    if not isinstance(record, dict):
        return None
    return record.get("status")


def main(argv=None):
    mcp_main.apply_host_aliases()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
    for name in ("google", "urllib3", "requests"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--download", action="store_true")
    action.add_argument("--delete", action="store_true")
    parser.add_argument("--file-id", required=True)
    parser.add_argument("--dest", default="work/originals")
    args = parser.parse_args(argv)
    try:
        cfg = mcp_main.MCPConfig()
        session = authorized_session()
        if args.download:
            manifest = download_original(session, args.file_id, args.dest, _source_ids(cfg), cfg.music_folder)
            print(json.dumps(manifest, ensure_ascii=False))
            return 0
        outcome = delete_published_source(
            session, args.file_id, _record_status(cfg, args.file_id), _source_ids(cfg), cfg.music_folder)
        core.LOG.info("Drive source file %s.", outcome)
        return 0
    except core.SafeError as exc:
        core.LOG.error("Stopped: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

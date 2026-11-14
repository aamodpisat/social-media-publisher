#!/usr/bin/env python3
"""MCP handoff entry point. Reuses main.py without direct Google Drive access."""
import argparse
from contextlib import nullcontext
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sys
from datetime import timedelta

import requests
from filelock import FileLock, Timeout
from google.cloud import storage
from google.oauth2 import service_account

import main as core
import media_pipeline as pipeline
import music
from remote_state import RemoteState
from dotenv import load_dotenv


def apply_host_aliases():
    load_dotenv(core.ROOT / ".env", override=False)
    private_defaults = core.ROOT / "runtime-config.json"
    if private_defaults.exists():
        allowed = {"GOOGLE_DRIVE_FOLDER_ID", "GOOGLE_DRIVE_POSTS_FOLDER_ID", "GOOGLE_DRIVE_STORIES_FOLDER_ID", "GOOGLE_DRIVE_REELS_FOLDER_ID", "GOOGLE_DRIVE_MUSIC_FOLDER_ID", "INSTAGRAM_EXPECTED_USERNAME", "INSTAGRAM_STORY_MENTIONS", "STATE_BACKEND", "BRAND_NAME", "BRAND_NICHE", "BRAND_AUDIENCE", "BRAND_VOICE", "BRAND_OFFER", "BRAND_CTA", "BRAND_HASHTAG"}
        values = json.loads(private_defaults.read_text(encoding="utf-8"))
        if not isinstance(values, dict) or any(k not in allowed or not isinstance(v, str) for k, v in values.items()):
            raise core.SafeError("Invalid private runtime defaults; only nonsecret brand/folder/state settings are allowed.")
        for key, value in values.items():
            if not os.getenv(key):
                os.environ[key] = value
    for target, source in {
        "INSTAGRAM_ACCESS_TOKEN": "META_PAGE_ACCESS_TOKEN",
        "INSTAGRAM_BUSINESS_ACCOUNT_ID": "META_IG_USER_ID",
    }.items():
        if not os.getenv(target) and os.getenv(source):
            os.environ[target] = os.environ[source]


class MCPConfig(core.Config):
    def __init__(self):
        super().__init__()
        keys = {"POST": "GOOGLE_DRIVE_POSTS_FOLDER_ID", "STORY": "GOOGLE_DRIVE_STORIES_FOLDER_ID", "REEL": "GOOGLE_DRIVE_REELS_FOLDER_ID"}
        present = {kind: os.getenv(key, "").strip() for kind, key in keys.items()}
        if any(present.values()):
            if not all(present.values()) or len(set(present.values())) != 3:
                raise core.SafeError("Configure three distinct Posts, Stories and Reels folder IDs.")
            if any(not re.fullmatch(r"[A-Za-z0-9_-]+", value) for value in present.values()):
                raise core.SafeError("Invalid media subfolder ID.")
            self.sources = {folder: kind for kind, folder in present.items()}
        else:
            self.sources = {self.folder: "POST"}
        self.expected_username = os.getenv("INSTAGRAM_EXPECTED_USERNAME", "").lstrip("@").strip()
        self.story_mentions = list(dict.fromkeys(
            name.strip().lstrip("@") for name in os.getenv("INSTAGRAM_STORY_MENTIONS", "").split(",") if name.strip()))
        if any(not re.fullmatch(r"[A-Za-z0-9._]{1,30}", name) for name in self.story_mentions) or len(self.story_mentions) > 20:
            raise core.SafeError("Configure at most 20 valid Instagram Story mention usernames.")
        self.music_folder = os.getenv("GOOGLE_DRIVE_MUSIC_FOLDER_ID", "").strip()
        if self.music_folder and (not re.fullmatch(r"[A-Za-z0-9_-]+", self.music_folder) or self.music_folder in self.sources):
            raise core.SafeError("Configure a distinct valid music folder ID.")

    def connect(self, kind="POST"):
        self.openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        if kind != "STORY" and not self.openai_key:
            raise core.SafeError("OPENAI_API_KEY is required for feed/Reel captions; Stories do not need it.")
        self.ig_token = core.required("INSTAGRAM_ACCESS_TOKEN")
        self.bucket = core.required("GCS_BUCKET_NAME")
        self.brand = {name: core.required(name) for name in (
            "BRAND_NAME", "BRAND_NICHE", "BRAND_AUDIENCE", "BRAND_VOICE",
            "BRAND_OFFER", "BRAND_CTA", "BRAND_HASHTAG",
        )}
        raw = core.required("GCS_SERVICE_ACCOUNT_JSON")
        try:
            info = json.loads(raw) if raw.lstrip().startswith("{") else json.loads(
                (core.ROOT / raw).read_text(encoding="utf-8"))
            self.credentials = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/devstorage.read_write"])
        except Exception:
            raise core.SafeError("Cannot read GCS_SERVICE_ACCOUNT_JSON. This key is for Storage only, not Drive.") from None


def pending_record(state):
    return next(((file_id, record) for file_id, record in state["records"].items()
                 if record["status"] == "pending"), None)


def plan(cfg, state):
    pending = pending_record(state)
    output = {
        "music_folder_id": getattr(cfg, "music_folder", ""),
        "folder_id": cfg.folder,
        "sources": [{"folder_id": folder, "kind": kind} for folder, kind in pipeline.source_map(cfg).items()],
        "tracked_file_ids": sorted(state["records"]),
        "search_filter": (
            "(" + " or ".join(f"'{folder}' in parents" for folder in pipeline.source_map(cfg)) + ") and trashed = false "
            "and (mimeType = 'image/jpeg' or mimeType = 'image/png' or mimeType = 'video/mp4' or mimeType = 'video/quicktime')"
        ),
    }
    if pending and pending[1].get("container_id"):
        output.update(action="resume", file_id=pending[0])
    elif pending:
        output.update(action="fetch_pending", file_id=pending[0], filename=pending[1]["name"])
        if pending[1].get("music"):
            output["pending_music"] = pending[1]["music"]
    else:
        output.update(action="search")
    return output


def read_input(path, cfg, state):
    path = Path(path)
    if path.stat().st_size > 65536:
        raise core.SafeError("The handoff JSON is too large.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        file_id = value["file_id"]
        filename = value["filename"]
        mime = value["mime_type"]
        parents = value["parent_ids"]
        local_path = Path(value["local_path"])
        checksum = value.get("md5_checksum")
        expected_sha = value.get("sha256")
        expected_size = value.get("file_size_bytes")
        valid = (
            isinstance(file_id, str)
            and re.fullmatch(r"[A-Za-z0-9_-]+", file_id)
            and isinstance(filename, str)
            and len(filename) <= 1024
            and isinstance(parents, list)
            and local_path.is_absolute()
            and (
                (isinstance(checksum, str) and re.fullmatch(r"[a-fA-F0-9]{32}", checksum))
                or (checksum is None and isinstance(expected_sha, str)
                    and re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha)
                    and isinstance(expected_size, int) and not isinstance(expected_size, bool) and expected_size > 0)
            )
        )
        if not valid:
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        raise core.SafeError("Invalid handoff JSON. Use real Drive metadata and a local absolute path. Supply the provider MD5 when exposed; otherwise supply connector file_size_bytes and a locally measured sha256.") from None
    kind, video = pipeline.classify(cfg, parents, mime, filename)
    pending = pending_record(state)
    if pending and pending[0] != file_id:
        raise core.SafeError("A different image is pending. Follow --plan before selecting a new image.")
    if pending and pending[1].get("kind", "POST") != kind:
        raise core.SafeError("Pending file moved to a different publishing format. Item held for review.")
    if not local_path.is_file():
        raise core.SafeError("Image is not a local file. Materialize the MCP file reference before publishing; a file_uri is not a path.")
    with local_path.open("rb") as stream:
        limit = pipeline.VIDEO_LIMIT if video else core.MAX_SOURCE
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise core.SafeError("Source exceeds the workflow limit: 25 MB images or 250 MB videos.")
    if checksum is not None and hashlib.md5(raw, usedforsecurity=False).hexdigest() != checksum.lower():
        raise core.SafeError("Downloaded bytes do not match Drive's MD5 checksum. Fetch the original file again.")
    if expected_size is not None and len(raw) != expected_size:
        raise core.SafeError("Local byte count differs from the connector-reported original size.")
    if expected_sha is not None and hashlib.sha256(raw).hexdigest() != expected_sha.lower():
        raise core.SafeError("Local bytes changed after materialization. Fetch the original again.")
    candidate = {"id": file_id, "name": filename, "size": str(len(raw)), "kind": kind, "is_video": video}
    if "music" in value:
        if video:
            raise core.SafeError("Music attachments are supported only for still photos; existing video audio is preserved.")
        candidate["music"] = music.read_handoff(value["music"], getattr(cfg, "music_folder", ""))
    if pending and pending[1].get("music") != (music.permanent_selection(candidate["music"]) if candidate.get("music") else None):
        raise core.SafeError("Pending music selection changed or is missing. Refetch the saved track; do not select another.")
    return candidate, raw


class MCPServices(core.Services):
    def __init__(self, cfg, supplied=None):
        # Do not call the original initializer: it creates a Drive client.
        self.cfg = cfg
        self.session = requests.Session()
        self.gcs = storage.Client(project=cfg.credentials.project_id, credentials=cfg.credentials)
        self.graph_base = f"https://graph.facebook.com/{cfg.version}"
        self.ig_headers = {"Authorization": f"Bearer {cfg.ig_token}"}
        self.supplied = supplied

    def files(self):
        return iter([self.supplied[0]] if self.supplied else [])

    def download(self, file):
        if not self.supplied or self.supplied[0]["id"] != file["id"]:
            raise core.SafeError("This image needs a new MCP download. Follow --plan and supply --input.")
        core.LOG.info("Using the verified local image supplied by Google Drive MCP...")
        return self.supplied[1]


    def validate_account(self, kind):
        # Facebook Login's IG User endpoint does not expose account_type.
        # Meta enforces Story eligibility when creating the STORIES container.
        account = self.graph("GET", self.cfg.account, params={"fields": "id,username"})
        if str(account.get("id", "")) != self.cfg.account:
            raise core.SafeError("Meta returned a different account ID. Nothing was published.")
        expected = getattr(self.cfg, "expected_username", "")
        if expected and account.get("username", "").casefold() != expected.casefold():
            raise core.SafeError("Instagram account handle does not match INSTAGRAM_EXPECTED_USERNAME. Check the configured account before publishing.")
        core.LOG.info("Instagram account identity checked for %s.", kind)

    def prepare(self, record, raw):
        if record.get("music"):
            selection = self.supplied[0].get("music") if self.supplied else None
            if not selection or music.permanent_selection(selection) != record["music"]:
                raise core.SafeError("Refetch the saved music track before rendering this pending photo.")
            jpeg = core.prepare_jpeg(raw, story=True)
            return music.render_photo(jpeg, selection), "video/mp4", jpeg
        return pipeline.prepare_media(record, raw)

    def upload_media(self, object_name, data, mime):
        core.LOG.info("Hosting temporary %s...", mime)
        blob = self.gcs.bucket(self.cfg.bucket).blob(object_name)
        blob.cache_control = "private, no-store, max-age=0"
        blob.upload_from_string(data, content_type=mime, timeout=180)
        url = blob.generate_signed_url(version="v4", expiration=timedelta(hours=6), method="GET")
        with core.http(self.session, "GET", url, stream=True) as response:
            if not response.headers.get("Content-Type", "").lower().startswith(mime):
                raise core.SafeError("Hosted media URL returned the wrong content type.")
            sample = next(response.iter_content(16), b"")
            if mime == "image/jpeg" and not sample.startswith(b"\xff\xd8"):
                raise core.SafeError("Hosted URL did not return JPEG bytes.")
            if mime == "video/mp4" and sample[4:8] != b"ftyp":
                raise core.SafeError("Hosted URL did not return MP4 bytes.")
        return url


def main():
    apply_host_aliases()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
    for name in ("google", "urllib3", "requests"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan", action="store_true")
    action.add_argument("--input", metavar="HANDOFF_JSON")
    action.add_argument("--resume", action="store_true")
    action.add_argument("--initialize-state", action="store_true")
    action.add_argument("--ensure-state", action="store_true")
    action.add_argument("--status", action="store_true")
    action.add_argument("--retire-pending", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run and not args.input:
        parser.error("--dry-run requires --input")
    remote = os.getenv("STATE_BACKEND", "local") == "gcs"
    if args.initialize_state and remote:
        parser.error("Use --ensure-state for the first remote deployment. Remote records are never reset.")
    if not remote and (args.initialize_state or args.status or args.retire_pending):
        return core.main()
    if args.ensure_state and not remote:
        parser.error("--ensure-state is only supported for canonical GCS state.")
    try:
        cfg = MCPConfig()
        cfg.state_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(cfg.state_path) + ".lock", timeout=0):
            if remote:
                cfg.connect(kind="STORY")
                if args.ensure_state:
                    MCPServices(cfg).validate_account("POST")
            context = RemoteState(cfg, allow_create=args.ensure_state) if remote else nullcontext()
            with context as remote_store:
                return execute(args, cfg, remote_store.state if remote else core.load_state(cfg))
    except Timeout:
        core.LOG.info("Another run is working. Stop this task without selecting another item.")
        return 0
    except core.SafeError as exc:
        core.LOG.error("Stopped: %s", exc)
        return 1
    except KeyboardInterrupt:
        core.LOG.error("Interrupted. Keep the posting record for recovery.")
        return 130
    except Exception as exc:
        core.LOG.error("Stopped (%s). Check configuration, credentials and networking; never reset posting state.", type(exc).__name__)
        return 1


def execute(args, cfg, state):
    if args.ensure_state:
        core.LOG.info("Canonical remote record is ready. Existing history was retained; nothing was published.")
        return 0
    if args.status:
        counts = {}
        for record in state["records"].values():
            counts[record["status"]] = counts.get(record["status"], 0) + 1
        core.LOG.info("Canonical record counts: %s", counts)
        return 0
    if args.retire_pending:
        for record in state["records"].values():
            if record["status"] == "pending":
                record["status"] = "retired"
                record["retired_at"] = core.now()
        core.atomic_save(cfg.state_path, state)
        core.LOG.info("Pending item permanently retired. Nothing was published.")
        return 0
    if args.plan:
        print(json.dumps(plan(cfg, state), ensure_ascii=False, indent=2))
        return 0
    pending = pending_record(state)
    if args.resume and pending and not pending[1].get("container_id"):
        raise core.SafeError("Pending image needs MCP bytes. Follow --plan and use --input.")
    supplied = read_input(args.input, cfg, state) if args.input else None
    # A repeated handoff for an already tracked file is a no-op.
    if supplied:
        existing = state["records"].get(supplied[0]["id"])
        if existing and existing["status"] != "pending":
            core.LOG.info("This Drive file is already tracked. Nothing will be posted.")
            return 0
    selected_kind = pending[1].get("kind", "POST") if pending else supplied[0]["kind"] if supplied else "STORY"
    cfg.connect(kind=selected_kind)
    pipeline.run_once(cfg, MCPServices(cfg, supplied), state, dry_run=args.dry_run)
    return 0

if __name__ == "__main__":
    sys.exit(main())

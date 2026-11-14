"""Canonical GCS posting record with generation checks and a distributed lease."""
import json
from pathlib import Path
import time
import uuid

from google.api_core.exceptions import NotFound, PreconditionFailed, Conflict
from google.cloud import storage

import main as core


class RemoteState:
    def __init__(self, cfg, *, allow_create=False, client=None):
        self.cfg = cfg
        self.allow_create = allow_create
        self.client = client or storage.Client(project=cfg.credentials.project_id, credentials=cfg.credentials)
        bucket = self.client.bucket(cfg.bucket)
        prefix = f"instagram-state/v1/{cfg.account}/{cfg.folder}"
        self.state_blob = bucket.blob(prefix + "/processed_images.json")
        self.marker_blob = bucket.blob(prefix + "/initialized.json")
        self.lease_blob = bucket.blob(prefix + "/lease.json")
        self.generation = None
        self.lease_generation = None
        self.owner = uuid.uuid4().hex
        self.original_save = core.atomic_save
        self.patched = False

    def upload(self, blob, value, generation):
        try:
            blob.upload_from_string(json.dumps(value, ensure_ascii=False), content_type="application/json", if_generation_match=generation, timeout=60)
            return blob.generation
        except (PreconditionFailed, Conflict):
            raise core.SafeError("Remote posting state or lock changed concurrently. Stopped without another publishing request.") from None

    def acquire(self):
        value = {"owner": self.owner, "expires_at": time.time() + 7200}
        try:
            self.lease_generation = self.upload(self.lease_blob, value, 0)
            return
        except core.SafeError:
            pass
        try:
            self.lease_blob.reload(timeout=30)
            generation = self.lease_blob.generation
            previous = json.loads(self.lease_blob.download_as_text(if_generation_match=generation, timeout=30))
            if float(previous["expires_at"]) >= time.time():
                raise core.SafeError("Another computer holds the remote posting lock. No media will be published by this invocation.")
            self.lease_blob.delete(if_generation_match=generation, timeout=30)
            self.lease_generation = self.upload(self.lease_blob, value, 0)
        except core.SafeError:
            raise
        except Exception:
            raise core.SafeError("Cannot safely acquire the remote posting lock. Check Storage access; do not delete posting records.") from None

    def load_or_create(self):
        try:
            self.state_blob.reload(timeout=30)
            self.generation = self.state_blob.generation
            text = self.state_blob.download_as_text(if_generation_match=self.generation, timeout=60)
            value = json.loads(text)
        except NotFound:
            if not self.allow_create:
                raise core.SafeError("Canonical remote posting record is missing. First deployment requires --ensure-state; an existing deployment must restore its current remote record, never reset it.") from None
            if self.marker_blob.exists(timeout=30):
                raise core.SafeError("Remote initialization marker exists but the posting record is missing. Refusing to recreate an empty record; restore the latest remote version.")
            if self.cfg.state_path.exists():
                previous = core.load_state(self.cfg)
                if previous["records"]:
                    raise core.SafeError("A nonempty local posting record exists. Migrate and verify that record explicitly before enabling remote state.")
            # Mark first deployment before creating state. A crash here fails closed.
            self.upload(self.marker_blob, {"binding": self.cfg.binding, "created_at": core.now()}, 0)
            value = {"schema": 1, "binding": self.cfg.binding, "records": {}}
            self.generation = self.upload(self.state_blob, value, 0)
        except (ValueError, TypeError):
            raise core.SafeError("Remote posting record is malformed. Restore the current valid version; do not initialize a new record.") from None
        self.original_save(self.cfg.state_path, value)
        validated = core.load_state(self.cfg)
        if not self.marker_blob.exists(timeout=30):
            self.upload(self.marker_blob, {"binding": self.cfg.binding, "created_at": core.now()}, 0)
        return validated

    def save(self, path, value):
        if Path(path).resolve() != self.cfg.state_path.resolve():
            return self.original_save(path, value)
        # Persist remotely BEFORE local cache or the publishing request.
        self.generation = self.upload(self.state_blob, value, self.generation)
        self.original_save(path, value)

    def __enter__(self):
        try:
            self.acquire()
            self.state = self.load_or_create()
            core.atomic_save = self.save
            self.patched = True
            return self
        except Exception:
            self.close()
            raise

    def close(self):
        if self.patched:
            core.atomic_save = self.original_save
            self.patched = False
        if self.lease_generation is not None:
            try:
                self.lease_blob.delete(if_generation_match=self.lease_generation, timeout=30)
            except Exception:
                core.LOG.warning("Remote lock cleanup failed; its lease expires after two hours. Remote posting state remains authoritative.")
            self.lease_generation = None

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False

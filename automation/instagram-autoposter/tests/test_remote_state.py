import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from google.api_core.exceptions import NotFound, PreconditionFailed
import main as core
from remote_state import RemoteState


class Blob:
    def __init__(self, bucket, name):
        self.bucket, self.name, self.generation = bucket, name, None
    def upload_from_string(self, text, *, if_generation_match, **kwargs):
        old = self.bucket.rows.get(self.name)
        actual = old[0] if old else 0
        if if_generation_match != actual:
            raise PreconditionFailed("generation changed")
        self.bucket.counter += 1
        self.generation = self.bucket.counter
        self.bucket.rows[self.name] = (self.generation, text)
    def reload(self, **kwargs):
        if self.name not in self.bucket.rows:
            raise NotFound("missing")
        self.generation = self.bucket.rows[self.name][0]
    def download_as_text(self, *, if_generation_match, **kwargs):
        self.reload()
        if self.generation != if_generation_match:
            raise PreconditionFailed("generation changed")
        return self.bucket.rows[self.name][1]
    def exists(self, **kwargs):
        return self.name in self.bucket.rows
    def delete(self, *, if_generation_match, **kwargs):
        self.reload()
        if self.generation != if_generation_match:
            raise PreconditionFailed("generation changed")
        del self.bucket.rows[self.name]


class Bucket:
    def __init__(self):
        self.rows, self.counter = {}, 0
    def blob(self, name):
        return Blob(self, name)


class Client:
    def __init__(self):
        self.store = Bucket()
    def bucket(self, name):
        return self.store


class RemoteStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = SimpleNamespace(account="123", folder="folder", bucket="private", binding={"folder_id": "folder", "instagram_account_id": "123"}, state_path=Path(self.tmp.name) / "cache.json")
        self.client = Client()
        self.original_save = core.atomic_save
        self.addCleanup(setattr, core, "atomic_save", self.original_save)

    def store(self, create=False):
        return RemoteState(self.cfg, allow_create=create, client=self.client)

    def test_new_remote_deployment_is_conditional_and_idempotent(self):
        with self.store(True) as store:
            self.assertEqual(store.state["records"], {})
        self.cfg.state_path.unlink()
        with self.store(True) as store:
            self.assertEqual(store.state["records"], {})

    def test_fresh_computer_restores_current_history(self):
        with self.store(True) as store:
            store.state["records"]["one"] = {"status": "published", "sha256": "a" * 64}
            core.atomic_save(self.cfg.state_path, store.state)
        self.cfg.state_path.unlink()
        with self.store() as store:
            self.assertEqual(store.state["records"]["one"]["status"], "published")

    def test_stale_local_record_never_replaces_remote_history(self):
        with self.store(True) as store:
            store.state["records"]["one"] = {"status": "published", "sha256": "a" * 64}
            core.atomic_save(self.cfg.state_path, store.state)
        self.original_save(self.cfg.state_path, {"schema": 1, "binding": self.cfg.binding, "records": {}})
        with self.store() as store:
            self.assertIn("one", store.state["records"])

    def test_missing_remote_record_without_init_fails(self):
        with self.assertRaises(core.SafeError):
            with self.store():
                pass

    def test_deleted_state_with_marker_cannot_be_reinitialized(self):
        with self.store(True) as store:
            name = store.state_blob.name
        del self.client.store.rows[name]
        with self.assertRaisesRegex(core.SafeError, "marker exists"):
            with self.store(True):
                pass

    def test_second_computer_cannot_enter_live_lease(self):
        first = self.store(True)
        with first:
            with self.assertRaisesRegex(core.SafeError, "remote posting lock"):
                with self.store():
                    pass
            self.assertIn(first.lease_blob.name, self.client.store.rows)

    def test_expired_lease_can_be_replaced_conditionally(self):
        with self.store(True):
            pass
        lease = self.store().lease_blob
        lease.upload_from_string(json.dumps({"owner": "old", "expires_at": 0}), if_generation_match=0)
        with self.store() as current:
            self.assertNotEqual(current.owner, "old")

    def test_stale_generation_cannot_write_publishing_intent(self):
        with self.store(True) as store:
            other = self.client.store.blob(store.state_blob.name)
            other.reload()
            other.upload_from_string(json.dumps(store.state), if_generation_match=other.generation)
            with self.assertRaisesRegex(core.SafeError, "changed concurrently"):
                core.atomic_save(self.cfg.state_path, store.state)

    def test_remote_intent_is_written_before_local_cache(self):
        with self.store(True) as store:
            store.state["records"]["one"] = {"status": "pending", "sha256": "a" * 64, "publish_attempted": True}
            def local_save(path, value):
                current = json.loads(self.client.store.rows[store.state_blob.name][1])
                self.assertTrue(current["records"]["one"]["publish_attempted"])
                self.original_save(path, value)
            store.original_save = local_save
            core.atomic_save(self.cfg.state_path, store.state)

    def test_nonempty_local_history_needs_explicit_migration(self):
        self.original_save(self.cfg.state_path, {"schema": 1, "binding": self.cfg.binding, "records": {"one": {"status": "published", "sha256": "a" * 64}}})
        with self.assertRaisesRegex(core.SafeError, "Migrate"):
            with self.store(True):
                pass

    def test_exception_restores_atomic_save_and_releases_lease(self):
        store = self.store(True)
        with self.assertRaises(RuntimeError):
            with store:
                raise RuntimeError("simulated crash")
        self.assertIs(core.atomic_save, self.original_save)
        self.assertNotIn(store.lease_blob.name, self.client.store.rows)


if __name__ == "__main__":
    unittest.main()

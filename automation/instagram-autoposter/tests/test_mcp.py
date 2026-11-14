import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import mcp_main as mcp
from test_workflow import png, FakeServices
import main as core


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = SimpleNamespace(folder="folder", account="123", state_path=self.root / "state.json", binding={"folder_id": "folder", "instagram_account_id": "123"})
        self.state = {"schema": 1, "binding": self.cfg.binding, "records": {}}
        self.raw = png()
        self.image = self.root / "image.png"
        self.image.write_bytes(self.raw)
        self.manifest = {"file_id": "one", "filename": "one.png", "mime_type": "image/png", "parent_ids": ["folder"], "local_path": str(self.image), "md5_checksum": hashlib.md5(self.raw, usedforsecurity=False).hexdigest()}
        self.path = self.root / "input.json"
        self.save_manifest()
        core.atomic_save(self.cfg.state_path, self.state)

    def save_manifest(self):
        self.path.write_text(json.dumps(self.manifest))

    def test_valid_original_bytes(self):
        file, raw = mcp.read_input(self.path, self.cfg, self.state)
        self.assertEqual(file["id"], "one")
        self.assertEqual(raw, self.raw)

    def test_wrong_parent_rejected(self):
        self.manifest["parent_ids"] = ["other"]
        self.save_manifest()
        with self.assertRaises(core.SafeError):
            mcp.read_input(self.path, self.cfg, self.state)

    def test_checksum_mismatch_rejected(self):
        self.manifest["md5_checksum"] = "0" * 32
        self.save_manifest()
        with self.assertRaises(core.SafeError):
            mcp.read_input(self.path, self.cfg, self.state)

    def test_file_uri_is_not_a_local_path(self):
        self.manifest["local_path"] = "file-service://reference"
        self.save_manifest()
        with self.assertRaises(core.SafeError):
            mcp.read_input(self.path, self.cfg, self.state)

    def test_missing_file_rejected(self):
        self.image.unlink()
        with self.assertRaises(core.SafeError):
            mcp.read_input(self.path, self.cfg, self.state)

    def test_pending_file_cannot_be_replaced(self):
        self.state["records"]["other"] = {"status": "pending", "name": "other.png"}
        with self.assertRaises(core.SafeError):
            mcp.read_input(self.path, self.cfg, self.state)

    def test_plan_includes_all_tracked_ids(self):
        self.state["records"]["old"] = {"status": "published"}
        result = mcp.plan(self.cfg, self.state)
        self.assertEqual(result["action"], "search")
        self.assertEqual(result["tracked_file_ids"], ["old"])
        self.assertIn("'folder' in parents", result["search_filter"])

    def test_saved_container_requires_no_download(self):
        self.state["records"]["old"] = {"status": "pending", "container_id": "123"}
        self.assertEqual(mcp.plan(self.cfg, self.state)["action"], "resume")

    def test_pending_before_container_requests_same_file(self):
        self.state["records"]["old"] = {"status": "pending", "name": "old.png"}
        result = mcp.plan(self.cfg, self.state)
        self.assertEqual(result["action"], "fetch_pending")
        self.assertEqual(result["file_id"], "old")

    def test_mcp_services_have_no_drive_client(self):
        cfg = SimpleNamespace(credentials=SimpleNamespace(project_id="test"), version="v27.0", ig_token="not-a-token")
        with patch.object(mcp.storage, "Client"):
            services = mcp.MCPServices(cfg, ({"id": "one"}, self.raw))
        self.assertFalse(hasattr(services, "drive"))
        self.assertEqual(services.download({"id": "one"}), self.raw)

    def test_handoff_runs_existing_publication_safely(self):
        file, raw = mcp.read_input(self.path, self.cfg, self.state)
        services = FakeServices([file])
        services.download = lambda selected: raw
        core.run_once(self.cfg, services, self.state)
        self.assertEqual(services.posts, ["123/media", "123/media_publish"])
        self.assertEqual(self.state["records"]["one"]["status"], "published")


if __name__ == "__main__":
    unittest.main()

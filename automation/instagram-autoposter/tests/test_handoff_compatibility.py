import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import main as core
import mcp_main as app
from test_workflow import png


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = png()
        (self.root / "image.png").write_bytes(self.raw)
        self.cfg = SimpleNamespace(folder="stories")
        self.state = {"records": {}}
        self.value = {"file_id": "one", "filename": "one.png", "mime_type": "image/png", "parent_ids": ["stories"], "local_path": str(self.root / "image.png"), "sha256": hashlib.sha256(self.raw).hexdigest(), "file_size_bytes": len(self.raw)}
        self.path = self.root / "handoff.json"

    def write(self):
        self.path.write_text(json.dumps(self.value))

    def test_authenticated_file_reference_without_md5_supported(self):
        self.write()
        _, raw = app.read_input(self.path, self.cfg, self.state)
        self.assertEqual(raw, self.raw)

    def test_connector_byte_count_mismatch_rejected(self):
        self.value["file_size_bytes"] += 1
        self.write()
        with self.assertRaises(core.SafeError):
            app.read_input(self.path, self.cfg, self.state)

    def test_changed_local_fingerprint_rejected(self):
        self.value["sha256"] = "0" * 64
        self.write()
        with self.assertRaises(core.SafeError):
            app.read_input(self.path, self.cfg, self.state)

    def test_no_integrity_evidence_rejected(self):
        self.value.pop("sha256")
        self.write()
        with self.assertRaises(core.SafeError):
            app.read_input(self.path, self.cfg, self.state)

    def test_story_credentials_do_not_require_openai(self):
        environment = {"INSTAGRAM_ACCESS_TOKEN": "test", "GCS_BUCKET_NAME": "test", "GCS_SERVICE_ACCOUNT_JSON": "{}"}
        environment.update({k: "brand" for k in ("BRAND_NAME", "BRAND_NICHE", "BRAND_AUDIENCE", "BRAND_VOICE", "BRAND_OFFER", "BRAND_CTA", "BRAND_HASHTAG")})
        cfg = object.__new__(app.MCPConfig)
        with patch.dict(os.environ, environment, clear=True), patch.object(app.service_account.Credentials, "from_service_account_info"):
            cfg.connect(kind="STORY")
            self.assertEqual(cfg.openai_key, "")
            with self.assertRaises(core.SafeError):
                cfg.connect(kind="REEL")


if __name__ == "__main__":
    unittest.main()

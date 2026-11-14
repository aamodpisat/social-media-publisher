import io
import os
import unittest
from unittest.mock import patch

import mcp_main as app


class SetupTests(unittest.TestCase):
    def test_aliases_use_existing_host_settings(self):
        with patch.dict(os.environ, {"META_PAGE_ACCESS_TOKEN": "private-test-value", "META_IG_USER_ID": "123"}, clear=True), patch.object(app, "load_dotenv"):
            app.apply_host_aliases()
            self.assertEqual(os.environ["INSTAGRAM_ACCESS_TOKEN"], "private-test-value")
            self.assertEqual(os.environ["INSTAGRAM_BUSINESS_ACCOUNT_ID"], "123")

    def test_aliases_preserve_explicit_credentials(self):
        with patch.dict(os.environ, {"META_PAGE_ACCESS_TOKEN": "fallback", "INSTAGRAM_ACCESS_TOKEN": "explicit"}, clear=True), patch.object(app, "load_dotenv"):
            app.apply_host_aliases()
            self.assertEqual(os.environ["INSTAGRAM_ACCESS_TOKEN"], "explicit")

    def test_empty_canonical_setting_uses_alias(self):
        with patch.dict(os.environ, {"META_PAGE_ACCESS_TOKEN": "fallback", "INSTAGRAM_ACCESS_TOKEN": ""}, clear=True), patch.object(app, "load_dotenv"):
            app.apply_host_aliases()
            self.assertEqual(os.environ["INSTAGRAM_ACCESS_TOKEN"], "fallback")

    def test_aliases_emit_no_secret_values(self):
        with patch.dict(os.environ, {"META_PAGE_ACCESS_TOKEN": "private-test-value"}, clear=True), patch.object(app, "load_dotenv"), patch("sys.stdout", new_callable=io.StringIO) as output:
            app.apply_host_aliases()
            self.assertNotIn("private-test-value", output.getvalue())


if __name__ == "__main__":
    unittest.main()
